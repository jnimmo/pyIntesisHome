import argparse
import asyncio
import json
import logging
import socket
import sys
from datetime import datetime

import aiohttp

_LOGGER = logging.getLogger("pyintesishome")

from .const import (
    API_URL,
    API_VER,
    COMMAND_MAP,
    CONFIG_MODE_BITS,
    DEVICE_AIRCONWITHME,
    DEVICE_ANYWAIR,
    DEVICE_INTESISHOME,
    DEVICE_INTESISHOME_LOCAL,
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


class IntesisHomeBase:
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
        self._connectionRetires = 0
        self._updateCallbacks = []
        self._errorMessage = None
        self._webSession = websession
        self._ownSession = False

        if loop:
            _LOGGER.debug("Using the provided event loop")
            self._eventLoop = loop
        else:
            _LOGGER.debug("Getting the running loop from asyncio")
            self._eventLoop = asyncio.get_running_loop()

        if not self._webSession:
            _LOGGER.debug("Creating new websession")
            self._webSession = aiohttp.ClientSession()
            self._ownSession = True

    async def _set_value(self, deviceId, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        raise NotImplementedError()

    def _get_value(self, deviceId, uid):
        """Internal method to get a device value"""
        return self._devices[str(deviceId)].get(uid)

    def _update_device_state(self, deviceId, uid, value):
        """Internal method to update the state table of IntesisHome/Airconwithme devices"""
        deviceId = str(deviceId)

        if uid in INTESIS_MAP:
            # If the value is null (32768), set as None
            if value == INTESIS_NULL:
                self._devices[deviceId][INTESIS_MAP[uid]["name"]] = None
            else:
                # Translate known UIDs to configuration item names
                value_map = INTESIS_MAP[uid].get("values")
                if value_map:
                    self._devices[deviceId][INTESIS_MAP[uid]["name"]] = value_map.get(
                        value, value
                    )
                else:
                    self._devices[deviceId][INTESIS_MAP[uid]["name"]] = value
        else:
            # Log unknown UIDs
            self._devices[deviceId][f"unknown_uid_{uid}"] = value

    def _update_rssi(self, deviceId, rssi):
        """Internal method to update the wireless signal strength."""
        if rssi and str(deviceId) in self._devices:
            self._devices[str(deviceId)]["rssi"] = rssi

    async def connect(self):
        """Public method for connecting to API"""
        raise NotImplementedError()

    async def stop(self):
        """Public method for shutting down connectivity."""
        raise NotImplementedError()

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device. Notifies subscribers if sendCallback True."""
        raise NotImplementedError()

    def get_devices(self):
        """Public method to return the state of all IntesisHome devices"""
        return self._devices

    def get_device(self, deviceId):
        """Public method to return the state of the specified device"""
        return self._devices.get(str(deviceId))

    def get_device_property(self, deviceId, property_name):
        """Public method to get a property of the specified device"""
        return self._devices[str(deviceId)].get(property_name)

    def get_run_hours(self, deviceId) -> str:
        """Public method returns the run hours of the IntesisHome controller."""
        run_hours = self._get_value(deviceId, "working_hours")
        return run_hours

    async def set_mode(self, deviceId, mode: str):
        """Internal method for setting the mode with a string value."""
        mode_control = "mode"
        if "mode" not in self._devices[str(deviceId)]:
            mode_control = "operating_mode"

        if mode in COMMAND_MAP[mode_control]["values"]:
            await self._set_value(
                deviceId,
                COMMAND_MAP[mode_control]["uid"],
                COMMAND_MAP[mode_control]["values"][mode],
            )

    async def set_preset_mode(self, deviceId, preset: str):
        """Internal method for setting the mode with a string value."""
        if preset in COMMAND_MAP["climate_working_mode"]["values"]:
            await self._set_value(
                deviceId,
                COMMAND_MAP["climate_working_mode"]["uid"],
                COMMAND_MAP["climate_working_mode"]["values"][preset],
            )

    async def set_temperature(self, deviceId, setpoint):
        """Public method for setting the temperature"""
        set_temp = uint32(setpoint * 10)
        await self._set_value(deviceId, COMMAND_MAP["setpoint"]["uid"], set_temp)

    async def set_fan_speed(self, deviceId, fan: str):
        """Public method to set the fan speed"""
        fan_map = self._get_fan_map(deviceId)
        map_fan_speed_to_int = {v: k for k, v in fan_map.items()}
        await self._set_value(
            deviceId, COMMAND_MAP["fan_speed"]["uid"], map_fan_speed_to_int[fan]
        )

    async def set_vertical_vane(self, deviceId, vane: str):
        """Public method to set the vertical vane"""
        await self._set_value(
            deviceId, COMMAND_MAP["vvane"]["uid"], COMMAND_MAP["vvane"]["values"][vane]
        )

    async def set_horizontal_vane(self, deviceId, vane: str):
        """Public method to set the horizontal vane"""
        await self._set_value(
            deviceId, COMMAND_MAP["hvane"]["uid"], COMMAND_MAP["hvane"]["values"][vane]
        )

    async def set_mode_heat(self, deviceId):
        """Public method to set device to heat asynchronously."""
        await self.set_mode(deviceId, "heat")

    async def set_mode_cool(self, deviceId):
        """Public method to set device to cool asynchronously."""
        await self.set_mode(deviceId, "cool")

    async def set_mode_fan(self, deviceId):
        """Public method to set device to fan asynchronously."""
        await self.set_mode(deviceId, "fan")

    async def set_mode_auto(self, deviceId):
        """Public method to set device to auto asynchronously."""
        await self.set_mode(deviceId, "auto")

    async def set_mode_dry(self, deviceId):
        """Public method to set device to dry asynchronously."""
        await self.set_mode(deviceId, "dry")

    async def set_power_off(self, deviceId):
        """Public method to turn off the device asynchronously."""
        await self._set_value(
            deviceId, COMMAND_MAP["power"]["uid"], COMMAND_MAP["power"]["values"]["off"]
        )

    async def set_power_on(self, deviceId):
        """Public method to turn on the device asynchronously."""
        await self._set_value(
            deviceId, COMMAND_MAP["power"]["uid"], COMMAND_MAP["power"]["values"]["on"]
        )

    def get_mode(self, deviceId) -> str:
        """Public method returns the current mode of operation."""
        if "mode" in self._devices[str(deviceId)]:
            return self._devices[str(deviceId)]["mode"]
        elif "operating_mode" in self._devices[str(deviceId)]:
            return self._devices[str(deviceId)]["operating_mode"]

    def get_mode_list(self, deviceId) -> list:
        """Public method to return the list of device modes."""
        mode_list = list()

        # By default, use config_mode_map to determine the available modes
        mode_map = self._get_value(deviceId, "config_mode_map")
        mode_bits = CONFIG_MODE_BITS

        if "config_operating_mode" in self._devices[str(deviceId)]:
            # If config_operating_mode is supplied, use that
            mode_map = self._get_value(deviceId, "config_operating_mode")
            mode_bits = OPERATING_MODE_BITS

        # Generate the mode list from the map
        for mode_bit in mode_bits.keys():
            if mode_map & mode_bit:
                mode_list.append(mode_bits.get(mode_bit))

        return mode_list

    def get_fan_speed(self, deviceId):
        """Public method returns the current fan speed."""
        fan_map = self._get_fan_map(deviceId)

        if "fan_speed" in self._devices[str(deviceId)] and isinstance(fan_map, dict):
            fan_speed = self._get_value(deviceId, "fan_speed")
            return fan_map.get(fan_speed, fan_speed)
        else:
            return None

    def get_fan_speed_list(self, deviceId):
        """Public method to return the list of possible fan speeds."""
        fan_map = self._get_fan_map(deviceId)
        if isinstance(fan_map, dict):
            return list(fan_map.values())
        else:
            return None

    def get_device_name(self, deviceId) -> str:
        """Public method to get the name of a device."""
        return self._get_value(deviceId, "name")

    def get_power_state(self, deviceId) -> str:
        """Public method returns the current power state."""
        return self._get_value(deviceId, "power")

    def get_instant_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        instant_power = self._get_value(deviceId, "instant_power_consumption")
        if instant_power:
            return int(instant_power)

    def get_total_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        accumulated_power = self._get_value(deviceId, "accumulated_power_consumption")
        if accumulated_power:
            return int(accumulated_power)

    def get_cool_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_cool = self._get_value(deviceId, "aquarea_cool_consumption")
        if aquarea_cool:
            return int(aquarea_cool)

    def get_heat_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_heat = self._get_value(deviceId, "aquarea_heat_consumption")
        if aquarea_heat:
            return int(aquarea_heat)

    def get_tank_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_tank = self._get_value(deviceId, "aquarea_tank_consumption")
        if aquarea_tank:
            return int(aquarea_tank)

    def get_preset_mode(self, deviceId) -> str:
        """Public method to get the current set preset mode."""
        return self._get_value(deviceId, "climate_working_mode")

    def is_on(self, deviceId) -> bool:
        """Return true if the controlled device is turned on"""
        return self._get_value(deviceId, "power") == "on"

    def has_vertical_swing(self, deviceId) -> bool:
        """Public method to check if the device has vertical swing."""
        vvane_config = self._get_value(deviceId, "config_vertical_vanes")
        return vvane_config and vvane_config > 1024

    def has_horizontal_swing(self, deviceId) -> bool:
        """Public method to check if the device has horizontal swing."""
        hvane_config = self._get_value(deviceId, "config_horizontal_vanes")
        return hvane_config and hvane_config > 1024

    def has_setpoint_control(self, deviceId) -> bool:
        """Public method to check if the device has setpoint control."""
        return "setpoint" in self._devices[str(deviceId)]

    def get_setpoint(self, deviceId) -> float:
        """Public method returns the target temperature."""
        setpoint = self._get_value(deviceId, "setpoint")
        if setpoint:
            setpoint = int(setpoint) / 10
        return setpoint

    def get_temperature(self, deviceId) -> float:
        """Public method returns the current temperature."""
        temperature = self._get_value(deviceId, "temperature")
        if temperature:
            temperature = twos_complement_16bit(int(temperature)) / 10
        return temperature

    def get_outdoor_temperature(self, deviceId) -> float:
        """Public method returns the current temperature."""
        outdoor_temp = self._get_value(deviceId, "outdoor_temp")
        if outdoor_temp:
            outdoor_temp = twos_complement_16bit(int(outdoor_temp)) / 10
        return outdoor_temp

    def get_max_setpoint(self, deviceId) -> float:
        """Public method returns the current maximum target temperature."""
        temperature = self._get_value(deviceId, "setpoint_max")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_min_setpoint(self, deviceId) -> float:
        """Public method returns the current minimum target temperature."""
        temperature = self._get_value(deviceId, "setpoint_min")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_rssi(self, deviceId) -> str:
        """Public method returns the current wireless signal strength."""
        rssi = self._get_value(deviceId, "rssi")
        return rssi

    def get_vertical_swing(self, deviceId) -> str:
        """Public method returns the current vertical vane setting."""
        swing = self._get_value(deviceId, "vvane")
        return swing

    def get_horizontal_swing(self, deviceId) -> str:
        """Public method returns the current horizontal vane setting."""
        swing = self._get_value(deviceId, "hvane")
        return swing

    def get_error(self, deviceId) -> str:
        """Public method returns the current error code + description."""
        error_code = self._get_value(deviceId, "error_code")
        remote_code = ERROR_MAP[error_code]["code"]
        error_desc = ERROR_MAP[error_code]["desc"]
        return "%s: %s" % (remote_code, error_desc)

    def _get_gen_value(self, deviceId, name) -> str:
        """Internal method for getting generic value"""
        value = None
        if name in self._devices[str(deviceId)]:
            value = self._get_value(name)
            _LOGGER.debug(f"{name} = {value}")
        else:
            _LOGGER.debug(f"No value for {deviceId} {name}")
        return value

    def _get_gen_num_value(self, deviceId, name):
        """Internal method for getting generic value and dividing by 10 if numeric"""
        value = self._get_gen_value(deviceId, name)
        if isinstance(value, int) or isinstance(value, float):
            temperature = float(value / 10)
            return temperature
        else:
            return value

    def _set_gen_mode(self, deviceId, type, mode):
        """Internal method for setting the generic mode (type in {operating_mode, climate_working_mode, tank, etc.}) with a string value"""
        if mode in COMMAND_MAP[type]["values"]:
            self._set_value(
                deviceId, COMMAND_MAP[type]["uid"], COMMAND_MAP[type]["values"][mode]
            )

    def _set_thermo_shift(self, deviceId, name, value):
        """Public method to set thermo shift temperature."""
        min_shift = int(COMMAND_MAP[name]["min"])
        max_shift = int(COMMAND_MAP[name]["max"])

        if min_shift <= value <= max_shift:
            unsigned_value = uint32(value * 10)  # unsigned int 16 bit
            self._set_value(deviceId, COMMAND_MAP[name]["uid"], unsigned_value)
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
        return self._connectionRetires

    @property
    def error_message(self) -> str:
        """Returns the last error message, or None if there were no errors."""
        return self._errorMessage

    @property
    def device_type(self) -> str:
        """Returns the device type (IntesisHome or airconwithme)."""
        return self._device_type

    @property
    def is_disconnected(self) -> bool:
        """Returns true when the TCP connection is disconnected and idle."""
        return not self._connected and not self._connecting

    async def _send_update_callback(self, deviceId=None):
        """Internal method to notify all update callback subscribers."""
        if self._updateCallbacks:
            for callback in self._updateCallbacks:
                await callback(device_id=deviceId)
        else:
            _LOGGER.debug("Update callback has not been set by client")

    async def add_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._updateCallbacks.append(method)

    def _get_fan_map(self, deviceId):
        """Private method to get the fan_map."""
        raise NotImplementedError()


class IntesisHome(IntesisHomeBase):
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
        self._cmdServer = None
        self._cmdServerPort = None
        self._authToken = None
        self._sendQueue = asyncio.Queue()
        self._sendQueueTask = None
        self._keepaliveTask = None
        self._reader = None
        self._writer = None
        self._reconnectionAttempt = 0
        self._last_message_received = 0

        super().__init__(username, password, loop, websession, device_type)

    async def _parse_api_messages(self, message):
        _LOGGER.debug(f"{self._device_type} API Received: {message}")
        self._last_message_received = datetime.now()
        resp = json.loads(message)
        # Parse response
        if resp["command"] == "connect_rsp":
            # New connection success
            if resp["data"]["status"] == "ok":
                _LOGGER.info(f"{self._device_type} succesfully authenticated")
                self._connected = True
                self._connecting = False
                self._connectionRetires = 0
                await self._send_update_callback()
        elif resp["command"] == "status":
            # Value has changed
            self._update_device_state(
                resp["data"]["deviceId"],
                resp["data"]["uid"],
                resp["data"]["value"],
            )
            if resp["data"]["uid"] != 60002:
                await self._send_update_callback(deviceId=str(resp["data"]["deviceId"]))
        elif resp["command"] == "rssi":
            # Wireless strength has changed
            self._update_rssi(resp["data"]["deviceId"], resp["data"]["value"])
        return

    async def _send_keepalive(self):
        if self._connected:
            _LOGGER.debug("sending keepalive")
            message = '{"command":"get"}'
            self._sendQueue.put_nowait(message)

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
            ) as e:
                _LOGGER.error(
                    "pyIntesisHome lost connection to the %s server. Exception: %s",
                    self._device_type,
                    e,
                )
                break

        self._connected = False
        self._connecting = False
        self._authToken = None
        self._reader = None
        self._writer = None
        self._sendQueueTask.cancel()
        await self._send_update_callback()
        return

    async def _send_queue(self):
        while self._connected or self._connecting:
            data = await self._sendQueue.get()
            try:
                self._writer.write(data.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug(f"Sent command {data}")
            except Exception as e:
                _LOGGER.error(f"Exception: {repr(e)}")
                return

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._connectionRetires = 0

            # Get authentication token over HTTP POST
            while not self._authToken:
                if self._connectionRetires:
                    _LOGGER.debug(
                        "Couldn't get API details, retrying in %i minutes",
                        self._connectionRetires,
                    )
                    await asyncio.sleep(self._connectionRetires * 60)
                try:
                    self._authToken = await self.poll_status()
                except IHConnectionError as ex:
                    _LOGGER.error(
                        "Error connecting to the %s server: %s", self._device_type, ex
                    )
                self._connectionRetires += 1

                _LOGGER.debug(
                    "Opening connection to %s API at %s:%i",
                    self._device_type,
                    self._cmdServer,
                    self._cmdServerPort,
                )

            try:
                # Create asyncio socket
                self._reader, self._writer = await asyncio.open_connection(
                    self._cmdServer, self._cmdServerPort
                )

                # Set socket timeout
                if self._reader._transport._sock:
                    self._reader._transport._sock.settimeout(60)
                    try:
                        self._reader._transport._sock.setsockopt(
                            socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60 * 1000
                        )
                        self._reader._transport._sock.setsockopt(
                            socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 60 * 1000
                        )
                    except:
                        _LOGGER.debug(
                            "Exception seting TCP_USER_TIMEOUT or SO_KEEPALIVE, you can probably ignore this"
                        )

                # Authenticate
                authMsg = '{"command":"connect_req","data":{"token":%s}}' % (
                    self._authToken
                )
                # Clear the OTP
                self._authToken = None
                self._writer.write(authMsg.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Data sent: %s", authMsg)
                _LOGGER.debug(
                    "Socket timeout is %s", self._reader._transport._sock.gettimeout()
                )

                self._eventLoop.create_task(self._handle_packets())
                # self._keepaliveTask = self._eventLoop.create_task(self._send_keepalive())
                self._sendQueueTask = self._eventLoop.create_task(self._send_queue())

            except (ConnectionRefusedError, Exception) as e:
                _LOGGER.error(
                    "Connection to %s:%s failed with exception %s",
                    self._cmdServer,
                    self._cmdServerPort,
                    e,
                )
                self._connected = False
                self._connecting = False
                await self._send_update_callback()

    async def stop(self):
        """Public method for shutting down connectivity with the envisalink."""
        self._connected = False
        if self._writer:
            self._writer._transport.close()

        if self._reader:
            self._reader._transport.close()

        if self._ownSession:
            await self._webSession.close()

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device. Notifies subscribers if sendCallback True."""
        get_status = {
            "username": self._username,
            "password": self._password,
            "cmd": INTESIS_CMD_STATUS,
            "version": self._api_ver,
        }

        status_response = None
        try:
            async with self._webSession.post(
                url=self._api_url, data=get_status
            ) as resp:
                status_response = await resp.json(content_type=None)
                _LOGGER.debug(status_response)
        except (aiohttp.client_exceptions.ClientConnectorError) as e:
            raise IHConnectionError
        except (aiohttp.client_exceptions.ClientError, socket.gaierror) as e:
            self._errorMessage = f"Error connecting to {self._device_type} API: {e}"
            _LOGGER.error(f"{type(e)} Exception. {repr(e.args)} / {e}")
            raise IHConnectionError

        if status_response:
            if "errorCode" in status_response:
                self._errorMessage = status_response["errorMessage"]
                _LOGGER.error(f"Error from API {repr(self._errorMessage)}")
                raise IHAuthenticationError()
                return

            config = status_response.get("config")
            if config:
                self._cmdServer = config.get("serverIP")
                self._cmdServerPort = config.get("serverPort")
                self._authToken = config.get("token")

                _LOGGER.debug(
                    "Server: %s:%i, Token: %s",
                    self._cmdServer,
                    self._cmdServerPort,
                    self._authToken,
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
                deviceId = str(status["deviceId"])

                # Handle devices which don't appear in installation
                if deviceId not in self._devices:
                    self._devices[deviceId] = {
                        "name": "Device " + deviceId,
                        "widgets": [42],
                    }

                self._update_device_state(deviceId, status["uid"], status["value"])

            if sendcallback:
                await self._send_update_callback(deviceId=str(deviceId))

        return self._authToken

    async def _set_value(self, deviceId, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = (
            '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}'
            % (deviceId, uid, value)
        )
        self._sendQueue.put_nowait(message)

    def _get_fan_map(self, deviceId):
        return self._get_value(deviceId, "config_fan_map")


class IntesisHomeLocal(IntesisHomeBase):
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

        response = await self._webSession.post(
            f"http://{self._host}/api.cgi", json=payload
        )

        if response.status != 200:
            raise IHConnectionError("HTTP response status is unexpected (not 200)")

        json_response = await response.json()

        if not json_response["success"]:
            if json_response["error"]["code"] in [1, 5]:
                if self._connectionRetires:
                    raise IHAuthenticationError(json_response["error"]["message"])

                # Try to reauthenticate once
                _LOGGER.debug("Request failed. Trying to reauthenticate.")
                self._connectionRetires += 1
                await self._authenticate()
                return await self._request(command, **kwargs)
            raise IHConnectionError(json_response["error"]["message"])

        self._connectionRetires = 0
        return json_response.get("data")

    async def _request_value(self, name: str) -> dict:
        """Get entity value by uid."""
        response = await self._request(
            LOCAL_CMD_GET_DP_VALUE, uid=COMMAND_MAP[name]["uid"]
        )
        return response["dpval"]["value"]

    async def _set_value(self, deviceId, uid, value):
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
        if not datapoint in COMMAND_MAP:
            return False
        return COMMAND_MAP[datapoint]["uid"] in self._datapoints

    async def connect(self):
        """Connect to the device and start periodic updater."""
        await self._authenticate()
        _LOGGER.debug("Succesful authenticated. Fetching Datapoints.")
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

        if self._ownSession:
            await self._webSession.close()

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

    def _get_fan_map(self, deviceId):
        uid = COMMAND_MAP["fan_speed"]["uid"]
        return {
            i: INTESIS_MAP[uid]["values"][i]
            for i in self._datapoints[uid]["descr"]["states"]
        }

    def has_vertical_swing(self, deviceId) -> bool:
        """Entity supports vertical swing."""
        return self._has_datapoint("vvane")

    def has_horizontal_swing(self, deviceId) -> bool:
        """Entity supports horizontal swing."""
        return self._has_datapoint("hvane")


async def main(loop):
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(description="Commands: mode fan temp")
    parser.add_argument(
        "--user",
        type=str,
        dest="user",
        help="username for user.intesishome.com",
        metavar="USER",
        default=None,
    )
    parser.add_argument(
        "--password",
        type=str,
        dest="password",
        help="password for user.intesishome.com",
        metavar="PASSWORD",
        default=None,
    )
    parser.add_argument(
        "--device",
        type=str,
        dest="device",
        help="Select API to connect to",
        choices=[
            DEVICE_INTESISHOME,
            DEVICE_AIRCONWITHME,
            DEVICE_ANYWAIR,
            DEVICE_INTESISHOME_LOCAL,
        ],
        default=DEVICE_INTESISHOME,
    )
    parser.add_argument(
        "--host",
        type=str,
        dest="host",
        help="Host IP or name when using device intesishome_local",
        metavar="HOST",
        default=None,
    )
    args = parser.parse_args()

    if (not args.user) or (not args.password):
        parser.print_help(sys.stderr)
        sys.exit(0)

    if args.device == DEVICE_INTESISHOME_LOCAL:
        controller = IntesisHomeLocal(
            args.host, args.user, args.password, loop=loop, device_type=args.device
        )
    else:
        controller = IntesisHome(
            args.user, args.password, loop=loop, device_type=args.device
        )
    await controller.connect()
    print(repr(controller.get_devices()))
    await controller.stop()


if __name__ == "__main__":
    import time

    s = time.perf_counter()
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main(loop))
    elapsed = time.perf_counter() - s
    print(f"{__file__} executed in {elapsed:0.2f} seconds.")
