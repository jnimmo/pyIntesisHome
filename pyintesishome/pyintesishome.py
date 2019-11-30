import asyncio
import logging
import aiohttp
import json
import sys
import argparse

_LOGGER = logging.getLogger("pyintesishome")

INTESIS_CMD_STATUS = '{"status":{"hash":"x"},"config":{"hash":"x"}}'

DEVICE_INTESISHOME = "IntesisHome"
DEVICE_AIRCONWITHME = "airconwithme"

API_DISCONNECTED = "Disconnected"
API_CONNECTING = "Connecting"
API_AUTHENTICATED = "Connected"
API_AUTH_FAILED = "Wrong username/password"

INTESIS_MAP = {
    1: {"name": "power", "values": {0: "off", 1: "on"}},
    2: {
        "name": "mode",
        "values": {0: "auto", 1: "heat", 2: "dry", 3: "fan", 4: "cool"},
    },
    4: {
        "name": "fan_speed"
    },
    5: {
        "name": "vvane",
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
    9: {"name": "setpoint", "null": 32768},
    10: {"name": "temperature"},
    13: {"name": "working_hours"},
    14: {"name": "alarm_status"},
    15: {"name": "error_code"},
    34: {"name": "quiet_mode"},
    35: {"name": "setpoint_min"},
    36: {"name": "setpoint_max"},
    37: {"name": "outdoor_temp"},
    42: {"name": "clima_working_mode"},
    44: {"name": "tank_working_mode"},
    45: {"name": "tank_water_temperature"},
    46: {"name": "solar_status"},
    48: {"name": "thermoshift_heat_eco"},
    49: {"name": "thermoshift_cool_eco"},
    51: {"name": "thermoshift_cool_powerful"},
    52: {"name": "thermoshift_tank_eco"},
    53: {"name": "thermoshift_tank_powerful"},
    54: {"name": "error_reset"},
    58: {"name": "operating_mode"},
    61: {"name": "config_mode_map"}, # 31 = auto, heat, cool, dry, fan, 
    63: {"name": "config_horizontal_vanes"},
    64: {"name": "config_vertical_vanes"},
    65: {"name": "config_quiet"},
    67: {"name": "config_fan_map"},  # 15 = auto, low, medium, high, #31 = auto, quiet, low, medium, high
    68: {"name": "instant_power_consumption"},
    69: {"name": "accumulated_power_consumption"},
    140: {"name": "extremes_protection_status"},
    148: {"name": "extremes_protection"},
    137: {"name": "farenheit_type"},
    184: {"name": "filter_due_hours"},
}

COMMAND_MAP = {
    "power": {"uid": 1, "values": {"off": 0, "on": 1}},
    "mode": {"uid": 2, "values": {"auto": 0, "heat": 1, "dry": 2, "fan": 3, "cool": 4}},
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
    "setpoint": {"uid": 9},
}


class IntesisHome(): 
    def __init__(self, username, password, loop=None, websession=None, device_type=DEVICE_INTESISHOME):
        # Select correct API for device type
        self._device_type = device_type
        if device_type == DEVICE_AIRCONWITHME:
            self._api_url = "https://user.airconwithme.com/api.php/get/control"
            self._api_ver = "1.6.2"
        else:
            self._api_url = "https://user.intesishome.com/api.php/get/control"
            self._api_ver = "1.8.5"
        self._username = username
        self._password = password
        self._cmdServer = None
        self._cmdServerPort = None
        self._devices = {}
        self._connectionStatus = API_DISCONNECTED
        self._sendQueue = asyncio.Queue()
        self._transport = None
        self._protocol = None
        self._updateCallbacks = []
        self._errorCallbacks = []
        self._errorMessage = None
        self._webSession = websession
        self._ownSession = False
        self._reader = None
        self._writer = None

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

    async def _handle_packets(self):
        while True:
            try: 
                data = await self._reader.readuntil(b'}}')
                if not data:
                    break

                message = data.decode("ascii")
                _LOGGER.debug(f"{self._device_type} API Received: {message}")
                resp = json.loads(message)
                # Parse response
                if resp["command"] == "connect_rsp":
                    # New connection success
                    if resp["data"]["status"] == "ok":
                        _LOGGER.info(f"{self._device_type} succesfully authenticated")
                        self._connectionStatus = API_AUTHENTICATED
                elif resp["command"] == "status":
                    # Value has changed
                    self._update_device_state(
                        resp["data"]["deviceId"],
                        resp["data"]["uid"],
                        resp["data"]["value"],
                    )
                    self._update_rssi(
                        resp["data"]["deviceId"], resp["data"]["rssi"]
                    )
                    if resp["data"]["uid"] != 60002:
                        self._send_update_callback()
                elif resp["command"] == "rssi":
                    # Wireless strength has changed
                    self._update_rssi(
                        resp["data"]["deviceId"], resp["data"]["value"]
                    )
            except asyncio.IncompleteReadError:
                _LOGGER.error(f"pyIntesisHome lost connection to the {self._device_type} server.")
                self._reader._transport.close()
                self._connectionStatus = API_DISCONNECTED
                self._send_update_callback()
                return


    async def _send_queue(self):
        while True:
            data = await self._sendQueue.get()
            try:
                self._writer.write(data.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug(f"Sent command {data}")
            except e:
                _LOGGER.error(f"Exception: {e}")

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if self._connectionStatus == API_DISCONNECTED:
            self._connectionStatus = API_CONNECTING
            try:
                # Get authentication token over HTTP POST
                await self.poll_status()
                if self._cmdServer and self._cmdServerPort and self._token:
                    # Create asyncio socket
                    _LOGGER.debug(
                        "Opening connection to {type} API at {server}:{port}".format(
                            type=self._device_type, server=self._cmdServer, port=self._cmdServerPort
                        )
                    )

                    self._reader, self._writer = await asyncio.open_connection(
                        self._cmdServer, self._cmdServerPort
                    )

                    # Authenticate
                    authMsg = '{"command":"connect_req","data":{"token":%s}}' % (
                        self._token
                    )
                    self._writer.write(authMsg.encode("ascii"))
                    await self._writer.drain()
                    _LOGGER.debug(f"Data sent: {authMsg}")

                    self._eventLoop.create_task(self._handle_packets())
                    self._eventLoop.create_task(self._send_queue())

            except Exception as e:
                _LOGGER.error(f"{type(e)} Exception. {repr(e.args)} / {e}")
                self._connectionStatus = API_DISCONNECTED
    
    async def stop(self):
        """Public method for shutting down connectivity with the envisalink."""
        self._connectionStatus = API_DISCONNECTED
        if self._transport:
            self._transport.close()

        if self._ownSession:
            await self._webSession.close()

    def get_devices(self):
        """Public method to return the state of all IntesisHome devices"""
        return self._devices

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device. Notifies subscribers if sendCallback True."""
        get_status = {
            "username": self._username,
            "password": self._password,
            "cmd": INTESIS_CMD_STATUS,
            "version": self._api_ver,
        }

        self._cmdServer = None
        self._cmdServerPort = None
        self._token = None

        try:
            async with self._webSession.post(url=self._api_url, data=get_status) as resp:
                status_response = await resp.json(content_type=None)
                _LOGGER.debug(status_response)

                if "errorCode" in status_response:
                    _LOGGER.error(
                        f"Error from {self._device_type} API: {status_response['errorMessage']}"
                    )
                    self._send_error_callback(status_response["errorMessage"])
                    self._connectionStatus = API_DISCONNECTED
                    return

                self._cmdServer = status_response["config"]["serverIP"]
                self._cmdServerPort = status_response["config"]["serverPort"]
                self._token = status_response["config"]["token"]
                _LOGGER.debug(
                    f"Server: {self._cmdServer}:{self._cmdServerPort}, Token: {self._token}"
                )

                # Setup devices
                for installation in status_response["config"]["inst"]:
                    for device in installation["devices"]:
                        self._devices[device["id"]] = {
                            "name": device["name"],
                            "widgets": device["widgets"],
                            "model": device["modelId"]
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
                    self._send_update_callback()
        except (aiohttp.client_exceptions.ClientError) as e:
            self._errorMessage = f"Error connecting to {self._device_type} API: {e}"
            _LOGGER.error(f"{type(e)} Exception. {repr(e.args)} / {e}")
            self._connectionStatus = API_DISCONNECTED

    def get_run_hours(self, deviceId) -> str:
        """Public method returns the run hours of the IntesisHome controller."""
        run_hours = self._devices[str(deviceId)].get("working_hours")
        return run_hours

    def _set_mode(self, deviceId, mode: str):
        """Internal method for setting the mode with a string value."""
        if mode in COMMAND_MAP["mode"]["values"]:
            self._set_value(
                deviceId,
                COMMAND_MAP["mode"]["uid"],
                COMMAND_MAP["mode"]["values"][mode],
            )

    def set_temperature(self, deviceId, setpoint):
        """Public method for setting the temperature"""
        set_temp = int(setpoint * 10)
        self._set_value(deviceId, COMMAND_MAP["setpoint"]["uid"], set_temp)

    def set_fan_speed(self, deviceId, fan: str):
        """Public method to set the fan speed"""
        self._set_value(
            deviceId,
            COMMAND_MAP["fan_speed"]["uid"],
            self._devices[deviceId]["fan_speed_list"].index(fan)
        )

    def set_vertical_vane(self, deviceId, vane: str):
        """Public method to set the vertical vane"""
        self._set_value(
            deviceId, COMMAND_MAP["vvane"]["uid"], COMMAND_MAP["vvane"]["values"][vane]
        )

    def set_horizontal_vane(self, deviceId, vane: str):
        """Public method to set the horizontal vane"""
        self._set_value(
            deviceId, COMMAND_MAP["hvane"]["uid"], COMMAND_MAP["hvane"]["values"][vane]
        )

    def _set_value(self, deviceId, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}' % (deviceId, uid, value)
        self._sendQueue.put_nowait(message)

    def _update_device_state(self, deviceId, uid, value):
        """Internal method to update the state table of IntesisHome/Airconwithme devices"""
        deviceId = str(deviceId)

        if uid in INTESIS_MAP:
            # Translate known UIDs to configuration item names
            if "values" in INTESIS_MAP[uid]:
                self._devices[deviceId][INTESIS_MAP[uid]["name"]] = INTESIS_MAP[uid][
                    "values"
                ][value]
            # If the UID has a null value set the value to none
            elif "null" in INTESIS_MAP[uid] and value == INTESIS_MAP[uid]["null"]:
                self._devices[deviceId][INTESIS_MAP[uid]["name"]] = None
            else:
                self._devices[deviceId][INTESIS_MAP[uid]["name"]] = value
            
            # Update fan speed map
            if uid == 67:
                if value <= 15:
                    self._devices[deviceId]["fan_speed_list"] = ["auto", "low", "medium", "high"]
                else:
                    self._devices[deviceId]["fan_speed_list"] = ["auto", "quiet", "low", "medium", "high"]
                    
        else:
            # Log unknown UIDs
            self._devices[deviceId][f"unknown_uid_{uid}"] = value

    def _update_rssi(self, deviceId, rssi):
        """Internal method to update the wireless signal strength."""
        if rssi:
            self._devices[str(deviceId)]["rssi"] = rssi

    def set_mode_heat(self, deviceId):
        """Public method to set device to heat asynchronously."""
        self._set_mode(deviceId, "heat")

    def set_mode_cool(self, deviceId):
        """Public method to set device to cool asynchronously."""
        self._set_mode(deviceId, "cool")

    def set_mode_fan(self, deviceId):
        """Public method to set device to fan asynchronously."""
        self._set_mode(deviceId, "fan")

    def set_mode_auto(self, deviceId):
        """Public method to set device to auto asynchronously."""
        self._set_mode(deviceId, "auto")

    def set_mode_dry(self, deviceId):
        """Public method to set device to dry asynchronously."""
        self._set_mode(deviceId, "dry")

    def set_power_off(self, deviceId):
        """Public method to turn off the device asynchronously."""
        self._set_value(
            deviceId, COMMAND_MAP["power"]["uid"], COMMAND_MAP["power"]["values"]["off"]
        )

    def set_power_on(self, deviceId):
        """Public method to turn on the device asynchronously."""
        self._set_value(
            deviceId, COMMAND_MAP["power"]["uid"], COMMAND_MAP["power"]["values"]["on"]
        )

    def get_mode(self, deviceId) -> str:
        """Public method returns the current mode of operation."""
        return self._devices[str(deviceId)].get("mode")

    def get_fan_speed(self, deviceId) -> str:
        """Public method returns the current fan speed."""
        fan_speed_int = self._devices[str(deviceId)].get("fan_speed")
        return self._devices[str(deviceId)].get("fan_speed_list")[fan_speed_int]

    def get_fan_speed_list(self, deviceId):
        """Public method to return the list of possible fan speeds."""
        return self._devices[str(deviceId)].get("fan_speed_list")

    def get_device_name(self, deviceId) -> str:
        return self._devices[str(deviceId)].get("name")

    def get_power_state(self, deviceId) -> str:
        """Public method returns the current power state."""
        return self._devices[str(deviceId)].get("power")

    def is_on(self, deviceId) -> bool:
        """Return true if the controlled device is turned on"""
        return self._devices[str(deviceId)].get("power") == "on"

    def has_swing_control(self, deviceId) -> bool:
        """Return true if the device supports swing modes."""
        return 42 in self._devices[str(deviceId)].get("widgets")

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

    def _send_update_callback(self):
        """Internal method to notify all update callback subscribers."""
        if self._updateCallbacks == []:
            _LOGGER.debug("Update callback has not been set by client.")

        for callback in self._updateCallbacks:
            callback()

    def _send_error_callback(self, message):
        """Internal method to notify all update callback subscribers."""
        self._errorMessage = message

        if self._errorCallbacks == []:
            _LOGGER.debug("Error callback has not been set by client.")

        for callback in self._errorCallbacks:
            callback(message)

    @property
    def is_connected(self) -> bool:
        """Returns true if the TCP connection is established."""
        return self._connectionStatus == API_AUTHENTICATED

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
        return self._connectionStatus == API_DISCONNECTED

    def add_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._updateCallbacks.append(method)

    def add_error_callback(self, method):
        """Public method to add a callback subscriber."""
        self._errorCallbacks.append(method)

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

    controller = IntesisHome(args.user, args.password, loop=loop, device_type=args.device)
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
