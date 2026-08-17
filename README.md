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
- `connect()` authenticates, loads state over HTTPS, and starts a poller. It does **not** open a socket, so start-up doesn't depend on a high port being reachable.
- State comes from polling the same HTTPS endpoint the mobile app uses, every `poll_interval` seconds.
- **Commands are the only thing that opens the TCP socket**, because it is the one transport that accepts them. It is opened on demand and reopened by the next command whenever it has died.
- While that socket is open it also **pushes status**, and polling stands down — so for the duration it is the source of state, not merely a bonus.
- Callbacks to be notified of state updates can be added with the add_update_callback() method.
- Use the `is_available` property to decide whether the device is usable — see below.

### How the connection works

The socket runs on a high port that many networks filter outbound, and the API
drops it periodically even under good conditions. So it is treated as
disposable rather than as the thing the integration is built on:

- **A keepalive maintains it while it is up**, which is also how a half-dead
  connection gets noticed — the keepalive write fails and the socket is torn
  down rather than sitting there looking connected.
- **Nothing reconnects it.** When it dies, that is not an error to recover
  from: state carries on over polling, and the next command opens a fresh one.
- **Polling stands down while a socket is up**, since its pushes already keep
  state current — so a healthy socket costs no extra API traffic. The keepalive
  is what makes this safe: a half-dead socket fails its next keepalive and is
  torn down, bounding how long a zombie connection can suppress polling.
- **A disconnect triggers an immediate poll** rather than waiting out the
  interval, so `is_available` doesn't dip in the gap.

| Property | Meaning |
| --- | --- |
| `is_connected` | Raw socket state. Usually `False`, since the socket only exists around commands. Not a health signal. |
| `is_available` | Whether a recent HTTPS poll succeeded (or a socket is up). **This is the one to gate availability on.** |

```python
controller = IntesisHome(
    'username', 'password',
    use_socket=True,     # default. False = never open a socket (read-only)
    poll_interval=120,   # seconds between HTTPS state polls
)
```

`poll_interval` is clamped to a 60 second floor to stay a good citizen of a
third-party API; pass `0` or `None` to disable polling entirely.

#### Limitation: commands require the socket

The cloud HTTPS endpoint appears to be read-only, so sending a command
(`set_temperature`, `set_power_on`, …) needs the socket. If it cannot be
established — for example on a network that blocks it outbound — the
controller still reports state correctly but is effectively **read-only**, and
the `set_*` methods return `False`.

This is a limitation of what has been implemented, not a proven property of
the API. `examples/probe_cloud_set.py` establishes that `api.php/get/control`
has no write command: it dispatches solely on the `cmd` parameter, treats that
as a map of section names, and echoes unknown sections back as `{"": ""}`
stubs — identically for `set`, `setdatapointvalue`, `control` and a deliberately
invented name. Request bodies are ignored, and `POST /api.php/set/control`
returns HTTP 404.

That result is scoped to one path. The API is path-based, and at least one
other path does perform writes: the official app activates a scene via
`POST /api.php/scenes/exe`. Since scene actions are `{deviceId, uid, value}`
triples — the same shape as a SET — a scene-based write path over HTTPS may
well be reachable. That has not been investigated yet.

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

    # Keep running while the device is reachable. is_available rather than
    # is_connected, so a dropped socket doesn't end the loop while the
    # library is still getting state over HTTP.
    while controller.is_available:
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
