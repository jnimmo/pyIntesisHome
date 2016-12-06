"""
Support for IntesisHome Smart AC Controllers

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/intesishome/
"""
import logging
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
        """Initialize the thermostat"""
        _LOGGER.info('Added climate device with state: %s',repr(device))

        self._deviceid = deviceid
        self._devicename = device['name']
        self._unit = temp_unit

        self._max_temp = None
        self._min_temp = None
        self._target_temp = None
        self._current_temp = None
        self._run_hours = None
        self._rssi = None

        self._power = STATE_UNKNOWN
        self._fan_speed = STATE_UNKNOWN
        self._current_operation = STATE_UNKNOWN
        self._vvane = STATE_UNKNOWN

        self._operation_list = [STATE_AUTO, STATE_COOL, STATE_DRY, STATE_OFF, STATE_HEAT, STATE_FAN]
        self._fan_list = ["Auto","Quiet","Low","Medium","High"]
        self._swing_list = ["Auto/Stop","Swing","Middle"]

        #
        intesishome.controller.add_callback(self.update_callback)
        self.update()

    @property
    def name(self):
        """Return the name of the AC device"""
        return self._devicename

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



    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        _LOGGER.debug("IntesisHome Set Temperature=%s")

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            intesishome.controller.set_temperature(self._deviceid, temperature)

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        _LOGGER.debug("IntesisHome Set Mode=%s", operation_mode)
        if operation_mode == STATE_OFF:
            intesishome.controller.set_power_off(self._deviceid)
        else:
            if intesishome.controller.get_power_state(self._deviceid) == 'off':
                intesishome.controller.set_power_on(self._deviceid)

            if operation_mode == STATE_HEAT:
                intesishome.controller.set_mode_heat(self._deviceid)
            elif operation_mode == STATE_COOL:
                intesishome.controller.set_mode_cool(self._deviceid)
            elif operation_mode == STATE_AUTO:
                intesishome.controller.set_mode_auto(self._deviceid)
            elif operation_mode == STATE_FAN:
                intesishome.controller.set_mode_fan(self._deviceid)
                self._target_temp = None
            elif operation_mode == STATE_DRY:
                intesishome.controller.set_mode_dry(self._deviceid)

            if self._target_temp:
                intesishome.controller.set_temperature(self._deviceid, self._target_temp)
            self.set_fan_mode(self._fan_speed)
            self.set_swing_mode(self._vvane)


    def set_fan_mode(self, fan):
        """Turn fan on/off."""
        if fan == "Auto":
            intesishome.controller.set_fan_speed(self._deviceid, 'auto')
        elif fan == "Quiet":
            intesishome.controller.set_fan_speed(self._deviceid, 'quiet')
        elif fan == "Low":
            intesishome.controller.set_fan_speed(self._deviceid, 'low')
        elif fan == "Medium":
            intesishome.controller.set_fan_speed(self._deviceid, 'medium')
        elif fan == "High":
            intesishome.controller.set_fan_speed(self._deviceid, 'high')

    def set_swing_mode(self, vvane):
        """Set the vertical vane."""
        if vvane == "Auto/Stop":
            intesishome.controller.set_vane_pos(self._deviceid, 'auto/stop')
        elif vvane == "Swing":
            intesishome.controller.set_vane_pos(self._deviceid, 'swing')
        elif vvane == "Middle":
            intesishome.controller.set_vane_pos(self._deviceid, 'manual3')

    def update(self):
        if intesishome.controller.is_disconnected:
            self._poll_status(False)

        self._target_temp = intesishome.controller.get_setpoint(self._deviceid)
        self._current_temp = intesishome.controller.get_temperature(self._deviceid)
        self._min_temp = intesishome.controller.get_min_setpoint(self._deviceid)
        self._max_temp = intesishome.controller.get_max_setpoint(self._deviceid)

        mode = intesishome.controller.get_mode(self._deviceid)
        if intesishome.controller.get_power_state(self._deviceid) == 'off':
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

        self._run_hours = intesishome.controller.get_run_hours(self._deviceid)

        fan_speed = intesishome.controller.get_fan_speed(self._deviceid)
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

        vvane = intesishome.controller.get_vane(self._deviceid)
        if vvane == 'auto/stop':
            self._vvane = "Auto/Stop"
        elif vvane == 'swing':
            self._vvane = "Swing"
        elif vvane == 'manual3':
            self._vvane = "Middle"
        else:
            self._vvane = STATE_UNKNOWN

        self._rssi = intesishome.controller.get_rssi(self._deviceid)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def _poll_status(self, shouldCallback):
        _LOGGER.info("Polling IntesisHome Status via HTTP")
        intesishome.controller.poll_status(shouldCallback)



    @property
    def icon(self):
        icon = None
        if self._current_operation == STATE_HEAT:
            icon = 'mdi:white-balance-sunny'
        elif self._current_operation == STATE_FAN:
            icon = 'mdi:fan'
        elif self._current_operation == STATE_DRY:
            icon = 'mdi:water-off'
        elif self._current_operation == STATE_COOL:
            icon = 'mdi:nest-thermostat'
        elif self._current_operation == STATE_AUTO:
            icon = 'mdi:cached'
        return icon

    def update_callback(self):
        """Called when data is received by pyIntesishome"""
        _LOGGER.info("IntesisHome sent a status update.")
        self.hass.async_add_job(self.update_ha_state,True)

    @property
    def min_temp(self):
        """Return the minimum temperature from the IntesisHome interface"""
        return self._min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature from the IntesisHome interface"""
        return self._max_temp

    @property
    def should_poll(self):
        """Poll for updates if pyIntesisHome doesn't have a socket open"""
        if intesishome.controller.is_connected:
            return False
        else:
            return True

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    @property
    def current_fan_mode(self):
        """Return whether the fan is on."""
        return self._fan_speed

    @property
    def current_swing_mode(self):
        """Return vvane position"""
        return self._vvane

    @property
    def fan_list(self):
        """List of available fan modes."""
        return self._fan_list

    @property
    def swing_list(self):
        """List of available vvane positions."""
        return self._swing_list

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