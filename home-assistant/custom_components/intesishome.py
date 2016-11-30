"""
Support for IntesisHome Smart AC Controllers

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/intesishome/
"""
import logging
# from datetime import timedelta
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (CONF_PASSWORD, CONF_USERNAME, CONF_STRUCTURE)
# from homeassistant.util import Throttle
# from homeassistant.components.discovery import load_platform

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'intesishome'
REQUIREMENTS = ['pyintesishome==0.2']

controller = None

# MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=180)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_STRUCTURE): vol.All(cv.ensure_list, cv.string)

    })
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Setup IntesisHome platform."""
    global controller
    from pyintesishome import IntesisHome

    conf = config[DOMAIN]
    _user = conf.get(CONF_USERNAME)
    _pass = conf.get(CONF_PASSWORD)

    controller = IntesisHome(_user,_pass, hass.loop)
    controller.poll_status()
    return True

def stop_intesishome():
    controller.stop()


def get_devices():
    return controller.get_devices()


