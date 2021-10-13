""" Main submodule for pyintesishome """
import asyncio
from asyncio.streams import StreamReader, StreamWriter
import logging
from datetime import datetime
from typing import List

import aiohttp
from asyncio.exceptions import IncompleteReadError

from pyintesishome.intesisbase import IntesisBase

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


class IntesisBox(IntesisBase):
    """pyintesishome local class"""

    INTESIS_MAP = INTESISBOX_MAP

    def __init__(self, host, loop=None):
        super().__init__(host=host, loop=loop, device_type=DEVICE_INTESISBOX)
        self._scan_interval = 60
        self._device_id: str = ""
        self._values: dict = {}
        self._info: dict = {}
        self._mac: str = ""
        self._update_task = None
        self._receive_task = None
        self._reader = None
        self._port = 3310
        self._writer = None
        self._last_command: str = ""
        self._received_response: asyncio.Event = asyncio.Event()

    async def connect(self):
        if self._connected:
            _LOGGER.debug("Already connected")
            return

        self._devices = {}
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                _LOGGER.debug("Receive task cancelled")

        _LOGGER.debug("Connecting")
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port, loop=self._event_loop
            )
            self._receive_task = asyncio.create_task(self._data_received())
            await asyncio.wait_for(self._initialise_connection(), timeout=60.0)
            await self._send_update_callback()

        except OSError as e:  # pylint: disable=broad-except
            _LOGGER.debug("Exception opening connection")
            _LOGGER.error("%s Exception. %s / %s", type(e), repr(e.args), e)

    async def _initialise_connection(self):
        """Requests the current state of the device"""
        for init_cmd in INTESISBOX_INIT:
            await self._send_command(init_cmd)

        initialized = False

        while not initialized:
            _LOGGER.debug("Awaiting initialisation (current temperature)")
            await asyncio.sleep(0.1)
            initialized = self._device_id in self._devices and (
                "temperature" in self._devices[self._device_id]
                or "hvane_list" in self._devices[self._device_id]
            )
        self._connected = True

    async def parse_response(self, decoded_data):
        linesReceived: List[str] = decoded_data.strip().splitlines()
        for line in linesReceived:
            cmdList = line.split(":", 1)
            cmd = cmdList[0]
            if cmd in ["CHN,1", "ID", "LIMITS", "ACK", "ERR"]:
                if len(cmdList) > 1:
                    args = cmdList[1]
                    if cmd == "ID":
                        self._parse_id_received(args)
                    elif cmd == "CHN,1":
                        self._parse_change_received(args)
                    elif cmd == "LIMITS":
                        self._parse_limits_received(args)
            if not self._received_response.is_set():
                _LOGGER.debug("Resolving set_value's await")
                self._received_response.set()

    async def _data_received(self):
        try:
            while self._reader:
                raw_data = await self._reader.readuntil(b"\r")
                if not raw_data:
                    break
                data = raw_data.decode("ascii")
                _LOGGER.debug(f"Received {data!r}")
                await self.parse_response(data)

        except IncompleteReadError as exc:
            _LOGGER.info(
                "pyIntesisHome lost connection to the %s server.", self._device_type
            )
        except (
            TimeoutError,
            ConnectionResetError,
            OSError,
        ) as exc:
            _LOGGER.error(
                "pyIntesisHome lost connection to the %s server. Exception: %s",
                self._device_type,
                exc,
            )
        finally:
            self._connected = False
            self._connecting = False
            await self._send_update_callback()

    def _parse_id_received(self, args):
        # ID:Model,MAC,IP,Protocol,Version,RSSI
        info = args.split(",")
        if len(info) >= 6:
            self._info["deviceModel"] = info[0]
            self._mac = info[1]
            self._device_id = info[1]
            self._info["firmware"] = info[4]
            self._info["rssi"] = info[5]
        self._controller_id = self._mac.lower()
        self._controller_name = f"{self._info['deviceModel']} ({self._mac[-4:]})"

        # Setup devices
        if self._device_id not in self._devices:
            self._devices[self._device_id] = {
                "name": f"{self._device_type} {self._mac[-4:]}",
                "widgets": [],
                "model": self._info["deviceModel"],
            }
        _LOGGER.debug(repr(self._devices))

    async def _send_command(self, command: str):
        try:
            _LOGGER.debug(f"Sending command '{command}'")
            self._received_response.clear()
            self._writer.write(command.encode("ascii"))
            await self._writer.drain()
            try:
                await asyncio.wait_for(
                    self._received_response.wait(),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                print("oops took longer than 5s!")
        except Exception as e:
            _LOGGER.error("%s Exception. %s / %s", type(e), e.args, e)

    def _parse_change_received(self, args):
        function, value = args.split(",")

        if value == INTESIS_NULL:
            value = None

        self._devices[self._device_id][
            INTESISBOX_MAP.get(function, function.lower())
        ] = value.lower()

    def _parse_limits_received(self, args):
        split_args = args.split(",", 1)

        if len(split_args) == 2:
            function = split_args[0]
            values = split_args[1][1:-1].lower().split(",")

            if function == INTESISBOX_CMD_SETPOINT and len(values) == 2:
                self._devices[self._device_id]["setpoint_min"] = int(values[0])
                self._devices[self._device_id]["setpoint_max"] = int(values[1])
            elif function == INTESISBOX_CMD_FANSP:
                self._devices[self._device_id]["config_fan_map"] = values
            elif function == INTESISBOX_CMD_MODE:
                self._devices[self._device_id]["mode_list"] = values
            elif function == INTESISBOX_CMD_VANEUD:
                self._devices[self._device_id]["vvane_list"] = values
            elif function == INTESISBOX_CMD_VANELR:
                self._devices[self._device_id]["hvane_list"] = values
        return

    async def set_mode(self, device_id, mode: str):
        """Internal method for setting the mode with a string value."""
        if mode in INTESISBOX_MODE_MAP:
            await self._set_value(device_id, "MODE", INTESISBOX_MODE_MAP[mode])

    async def _request_values(self) -> dict:
        """Get all entity values."""
        raise NotImplementedError()
        # response = await self._request(LOCAL_CMD_GET_DP_VALUE, uid="all")
        # self._values = {dpval["uid"]: dpval["value"] for dpval in response["dpval"]}
        # return self._values

    async def _send_keepalive(self):
        """Run a loop that updates the values every _scan_interval."""
        while True:
            await asyncio.sleep(30)
            await self._send_command("GET,1:AMBTEMP")

    async def _authenticate(self) -> bool:
        """Authenticate using username and password."""
        raise NotImplementedError()

    async def _set_value(self, device_id, uid, value):
        """Internal method to send a command to the API"""
        command = f"SET,1:{uid},{value}\r"
        await self._send_command(command)

    async def set_power_off(self, device_id=None):
        """Public method to turn off the device asynchronously."""
        await self._set_value(device_id, INTESISBOX_CMD_ONOFF, "OFF")

    async def set_power_on(self, device_id=None):
        """Public method to turn on the device asynchronously."""
        await self._set_value(device_id, INTESISBOX_CMD_ONOFF, "ON")

    async def set_temperature(self, device_id, setpoint):
        """Public method for setting the temperature"""
        set_temp = uint32(setpoint * 10)
        await self._set_value(device_id, INTESISBOX_CMD_SETPOINT, set_temp)

    async def set_fan_speed(self, device_id, fan: str):
        """Public method to set the fan speed"""
        await self._set_value(device_id, INTESISBOX_CMD_FANSP, fan)

    async def set_vertical_vane(self, device_id, vane: str):
        """Public method to set the vertical vane"""
        await self._set_value(device_id, INTESISBOX_CMD_VANEUD, vane)

    async def set_horizontal_vane(self, device_id, vane: str):
        """Public method to set the horizontal vane"""
        await self._set_value(device_id, INTESISBOX_CMD_VANELR, vane)

    async def stop(self):
        """Disconnect and stop periodic updater."""
        _LOGGER.debug("Stopping receive task.")
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                _LOGGER.debug("Receive task cancelled")

    async def poll_status(self, sendcallback=False):
        if self._connected:
            _LOGGER.debug("Polling status")
            try:
                self._writer.write(INTESISBOX_CMD_GET_AVAIL_DP.encode("ascii"))
                await self._writer.drain()
            except Exception as e:
                _LOGGER.error("%s Exception. %s / %s", type(e), e.args, e)

    def get_mode_list(self, device_id) -> list:
        """Get possible entity modes."""
        return self._devices[self._device_id].get("mode_list")

    def _get_fan_map(self, device_id):
        fan_map_list = self._devices[self._device_id].get("config_fan_map")
        if isinstance(fan_map_list, list):
            return dict(zip(fan_map_list, fan_map_list))
        else:
            return None
