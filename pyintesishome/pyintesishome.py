import argparse
import asyncio
import json
import logging
import sys
import socket
import aiohttp

from datetime import datetime

_LOGGER = logging.getLogger("pyintesishome")

INTESIS_CMD_STATUS = '{"status":{"hash":"x"},"config":{"hash":"x"}}'
INTESIS_NULL = 32768

DEVICE_INTESISHOME = "IntesisHome"
DEVICE_AIRCONWITHME = "airconwithme"

API_DISCONNECTED = "Disconnected"
API_CONNECTING = "Connecting"
API_AUTHENTICATED = "Connected"
API_AUTH_FAILED = "Wrong username/password"

CONFIG_MODE_BITS = {1: "auto", 2: "heat", 4: "dry", 8: "fan", 16: "cool"}
OPERATING_MODE_BITS = {
                        1: "heat",
                        2: "heat+tank",
                        4: "tank",
                        8: "cool+tank",
                        16: "cool",
                        32: "auto",
                        64: "auto+tank"
                      }

INTESIS_MAP = {
    1: {"name": "power", "values": {0: "off", 1: "on"}},
    2: {
        "name": "mode",
        "values": {0: "auto", 1: "heat", 2: "dry", 3: "fan", 4: "cool"},
    },
    4: {"name": "fan_speed"},
    5: {
        "name": "vvane",
        "values": {
            0: "auto/stop",
            1: "manual1",
            2: "manual2",
            3: "manual3",
            4: "manual4",
            5: "manual5",
            6: "manual6",
            7: "manual7",
            8: "manual8",
            9: "manual9",
            10: "swing",
        },
    },
    6: {
        "name": "hvane",
        "values": {
            0: "auto/stop",
            10: "swing",
            1: "manual1",
            2: "manual2",
            3: "manual3",
            4: "manual4",
            5: "manual5",
        },
    },
    9: {"name": "setpoint"},
    10: {"name": "temperature"},
    12: {"name": "remote_controller_lock"},
    13: {"name": "working_hours"},
    14: {"name": "alarm_status"},
    15: {"name": "error_code"},
    34: {"name": "quiet_mode", "values": {0: "off", 1: "on"}},
    35: {"name": "setpoint_min"},
    36: {"name": "setpoint_max"},
    37: {"name": "outdoor_temp"},
    38: {"name": "water_outlet_temperature"},
    39: {"name": "water_inlet_temperature"},
    42: {
        "name": "climate_working_mode",
        "values": {0: "comfort", 1: "eco", 2: "powerful"},
    },
    44: {
        "name": "tank_working_mode",
        "values": {0: "comfort", 1: "eco", 2: "powerful"},
    },
    45: {"name": "tank_water_temperature"},
    46: {"name": "solar_status"},
    48: {"name": "thermoshift_heat_eco"},
    49: {"name": "thermoshift_cool_eco"},
    50: {"name": "thermoshift_heat_powerful"},
    51: {"name": "thermoshift_cool_powerful"},
    52: {"name": "thermoshift_tank_eco"},
    53: {"name": "thermoshift_tank_powerful"},
    54: {"name": "error_reset"},
    55: {"name": "heat_thermo_shift"},
    56: {"name": "cool_water_setpoint_temperature"},
    57: {"name": "tank_setpoint_temperature"},
    58: {
        "name": "operating_mode",
        "values": {
            0: "maintenance",
            1: "heat",
            2: "heat+tank",
            3: "tank",
            4: "cool+tank",
            5: "cool",
            6: "auto",
            7: "auto+tank",
        },
    },
    60: {"name": "heat_8_10"},
    61: {"name": "config_mode_map"},
    62: {"name": "runtime_mode_restrictions"},
    63: {"name": "config_horizontal_vanes"},
    64: {"name": "config_vertical_vanes"},
    65: {"name": "config_quiet"},
    66: {"name": "config_confirm_off"},
    67: {
        "name": "config_fan_map",
        "values": {
            6: {1: "low", 2: "high"},
            7: {0: "auto", 1: "low", 2: "high"},
            14: {1: "low", 2: "medium", 3: "high"},
            15: {0: "auto", 1: "low", 2: "medium", 3: "high"},
            30: {1: "quiet", 2: "low", 3: "medium", 4: "high"},
            31: {0: "auto", 1: "quiet", 2: "low", 3: "medium", 4: "high"},
            62: {1: "quiet", 2: "low", 3: "medium", 4: "high", 5: "max"},
            63: {0: "auto", 1: "quiet", 2: "low", 3: "medium", 4: "high", 5: "max"},
        },
    },
    68: {"name": "instant_power_consumption"},
    69: {"name": "accumulated_power_consumption"},
    75: {"name": "config_operating_mode"},
    77: {"name": "config_vanes_pulse"},
    80: {"name": "aquarea_tank_consumption"},
    81: {"name": "aquarea_cool_consumption"},
    82: {"name": "aquarea_heat_consumption"},
    83: {"name": "heat_high_water_set_temperature"},
    84: {"name": "heating_off_temperature"},
    87: {"name": "heater_setpoint_temperature"},
    90: {"name": "water_target_temperature"},
    95: {
        "name": "heat_interval",
        "values": {
            1: 30,
            2: 60,
            3: 90,
            4: 120,
            5: 150,
            6: 180,
            7: 210,
            8: 240,
            9: 270,
            10: 300,
            11: 330,
            12: 360,
            13: 390,
            14: 420,
            15: 450,
            16: 480,
            17: 510,
            18: 540,
            19: 570,
            20: 600,
        },
    },
    107: {"name": "aquarea_working_hours"},
    123: {"name": "ext_thermo_control", "values": {85: "off", 170: "on"}},
    124: {"name": "tank_present", "values": {85: "off", 170: "on"}},
    125: {"name": "solar_priority", "values": {85: "off", 170: "on"}},
    134: {"name": "heat_low_outdoor_set_temperature"},
    135: {"name": "heat_high_outdoor_set_temperature"},
    136: {"name": "heat_low_water_set_temperature"},
    137: {"name": "farenheit_type"},
    140: {"name": "extremes_protection_status"},
    144: {"name": "error_code"},
    148: {"name": "extremes_protection"},
    149: {"name": "binary_input"},
    153: {"name": "config_binary_input"},
    168: {"name": "uid_binary_input_on_off"},
    169: {"name": "uid_binary_input_occupancy"},
    170: {"name": "uid_binary_input_window"},
    181: {"name": "mainenance_w_reset"},
    182: {"name": "mainenance_wo_reset"},
    183: {"name": "filter_clean"},
    184: {"name": "filter_due_hours"},
    185: {"name": "uid_185"},
    186: {"name": "uid_186"},
    191: {"name": "uid_binary_input_sleep_mode"},
    50000: {
        "name": "external_led",
        "values": {0: "off", 1: "on", 2: "blinking only on change"},
    },
    50001: {"name": "internal_led", "values": {0: "off", 1: "on"}},
    50002: {"name": "internal_temperature_offset"},
    50003: {"name": "temp_limitation", "values": {0: "off", 2: "on"}},
    50004: {"name": "cool_temperature_min"},
    50005: {"name": "cool_temperature_max"},
    50006: {"name": "heat_temperature_min"},
    50007: {"name": "heat_temperature_min"},
    60002: {"name": "rssi"},
}

COMMAND_MAP = {
    "power": {"uid": 1, "values": {"off": 0, "on": 1}},
    "mode": {"uid": 2, "values": {"auto": 0, "heat": 1, "dry": 2, "fan": 3, "cool": 4}},
    "operating_mode": {
        "uid": 58,
        "values": {
            "heat": 1,
            "heat+tank": 2,
            "tank": 3,
            "cool+tank": 4,
            "cool": 5,
            "auto": 6,
            "auto+tank": 7,
        },
    },
    "climate_working_mode": {
        "uid": 42,
        "values": {"comfort": 0, "eco": 1, "powerful": 2},
    },
    "fan_speed": {"uid": 4},
    "vvane": {
        "uid": 5,
        "values": {
            "auto/stop": 0,
            "swing": 10,
            "manual1": 1,
            "manual2": 2,
            "manual3": 3,
            "manual4": 4,
            "manual5": 5,
        },
    },
    "hvane": {
        "uid": 6,
        "values": {
            "auto/stop": 0,
            "swing": 10,
            "manual1": 1,
            "manual2": 2,
            "manual3": 3,
            "manual4": 4,
            "manual5": 5,
        },
    },
    "setpoint": {"uid": 9}
     # aquarea
    ,"quiet": {"uid": 34, "values": {"off": 0, "on": 1}}
    ,"tank": {"uid": 44, "values": {"comfort": 0, "eco": 1, "powerful": 2}}
    ,"reset_eror": {"uid": 54, "values": {"on": 1}}
    ,"tank_setpoint_temperature": {"uid": 57}
    ,"thermoshift_heat_eco": {"uid": 48, "min": 0, "max": 5}
    ,"thermoshift_cool_eco": {"uid": 49, "min": 0, "max": 5} # 172
    ,"thermoshift_heat_powerful": {"uid": 50, "min": 0, "max": 5}
    ,"thermoshift_cool_powerful": {"uid": 51, "min": 0, "max": 5} # 171
    ,"thermoshift_tank_eco": {"uid": 52, "min": 0, "max": 10}
    ,"thermoshift_tank_powerful": {"uid": 53, "min": 0, "max": 10}
    ,"heat_thermo_shift": {"uid": 55, "min": -5, "max": 5}
    ,"cool_water_setpoint_temperature": {"uid": 56}
    ,"heat_high_water_set_temperature": {"uid": 83, "min": 25, "max": 55}
    ,"heat_low_outdoor_set_temperature": {"uid": 134, "min": -15, "max": 15}
    ,"heat_high_outdoor_set_temperature": {"uid": 135, "min": -15, "max": 15}
    ,"heat_low_water_set_temperature": {"uid": 136, "min": 25, "max": 55}
    ,"resync": {"uid": 143, "values": {"on": 1}}
    ,"remote_control_block": {"uid": 12, "values": {"on": 2, "off": 0}}
}

# aquarea
ERROR_MAP = {
      0 : { 'code': 'H00', 'desc': 'No abnormality detected'},
      2 : { 'code': 'H91', 'desc': 'Tank booster heater OLP abnormality'},
     13 : { 'code': 'F38', 'desc': 'Unknown'},
     20 : { 'code': 'H90', 'desc': 'Indoor / outdoor abnormal communication'},
     36 : { 'code': 'H99', 'desc': 'Indoor heat exchanger freeze prevention'},
     38 : { 'code': 'H72', 'desc': 'Tank temperature sensor abnormality'},
     42 : { 'code': 'H12', 'desc': 'Indoor / outdoor capacity unmatched'},
    156 : { 'code': 'H76', 'desc': 'Indoor - control panel communication abnormality'},
    193 : { 'code': 'F12', 'desc': 'Pressure switch activate'},
    195 : { 'code': 'F14', 'desc': 'Outdoor compressor abnormal rotation'},
    196 : { 'code': 'F15', 'desc': 'Outdoor fan motor lock abnormality'},
    197 : { 'code': 'F16', 'desc': 'Total running current protection'},
    200 : { 'code': 'F20', 'desc': 'Outdoor compressor overheating protection'},
    202 : { 'code': 'F22', 'desc': 'IPM overheating protection'},
    203 : { 'code': 'F23', 'desc': 'Outdoor DC peak detection'},
    204 : { 'code': 'F24', 'desc': 'Refrigerant cycle abnormality'},
    205 : { 'code': 'F27', 'desc': 'Pressure switch abnormality'},
    207 : { 'code': 'F46', 'desc': 'Outdoor current transformer open circuit'},
    208 : { 'code': 'F36', 'desc': 'Outdoor air temperature sensor abnormality'},
    209 : { 'code': 'F37', 'desc': 'Indoor water inlet temperature sensor abnormality'},
    210 : { 'code': 'F45', 'desc': 'Indoor water outlet temperature sensor abnormality'},
    212 : { 'code': 'F40', 'desc': 'Outdoor discharge pipe temperature sensor abnormality'},
    214 : { 'code': 'F41', 'desc': 'PFC control'},
    215 : { 'code': 'F42', 'desc': 'Outdoor heat exchanger temperature sensor abnormality'},
    216 : { 'code': 'F43', 'desc': 'Outdoor defrost temperature sensor abnormality'},
    222 : { 'code': 'H95', 'desc': 'Indoor / outdoor wrong connection'},
    224 : { 'code': 'H15', 'desc': 'Outdoor compressor temperature sensor abnormality'},
    225 : { 'code': 'H23', 'desc': 'Indoor refrigerant liquid temperature sensor abnormality'},
    226 : { 'code': 'H24', 'desc': 'Unknown'},
    227 : { 'code': 'H38', 'desc': 'Indoor / outdoor mismatch'},
    228 : { 'code': 'H61', 'desc': 'Unknown'},
    229 : { 'code': 'H62', 'desc': 'Water flow switch abnormality'},
    230 : { 'code': 'H63', 'desc': 'Refrigerant low pressure abnormality'},
    231 : { 'code': 'H64', 'desc': 'Refrigerant high pressure abnormality'},
    232 : { 'code': 'H42', 'desc': 'Compressor low pressure abnormality'},
    233 : { 'code': 'H98', 'desc': 'Outdoor high pressure overload protection'},
    234 : { 'code': 'F25', 'desc': 'Cooling / heating cycle changeover abnormality'},
    235 : { 'code': 'F95', 'desc': 'Cooling high pressure overload protection'},
    236 : { 'code': 'H70', 'desc': 'Indoor backup heater OLP abnormality'},
    237 : { 'code': 'F48', 'desc': 'Outdoor EVA outlet temperature sensor abnormality'},
    238 : { 'code': 'F49', 'desc': 'Outdoor bypass outlet temperature sensor abnormality'},
  65535 : { 'code': 'N/A', 'desc': 'Communication error between PA-IntesisHome'}
}

API_URL = {
    DEVICE_AIRCONWITHME: "https://user.airconwithme.com/api.php/get/control",
    DEVICE_INTESISHOME: "https://user.intesishome.com/api.php/get/control",
}

API_VER = {DEVICE_AIRCONWITHME: "1.6.2", DEVICE_INTESISHOME: "1.8.5"}


class IHConnectionError(Exception):
    pass


class IHAuthenticationError(ConnectionError):
    pass


class IntesisHome:
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
        self._api_url = API_URL[device_type]
        self._api_ver = API_VER[device_type]
        self._username = username
        self._password = password
        self._cmdServer = None
        self._cmdServerPort = None
        self._connectionRetires = 0
        self._authToken = None
        self._devices = {}
        self._connected = False
        self._connecting = False
        self._sendQueue = asyncio.Queue()
        self._sendQueueTask = None
        self._keepaliveTask = None
        self._updateCallbacks = []
        self._errorMessage = None
        self._webSession = websession
        self._ownSession = False
        self._reader = None
        self._writer = None
        self._reconnectionAttempt = 0
        self._last_message_received = 0

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

    async def parse_api_messages(self, message):
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
            self._update_rssi(resp["data"]["deviceId"], resp["data"]["rssi"])
            if resp["data"]["uid"] != 60002:
                await self._send_update_callback(
                    deviceId=str(resp["data"]["deviceId"])
                )
        elif resp["command"] == "rssi":
            # Wireless strength has changed
            self._update_rssi(resp["data"]["deviceId"], resp["data"]["value"])
        return

    async def _send_keepalive(self):
        if self._connected:
            _LOGGER.debug("sending keepalive")
            message = (
                '{"command":"get"}'
            )
            self._sendQueue.put_nowait(message)
            
    
    async def _handle_packets(self):
        data = True
        while data:
            try:
                data = await self._reader.readuntil(b"}}")
                if not data:
                    break
                message = data.decode("ascii")
                await self.parse_api_messages(message)

            except (asyncio.IncompleteReadError, TimeoutError, ConnectionResetError, OSError) as e:
                _LOGGER.error(
                    "pyIntesisHome lost connection to the %s server. Exception: %s", self._device_type, e
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

    async def connect(self, *args):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._connectionRetires = 0

            # Get authentication token over HTTP POST
            while not self._authToken:
                if self._connectionRetires:
                    _LOGGER.debug(
                        "Couldn't get API details, retrying in %i minutes", self._connectionRetires
                    )
                    await asyncio.sleep(self._connectionRetires * 60)
                try:
                    self._authToken = await self.poll_status()
                except IHConnectionError as ex:
                    _LOGGER.error("Error connecting to the %s server: %s", self._device_type, ex)
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
                    self._reader._transport._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60*1000)
                    self._reader._transport._sock.setsockopt(socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 60*1000)

                # Authenticate
                authMsg = '{"command":"connect_req","data":{"token":%s}}' % (
                    self._authToken
                )
                # Clear the OTP
                self._authToken = None
                self._writer.write(authMsg.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Data sent: %s", authMsg)
                _LOGGER.debug("Socket timeout is %s", self._reader._transport._sock.gettimeout())

                self._eventLoop.create_task(self._handle_packets())
                #self._keepaliveTask = self._eventLoop.create_task(self._send_keepalive())
                self._sendQueueTask = self._eventLoop.create_task(self._send_queue())

            except (ConnectionRefusedError, Exception) as e:
                _LOGGER.error(
                    "Connection to %s:%s failed with exception %s",
                    self._cmdServer, self._cmdServerPort, e)
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

    def get_devices(self):
        """Public method to return the state of all IntesisHome devices"""
        return self._devices

    def get_device(self, deviceId):
        """Public method to return the state of the specified device"""
        return self._devices.get(str(deviceId))

    def get_device_property(self, deviceId, property_name):
        return self._devices[str(deviceId)].get(property_name)

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

    def _get_uint32(self, value):
        result = int(value) & 0xffff
        return result

    def get_run_hours(self, deviceId) -> str:
        """Public method returns the run hours of the IntesisHome controller."""
        run_hours = self._devices[str(deviceId)].get("working_hours")
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
        set_temp = self._get_uint32((setpoint * 10))
        await self._set_value(deviceId, COMMAND_MAP["setpoint"]["uid"], set_temp)

    async def set_fan_speed(self, deviceId, fan: str):
        """Public method to set the fan speed"""
        config_fan_map = self._devices[str(deviceId)].get("config_fan_map")
        map_fan_speed_to_int = {v: k for k, v in config_fan_map.items()}
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

    async def _set_value(self, deviceId, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = (
            '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}'
            % (deviceId, uid, value)
        )
        self._sendQueue.put_nowait(message)

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
        if rssi:
            self._devices[str(deviceId)]["rssi"] = rssi

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
        mode_map = self._devices[str(deviceId)].get("config_mode_map")
        mode_bits = CONFIG_MODE_BITS

        if "config_operating_mode" in self._devices[str(deviceId)]:
            # If config_operating_mode is supplied, use that
            mode_map = self._devices[str(deviceId)].get("config_operating_mode")
            mode_bits = OPERATING_MODE_BITS
        
        # Generate the mode list from the map
        for mode_bit in mode_bits.keys():
            if mode_map & mode_bit:
                mode_list.append(mode_bits.get(mode_bit))

        return mode_list

    def get_fan_speed(self, deviceId):
        """Public method returns the current fan speed."""
        config_fan_map = self._devices[str(deviceId)].get("config_fan_map")

        if "fan_speed" in self._devices[str(deviceId)] and config_fan_map:
            fan_speed_int = self._devices[str(deviceId)].get("fan_speed")
            return config_fan_map.get(fan_speed_int)
        else:
            return None

    def get_fan_speed_list(self, deviceId):
        """Public method to return the list of possible fan speeds."""
        config_fan_map = self._devices[str(deviceId)].get("config_fan_map")
        if config_fan_map:
            return list(config_fan_map.values())
        else:
            return None

    def get_device_name(self, deviceId) -> str:
        return self._devices[str(deviceId)].get("name")

    def get_power_state(self, deviceId) -> str:
        """Public method returns the current power state."""
        return self._devices[str(deviceId)].get("power")

    def get_instant_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        instant_power = self._devices[str(deviceId)].get("instant_power_consumption")
        if instant_power:
            return int(instant_power)

    def get_total_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        accumulated_power = self._devices[str(deviceId)].get(
            "accumulated_power_consumption"
        )
        if accumulated_power:
            return int(accumulated_power)

    def get_cool_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_cool = self._devices[str(deviceId)].get("aquarea_cool_consumption")
        if aquarea_cool:
            return int(aquarea_cool)

    def get_heat_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_heat = self._devices[str(deviceId)].get("aquarea_heat_consumption")
        if aquarea_heat:
            return int(aquarea_heat)

    def get_tank_power_consumption(self, deviceId) -> int:
        """Public method returns the current power state."""
        aquarea_tank = self._devices[str(deviceId)].get("aquarea_tank_consumption")
        if aquarea_tank:
            return int(aquarea_tank)

    def get_preset_mode(self, deviceId) -> str:
        return self._devices[str(deviceId)].get("climate_working_mode")

    def is_on(self, deviceId) -> bool:
        """Return true if the controlled device is turned on"""
        return self._devices[str(deviceId)].get("power") == "on"

    def has_vertical_swing(self, deviceId) -> bool:
        vvane_config = self._devices[str(deviceId)].get("config_vertical_vanes")
        return vvane_config and vvane_config > 1024

    def has_horizontal_swing(self, deviceId) -> bool:
        hvane_config = self._devices[str(deviceId)].get("config_horizontal_vanes")
        return hvane_config and hvane_config > 1024

    def has_setpoint_control(self, deviceId) -> bool:
        return "setpoint" in self._devices[str(deviceId)]

    def get_setpoint(self, deviceId) -> float:
        """Public method returns the target temperature."""
        setpoint = self._devices[str(deviceId)].get("setpoint")
        if setpoint:
            setpoint = int(setpoint) / 10
        return setpoint

    def get_temperature(self, deviceId) -> float:
        """Public method returns the current temperature."""
        temperature = self._devices[str(deviceId)].get("temperature")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_outdoor_temperature(self, deviceId) -> float:
        """Public method returns the current temperature."""
        outdoor_temp = self._devices[str(deviceId)].get("outdoor_temp")
        if outdoor_temp:
            outdoor_temp = int(outdoor_temp) / 10
        return outdoor_temp

    def get_max_setpoint(self, deviceId) -> float:
        """Public method returns the current maximum target temperature."""
        temperature = self._devices[str(deviceId)].get("setpoint_max")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_min_setpoint(self, deviceId) -> float:
        """Public method returns the current minimum target temperature."""
        temperature = self._devices[str(deviceId)].get("setpoint_min")
        if temperature:
            temperature = int(temperature) / 10
        return temperature

    def get_rssi(self, deviceId) -> str:
        """Public method returns the current wireless signal strength."""
        rssi = self._devices[str(deviceId)].get("rssi")
        return rssi

    def get_vertical_swing(self, deviceId) -> str:
        """Public method returns the current vertical vane setting."""
        swing = self._devices[str(deviceId)].get("vvane")
        return swing

    def get_horizontal_swing(self, deviceId) -> str:
        """Public method returns the current horizontal vane setting."""
        swing = self._devices[str(deviceId)].get("hvane")
        return swing

    async def _send_update_callback(self, deviceId=None):
        """Internal method to notify all update callback subscribers."""
        if self._updateCallbacks:
            for callback in self._updateCallbacks:
                await callback(device_id=deviceId)
        else:
            _LOGGER.debug("Update callback has not been set by client")

    def get_error(self, deviceId) -> str:
        """Public method returns the current error code + description."""
        error_code = self._devices[str(deviceId)].get('error_code')
        remote_code = ERROR_MAP[error_code]['code']
        error_desc = ERROR_MAP[error_code]['desc']
        return (("%s: %s" % (remote_code, error_desc)))

    def _get_gen_value(self, deviceId, name) -> str:
        """ Internal method for getting generic value """
        value = None
        if name in self._devices[str(deviceId)]:
            value = self._devices[str(deviceId)].get(name)
            _LOGGER.debug(f"{name} = {value}")
        else:
            _LOGGER.debug(f"No value for {deviceId} {name}")
        return value

    def _get_gen_num_value(self, deviceId, name):
        """ Internal method for getting generic value and dividing by 10 if numeric """
        value = self._get_gen_value(deviceId, name)
        if (isinstance(value, int) or isinstance(value, float)):
            temperature = float(value / 10)
            return temperature
        else:
            return value

    def _set_gen_mode(self, deviceId, type, mode):
        """Internal method for setting the generic mode (type in {operating_mode, climate_working_mode, tank, etc.}) with a string value"""
        if mode in COMMAND_MAP[type]['values']:
            self._set_value( deviceId, COMMAND_MAP[type]['uid'], COMMAND_MAP[type]['values'][mode])

    def _set_thermo_shift(self, deviceId, name, value):
        """Public method to set thermo shift temperature."""
        min_shift = int(COMMAND_MAP[name]['min'])
        max_shift = int(COMMAND_MAP[name]['max'])

        if (min_shift <= value <= max_shift):
            unsigned_value = self._get_uint32((value*10)) # unsigned int 16 bit
            self._set_value(deviceId, COMMAND_MAP[name]['uid'], unsigned_value)
        else:
            raise ValueError("Value for %s has to be in range [%d,%d]" % name, min_shift, max_shift)

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

    async def add_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._updateCallbacks.append(method)


def help():
    print("syntax: pyintesishome [options] command [command_args]")
    print("options:")
    print("   --user <username>       ... username on user.intesishome.com")
    print("   --password <password>   ... password on user.intesishome.com")
    print("   --id <number>           ... specify device id of unit to control")
    print()
    print("commands: show")
    print("    show                   ... show current state")
    print()
    print("examples:")
    print("    pyintesishome.py --user joe@user.com --password swordfish show")


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
        help="IntesisHome or airconwithme",
        metavar="IntesisHome or airconwithme",
        default=DEVICE_INTESISHOME,
    )
    args = parser.parse_args()

    if (not args.user) or (not args.password):
        help()
        sys.exit(0)

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
