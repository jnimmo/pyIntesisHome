# pyIntesisHome
This project is a python3 library for interfacing with the IntesisHome and airconwithme AC controllers.
It is fully asynchronous using the aiohttp library, and utilises the private API used by the IntesisHome mobile apps.

### Home Assistant
To use with [Home Assistant](https://www.home-assistant.io/integrations/intesishome/), add the following to your configuration.yaml 

```yaml
climate:
  - platform: intesishome
    username: YOUR_USERNAME
    password: YOUR_PASSWORD
```

For IntesisBox support, see [hass-intesisbox](https://github.com/jnimmo/hass-intesisbox) for an initial release.

## Library usage
 - Instantiate the IntesisHome controller device with username and password for the user.intesishome.com website.
 - Status can be polled using the poll_status command suggested maximum of once every 5 minutes.
 - Commands are sent using a TCP connection to the API which will then remain open until the connection times out. 
 - While the persistent TCP connection is open, status updates are pushed to the device over the socket meaning polling is not required (check using *is_connected* property)
 - Callbacks to be notified of state updates can be added with the add_callback() method.

### Library basic example
```python
import asyncio
from pyintesishome import IntesisHome

async def main(loop):
    controller = IntesisHome('username', 'password', loop=loop, device_type='airconwithme')
    await controller.connect()
    print(repr(controller.get_devices()))
    # Imagine you have a device with id 12015601252591
    if await controller.get_power_state('12015601252591') == 'off':
        await controller.set_power_on('12015601252591')

    await controller.set_mode_heat('12015601252591')
    await controller.set_temperature('12015601252591', 22)
    await controller.set_fan_speed('12015601252591','quiet')

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(main(loop))

```
### Control methods

 - set_mode_heat(deviceID)
 - set_mode_cool(deviceID)
 - set_mode_fan(deviceID)
 - set_mode_dry(deviceID)
 - set_mode_auto(deviceID)
 - set_temperature(deviceID, temperature)
 - set_fan_speed(deviceID, 'quiet' | 'low' | 'medium' | 'high' | 'auto')
 - set_power_on(deviceID)
 - set_power_off(deviceID)
 
