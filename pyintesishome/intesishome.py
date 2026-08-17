"""Main submodule for pyintesishome"""

import asyncio
import json
import logging
import socket
from datetime import datetime, timezone
from typing import NamedTuple

import aiohttp

from .const import (
    API_OS,
    API_URL,
    API_VER,
    DEVICE_INTESISHOME,
    INTESIS_CMD_STATUS,
    POLL_INTERVAL_MIN,
)
from .exceptions import IHAuthenticationError, IHConnectionError
from .intesisbase import IntesisBase


class _PendingSet(NamedTuple):
    """A SET awaiting its set_ack from the cloud."""

    uid: int
    value: int
    device_id: int
    future: asyncio.Future


_LOGGER = logging.getLogger("pyintesishome")

# The official app builds its socket frames with String.format, so they carry
# no whitespace at all. json.dumps defaults to ", " and ": ", which is
# equivalent to any JSON parser but a different byte sequence on the wire.
# Match the app exactly, so a server inspecting frame shape sees what it
# expects from a first-party client.
_JSON_SEPARATORS = (",", ":")


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
            all. False makes the controller read-only.
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

                if self._connected:
                    # Push is carrying state; nothing to fetch.
                    continue

                try:
                    await self.poll_status(sendcallback=True)
                except IHAuthenticationError as exc:
                    # Rejected credentials will not fix themselves.
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
                self._reader, self._writer = await asyncio.open_connection(
                    self._cmd_server, self._cmd_server_port
                )
            except OSError as exc:
                _LOGGER.warning(
                    "Connection to %s:%s failed: %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    exc,
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
        }

        status_response = None
        try:
            async with self._web_session.post(
                url=self._api_url, data=get_status
            ) as resp:
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
                self._error_message = status_response["errorMessage"]
                _LOGGER.error("Error from API %s", repr(self._error_message))
                raise IHAuthenticationError()

            self._apply_config(status_response.get("config"))
            updated_devices = self._apply_statuses(status_response)
            self._error_message = None

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

        SETs travel over the socket only - the cloud HTTP endpoint this
        library uses appears to be read-only - so this is the one place
        that opens one. A controller that cannot establish the socket is
        read-only, and says so rather than hanging until the ack timeout.
        """
        if not await self._ensure_socket():
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
