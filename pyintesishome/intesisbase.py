"""Base class for Intesis controllers."""
import asyncio
import logging
from asyncio.exceptions import IncompleteReadError
from asyncio.streams import StreamReader, StreamWriter

import aiohttp

from .const import (
    COMMAND_MAP,
    CONFIG_MODE_BITS,
    DEVICE_INTESISHOME,
    DEVICE_INTESISHOME_LOCAL,
    ERROR_MAP,
    INTESIS_MAP,
    INTESIS_NULL,
    OPERATING_MODE_BITS,
)
from .helpers import twos_complement_16bit, uint32

_LOGGER = logging.getLogger("pyintesishome")


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-public-methods
class IntesisBase:
    """Base class for Intesis controllers."""

    def __init__(
        self,
        username=None,
        password=None,
        host=None,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
    ):
        """Initialize IntesisBox controller."""
        # Select correct API for device type
        self._username = username
        self._password = password
        self._host = host
        self._device_type = device_type
        self._devices = {}
        self._connected = False
        self._connecting = False
        self._connection_retries = 0
        self._update_callbacks = []
        self._keepalive_task: asyncio.Task = None
        self._receive_task: asyncio.Task = None
        self._error_message = None
        self._web_session = websession
        self._own_session = False
        self._controller_id = username
        self._controller_name = username
        self._writer: StreamWriter = None
        self._reader: StreamReader = None
        self._received_response: asyncio.Event = asyncio.Event()
        self._data_delimiter = b"}}"

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
        """Internal method to send a value to the device."""
        raise NotImplementedError()

    async def _send_command(self, command: str):
        try:
            _LOGGER.debug("Sending command %s", command)
            self._received_response.clear()
            if self._writer:
                self._writer.write(command.encode("ascii"))
                await self._writer.drain()
                try:
                    await asyncio.wait_for(
                        self._received_response.wait(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    print("oops took longer than 5s!")
        except OSError as exc:
            _LOGGER.error("%s Exception. %s / %s", type(exc), exc.args, exc)

    async def _data_received(self):
        try:
            while self._reader:
                raw_data = await self._reader.readuntil(self._data_delimiter)
                if not raw_data:
                    break
                data = raw_data.decode("ascii")
                _LOGGER.debug("Received: %s", data)
                await self._parse_response(data)

                if not self._received_response.is_set():
                    _LOGGER.debug("Resolving set_value's await")
                    self._received_response.set()
        except IncompleteReadError:
            _LOGGER.info(
                "pyIntesisHome lost connection to the %s server.", self._device_type
            )
        except asyncio.CancelledError:
            pass
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

    def _update_device_state(self, device_id, uid, value):
        """Internal method to update the state table of IntesisHome/Airconwithme devices."""
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
        self._connected = False
        await self._cancel_task_if_exists(self._receive_task)
        await self._cancel_task_if_exists(self._keepalive_task)
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

        if self._own_session:
            await self._web_session.close()

    @staticmethod
    async def _cancel_task_if_exists(task: asyncio.Task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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
        mode_list = []

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
        vane_config = self.get_device_property(device_id, "config_vertical_vanes")
        vane_list = self.get_device_property(device_id, "vvane_list")
        return isinstance(vane_list, list) | bool(vane_config and vane_config > 1024)

    def has_horizontal_swing(self, device_id) -> bool:
        """Public method to check if the device has horizontal swing."""
        vane_config = self.get_device_property(device_id, "config_horizontal_vanes")
        vane_list = self.get_device_property(device_id, "hvane_list")
        return isinstance(vane_list, list) | bool(vane_config and vane_config > 1024)

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
            if self.device_type == DEVICE_INTESISHOME_LOCAL:
                outdoor_temp = int(outdoor_temp) / 10
            else:
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
        return f"{remote_code}: {error_desc}"

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
                f"Value for {name} has to be in range [{min_shift}],{max_shift}]"
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
    def controller_id(self) -> str:
        """Returns an account/device identifier - Serial, MAC or username."""
        if self._controller_id:
            return self._controller_id.lower()
        return None

    @property
    def name(self) -> str:
        """Returns an account/device identifier - Serial, MAC or username."""
        if self._controller_name:
            return self._controller_name
        return None

    @property
    def is_disconnected(self) -> bool:
        """Returns true when the TCP connection is disconnected and idle."""
        return not self._connected and not self._connecting

    async def _send_update_callback(self, device_id=None):
        """Internal method to notify all update callback subscribers."""
        if self._update_callbacks:
            for callback in self._update_callbacks:
                await callback(device_id=device_id)

    def add_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._update_callbacks.append(method)

    def remove_update_callback(self, method):
        """Public method to add a callback subscriber."""
        self._update_callbacks.remove(method)

    def _get_fan_map(self, device_id):
        """Private method to get the fan_map."""
        raise NotImplementedError()

    async def _parse_response(self, decoded_data):
        """Private method to parse the API response."""
        raise NotImplementedError()
