""" Main submodule for pyintesishome """
import asyncio
import json
import logging
import socket
from datetime import datetime

import aiohttp

from .const import (
    API_URL,
    API_VER,
    COMMAND_MAP,
    CONFIG_MODE_BITS,
    DEVICE_INTESISHOME,
    ERROR_MAP,
    INTESIS_CMD_STATUS,
    INTESIS_MAP,
    INTESIS_NULL,
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


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-public-methods
class IntesisHomeBase:
    """pyintesishome base class"""

    def __init__(
        self,
        username,
        password,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
    ):
        # Select correct API for device type
        self._device_type = device_type
        self._username = username
        self._password = password
        self._devices = {}
        self._connected = False
        self._connecting = False
        self._connection_retries = 0
        self._update_callbacks = []
        self._error_message = None
        self._web_session = websession
        self._own_session = False

        if loop:
            _LOGGER.debug("Using the provided event loop")
            self._event_loop = loop
        else:
            _LOGGER.debug("Getting the running loop from asyncio")
            self._event_loop = asyncio.get_running_loop()

        if not self._web_session:
            _LOGGER.debug("Creating new websession")
            self._web_session = aiohttp.ClientSession()
            self._own_session = True

    async def _set_value(self, device_id, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        raise NotImplementedError()

    def _update_device_state(self, device_id, uid, value):
        """Internal method to update the state table of IntesisHome/Airconwithme devices"""
        device_id = str(device_id)

        if uid in INTESIS_MAP:
            # If the value is null (32768), set as None
            if value == INTESIS_NULL:
                self._devices[device_id][INTESIS_MAP[uid]["name"]] = None
            else:
                # Translate known UIDs to configuration item names
                value_map = INTESIS_MAP[uid].get("values")
                if value_map:
                    self._devices[device_id][INTESIS_MAP[uid]["name"]] = value_map.get(
                        value, value
                    )
                else:
                    self._devices[device_id][INTESIS_MAP[uid]["name"]] = value
        else:
            # Log unknown UIDs
            self._devices[device_id][f"unknown_uid_{uid}"] = value

    def _update_rssi(self, device_id, rssi):
        """Internal method to update the wireless signal strength."""
        if rssi and str(device_id) in self._devices:
            self._devices[str(device_id)]["rssi"] = rssi

    async def connect(self):
        """Public method for connecting to API"""
        raise NotImplementedError()

    async def stop(self):
        """Public method for shutting down connectivity."""
        raise NotImplementedError()

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device.
        Notifies subscribers if sendCallback True."""
        raise NotImplementedError()

    def get_devices(self):
        """Public method to return the state of all IntesisHome devices"""
        return self._devices

    def get_device(self, device_id):
        """Public method to return the state of the specified device"""
        return self._devices.get(str(device_id))

    def get_device_property(self, device_id, property_name):
        """Public method to get a property of the specified device"""
        return self._devices[str(device_id)].get(property_name)

    def get_run_hours(self, device_id) -> str:
        """Public method returns the run hours of the IntesisHome controller."""
        run_hours = self.get_device_property(device_id, "working_hours")
        return run_hours

    async def set_mode(self, device_id, mode: str):
        """Internal method for setting the mode with a string value."""
        mode_control = "mode"
        if "mode" not in self._devices[str(device_id)]:
            mode_control = "operating_mode"

        if mode in COMMAND_MAP[mode_control]["values"]:
            await self._set_value(
                device_id,
                COMMAND_MAP[mode_control]["uid"],
                COMMAND_MAP[mode_control]["values"][mode],
            )

    async def set_preset_mode(self, device_id, preset: str):
        """Internal method for setting the mode with a string value."""
        if preset in COMMAND_MAP["climate_working_mode"]["values"]:
            await self._set_value(
                device_id,
                COMMAND_MAP["climate_working_mode"]["uid"],
                COMMAND_MAP["climate_working_mode"]["values"][preset],
            )

    async def set_temperature(self, device_id, setpoint):
        """Public method for setting the temperature"""
        set_temp = uint32(setpoint * 10)
        await self._set_value(device_id, COMMAND_MAP["setpoint"]["uid"], set_temp)

    async def set_fan_speed(self, device_id, fan: str):
        """Public method to set the fan speed"""
        fan_map = self._get_fan_map(device_id)
        map_fan_speed_to_int = {v: k for k, v in fan_map.items()}
        await self._set_value(
            device_id, COMMAND_MAP["fan_speed"]["uid"], map_fan_speed_to_int[fan]
        )

    async def set_vertical_vane(self, device_id, vane: str):
        """Public method to set the vertical vane"""
        await self._set_value(
            device_id, COMMAND_MAP["vvane"]["uid"], COMMAND_MAP["vvane"]["values"][vane]
        )

    async def set_horizontal_vane(self, device_id, vane: str):
        """Public method to set the horizontal vane"""
        await self._set_value(
            device_id, COMMAND_MAP["hvane"]["uid"], COMMAND_MAP["hvane"]["values"][vane]
        )

    async def set_mode_heat(self, device_id):
        """Public method to set device to heat asynchronously."""
        await self.set_mode(device_id, "heat")

    async def set_mode_cool(self, device_id):
        """Public method to set device to cool asynchronously."""
        await self.set_mode(device_id, "cool")

    async def set_mode_fan(self, device_id):
        """Public method to set device to fan asynchronously."""
        await self.set_mode(device_id, "fan")

    async def set_mode_auto(self, device_id):
        """Public method to set device to auto asynchronously."""
        await self.set_mode(device_id, "auto")

    async def set_mode_dry(self, device_id):
        """Public method to set device to dry asynchronously."""
        await self.set_mode(device_id, "dry")

    async def set_power_off(self, device_id):
        """Public method to turn off the device asynchronously."""
        await self._set_value(
            device_id,
            COMMAND_MAP["power"]["uid"],
            COMMAND_MAP["power"]["values"]["off"],
        )

    async def set_power_on(self, device_id):
        """Public method to turn on the device asynchronously."""
        await self._set_value(
            device_id, COMMAND_MAP["power"]["uid"], COMMAND_MAP["power"]["values"]["on"]
        )

    def get_mode(self, device_id) -> str:
        """Public method returns the current mode of operation."""
        if "mode" in self._devices[str(device_id)]:
            return self._devices[str(device_id)]["mode"]
        if "operating_mode" in self._devices[str(device_id)]:
            return self._devices[str(device_id)]["operating_mode"]
        return None

    def get_mode_list(self, device_id) -> list:
        """Public method to return the list of device modes."""
        mode_list = list()

        # By default, use config_mode_map to determine the available modes
        mode_map = self.get_device_property(device_id, "config_mode_map")
        mode_bits = CONFIG_MODE_BITS

        if "config_operating_mode" in self._devices[str(device_id)]:
            # If config_operating_mode is supplied, use that
            mode_map = self.get_device_property(device_id, "config_operating_mode")
            mode_bits = OPERATING_MODE_BITS

        # Generate the mode list from the map
        for mode_bit in mode_bits:
            if mode_map & mode_bit:
                mode_list.append(mode_bits.get(mode_bit))

        return mode_list

    def get_fan_speed(self, device_id):
        """Public method returns the current fan speed."""
        fan_map = self._get_fan_map(device_id)

        if "fan_speed" in self._devices[str(device_id)] and isinstance(fan_map, dict):
            fan_speed = self.get_device_property(device_id, "fan_speed")
            return fan_map.get(fan_speed, fan_speed)
        return None

    def get_fan_speed_list(self, device_id):
        """Public method to return the list of possible fan speeds."""
        fan_map = self._get_fan_map(device_id)
        if isinstance(fan_map, dict):
            return list(fan_map.values())
        return None

    def get_device_name(self, device_id) -> str:
        """Public method to get the name of a device."""
        return self.get_device_property(device_id, "name")

    def get_power_state(self, device_id) -> str:
        """Public method returns the current power state."""
        return self.get_device_property(device_id, "power")

    def get_instant_power_consumption(self, device_id) -> int:
        """Public method returns the current power state."""
        instant_power = self.get_device_property(device_id, "instant_power_consumption")
        if instant_power:
            return int(instant_power)
        return None

    def get_total_power_consumption(self, device_id) -> int:
        """Public method returns the current power state."""
        accumulated_power = self.get_device_property(
            device_id, "accumulated_power_consumption"
        )
        if accumulated_power:
            return int(accumulated_power)
        return None

    def get_cool_power_consumption(self, device_id) -> int:
        """Public method returns the current power state."""
        aquarea_cool = self.get_device_property(device_id, "aquarea_cool_consumption")
        if aquarea_cool:
            return int(aquarea_cool)
        return None

    def get_heat_power_consumption(self, device_id) -> int:
        """Public method returns the current power state."""
        aquarea_heat = self.get_device_property(device_id, "aquarea_heat_consumption")
        if aquarea_heat:
            return int(aquarea_heat)
        return None

    def get_tank_power_consumption(self, device_id) -> int:
        """Public method returns the current power state."""
        aquarea_tank = self.get_device_property(device_id, "aquarea_tank_consumption")
        if aquarea_tank:
            return int(aquarea_tank)
        return None

    def get_preset_mode(self, device_id) -> str:
        """Public method to get the current set preset mode."""
        return self.get_device_property(device_id, "climate_working_mode")

    def is_on(self, device_id) -> bool:
        """Return true if the controlled device is turned on"""
        return self.get_device_property(device_id, "power") == "on"

    def has_vertical_swing(self, device_id) -> bool:
        """Public method to check if the device has vertical swing."""
        vvane_config = self.get_device_property(device_id, "config_vertical_vanes")
        return bool(vvane_config and vvane_config > 1024)

    def has_horizontal_swing(self, device_id) -> bool:
        """Public method to check if the device has horizontal swing."""
        hvane_config = self.get_device_property(device_id, "config_horizontal_vanes")
        return bool(hvane_config and hvane_config > 1024)

    def has_setpoint_control(self, device_id) -> bool:
        """Public method to check if the device has setpoint control."""
        return "setpoint" in self._devices[str(device_id)]

    def get_setpoint(self, device_id) -> float:
        """Public method returns the target temperature."""
        setpoint = self.get_device_property(device_id, "setpoint")
        if setpoint:
            setpoint = int(setpoint) / 10
        return setpoint

    def get_temperature(self, device_id) -> float:
        """Public method returns the current temperature."""
        temperature = self.get_device_property(device_id, "temperature")
        if temperature:
            temperature = twos_complement_16bit(int(temperature)) / 10
        return temperature

    def get_outdoor_temperature(self, device_id) -> float:
        """Public method returns the current temperature."""
        outdoor_temp = self.get_device_property(device_id, "outdoor_temp")
        if outdoor_temp:
            outdoor_temp = twos_complement_16bit(int(outdoor_temp)) / 10
        return outdoor_temp

    def get_max_setpoint(self, device_id) -> float:
        """Public method returns the current maximum target temperature."""
        temperature = self.get_device_property(device_id, "setpoint_max")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_min_setpoint(self, device_id) -> float:
        """Public method returns the current minimum target temperature."""
        temperature = self.get_device_property(device_id, "setpoint_min")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_rssi(self, device_id) -> str:
        """Public method returns the current wireless signal strength."""
        rssi = self.get_device_property(device_id, "rssi")
        return rssi

    def get_vertical_swing(self, device_id) -> str:
        """Public method returns the current vertical vane setting."""
        swing = self.get_device_property(device_id, "vvane")
        return swing

    def get_horizontal_swing(self, device_id) -> str:
        """Public method returns the current horizontal vane setting."""
        swing = self.get_device_property(device_id, "hvane")
        return swing

    def get_error(self, device_id) -> str:
        """Public method returns the current error code + description."""
        error_code = self.get_device_property(device_id, "error_code")
        remote_code = ERROR_MAP[error_code]["code"]
        error_desc = ERROR_MAP[error_code]["desc"]
        return "%s: %s" % (remote_code, error_desc)

    def _get_gen_value(self, device_id, name) -> str:
        """Internal method for getting generic value"""
        value = None
        if name in self._devices[str(device_id)]:
            value = self.get_device_property(device_id, name)
            _LOGGER.debug("%s = %s", name, value)
        else:
            _LOGGER.debug("No value for %s %s", device_id, name)
        return value

    def _get_gen_num_value(self, device_id, name):
        """Internal method for getting generic value and dividing by 10 if numeric"""
        value = self._get_gen_value(device_id, name)
        if isinstance(value, (int, float)):
            temperature = float(value / 10)
            return temperature
        return value

    def _set_gen_mode(self, device_id, gen_type, mode):
        """Internal method for setting the generic mode (gen_type in
        {operating_mode, climate_working_mode, tank, etc.}) with a string value"""
        if mode in COMMAND_MAP[gen_type]["values"]:
            self._set_value(
                device_id,
                COMMAND_MAP[gen_type]["uid"],
                COMMAND_MAP[gen_type]["values"][mode],
            )

    def _set_thermo_shift(self, device_id, name, value):
        """Public method to set thermo shift temperature."""
        min_shift = int(COMMAND_MAP[name]["min"])
        max_shift = int(COMMAND_MAP[name]["max"])

        if min_shift <= value <= max_shift:
            unsigned_value = uint32(value * 10)  # unsigned int 16 bit
            self._set_value(device_id, COMMAND_MAP[name]["uid"], unsigned_value)
        else:
            raise ValueError(
                "Value for %s has to be in range [%d,%d]" % name, min_shift, max_shift
            )

    @property
    def is_connected(self) -> bool:
        """Returns true if the TCP connection is established."""
        return self._connected

    @property
    def connection_retries(self) -> int:
        """Returns the number of connection retries."""
        return self._connection_retries

    @property
    def error_message(self) -> str:
        """Returns the last error message, or None if there were no errors."""
        return self._error_message

    @property
    def device_type(self) -> str:
        """Returns the device type (IntesisHome or airconwithme)."""
        return self._device_type

    @property
    def is_disconnected(self) -> bool:
        """Returns true when the TCP connection is disconnected and idle."""
        return not self._connected and not self._connecting

    async def _send_update_callback(self, device_id=None):
        """Internal method to notify all update callback subscribers."""
        if self._update_callbacks:
            for callback in self._update_callbacks:
                await callback(device_id=device_id)
        else:
            _LOGGER.debug("Update callback has not been set by client")

    async def add_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._update_callbacks.append(method)

    def _get_fan_map(self, device_id):
        """Private method to get the fan_map."""
        raise NotImplementedError()


class IntesisHome(IntesisHomeBase):
    """pyintesishome cloud class"""

    def __init__(
        self,
        username,
        password,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
    ):
        self._api_url = API_URL[device_type]
        self._api_ver = API_VER[device_type]
        self._cmd_server = None
        self._cmd_server_port = None
        self._auth_token = None
        self._send_queue = asyncio.Queue()
        self._send_queue_task = None
        self._keepalive_task = None
        self._reader = None
        self._writer = None
        self._reconnection_attempt = 0
        self._last_message_received = 0

        super().__init__(username, password, loop, websession, device_type)

    async def _parse_api_messages(self, message):
        _LOGGER.debug("%s API Received: %s", self._device_type, message)
        self._last_message_received = datetime.now()
        resp = json.loads(message)
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
        return

    async def _send_keepalive(self):
        if self._connected:
            _LOGGER.debug("sending keepalive")
            message = '{"command":"get"}'
            self._send_queue.put_nowait(message)

    async def _handle_packets(self):
        data = True
        while data:
            try:
                data = await self._reader.readuntil(b"}}")
                if not data:
                    break
                message = data.decode("ascii")
                await self._parse_api_messages(message)

            except (
                asyncio.IncompleteReadError,
                TimeoutError,
                ConnectionResetError,
                OSError,
            ) as exc:
                _LOGGER.error(
                    "pyIntesisHome lost connection to the %s server. Exception: %s",
                    self._device_type,
                    exc,
                )
                break

        self._connected = False
        self._connecting = False
        self._auth_token = None
        self._reader = None
        self._writer = None
        self._send_queue_task.cancel()
        await self._send_update_callback()
        return

    async def _run_send_queue(self):
        while self._connected or self._connecting:
            data = await self._send_queue.get()
            try:
                self._writer.write(data.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Sent command %s", data)
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Exception: %s", exc)
                return

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._connection_retries = 0

            # Get authentication token over HTTP POST
            while not self._auth_token:
                if self._connection_retries:
                    _LOGGER.debug(
                        "Couldn't get API details, retrying in %i minutes",
                        self._connection_retries,
                    )
                    await asyncio.sleep(self._connection_retries * 60)
                try:
                    self._auth_token = await self.poll_status()
                except IHConnectionError as ex:
                    _LOGGER.error(
                        "Error connecting to the %s server: %s", self._device_type, ex
                    )
                self._connection_retries += 1

                _LOGGER.debug(
                    "Opening connection to %s API at %s:%i",
                    self._device_type,
                    self._cmd_server,
                    self._cmd_server_port,
                )

            try:
                # Create asyncio socket
                self._reader, self._writer = await asyncio.open_connection(
                    self._cmd_server, self._cmd_server_port
                )

                # Set socket timeout
                if self._reader._transport._sock:  # pylint: disable=protected-access
                    self._reader._transport._sock.settimeout(  # pylint: disable=protected-access
                        60
                    )
                    try:
                        self._reader._transport._sock.setsockopt(  # pylint: disable=protected-access
                            socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60 * 1000
                        )
                        self._reader._transport._sock.setsockopt(  # pylint: disable=protected-access
                            socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 60 * 1000
                        )
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.debug(
                            "Exception setting TCP_USER_TIMEOUT or SO_KEEPALIVE,"
                            "you can probably ignore this"
                        )

                # Authenticate
                auth_msg = '{"command":"connect_req","data":{"token":%s}}' % (
                    self._auth_token
                )
                # Clear the OTP
                self._auth_token = None
                self._writer.write(auth_msg.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Data sent: %s", auth_msg)
                _LOGGER.debug(
                    "Socket timeout is %s",
                    self._reader._transport._sock.gettimeout(),  # pylint: disable=protected-access
                )

                self._event_loop.create_task(self._handle_packets())
                # self._keepalive_task = self._event_loop.create_task(self._send_keepalive())
                self._send_queue_task = self._event_loop.create_task(
                    self._run_send_queue()
                )

            except (  # pylint: disable=broad-except
                ConnectionRefusedError,
                Exception,
            ) as exc:
                _LOGGER.error(
                    "Connection to %s:%s failed with exception %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    exc,
                )
                self._connected = False
                self._connecting = False
                await self._send_update_callback()

    async def stop(self):
        """Public method for shutting down connectivity with the envisalink."""
        self._connected = False
        if self._writer:
            self._writer._transport.close()  # pylint: disable=protected-access

        if self._reader:
            self._reader._transport.close()  # pylint: disable=protected-access

        if self._own_session:
            await self._web_session.close()

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device.
        Notifies subscribers if sendCallback True."""
        get_status = {
            "username": self._username,
            "password": self._password,
            "cmd": INTESIS_CMD_STATUS,
            "version": self._api_ver,
        }

        status_response = None
        try:
            async with self._web_session.post(
                url=self._api_url, data=get_status
            ) as resp:
                status_response = await resp.json(content_type=None)
                _LOGGER.debug(status_response)
        except (aiohttp.client_exceptions.ClientConnectorError) as exc:
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

            config = status_response.get("config")
            if config:
                self._cmd_server = config.get("serverIP")
                self._cmd_server_port = config.get("serverPort")
                self._auth_token = config.get("token")

                _LOGGER.debug(
                    "Server: %s:%i, Token: %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    self._auth_token,
                )

            # Setup devices
            for installation in config.get("inst"):
                for device in installation.get("devices"):
                    self._devices[device["id"]] = {
                        "name": device["name"],
                        "widgets": device["widgets"],
                        "model": device["modelId"],
                    }
                    _LOGGER.debug(repr(self._devices))

            # Update device status
            for status in status_response["status"]["status"]:
                device_id = str(status["deviceId"])

                # Handle devices which don't appear in installation
                if device_id not in self._devices:
                    self._devices[device_id] = {
                        "name": "Device " + device_id,
                        "widgets": [42],
                    }

                self._update_device_state(device_id, status["uid"], status["value"])

            if sendcallback:
                await self._send_update_callback(device_id=str(device_id))

        return self._auth_token

    async def _set_value(self, device_id, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = (
            '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}'
            % (device_id, uid, value)
        )
        self._send_queue.put_nowait(message)

    def _get_fan_map(self, device_id):
        return self.get_device_property(device_id, "config_fan_map")


class IntesisHomeLocal(IntesisHomeBase):
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
        self._host: str = host
        self._session_id: str = ""
        self._datapoints: dict = {}
        self._scan_interval = 5
        self._device_id: str = ""
        self._values: dict = {}
        self._info: dict = {}
        self._update_task = None
        super().__init__(username, password, loop, websession, device_type)

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
        return INTESIS_MAP[67]["values"][63]

    def has_vertical_swing(self, device_id) -> bool:
        """Entity supports vertical swing."""
        return self._has_datapoint("vvane")

    def has_horizontal_swing(self, device_id) -> bool:
        """Entity supports horizontal swing."""
        return self._has_datapoint("hvane")
