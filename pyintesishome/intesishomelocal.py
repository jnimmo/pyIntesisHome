from pyintesishome.intesisbase import IntesisBase

""" Main submodule for pyintesishome """
import asyncio
from asyncio import queues
from asyncio.streams import StreamReader, StreamWriter
import json
import logging
import socket
from datetime import datetime
from typing import List

import aiohttp
from asyncio.exceptions import IncompleteReadError

from .const import (
    API_URL,
    API_VER,
    COMMAND_MAP,
    CONFIG_MODE_BITS,
    DEVICE_INTESISBOX,
    DEVICE_INTESISHOME,
    ERROR_MAP,
    INTESIS_CMD_STATUS,
    INTESIS_MAP,
    INTESIS_NULL,
    INTESISBOX_CMD_FANSP,
    INTESISBOX_CMD_GET_AVAIL_DP,
    INTESISBOX_CMD_MODE,
    INTESISBOX_CMD_ONOFF,
    INTESISBOX_CMD_SETPOINT,
    INTESISBOX_CMD_VANELR,
    INTESISBOX_CMD_VANEUD,
    INTESISBOX_INIT,
    INTESISBOX_MAP,
    INTESISBOX_MODE_MAP,
    LOCAL_CMD_GET_AVAIL_DP,
    LOCAL_CMD_GET_DP_VALUE,
    LOCAL_CMD_GET_INFO,
    LOCAL_CMD_LOGIN,
    LOCAL_CMD_SET_DP_VALUE,
    OPERATING_MODE_BITS,
)
from .exceptions import IHAuthenticationError, IHConnectionError
from .helpers import twos_complement_16bit, uint32

_LOGGER = logging.getLogger("pyintesishome")


class IntesisHomeLocal(IntesisBase):
    """pyintesishome local class"""

    def __init__(
        self,
        host,
        username,
        password,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
    ):
        self._session_id: str = ""
        self._datapoints: dict = {}
        self._scan_interval = 5
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
        response = await self._request(LOCAL_CMD_GET_DP_VALUE, uid="all")
        self._values = {dpval["uid"]: dpval["value"] for dpval in response["dpval"]}
        return self._values

    async def _run_updater(self):
        """Run a loop that updates the values every _scan_interval."""
        while True:
            values = await self._request_values()
            for uid, value in values.items():
                self._update_device_state(self._device_id, uid, value)

            await self._send_update_callback(self._device_id)
            await asyncio.sleep(self._scan_interval)

    async def _authenticate(self) -> bool:
        """Authenticate using username and password."""
        response = await self._request(
            LOCAL_CMD_LOGIN, username=self._username, password=self._password
        )
        self._session_id = response["id"].get("sessionID")

    async def _request(self, command: str, **kwargs) -> dict:
        """Make a request."""
        payload = {
            "command": command,
            "data": {"sessionID": self._session_id, **kwargs},
        }

        async with self._web_session.post(
            f"http://{self._host}/api.cgi", json=payload
        ) as response:
            if response.status != 200:
                raise IHConnectionError("HTTP response status is unexpected (not 200)")

            json_response = await response.json()

        if not json_response["success"]:
            if json_response["error"]["code"] in [1, 5]:
                if self._connection_retries:
                    raise IHAuthenticationError(json_response["error"]["message"])

                # Try to reauthenticate once
                _LOGGER.debug("Request failed. Trying to reauthenticate.")
                self._connection_retries += 1
                await self._authenticate()
                return await self._request(command, **kwargs)
            raise IHConnectionError(json_response["error"]["message"])

        self._connection_retries = 0
        return json_response.get("data")

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
        _LOGGER.debug("Successful authenticated and polled. Fetching Datapoints.")
        await self.get_datapoints()

        _LOGGER.debug("Starting updater task.")
        self._update_task = asyncio.create_task(self._run_updater())
        self._connected = True

    async def stop(self):
        """Disconnect and stop periodic updater."""
        _LOGGER.debug("Stopping updater task.")
        try:
            self._update_task.cancel()
            await self._update_task
        except asyncio.CancelledError:
            pass
        self._connected = False

        if self._own_session:
            await self._web_session.close()

    async def get_info(self) -> dict:
        """Get device info."""
        response = await self._request(LOCAL_CMD_GET_INFO)
        self._info = response["info"]
        return self._info

    async def poll_status(self, sendcallback=False):
        await self._authenticate()
        info = await self.get_info()
        self._device_id = info["sn"]
        self._controller_id = info["sn"].lower()
        self._controller_name = f"{self._info['deviceModel']} ({info['ownSSID']})"
        # Setup devices
        self._devices[self._device_id] = {
            "name": info["ownSSID"],
            "widgets": [],
            "model": info["deviceModel"],
        }

        await self.get_datapoints()
        _LOGGER.debug(repr(self._devices))

        self._update_device_state(self._device_id, "acStatus", info["acStatus"])

        if sendcallback:
            await self._send_update_callback(str(self._device_id))

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
