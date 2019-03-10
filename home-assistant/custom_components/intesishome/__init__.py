"""
Support for IntesisHome Smart AC Controllers

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/intesishome/
"""
import logging
# from datetime import timedelta
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (CONF_PASSWORD, CONF_USERNAME)
# from homeassistant.util import Throttle
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.components import persistent_notification

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'intesishome'
DATA_INTESISHOME = 'intesishome'
REQUIREMENTS = ['pyintesishome==0.6']

controller = None
hass = None

# MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=180)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME, 'authentication'): cv.string,
        vol.Required(CONF_PASSWORD, 'authentication'): cv.string
    })
}, extra=vol.ALLOW_EXTRA)


def setup(hass, hass_config):
    """Sets up the IntesisHome platform."""
    global controller
    from pyintesishome import IntesisHome

    _user = hass_config[DOMAIN][CONF_USERNAME]
    _pass = hass_config[DOMAIN][CONF_PASSWORD]

    if controller is None:
        controller = IntesisHome(_user, _pass, hass.loop)
    
    hass.data[DATA_INTESISHOME] = controller
    controller.connect()

    hass.async_create_task(
        async_load_platform(hass, 'climate', DOMAIN, None, hass_config))

    if controller.error_message:
        persistent_notification.create(
            hass, controller.error_message, "IntesisHome Error", 'intesishome')

    return True


def stop_intesishome():
    controller.stop()

