"""Main submodule for pyintesishome"""

import asyncio
import json
import logging
import re
import socket
from datetime import datetime, timezone
from typing import NamedTuple

import aiohttp

from .const import (
    API_APP_NAME,
    API_EXTRA_HEADERS,
    API_OS,
    API_OS_VERSION,
    API_UA_SCALE,
    API_URL,
    API_VER,
    DEVICE_INTESISHOME,
    INTESIS_CMD_STATUS,
    POLL_INTERVAL_MIN,
    PORTAL_TIMEOUT,
    PORTAL_URL,
    PORTAL_USER_AGENT,
    SOCKET_CONNECT_TIMEOUT,
)
from .exceptions import IHAuthenticationError, IHConnectionError
from .intesisbase import IntesisBase


class _PendingSet(NamedTuple):
    """A SET awaiting its set_ack from the cloud."""

    uid: int
    value: int
    device_id: int
    future: asyncio.Future


# errorCodes from /api.php/get/control that mean the credentials
# themselves were rejected, as opposed to a failure a retry might survive.
# Observed: 3 / WRONG_USERNAME_PASSWORD. The full table is not published,
# so anything not listed here is treated as transient - see
# _raise_api_error for why that is the safe direction to be wrong in.
AUTH_ERROR_CODES = frozenset({3})

_LOGGER = logging.getLogger("pyintesishome")

# The official app builds its socket frames with String.format, so they carry
# no whitespace at all. json.dumps defaults to ", " and ": ", which is
# equivalent to any JSON parser but a different byte sequence on the wire.
# Match the app exactly, so a server inspecting frame shape sees what it
# expects from a first-party client.
_JSON_SEPARATORS = (",", ":")

# The web portal's login page and post-login panel are server-rendered HTML.
# These pull the two values the command fallback needs out of it: the CSRF
# token from the login form, and the account's userId, which only appears in
# the panel JS once a login has succeeded.
_PORTAL_CSRF_RE = re.compile(r'name="signin\[_csrf_token\]"[^>]*value="([^"]+)"')
_PORTAL_USERID_RE = re.compile(r"userId=(\d+)")
_PORTAL_XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-positional-arguments, too-many-public-methods
class IntesisHome(IntesisBase):
    """pyintesishome cloud class"""

    def __init__(
        self,
        username,
        password,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
        *,
        use_socket: bool = True,
        poll_interval: int = 120,
    ):
        """Construct a cloud controller.

        Commands are the only thing that *opens* the socket, since it is
        the sole transport that accepts them - but while it is open it is
        also the state source, and polling stands down for the duration.
        Outside that window state comes from polling the HTTP endpoint.

        The socket's lifetime is therefore command-scoped: opened on
        demand by a command, kept healthy by a keepalive for as long as
        it lives so a half-dead connection is noticed rather than
        trusted, and reused by follow-up commands. Its status pushes are
        applied throughout, which is both a latency win and - while
        polling is stood down - the only thing keeping state current.

        What it is *not* is self-healing. When it dies it stays dead:
        state carries on over polling and the next command opens a fresh
        one. That is the deliberate part - the socket runs on a high port
        many networks filter outbound and the cloud drops it periodically
        even in good conditions, so reconnecting on a timer produced the
        availability flapping this design exists to remove.

        :param use_socket: allow the socket to be opened for commands at
            all. False makes the controller read-only - it disables the
            web portal command fallback too, so nothing sends commands.
        :param poll_interval: seconds between HTTP state polls. Clamped
            to a 60s floor to stay a good citizen of a third-party cloud
            API. Pass 0 or None to disable polling, which leaves state
            updating only while a socket happens to be open.
        """
        super().__init__(
            device_type=device_type,
            username=username,
            loop=loop,
            password=password,
            websession=websession,
        )
        self._api_url = API_URL[device_type]
        self._api_ver = API_VER[device_type]
        # The cloud API sets a session cookie (observed: a Symfony PHP
        # session, e.g. "symfony=..."), presumably for backend session
        # affinity. Tracked here rather than relied upon from the session's
        # own cookie jar, since callers commonly hand in an external
        # aiohttp.ClientSession (e.g. Home Assistant's shared session, whose
        # jar is a DummyCookieJar by design) that would otherwise silently
        # drop it.
        self._cookies: dict = {}
        self._cmd_server = None
        self._cmd_server_port = None
        self._auth_token = None
        self._controller_id = username
        self._use_socket = use_socket
        self._stopping = False
        if poll_interval and poll_interval < POLL_INTERVAL_MIN:
            _LOGGER.debug(
                "poll_interval of %ss is below the %ss floor; using %ss",
                poll_interval,
                POLL_INTERVAL_MIN,
                POLL_INTERVAL_MIN,
            )
        self._poll_interval = (
            max(POLL_INTERVAL_MIN, poll_interval) if poll_interval else None
        )
        # Tolerate one missed poll before reporting the device unavailable,
        # plus a margin for a slow request. Without the margin a single
        # timed-out poll would flap availability, which is the bug this
        # whole mechanism exists to fix.
        self._stale_after = (self._poll_interval or 120) * 2 + 60
        self._poll_task: asyncio.Task = None
        # Lets a disconnect pull the next poll forward. Without it, state
        # would sit unrefreshed for up to a full interval after the socket
        # that had been suppressing polls goes away.
        self._poll_wakeup: asyncio.Event = asyncio.Event()
        # poll_status() mutates _auth_token/_cmd_server as a side effect and
        # the token is single-use, so a poll racing connect() would consume
        # the credential connect() is about to present.
        self._poll_lock = asyncio.Lock()
        # SET correlation. The cloud's set_ack frame echoes our seqNo
        # masked to the low byte (seqNo & 0xFF) regardless of whether the
        # SET was applied, clamped, or targeted an invalid uid - there's
        # no success/failure signal in the seqNo. seqNos cycle 0..255 so
        # the cloud's echo lines up with the value we sent and lookups
        # are a direct dict access.
        self._set_seq_counter = -1
        self._pending_set_acks: dict[int, _PendingSet] = {}
        self._set_ack_timeout = 5.0
        # Command fallback via the brand's web portal, used when the
        # socket cannot be opened. Gets its own session (created lazily,
        # closed in stop()) so the portal's login cookies never land in a
        # caller-supplied shared session.
        self._portal_session: aiohttp.ClientSession = None
        self._portal_user_id: str = None
        self._portal_lock = asyncio.Lock()

    async def _parse_response(self, decoded_data):
        _LOGGER.debug("%s API Received: %s", self._device_type, decoded_data)
        resp = json.loads(decoded_data)
        # Parse response
        if resp["command"] == "connect_rsp":
            # New connection success
            if resp["data"]["status"] == "ok":
                _LOGGER.info("%s successfully authenticated", self._device_type)
                self._connected = True
                self._connecting = False
                self._connection_retries = 0
                await self._send_update_callback()
        elif resp["command"] == "status":
            # Value has changed
            self._update_device_state(
                resp["data"]["deviceId"],
                resp["data"]["uid"],
                resp["data"]["value"],
            )
            if resp["data"]["uid"] != 60002:
                await self._send_update_callback(
                    device_id=str(resp["data"]["deviceId"])
                )
        elif resp["command"] == "rssi":
            # Wireless strength has changed
            self._update_rssi(resp["data"]["deviceId"], resp["data"]["value"])
        elif resp["command"] == "set_ack":
            self._handle_set_ack(resp["data"])
        else:
            _LOGGER.debug("Unexpected command received: %s", resp["command"])
        # Ensure the _received_response event is set
        if not self._received_response.is_set():
            _LOGGER.debug("Setting _received_response event")
            self._received_response.set()
        return

    async def _send_keepalive(self):
        """Keep the command socket healthy for as long as it is open.

        Two jobs. It stops the server dropping an idle connection, and -
        more usefully - it is how a half-dead socket gets noticed: the
        write fails, _send_command closes the writer, and _data_received
        unwinds into the disconnect path. Without it a TCP half-open
        would sit there looking connected while carrying nothing.

        This does not resurrect a dead socket; it only maintains a live
        one. Reopening is the next command's job.
        """
        try:
            while True:
                await asyncio.sleep(120)
                _LOGGER.debug("sending keepalive to %s", self._device_type)
                device_id = str(next(iter(self._devices)))
                message = (
                    f'{{"command":"get","data":{{"deviceId":{device_id},"uid":10}}}}'
                )
                # Fire and forget. The cloud doesn't appear to emit a
                # synthetic response to a get, so waiting on
                # _received_response would always time out and tear the
                # socket down. The point is to put bytes on the wire; any
                # reply arrives via _data_received like a normal push.
                await self._send_command(message, wait_for_response=False)
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the keepalive task")

    async def _run_poller(self):
        """Refresh state over HTTP whenever push isn't carrying it.

        Polls are skipped while a socket is up, since its pushes are
        already keeping state current. What makes that safe is the
        keepalive: a half-dead socket fails its next keepalive write and
        is torn down, so the window in which a zombie connection can
        suppress polling is bounded by the keepalive interval rather than
        being open-ended.

        The task itself never stops. It waits on an event with a timeout,
        so a disconnect can wake it for an immediate poll instead of
        leaving state unrefreshed until the next scheduled one.
        """
        _LOGGER.debug("Polling %s every %ss", self._device_type, self._poll_interval)
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        self._poll_wakeup.wait(), timeout=self._poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
                self._poll_wakeup.clear()

                if self._stopping:
                    # Retire on the flag stop() sets, rather than trusting
                    # the cancel it sends straight after to arrive. On
                    # Python < 3.12 it does not always: asyncio.wait_for
                    # discarded a cancellation delivered while the future
                    # it was waiting on had already completed, which is
                    # what stop() racing a disconnect produces, since
                    # _handle_disconnect sets _poll_wakeup. The poller
                    # absorbed its only cancel, looped on, and the await in
                    # _cancel_task_if_exists never returned.
                    #
                    # 3.12 rewrote wait_for over asyncio.timeout and
                    # propagates the cancel correctly, so on the versions
                    # this package supports the check is belt-and-braces.
                    # It is kept because shutdown should not rest on the
                    # cancellation semantics of one await deep in the loop.
                    _LOGGER.debug("Stopping the %s poller", self._device_type)
                    return

                if self._connected:
                    # Push is carrying state; nothing to fetch.
                    continue

                try:
                    await self.poll_status(sendcallback=True)
                except IHAuthenticationError as exc:
                    # Rejected credentials will not fix themselves, and
                    # _raise_api_error only classifies a failure this way
                    # when the API named the credentials. Retiring is safe
                    # because authentication_failed is now set: the
                    # consumer sees an unavailable controller, reauthenticates,
                    # and rebuilds this object with a fresh poller.
                    _LOGGER.error(
                        "Authentication with %s was rejected while polling; "
                        "stopping: %s",
                        self._device_type,
                        exc,
                    )
                    return
                except IHConnectionError as exc:
                    # Leave _last_successful_update alone: is_available
                    # decides for itself when the cached state has gone
                    # stale, so a single failed poll isn't fatal.
                    _LOGGER.warning("Poll of %s failed: %s", self._device_type, exc)
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the poll task")

    def _start_poller(self):
        """Start the state poller if it isn't already running."""
        if self._poll_interval is None or self._stopping:
            return
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self._event_loop.create_task(self._run_poller())

    async def _handle_disconnect(self):
        """Deliberately does nothing but log. The socket is disposable.

        The socket exists to carry commands, so there is nothing to
        reconnect *for* until the next one arrives - and _ensure_socket
        will open a fresh one then. Polling is unaffected and keeps state
        flowing, which is why losing the socket is no longer an event the
        consumer needs to see.

        In-flight SET futures are left pending rather than failed here,
        so a command that races a drop still has until its own timeout to
        be acknowledged. stop() does fail them, since that is an
        intentional shutdown and callers shouldn't block on it.
        """
        _LOGGER.debug(
            "%s command socket closed; it will reopen on the next command",
            self._device_type,
        )
        # Polling was suppressed while the socket was up, so its pushes
        # were the only thing keeping state fresh. Poll now rather than
        # waiting out the interval, or availability would flap false in
        # the gap - the exact behaviour this design exists to remove.
        self._poll_wakeup.set()

    async def stop(self):
        """Shut the controller down fully."""
        self._stopping = True
        # Cancel the poller before super().stop() closes the web session
        # out from under an in-flight request.
        await self._cancel_task_if_exists(self._poll_task)
        self._poll_task = None
        # Fail any pending SETs so awaiting callers don't hang.
        for pending in list(self._pending_set_acks.values()):
            if not pending.future.done():
                pending.future.set_result(False)
        self._pending_set_acks.clear()
        if self._portal_session:
            if not self._portal_session.closed:
                await self._portal_session.close()
            self._portal_session = None
        # The cached userId belongs to the session that just went away.
        # Leaving it set would make the next _portal_set_value skip the
        # login and post through a session that no longer exists.
        self._portal_user_id = None
        await super().stop()

    async def _ensure_socket(self) -> bool:
        """Open the command socket if it isn't already up.

        Returns True if a usable socket exists afterwards. Called only
        from the command path - nothing else should be opening one.
        """
        if self._connected:
            return True
        if not self._use_socket:
            _LOGGER.warning(
                "Cannot open a socket to %s: use_socket=False", self._device_type
            )
            return False
        if self._connecting:
            return False

        self._connecting = True
        try:
            await self._cancel_task_if_exists(self._receive_task)
            self._receive_task = None

            # Hold the token locally. It is single-use, and a poll landing
            # between here and the connect_req below would replace
            # self._auth_token with one the server has already invalidated.
            auth_token = await self.poll_status()

            _LOGGER.debug(
                "Opening command socket to %s at %s:%s",
                self._device_type,
                self._cmd_server,
                self._cmd_server_port,
            )
            try:
                # Bound the attempt: a filtered port takes a full kernel
                # TCP timeout (~130s) to fail, and every command would pay
                # it before discovering the socket is unusable.
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._cmd_server, self._cmd_server_port),
                    timeout=SOCKET_CONNECT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # Spelled out rather than logged as the exception: str() on
                # a TimeoutError is empty, which would report the failure
                # with no reason at all.
                reason = f"timed out after {SOCKET_CONNECT_TIMEOUT}s"
            except OSError as exc:
                reason = str(exc) or type(exc).__name__
            else:
                reason = None
            if reason:
                _LOGGER.warning(
                    "Connection to %s:%s failed: %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    reason,
                )
                return False

            auth_msg = json.dumps(
                {"command": "connect_req", "data": {"token": auth_token}},
                separators=_JSON_SEPARATORS,
            )
            self._receive_task = self._event_loop.create_task(self._data_received())
            await self._send_command(auth_msg)
            auth_token = None
            self._auth_token = None

            if not self._connected:
                _LOGGER.warning(
                    "Did not receive connect_rsp from %s", self._device_type
                )
                self._close_writer()
                return False

            # Keep this socket healthy while it lives. _data_received's
            # finally block cancels it on disconnect, and nothing starts
            # it again until another command opens a new socket.
            self._keepalive_task = self._event_loop.create_task(self._send_keepalive())
            return True
        finally:
            self._connecting = False

    async def connect(self):
        """Authenticate, load state, and start polling.

        Deliberately does not open the socket. State comes from polling,
        and the socket is opened lazily by the first command, so start-up
        no longer depends on a high port being reachable.
        """
        self._stopping = False
        self._connection_retries = 0

        # Don't wipe self._devices here. poll_status() overwrites entries
        # in place and the brief reset-then-repopulate window is a race
        # against any concurrent consumer reading get_devices().
        try:
            await self.poll_status()
        except IHAuthenticationError as exc:
            _LOGGER.error("Error connecting to IntesisHome API: %s", exc)
            raise IHAuthenticationError from exc
        except IHConnectionError as exc:
            _LOGGER.error("Error connecting to IntesisHome API: %s", exc)
            raise IHConnectionError from exc

        self._start_poller()

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device.
        Notifies subscribers if sendCallback True.

        Returns a fresh single-use socket token as a side effect of the
        same request, which is why connect() calls this first. The token
        and server address are also stored on the instance, so the call is
        serialised under _poll_lock to stop a fallback poll from consuming
        the token a concurrent connect() is about to present.
        """
        async with self._poll_lock:
            return await self._poll_status(sendcallback)

    def _raise_api_error(self, status_response):
        """Turn an errorCode response into the exception it deserves.

        The cloud answers every failure the same way - HTTP 200 carrying
        an errorCode - so this is the only place the two kinds can be told
        apart, and getting it wrong is expensive in both directions. Every
        errorCode used to raise IHAuthenticationError, which retires the
        poller permanently, so one transient error from the backend left
        the controller dead until the consumer restarted.

        Only the codes known to mean rejected credentials are treated as
        such; the rest default to transient. That asymmetry is deliberate,
        because the full code table is not published: guessing transient
        costs one poll interval and a retry, while guessing auth costs the
        user a controller that has stopped polling for good. An unknown
        code logs the number it saw, so adding it here is a one-line
        change once its meaning is known.
        """
        self._error_message = status_response.get("errorMessage")
        code = status_response.get("errorCode")

        if code in AUTH_ERROR_CODES:
            _LOGGER.error(
                "%s rejected the credentials (code %s): %s",
                self._device_type,
                code,
                self._error_message,
            )
            self._authentication_failed = True
            raise IHAuthenticationError(self._error_message)

        _LOGGER.warning(
            "%s returned error code %s: %s. Treating it as transient",
            self._device_type,
            code,
            self._error_message,
        )
        raise IHConnectionError(self._error_message)

    def _apply_config(self, config):
        """Store the socket address and token, and register known devices."""
        if not config:
            # The poller calls this on a loop, so a response missing the
            # config block must not take the whole poll down.
            return

        self._cmd_server = config.get("serverIP")
        self._cmd_server_port = config.get("serverPort")
        self._auth_token = config.get("token")

        _LOGGER.debug(
            "Server: %s:%s, Token: %s",
            self._cmd_server,
            self._cmd_server_port,
            self._auth_token,
        )

        for installation in config.get("inst") or []:
            for device in installation.get("devices") or []:
                self._devices[device["id"]] = {
                    "name": device["name"],
                    "widgets": device["widgets"],
                    "model": device["modelId"],
                }
                _LOGGER.debug(repr(self._devices))

    def _apply_statuses(self, status_response) -> list:
        """Apply the status list, returning the device ids it carried.

        An empty return means the response carried no device state at all,
        which the caller treats as "the account answered but the hardware
        is not reporting".
        """
        updated_devices = []
        statuses = (status_response.get("status") or {}).get("status") or []
        for status in statuses:
            device_id = str(status["deviceId"])

            # Handle devices which don't appear in installation
            if device_id not in self._devices:
                self._devices[device_id] = {
                    "name": "Device " + device_id,
                    "widgets": [42],
                }
            if device_id not in updated_devices:
                updated_devices.append(device_id)

            self._update_device_state(device_id, status["uid"], status["value"])
        return updated_devices

    async def _poll_status(self, sendcallback=False):
        """Body of poll_status(), called with _poll_lock held."""
        get_status = {
            "username": self._username,
            "password": self._password,
            "cmd": INTESIS_CMD_STATUS,
            "version": self._api_ver,
            "os": API_OS,
            "osVersion": API_OS_VERSION,
        }
        user_agent = (
            f"{API_APP_NAME[self._device_type]}/{self._api_ver} "
            f"(iPhone; iOS {API_OS_VERSION}; Scale/{API_UA_SCALE})"
        )

        status_response = None
        try:
            async with self._web_session.post(
                url=self._api_url,
                data=get_status,
                headers={"User-Agent": user_agent, **API_EXTRA_HEADERS},
                cookies=self._cookies,
            ) as resp:
                # Sent explicitly above rather than left to the session's own
                # cookie jar (see the note on self._cookies), so captured
                # here the same way regardless of what jar, if any, the
                # session actually has.
                for name, morsel in resp.cookies.items():
                    self._cookies[name] = morsel.value
                status_response = await resp.json(content_type=None)
                _LOGGER.debug(status_response)
        except aiohttp.client_exceptions.ClientConnectorError as exc:
            raise IHConnectionError from exc
        except (aiohttp.client_exceptions.ClientError, socket.gaierror) as exc:
            self._error_message = f"Error connecting to {self._device_type} API: {exc}"
            _LOGGER.error("%s Exception. %s / %s", type(exc), repr(exc.args), exc)
            raise IHConnectionError from exc

        if status_response:
            if "errorCode" in status_response:
                self._raise_api_error(status_response)

            self._apply_config(status_response.get("config"))
            updated_devices = self._apply_statuses(status_response)
            self._error_message = None
            # Credentials that work now supersede an earlier rejection.
            self._authentication_failed = False

            # Only an answer that actually carried device state counts as a
            # successful update. When every device on the account is
            # offline the cloud still returns 200 with a full config block
            # and an empty status list - the account is reachable, the
            # hardware is not. Stamping the timestamp on that would pin
            # is_available to True forever while serving state that never
            # refreshes, which is the availability bug this mechanism
            # exists to fix, only inverted.
            #
            # Note this is an account-level signal: in a multi-device
            # installation one reporting device keeps the controller
            # available. Per-device liveness would need per-device
            # timestamps.
            if updated_devices:
                self._last_successful_update = datetime.now(timezone.utc)
            else:
                _LOGGER.debug(
                    "%s returned no device state; devices are offline",
                    self._device_type,
                )

            # One callback per device. A status list can span several
            # devices, and firing only for the last one leaves every other
            # device in a multi-device installation showing stale state.
            if sendcallback:
                for device_id in updated_devices:
                    await self._send_update_callback(device_id=device_id)

        return self._auth_token

    async def _set_value(self, device_id, uid, value) -> bool:
        """Send a SET to the cloud and wait for the matching set_ack.

        Returns True if the cloud acknowledged receiving the SET, False
        if no acknowledgement arrived within ``_set_ack_timeout`` seconds
        (i.e. the connection is broken or the cloud is unresponsive).

        Note: the cloud always ACKs malformed or out-of-range SETs the
        same way it ACKs valid ones - there's no protocol-level
        rejection signal we can detect here. False reliably indicates a
        connection problem; True only indicates the SET reached the
        cloud, not that the device applied the requested value
        unchanged (the cloud may have clamped it).

        Multiple SETs can be in flight concurrently. Each gets its own
        seqNo and the cloud echoes it (mod 256). The future stored in
        ``_pending_set_acks[seq]`` is resolved by ``_handle_set_ack``.

        SETs normally travel over the socket - the cloud HTTP endpoint
        this library uses is read-only - so this is the one place that
        opens one. When the socket cannot be established, the SET is
        attempted through the brand's web portal instead (see
        ``_portal_set_value``); only if both paths fail is the
        controller effectively read-only, and it says so rather than
        hanging until the ack timeout.

        ``use_socket=False`` is exempt: that is a deliberate read-only
        controller rather than a broken socket, so it does not fall back.
        """
        if not await self._ensure_socket():
            # use_socket=False is a caller saying "this controller is
            # read-only", not a socket that failed to open, so it must not
            # be quietly upgraded into portal commands.
            if self._use_socket:
                if await self._portal_set_value(device_id, uid, value):
                    return True
            _LOGGER.warning(
                "Cannot send SET to %s: no command socket. Commands need "
                "outbound access to %s:%s",
                self._device_type,
                self._cmd_server,
                self._cmd_server_port,
            )
            return False

        seq = self._next_set_seqno()
        fut = self._event_loop.create_future()
        self._pending_set_acks[seq] = _PendingSet(
            uid=int(uid),
            value=int(value),
            device_id=int(device_id),
            future=fut,
        )
        message = json.dumps(
            {
                "command": "set",
                "data": {
                    "deviceId": int(device_id),
                    "uid": int(uid),
                    "value": int(value),
                    "seqNo": seq,
                },
            },
            separators=_JSON_SEPARATORS,
        )
        try:
            await self._send_command(message, wait_for_response=False)
            return await asyncio.wait_for(fut, timeout=self._set_ack_timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "SET uid=%s value=%s seqNo=%s not acknowledged within %ss",
                uid,
                value,
                seq,
                self._set_ack_timeout,
            )
            return False
        finally:
            self._pending_set_acks.pop(seq, None)

    async def _portal_set_value(self, device_id, uid, value) -> bool:
        """Send a SET through the brand's web portal.

        Fallback for when the command socket cannot be opened. The web
        portal delivers commands over plain HTTPS - a logged-in session
        POSTs to /device/setVal with the same uid/value datapoints the
        socket protocol uses - and it kept working through the August
        2026 outage that left the socket server unreachable for days
        while the HTTP API stayed up (hass-intesishome#68).

        Returns True if the portal answered OK. Never raises: any
        failure logs a warning, drops the cached login so the next
        attempt starts fresh, and returns False so the caller can report
        the SET as unacknowledged.
        """
        if self._device_type not in PORTAL_URL:
            return False
        async with self._portal_lock:
            try:
                if self._portal_user_id is None or self._portal_session is None:
                    await self._portal_login()
                if await self._portal_post_set(device_id, uid, value):
                    return True
                # A non-OK answer with a cached login usually means the
                # session expired: retry once with a fresh one.
                await self._portal_login()
                return await self._portal_post_set(device_id, uid, value)
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
                IHAuthenticationError,
                IHConnectionError,
            ) as exc:
                _LOGGER.warning("Portal command fallback failed: %s", exc)
                self._portal_user_id = None
                return False

    async def _portal_login(self) -> None:
        """Log in to the web portal and cache the account's userId.

        The portal is a server-rendered web app, so this speaks its
        form-login flow: fetch the login page for the CSRF token, POST
        the credentials the controller already holds, then read the
        userId out of the post-login panel. The userId is only rendered
        for an authenticated session, so finding it doubles as the
        success check.
        """
        if self._portal_session is None or self._portal_session.closed:
            self._portal_session = aiohttp.ClientSession(
                headers={"User-Agent": PORTAL_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=PORTAL_TIMEOUT),
            )
        base = PORTAL_URL[self._device_type]
        async with self._portal_session.get(f"{base}/login") as resp:
            login_page = await resp.text()
        match = _PORTAL_CSRF_RE.search(login_page)
        if not match:
            raise IHConnectionError("Portal login page carried no CSRF token")
        form = {
            "signin[username]": self._username,
            "signin[password]": self._password,
            "signin[_csrf_token]": match.group(1),
        }
        async with self._portal_session.post(f"{base}/login", data=form) as resp:
            await resp.text()
        async with self._portal_session.get(
            f"{base}/panel/headers", headers=_PORTAL_XHR_HEADERS
        ) as resp:
            panel = await resp.text()
        match = _PORTAL_USERID_RE.search(panel)
        if not match:
            raise IHAuthenticationError("Portal login failed")
        self._portal_user_id = match.group(1)
        _LOGGER.debug("Portal login succeeded, userId=%s", self._portal_user_id)

    async def _portal_post_set(self, device_id, uid, value) -> bool:
        """POST one SET to the portal. True on an OK answer."""
        base = PORTAL_URL[self._device_type]
        url = (
            f"{base}/device/setVal?id={int(device_id)}"
            f"&uid={int(uid)}&value={int(value)}"
            f"&userId={self._portal_user_id}"
        )
        async with self._portal_session.post(url, headers=_PORTAL_XHR_HEADERS) as resp:
            body = (await resp.text()).strip()
        if body == "OK":
            _LOGGER.info(
                "SET uid=%s value=%s sent via the web portal (no socket)",
                uid,
                value,
            )
            return True
        return False

    def _next_set_seqno(self) -> int:
        """Allocate a SET seqNo in the 0..255 range.

        The cloud uses an 8-bit seqNo in set_ack regardless of what we
        send, so there's no point sending wider values. Cycling 0..255
        bounds the in-flight pending dict to 256 entries and guarantees
        concurrently outstanding SETs each get a unique echo.
        """
        self._set_seq_counter = (self._set_seq_counter + 1) % 256
        return self._set_seq_counter

    def _handle_set_ack(self, data: dict) -> None:
        """Resolve the originating SET's future on receiving the ack.

        The cloud's set_ack echoes the seqNo we sent (8-bit) regardless
        of whether the SET was applied, clamped, or rejected. We treat
        any matching ACK as success - cloud-side rejections of malformed
        SETs are not visible at this layer. The ACK also carries a fresh
        rssi value which we surface like a normal rssi frame.
        """
        seq = data.get("seqNo")
        rssi = data.get("rssi")
        device_id = data.get("deviceId")
        if rssi is not None:
            self._update_rssi(device_id, rssi)

        if seq is None:
            _LOGGER.debug("set_ack with no seqNo: %s", data)
            return

        pending = self._pending_set_acks.get(seq)
        if pending is None:
            _LOGGER.debug("Stale or unmatched set_ack seqNo=%s", seq)
            return

        _LOGGER.debug(
            "SET acknowledged: uid=%s value=%s seqNo=%s device=%s",
            pending.uid,
            pending.value,
            seq,
            device_id,
        )
        if not pending.future.done():
            pending.future.set_result(True)

    def _get_fan_map(self, device_id):
        return self.get_device_property(device_id, "config_fan_map")
