"""Main submodule for pyintesishome."""

import asyncio
import logging
from datetime import datetime, timezone
from json import JSONDecodeError

import aiohttp

from .const import (
    COMMAND_MAP,
    DEVICE_INTESISHOME_LOCAL,
    INTESIS_MAP,
    LOCAL_CMD_GET_AVAIL_DP,
    LOCAL_CMD_GET_DP_VALUE,
    LOCAL_CMD_GET_INFO,
    LOCAL_CMD_LOGIN,
    LOCAL_CMD_SET_DP_VALUE,
)
from .exceptions import IHAuthenticationError, IHConnectionError
from .intesisbase import IntesisBase

_LOGGER = logging.getLogger("pyintesishome")


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-positional-arguments, too-many-public-methods
class IntesisHomeLocal(IntesisBase):
    """pyintesishome local class."""

    def __init__(self, host, username, password, loop=None, websession=None) -> None:
        """Constructor"""
        device_type = DEVICE_INTESISHOME_LOCAL
        self._session_id: str = ""
        self._datapoints: dict = {}
        self._scan_interval = 6
        # Ceiling on the backed-off poll interval while the device is
        # failing. These units are not powerful, and polling a struggling
        # one every _scan_interval can make matters worse.
        self._max_scan_interval = 30
        # Seconds without a successful poll before the device is reported
        # as disconnected. Deliberately expressed as elapsed time rather
        # than a failure count: a failed request can occupy anywhere from
        # milliseconds (connection refused) to ~20s (two timed-out
        # attempts), so a count would not map to any fixed grace period.
        self._unavailable_after = 300
        self._consecutive_failures = 0
        self._last_success: float = 0.0
        self._running = False
        self._device_id: str = ""
        self._values: dict = {}
        self._info: dict = {}
        self._update_task = None
        super().__init__(
            host=host,
            username=username,
            password=password,
            loop=loop,
            websession=websession,
            device_type=device_type,
        )

    async def _request_values(self) -> dict:
        """Get all entity values.

        Returns an empty dict if the device answered without values, and
        raises IHConnectionError or IHAuthenticationError if the request
        failed outright. Failures are classified by the caller rather than
        absorbed here, so the updater can tell a transient outage apart
        from rejected credentials.
        """
        response = await self._request(LOCAL_CMD_GET_DP_VALUE, uid="all")

        if response and "dpval" in response:
            self._values = {dpval["uid"]: dpval["value"] for dpval in response["dpval"]}
            return self._values
        return {}

    def _current_scan_interval(self) -> float:
        """Seconds to wait before the next poll, backing off while failing."""
        if not self._consecutive_failures:
            return self._scan_interval
        # Bound the exponent so the intermediate value stays sane during a
        # long outage. High enough that _max_scan_interval is always what
        # actually limits the result.
        exponent = min(self._consecutive_failures - 1, 16)
        return min(self._scan_interval * 2**exponent, self._max_scan_interval)

    def _register_poll_success(self):
        """Record a poll that returned values, marking the device reachable."""
        # Decay rather than reset. A unit that is struggling rather than
        # dead alternates timeouts and successes, and resetting to zero
        # would hold it at the full poll rate throughout - exactly when
        # easing off would help it recover.
        self._consecutive_failures = max(0, self._consecutive_failures - 1)
        self._error_message = None
        self._last_success = self._event_loop.time()
        self._last_successful_update = datetime.now(timezone.utc)
        if not self._connected:
            _LOGGER.info("Reconnected to %s", self._host)
        self._connected = True

    def _register_poll_failure(self):
        """Record a failed poll, giving up on the device once the grace
        period has elapsed."""
        self._consecutive_failures += 1
        elapsed = self._event_loop.time() - self._last_success
        if self._connected and elapsed >= self._unavailable_after:
            _LOGGER.warning(
                "No successful update from %s in %.0f seconds, "
                "reporting it as disconnected",
                self._host,
                elapsed,
            )
            self._connected = False

    async def _run_updater(self):
        """Poll the device every _scan_interval until stop() is called.

        The loop is governed by _running, not _connected: _connected is a
        reachability signal that goes False after _unavailable_after
        seconds without a successful poll and True again on the next
        success. Keeping them separate is what lets a device that recovers
        do so on its own, without the consumer rebuilding the controller.
        """
        try:
            while self._running:
                try:
                    values = await self._request_values()
                except IHAuthenticationError as exc:
                    # Rejected credentials are not transient, so there is
                    # nothing to be gained by continuing to poll. Mirrors
                    # the cloud reconnect loop, which also stops on auth
                    # failure rather than retrying forever.
                    _LOGGER.error(
                        "Authentication with %s was rejected, stopping updater: %s",
                        self._host,
                        exc,
                    )
                    self._error_message = str(exc)
                    self._connected = False
                    await self._send_update_callback(self._device_id)
                    return
                except IHConnectionError as exc:
                    _LOGGER.error("Error during updater task: %s", exc)
                    self._error_message = str(exc)
                    values = {}

                if values:
                    self._register_poll_success()
                    for uid, value in values.items():
                        self._update_device_state(self._device_id, uid, value)
                else:
                    self._register_poll_failure()

                await self._send_update_callback(self._device_id)
                await asyncio.sleep(self._current_scan_interval())
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the updater task")
        _LOGGER.debug("Updater task is exiting")

    async def _authenticate(self) -> bool:
        """Authenticate using username and password.

        Returns True if a session ID was obtained, False if the device
        answered with something unexpected. Raises IHConnectionError if the
        device could not be reached at all.
        """
        payload = {
            "command": LOCAL_CMD_LOGIN,
            "data": {"username": self._username, "password": self._password},
        }
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with self._web_session.post(
                f"http://{self._host}/api.cgi", json=payload, timeout=timeout
            ) as response:
                if response.status != 200:
                    raise IHConnectionError(
                        f"HTTP response status is unexpected for {self._host} "
                        f"(got {response.status}, want 200)"
                    )
                json_response = await response.json()
        except (
            asyncio.exceptions.TimeoutError,
            aiohttp.ClientError,
            JSONDecodeError,
        ) as exception:
            raise IHConnectionError(
                f"Error during authentication with {self._host}: {exception}"
            ) from exception

        # Check if the response has the expected format. The device answers a
        # rejected login with data=None, so don't assume any level is a dict.
        session_id = ((json_response.get("data") or {}).get("id") or {}).get(
            "sessionID"
        )
        if session_id:
            self._session_id = session_id
            _LOGGER.debug("Authenticated with new session ID %s", self._session_id)
            return True

        error = json_response.get("error") or {}
        if error.get("code") == 5:
            raise IHAuthenticationError(
                f"Authentication with {self._host} was rejected: {error.get('message')}"
            )

        _LOGGER.error(
            "Unexpected response format during authentication with %s: %r",
            self._host,
            json_response,
        )
        return False

    async def _request(self, command: str, **kwargs) -> dict:
        """Make a request."""
        connection_attempts = 0

        while connection_attempts < 2:
            connection_attempts += 1
            if not self._session_id:
                try:
                    await self._authenticate()
                except IHConnectionError as exc:
                    _LOGGER.error(
                        "IntesisHome authentication error for %s: %s",
                        self._host,
                        exc,
                    )
                    continue

            payload = {
                "command": command,
                "data": {"sessionID": self._session_id, **kwargs},
            }
            _LOGGER.debug(
                "Sending intesishome_local command %s to %s", command, self._host
            )
            timeout = aiohttp.ClientTimeout(total=10)
            json_response = {}
            try:
                async with self._web_session.post(
                    f"http://{self._host}/api.cgi",
                    json=payload,
                    timeout=timeout,
                ) as response:
                    if response.status != 200:
                        raise IHConnectionError(
                            f"HTTP response status is unexpected for {self._host} "
                            f"(got {response.status}, want 200)"
                        )
                    json_response = await response.json()
            except asyncio.exceptions.TimeoutError as exc:
                _LOGGER.error(
                    "IntesisHome HTTP timeout error for %s: %s",
                    self._host,
                    exc,
                )
            except aiohttp.ClientError as exc:
                _LOGGER.error(
                    "IntesisHome HTTP error for %s: %s",
                    self._host,
                    exc,
                )

            # If the response has a non-false "success", return the data.
            #
            # If the key doesn't exist, treat it as "false" and continue with
            # error handling.
            #
            # If the error code is one we know requires re-authentication,
            # clear the session key so we re-authenticate on the next attempt,
            # otherwise just log the code and error message.
            #
            # If there's neither a "success" or "error" key, something is very
            # wonky, so log an error plus the entire response.
            if json_response.get("success", False):
                return json_response.get("data") or {}
            if "error" in json_response:
                error = json_response["error"]
                if error.get("code") in [1, 5]:
                    self._session_id = ""
                    _LOGGER.debug(
                        "Request failed for %s (code=%s, message=%r)."
                        "Clearing session key to force re-authentication",
                        self._host,
                        error.get("code"),
                        error.get("message"),
                    )
                else:
                    _LOGGER.debug(
                        "Request failed for %s (code=%s, message=%r). Error not handled",
                        self._host,
                        error.get("code"),
                        error.get("message"),
                    )
            else:
                _LOGGER.debug(
                    "Request failed for %s - no 'success' or 'error' keys. json_response=%r",
                    self._host,
                    json_response,
                )

    async def _request_value(self, name: str) -> dict:
        """Get entity value by uid."""
        response = await self._request(
            LOCAL_CMD_GET_DP_VALUE, uid=COMMAND_MAP[name]["uid"]
        )
        if response is None:
            return None
        return response["dpval"]["value"]

    async def _set_value(self, device_id, uid, value):
        result = await self._request(
            LOCAL_CMD_SET_DP_VALUE,
            uid=uid,
            value=value,
        )
        return result is not None

    async def get_datapoints(self) -> dict:
        """Get all available datapoints."""
        response = await self._request(LOCAL_CMD_GET_AVAIL_DP)
        if response is None:
            return self._datapoints
        self._datapoints = {
            dpoint["uid"]: dpoint for dpoint in response["dp"]["datapoints"]
        }
        if self._device_id:
            for dpoint in response["dp"]["datapoints"]:
                dpoint_name = INTESIS_MAP[dpoint["uid"]]["name"]
                self._devices[self._device_id][dpoint_name] = None
        return self._datapoints

    def _has_datapoint(self, datapoint: str):
        """Entity has a datapoint."""
        if datapoint not in COMMAND_MAP:
            return False
        return COMMAND_MAP[datapoint]["uid"] in self._datapoints

    async def connect(self):
        """Connect to the device and start periodic updater."""
        await self.poll_status()
        _LOGGER.debug("Successful authenticated and polled. Fetching Datapoints")
        await self.get_datapoints()
        self._consecutive_failures = 0
        self._last_success = self._event_loop.time()
        self._last_successful_update = datetime.now(timezone.utc)
        self._connected = True
        self._running = True
        _LOGGER.debug("Starting updater task")
        self._update_task = asyncio.create_task(self._run_updater())

    async def stop(self):
        """Disconnect and stop periodic updater."""
        _LOGGER.debug("Stopping updater task")
        self._running = False
        await self._cancel_task_if_exists(self._update_task)
        self._connected = False

        if self._own_session:
            await self._web_session.close()

    async def get_info(self) -> dict:
        """Get device info."""
        response = await self._request(LOCAL_CMD_GET_INFO)
        if response is None:
            return self._info
        self._info = response["info"]
        return self._info

    async def poll_status(self, sendcallback=False):
        """Get device info for setup purposes.

        Raises IHConnectionError if the device could not be reached or did not
        return usable device information, so that callers can tell a failed
        poll apart from a successful one.
        """
        try:
            await self._authenticate()
            info = await self.get_info()

            # Extract device_id up to the first space, if there is a space
            raw_id = (info or {}).get("sn")
            if not raw_id:
                raise IHConnectionError(
                    f"No device information returned from {self._host}"
                )

            device_id, *_ = raw_id.split(" ")
            self._device_id = device_id
            self._controller_id = device_id.lower()

            self._controller_name = (
                f"{self._info.get('deviceModel')} ({info.get('ownSSID')})"
            )
            # Setup devices
            self._devices[self._device_id] = {
                "name": info.get("ownSSID"),
                "widgets": [],
                "model": info.get("deviceModel"),
                "fw_version": info.get("wlanFwVersion"),
            }

            await self.get_datapoints()
            _LOGGER.debug(repr(self._devices))

            self._update_device_state(self._device_id, "acStatus", info.get("acStatus"))

            if sendcallback:
                await self._send_update_callback(str(self._device_id))
        except KeyError as exception:
            raise IHConnectionError(
                f"Unexpected response from {self._host} while polling status: "
                f"missing key {exception}"
            ) from exception

    def get_mode_list(self, device_id) -> list:
        """Get possible entity modes."""
        uid = COMMAND_MAP["mode"]["uid"]
        return [
            INTESIS_MAP[uid]["values"][i]
            for i in self._datapoints[uid]["descr"]["states"]
        ]

    def _get_fan_map(self, device_id):
        if 4 not in self._datapoints:
            return None
        fan_values = sorted(self._datapoints[4]["descr"]["states"])
        # MH-AC-WIFI-1 supports AUTO fan (uid 4 value 0) even when not
        # advertised in the datapoints descriptor
        device_model = self._info.get("deviceModel", "") if self._info else ""
        if 0 not in fan_values and "MH-AC-WIFI" in device_model:
            fan_values = [0] + fan_values
        for values in INTESIS_MAP[67]["values"].values():
            if sorted(values.keys()) == fan_values:
                return values
        return INTESIS_MAP[67]["values"][63]

    def get_vertical_swing_list(self, device_id) -> list:
        """Get possible entity modes."""
        uid = COMMAND_MAP["vvane"]["uid"]
        return [
            INTESIS_MAP[uid]["values"][i]
            for i in self._datapoints[uid]["descr"]["states"]
        ]

    def has_vertical_swing(self, device_id) -> bool:
        """Entity supports vertical swing."""
        return self._has_datapoint("vvane")

    def get_horizontal_swing_list(self, device_id) -> list:
        """Get possible entity modes."""
        if not self._has_datapoint("hvane"):
            return []
        uid = COMMAND_MAP["hvane"]["uid"]
        return [
            INTESIS_MAP[uid]["values"][i]
            for i in self._datapoints[uid]["descr"]["states"]
        ]

    def has_horizontal_swing(self, device_id) -> bool:
        """Entity supports horizontal swing."""
        return self._has_datapoint("hvane")

    async def _parse_response(self, decoded_data):
        """Private method to parse the API response."""
        raise NotImplementedError()
