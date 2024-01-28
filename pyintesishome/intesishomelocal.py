"""Main submodule for pyintesishome."""

import asyncio
import logging
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


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-public-methods
class IntesisHomeLocal(IntesisBase):
    """pyintesishome local class."""

    def __init__(self, host, username, password, loop=None, websession=None) -> None:
        """Constructor"""
        device_type = DEVICE_INTESISHOME_LOCAL
        self._session_id: str = ""
        self._datapoints: dict = {}
        self._scan_interval = 6
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
        """Get all entity values."""
        response = {}
        try:
            response = await self._request(LOCAL_CMD_GET_DP_VALUE, uid="all")
        except (IHConnectionError, IHAuthenticationError) as exc:
            _LOGGER.error(
                "IntesisHome connection error: %s",
                exc,
            )

        if response and "dpval" in response:
            self._values = {dpval["uid"]: dpval["value"] for dpval in response["dpval"]}
            return self._values
        return {}

    async def _run_updater(self):
        """Run a loop that updates the values every _scan_interval."""
        try:
            while self._connected:
                try:
                    values = await self._request_values()
                    for uid, value in values.items():
                        self._update_device_state(self._device_id, uid, value)

                    await self._send_update_callback(self._device_id)
                except IHConnectionError as exc:
                    _LOGGER.error("Error during updater task: %s", exc)
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the updater task")
        _LOGGER.debug("Updater task is exiting")

    async def _authenticate(self) -> bool:
        """Authenticate using username and password."""
        payload = {
            "command": LOCAL_CMD_LOGIN,
            "data": {"username": self._username, "password": self._password},
        }
        try:
            async with self._web_session.post(
                f"http://{self._host}/api.cgi", json=payload
            ) as response:
                if response.status != 200:
                    raise IHConnectionError(
                        "HTTP response status is unexpected (not 200)"
                    )
                json_response = await response.json()
                # Check if the response has the expected format
                if (
                    "data" in json_response
                    and "id" in json_response["data"]
                    and "sessionID" in json_response["data"]["id"]
                ):
                    self._session_id = json_response["data"]["id"]["sessionID"]
                    _LOGGER.debug(
                        "Authenticated with new session ID %s", self._session_id
                    )
                else:
                    _LOGGER.error("Unexpected response format during authentication")
        except (
            aiohttp.ClientConnectionError,
            aiohttp.ClientResponseError,
            aiohttp.ClientPayloadError,
            aiohttp.ContentTypeError,
            JSONDecodeError,
        ) as exception:
            _LOGGER.error("Error during authentication: %s", str(exception))

    async def _request(self, command: str, **kwargs) -> dict:
        """Make a request."""
        connection_attempts = 0

        while connection_attempts < 2:
            connection_attempts += 1
            if not self._session_id:
                await self._authenticate()

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
                            f"HTTP response status is unexpected for {self._host}"
                            "(got {response.status}, want 200)"
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
                return json_response.get("data")
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
        return response["dpval"]["value"]

    async def _set_value(self, device_id, uid, value):
        return await self._request(
            LOCAL_CMD_SET_DP_VALUE,
            uid=uid,
            value=value,
        )

    async def get_datapoints(self) -> dict:
        """Get all available datapoints."""
        response = await self._request(LOCAL_CMD_GET_AVAIL_DP)
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
        self._connected = True
        _LOGGER.debug("Starting updater task")
        self._update_task = asyncio.create_task(self._run_updater())

    async def stop(self):
        """Disconnect and stop periodic updater."""
        _LOGGER.debug("Stopping updater task")
        await self._cancel_task_if_exists(self._update_task)
        self._connected = False

        if self._own_session:
            await self._web_session.close()

    async def get_info(self) -> dict:
        """Get device info."""
        response = await self._request(LOCAL_CMD_GET_INFO)
        self._info = response["info"]
        return self._info

    async def poll_status(self, sendcallback=False):
        """Get device info for setup purposes."""
        try:
            await self._authenticate()
            info = await self.get_info()

            # Extract device_id up to the first space, if there is a space
            raw_id = info.get("sn")
            if raw_id:
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
            }

            await self.get_datapoints()
            _LOGGER.debug(repr(self._devices))

            self._update_device_state(self._device_id, "acStatus", info.get("acStatus"))

            if sendcallback:
                await self._send_update_callback(str(self._device_id))
        except (IHConnectionError, KeyError) as exception:
            _LOGGER.error("Error during polling status: %s", str(exception))

    def get_mode_list(self, device_id) -> list:
        """Get possible entity modes."""
        uid = COMMAND_MAP["mode"]["uid"]
        return [
            INTESIS_MAP[uid]["values"][i]
            for i in self._datapoints[uid]["descr"]["states"]
        ]

    def _get_fan_map(self, device_id):
        fan_values = sorted(self._datapoints[4]["descr"]["states"])
        for values in INTESIS_MAP[67]["values"].values():
            if sorted(values.keys()) == fan_values:
                return values
        return INTESIS_MAP[67]["values"][63]

    def has_vertical_swing(self, device_id) -> bool:
        """Entity supports vertical swing."""
        return self._has_datapoint("vvane")

    def has_horizontal_swing(self, device_id) -> bool:
        """Entity supports horizontal swing."""
        return self._has_datapoint("hvane")

    async def _parse_response(self, decoded_data):
        """Private method to parse the API response."""
        raise NotImplementedError()
