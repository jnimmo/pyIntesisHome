"""
Support for IntesisHome Smart AC Controllers

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/intesishome/
"""
import logging
import asyncio
import voluptuous as vol
from custom_components import intesishome
from homeassistant.util import Throttle
from datetime import timedelta
from homeassistant.components.climate import (
    STATE_AUTO, STATE_COOL, STATE_HEAT, STATE_DRY, STATE_FAN_ONLY, ClimateDevice,
    PLATFORM_SCHEMA, ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW,
    ATTR_TEMPERATURE)
from homeassistant.const import (
    TEMP_CELSIUS, CONF_SCAN_INTERVAL, STATE_ON, STATE_OFF, STATE_UNKNOWN)

DEPENDENCIES = ['intesishome']
_LOGGER = logging.getLogger(__name__)
STATE_FAN = 'fan'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_SCAN_INTERVAL):
        vol.All(vol.Coerce(int), vol.Range(min=1)),
})

# Return cached results if last scan time was less than this value.
# If a persistent connection is established for the controller, changes to values are in realtime.
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=120)


try:
    from asyncio import ensure_future
except ImportError:
    # Python 3.4.3 and ealier has this as async
    # pylint: disable=unused-import
    from asyncio import async
    ensure_future = async


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Nest thermostat."""
    temp_unit = hass.config.units.temperature_unit
    add_devices([IntesisAC(deviceid, device, temp_unit)
                 for deviceid, device in intesishome.get_devices().items()])

class IntesisAC(ClimateDevice):
    def __init__(self, deviceid, device, temp_unit):
        """Initialize the thermostat."""
        self._unit = temp_unit
        self.deviceid = deviceid
        self.devicename = device['name']

        self._operation_list = [STATE_AUTO, STATE_COOL, STATE_DRY, STATE_OFF, STATE_HEAT, STATE_FAN]
        self._fan_list = ["Auto","Quiet","Low","Medium","High"]
        _LOGGER.info('Added climate device with state: %s',repr(device))

        self._current_operation = STATE_UNKNOWN
        self._current_temp = None
        self._max_temp = None
        self._min_temp = None
        self._target_temp = None
        self._power = STATE_UNKNOWN
        self._run_hours = None
        self._fan_speed = STATE_UNKNOWN
        self._rssi = None

        intesishome.controller.callback_update = self.update_callback
        self.update()

    @property
    def name(self):
        """Return the name of the AC device"""
        return self.devicename

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return {
            "run_hours": self._run_hours,
            "rssi": self._rssi,
            "temperature": self._target_temp,
            "current_temperature": self._current_temp
        }

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temp

    @property
    def current_operation(self):
        return self._current_operation

    @property
    def target_temperature(self):
        return self._target_temp

    @property
    def target_temperature_low(self):
        return None

    @property
    def target_temperature_high(self):
        return None

    @property
    def is_away_mode_on(self):
        """Return if away mode is on."""
        return None

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        _LOGGER.debug("IntesisHome Set Temperature=%s")

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            intesishome.controller.set_temperature(self.deviceid,temperature)

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        _LOGGER.debug("IntesisHome Set Mode=%s", operation_mode)
        if operation_mode == STATE_OFF:
            intesishome.controller.set_power_off(self.deviceid)
        else:
            if intesishome.controller.get_power_state(self.deviceid) == 'off':
                intesishome.controller.set_power_on(self.deviceid)

            if operation_mode == STATE_HEAT:
                intesishome.controller.set_mode_heat(self.deviceid)
            elif operation_mode == STATE_COOL:
                intesishome.controller.set_mode_cool(self.deviceid)
            elif operation_mode == STATE_AUTO:
                intesishome.controller.set_mode_auto(self.deviceid)
            elif operation_mode == STATE_FAN:
                intesishome.controller.set_mode_fan(self.deviceid)
                self._target_temp = None
            elif operation_mode == STATE_DRY:
                intesishome.controller.set_mode_dry(self.deviceid)
    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    @property
    def current_fan_mode(self):
        """Return whether the fan is on."""
        return self._fan_speed

    @property
    def fan_list(self):
        """List of available fan modes."""
        return self._fan_list

    def set_fan_mode(self, fan):
        """Turn fan on/off."""
        if fan == "Auto":
            intesishome.controller.set_fan_speed(self.deviceid, 'auto')
        elif fan == "Quiet":
            intesishome.controller.set_fan_speed(self.deviceid, 'quiet')
        elif fan == "Low":
            intesishome.controller.set_fan_speed(self.deviceid, 'low')
        elif fan == "Medium":
            intesishome.controller.set_fan_speed(self.deviceid, 'medium')
        elif fan == "High":
            intesishome.controller.set_fan_speed(self.deviceid, 'high')

    @property
    def min_temp(self):
        """Identify min_temp in Nest API or defaults if not available."""
        return self._min_temp

    @property
    def max_temp(self):
        """Identify max_temp in Nest API or defaults if not available."""
        return self._max_temp

    def update(self):
        if intesishome.controller.is_disconnected:
            self._poll_status(False)

        self._target_temp = intesishome.controller.get_setpoint(self.deviceid)
        self._current_temp = intesishome.controller.get_temperature(self.deviceid)
        self._min_temp = intesishome.controller.get_min_setpoint(self.deviceid)
        self._max_temp = intesishome.controller.get_max_setpoint(self.deviceid)

        mode = intesishome.controller.get_mode(self.deviceid)
        if intesishome.controller.get_power_state(self.deviceid) == 'off':
            self._current_operation = STATE_OFF
            self._target_temp = None
        elif mode == 'cool':
            self._current_operation = STATE_COOL
        elif mode == 'heat':
            self._current_operation = STATE_HEAT
        elif mode == 'auto':
            self._current_operation = STATE_AUTO
        elif mode == 'dry':
            self._current_operation = STATE_DRY
        elif mode == 'fan':
            self._current_operation = STATE_FAN
            self._target_temp = None
        else:
            self._current_operation = STATE_UNKNOWN

        self._run_hours = intesishome.controller.get_run_hours(self.deviceid)

        fan_speed = intesishome.controller.get_fan_speed(self.deviceid)
        if fan_speed == 'auto':
            self._fan_speed = "Auto"
        elif fan_speed == 'quiet':
            self._fan_speed = "Quiet"
        elif fan_speed == 'low':
            self._fan_speed = "Low"
        elif fan_speed == 'medium':
            self._fan_speed = "Medium"
        elif fan_speed == 'high':
            self._fan_speed = "High"
        else:
            self._fan_speed = STATE_UNKNOWN

        self._rssi = intesishome.controller.get_rssi(self.deviceid)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def _poll_status(self, shouldCallback):
        _LOGGER.info("Polling IntesisHome Status via HTTP")
        intesishome.controller.poll_status(shouldCallback)

    @property
    def should_poll(self):
        if intesishome.controller.is_connected:
            return False
        else:
            return True

    def update_callback(self):
        """Called when data is received by pyIntesishome"""
        _LOGGER.info("IntesisHome sent a status update.")
        self.hass.async_add_job(self.update_ha_state,True)
