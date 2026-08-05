# pyIntesisHome

This project is a python3 library for interfacing with Intesis air conditioning controllers, including cloud control of IntesisHome (Airconwithme + anywAiR) and local control of IntesisBox devices.
It is fully asynchronous using the aiohttp library, and utilises the private API used by the IntesisHome mobile apps.

### Home Assistant

To use with [Home Assistant](https://www.home-assistant.io/integrations/intesishome/), add the following to your configuration.yaml

#### IntesisHome configuration example

```yaml
climate:
  - platform: intesishome
    username: YOUR_USERNAME
    password: YOUR_PASSWORD
```

#### IntesisBox configuration example

```yaml
climate:
  - platform: intesishome
    device: IntesisBox
    host: 192.168.1.50
```

## Library usage

- Instantiate the IntesisHome controller device with username and password for the accloud.intesis.com website.
- Status can be polled using the poll_status command suggested maximum of once every 5 minutes.
- Commands are sent using a TCP connection to the API which will then remain open until the connection times out.
- While the persistent TCP connection is open, status updates are pushed to the device over the socket meaning polling is not required (check using _is_connected_ property)
- Callbacks to be notified of state updates can be added with the add_update_callback() method.

### Library basic example

```python
import asyncio
from pyintesishome import IntesisHome


async def main():
    controller = IntesisHome("username", "password", device_type="airconwithme")
    await controller.connect()
    print(repr(controller.get_devices()))
    # Imagine you have a device with id 12015601252591
    if not controller.is_on("12015601252591"):
        await controller.set_power_on("12015601252591")

    await controller.set_mode_heat("12015601252591")
    await controller.set_temperature("12015601252591", 22)
    await controller.set_fan_speed("12015601252591", "quiet")

    await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Callback-driven example

Rather than polling, subscribe to state-change notifications with `add_update_callback()`. The callback fires whenever the controller receives a push update over its connection, so this example just connects and reacts to changes as they arrive:

```python
import asyncio
from pyintesishome import IntesisHome


async def on_update(device_id=None):
    print(f"Device {device_id} updated")


async def main():
    controller = IntesisHome("username", "password", device_type="airconwithme")
    controller.add_update_callback(on_update)
    await controller.connect()

    # Keep the connection open to keep receiving pushed updates
    while controller.is_connected:
        await asyncio.sleep(60)

    await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
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
