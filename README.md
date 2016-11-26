# pyIntesisHome
This project is a python3 library for interfacing with the IntesisHome Smart AC controllers.
It is fully asynchronous using the asyncio library, and utilises the private API used by the IntesisHome mobile apps.

## Usage
 - Instantiate the IntesisHome controller device with username and password for the user.intesishome.com website.
 - Status can be polled using the poll_status command suggested maximum of once every 5 minutes.
 - Commands are sent using a TCP connection to the API which will then remain open until the connection times out. 
 - While the persistent TCP connection is open, status updates are pushed to the device over the socket meaning polling is not required (check using *is_connected* property)
 - Callbacks to be notified of state updates can be added with the add_callback() method.

## Basic example
*Requires an async event loop to connect to the API and send commands*
'''
controller = IntesisHome(username, password, eventloop)
controller.poll_status()
controller.add_callback(update_callback())

if controller.get_power_state('12015601252591') == 'off':
  controller.set_power_on('12015601252591')
controller.set_mode_heat('12015601252591')
controller.set_temperature('12015601252591', 22)
controller.set_fan_speed('12015601252591','quiet')

def update_callback()
  print("IntesisHome status changed.")
'''
