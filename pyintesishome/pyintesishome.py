import threading
import asyncio
import logging
import requests
import json
import time
import queue
import sys
from optparse import OptionParser

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

INTESIS_URL = "https://user.intesishome.com/api.php/get/control"
INTESIS_CMD_STATUS = '{"status":{"hash":"x"},"config":{"hash":"x"}}'
INTESIS_API_VER = "1.8.5"

API_DISCONNECTED = "Disconnected"
API_CONNECTING = "Connecting"
API_AUTHENTICATED = "Connected"

INTESIS_MAP = {
    1: {'name': 'power', 'values': {0: 'off', 1: 'on'}},
    2: {'name': 'mode', 'values': {0: 'auto', 1: 'heat', 2: 'dry', 3: 'fan', 4: 'cool'}},
    4: {'name': 'fan_speed', 'values': {0: "auto", 1: "quiet", 2: "low", 3: "medium", 4: "high"}},
    9: {'name': 'setpoint', 'null': 32768},
    10: {'name': 'temperature'},
    13: {'name': 'working_hours'},
    35: {'name': 'setpoint_min'},
    36: {'name': 'setpoint_max'}
}

COMMAND_MAP = {
    'power': {'uid': 1, 'values': {'off':0, 'on':1}},
    'mode': {'uid': 2, 'values': {'auto':0,'heat':1,"dry":2,"fan":3,"cool":4}},
    'fan_speed': {'uid': 4, 'values': {'auto':0,'quiet':1,"low":2,"medium":3,"high":4}},
    'setpoint': {'uid': 9}
}

try:
    from asyncio import ensure_future
except ImportError:
    # Python 3.4.3 and ealier has this as async
    # pylint: disable=unused-import
    from asyncio import async
    ensure_future = async

class IntesisHome():
    def __init__(self, username, password, loop = None):
        self._username = username
        self._password = password
        self._cmdServer = None
        self._cmdServerPort = None
        self._devices = {}
        self._connectionStatus = API_DISCONNECTED
        self._commandQueue = queue.Queue()
        self._transport = None
        self._updateCallbacks = []

        if loop:
            _LOGGER.info("Latching onto an existing event loop.")
            self._eventLoop = loop
            self._ownLoop = False
        else:
            _LOGGER.info("Creating our own event loop.")
            self._eventLoop = asyncio.new_event_loop()
            self._ownLoop = True

    def connection_made(self, transport):
        """asyncio callback for a successful connection."""
        _LOGGER.info("Connected to Intesis API")
        self._transport = transport

        # Authenticate
        authMsg = '{"command":"connect_req","data":{"token":%s}}' % (self._token)
        self._transport.write(authMsg.encode('ascii'))
        _LOGGER.debug("Data sent: {!r}".format(authMsg))

    def data_received(self, data):
        """asyncio callback when data is received on the socket"""
        if data != '':
            fullData = data.decode('ascii')
            # Sometimes receive two status updates without a line break
            lines = fullData.replace('}}{"command','}}\r\n{"command')
            lines = str.split(lines, '\r\n')
            for line in lines:
                jsonResponse = json.loads(fullData)
                # Parse response
                if jsonResponse['command'] == "connect_rsp":
                    # New connection success
                    if jsonResponse['data']['status'] == "ok":
                        _LOGGER.info("IntesisHome succesfully authenticated")
                        self._connectionStatus = API_AUTHENTICATED
                        self._dequeue()
                elif jsonResponse['command'] == "status":
                        # Value has changed
                        self._update_device_state(jsonResponse['data']['deviceId'],jsonResponse['data']['uid'],jsonResponse['data']['value'])
                        self._update_rssi(jsonResponse['data']['deviceId'],jsonResponse['data']['rssi'])
                        self._send_update_callback()
                elif jsonResponse['command'] == "rssi":
                        # Wireless strength has changed
                        self._update_rssi(jsonResponse['data']['deviceId'],jsonResponse['data']['value'])

    def connection_lost(self, exc):
        """asyncio callback for a lost TCP connection"""
        self._connectionStatus = API_DISCONNECTED
        _LOGGER.info('The server closed the connection')

        if self._ownLoop:
            _LOGGER.info('Stop the event loop')
            self._eventLoop.stop()

    def connect(self):
        """Public method for connecting to IntesisHome API"""
        if self._connectionStatus == API_DISCONNECTED:
            self._connectionStatus = API_CONNECTING
            # Must poll to get the authentication token
            self.poll_status(True)

            try:
                # Create asyncio socket
                coro = self._eventLoop.create_connection(lambda: self, self._cmdServer, self._cmdServerPort)
                _LOGGER.info('Opening connection to Intesis API at %s:%s',self._cmdServer,self._cmdServerPort)
                ensure_future(coro,loop=self._eventLoop)

                if self._ownLoop:
                    _LOGGER.info("Starting IntesisHome event loop.")
                    self._eventLoop.run_until_complete(coro)
                    self._eventLoop.run_forever()
                    self._eventLoop.close()
                    _LOGGER.info("Connection closed.")

            except Exception:
                _LOGGER.error('%s Exception. %s / %s',type(Exception), repr(Exception.args), Exception)

    def stop(self):
        """Public method for shutting down connectivity with the envisalink."""
        self._connectionStatus = API_DISCONNECTED
        self._transport.close()

        if self._ownLoop:
            _LOGGER.info("Shutting down IntesisHome client connection...")
            self._eventLoop.call_soon_threadsafe(self._eventLoop.stop)
        else:
            _LOGGER.info("An event loop was given to us- we will shutdown when that event loop shuts down.")

    def get_devices(self):
        """Public method to return the state of all IntesisHome devices"""
        return self._devices

    def poll_status(self, sendCallback = False):
        """Public method to query IntesisHome for state of device. Notifies subscribers if sendCallback True."""
        payload = {'username': self._username, 'password': self._password, 'cmd': INTESIS_CMD_STATUS,
                   'version': INTESIS_API_VER}

        try:
            r = requests.post(INTESIS_URL, payload)
            if r.status_code == 200:
                status_response = r.json()

                if 'errorCode' in status_response:
                    _LOGGER.error("Error from IntesisHome API: " + status_response['errorMessage'])
                else:
                    self._cmdServer = status_response['config']['serverIP']
                    self._cmdServerPort = status_response['config']['serverPort']
                    self._token = status_response['config']['token']
                    _LOGGER.debug(str.format("Server: {0}:{1}, Token: {2}",self._cmdServer, self._cmdServerPort,
                                             self._token))

                    # Setup devices
                    for installation in status_response['config']['inst']:
                        for device in installation['devices']:
                            if device['id'] not in self._devices:
                                _LOGGER.info("Adding Intesis device ID %s",device['id'])
                                self._devices[device['id']] = {"name": device['name']}
                                _LOGGER.debug(repr(self._devices))

                    # Update device status
                    for status in status_response['status']['status']:
                        uid = status['uid']
                        value = status['value']
                        self._update_device_state(status['deviceId'],status['uid'],status['value'])

                    if sendCallback:
                        self._send_update_callback()

        except requests.RequestException:
                _LOGGER.error('%s Exception. %s / %s',type(Exception), repr(Exception.args), Exception)

    def get_run_hours(self, deviceid):
        """Public method returns the run hours of the IntesisHome controller"""
        run_hours = self._devices[str(deviceid)].get('working_hours')
        return run_hours

    def _set_mode(self, deviceId, mode):
        """Internal method for setting the mode with a string value"""
        if mode in COMMAND_MAP['mode']['values']:
            msg = '{"command":"set","data":{"deviceId":%s,"value":%s,"uid":%s,"seqNo":0}}' % (deviceId, COMMAND_MAP['mode']['values'][mode], COMMAND_MAP['mode']['uid'])
            self._send_command(msg)
            self._devices[str(deviceId)]['mode'] = mode

    def set_temperature(self, deviceId, setpoint):
        """Public method for setting the temperature"""
        set_temp = int(setpoint*10)
        msg = '{"command":"set","data":{"deviceId":%s,"value":%i,"uid":%s,"seqNo":0}}' % (deviceId, set_temp, COMMAND_MAP['setpoint']['uid'])
        self._send_command(msg)
        self._devices[str(deviceId)]['setpoint'] = set_temp

    def set_fan_speed(self, deviceId, fan):
        """Public method to set the fan speed"""
        msg = '{"command":"set","data":{"deviceId":%s,"value":%i,"uid":%s,"seqNo":0}}' % (deviceId, COMMAND_MAP['fan_speed']['values'][fan], COMMAND_MAP['fan_speed']['uid'])
        self._send_command(msg)
        self._devices[str(deviceId)]['fan_speed'] = fan

    def _set_power(self, deviceId, power):
        """Internal method to set power on or off"""
        msg = '{"command":"set","data":{"deviceId":%s,"value":%s,"uid":%s,"seqNo":0}}' % (deviceId, COMMAND_MAP['power']['values'][power], COMMAND_MAP['power']['uid'])
        self._send_command(msg)
        self._devices[str(deviceId)]['power'] = power

    def _send_command(self, message):
        """Internal method to send a command to the API (and connect if necessary)"""
        if self._connectionStatus == API_AUTHENTICATED:
            #try:
            self._transport.write(message.encode('ascii'))
            _LOGGER.debug("Data sent: {!r}".format(message))
            #except Exception:
            #    _LOGGER.error('%s Exception. %s / %s', type(Exception), Exception.args, Exception)
        else:
            _LOGGER.debug("Added message to queue {!r}".format(message))
            self._commandQueue.put(message)
            if self._connectionStatus == API_DISCONNECTED:
                self.connect()

    def _dequeue(self):
        """Internal method to send the command queue to the API"""
        _LOGGER.debug("Dequeue")

        while not self._commandQueue.empty():
            cmd = self._commandQueue.get_nowait()
            if cmd:
                _LOGGER.debug("Sending from queue: {!r}".format(cmd))
                self._transport.write(cmd.encode('ascii'))

    def _update_device_state(self, deviceid, uid, value):
        """Internal method to update the state table of IntesisHome devices"""
        deviceid = str(deviceid)

        if uid in INTESIS_MAP:
            if 'values' in INTESIS_MAP[uid]:
                self._devices[deviceid][INTESIS_MAP[uid]['name']] = INTESIS_MAP[uid]['values'][value]
            elif 'null' in INTESIS_MAP[uid] and value == INTESIS_MAP[uid]['null']:
                self._devices[deviceid][INTESIS_MAP[uid]['name']] = None
            else:
                self._devices[deviceid][INTESIS_MAP[uid]['name']] = value
                _LOGGER.debug(self._devices)

    def _update_rssi(self, deviceid, rssi):
        """Internal method to update the wireless signal strength."""
        if rssi:
            self._devices[str(deviceid)]['rssi'] = rssi

    def set_mode_heat(self, deviceId):
        """Public method to set device to heat asynchronously."""
        self._set_mode(deviceId, 'heat')

    def set_mode_cool(self, deviceId):
        """Public method to set device to cool asynchronously."""
        self._set_mode(deviceId, 'cool')

    def set_mode_fan(self, deviceId):
        """Public method to set device to fan asynchronously."""
        self._set_mode(deviceId, 'fan')

    def set_mode_auto(self, deviceId):
        """Public method to set device to auto asynchronously."""
        self._set_mode(deviceId, 'auto')

    def set_mode_dry(self, deviceId):
        """Public method to set device to dry asynchronously."""
        self._set_mode(deviceId, 'dry')

    def set_power_off(self, deviceId):
        """Public method to turn off the device asynchronously."""
        self._set_power(deviceId, 'off')

    def set_power_on(self, deviceId):
        """Public method to turn on the device asynchronously."""
        self._set_power(deviceId, 'on')

    def get_mode(self, deviceId):
        """Public method returns the current mode of operation."""
        return self._devices[str(deviceId)].get('mode')

    def get_fan_speed(self, deviceid):
        """Public method returns the current fan speed."""
        return self._devices[str(deviceid)].get('fan_speed')

    def get_power_state(self, deviceid):
        """Public method returns the current power state."""
        return self._devices[str(deviceid)].get('power')

    def get_setpoint(self, deviceid):
        """Public method returns the target temperature."""
        setpoint = self._devices[str(deviceid)].get('setpoint')
        if setpoint:
            setpoint = int(setpoint)/10
        return setpoint

    def get_temperature(self, deviceid):
        """Public method returns the current temperature."""
        temperature = self._devices[str(deviceid)].get('temperature')
        if temperature:
            temperature = int(temperature)/10
        return temperature

    def get_max_setpoint(self, deviceid):
        """Public method returns the current maximum target temperature."""
        temperature = self._devices[str(deviceid)].get('setpoint_max')
        if temperature:
            temperature = int(temperature)/10
        return temperature

    def get_min_setpoint(self, deviceid):
        """Public method returns the current minimum target temperature."""
        temperature = self._devices[str(deviceid)].get('setpoint_min')
        if temperature:
            temperature = int(temperature)/10
        return temperature

    def get_rssi(self, deviceid):
        """Public method returns the current wireless signal strength."""
        rssi = self._devices[str(deviceid)].get('rssi')
        return rssi

    def _send_update_callback(self):
        """Internal method to notify all update callback subscribers."""
        if self._updateCallbacks == []:
            _LOGGER.debug("Callback has not been set by client.")

        for callback in self._updateCallbacks:
            callback()

    @property
    def is_connected(self):
        """Returns true if the TCP connection is established."""
        return self._connectionStatus == API_AUTHENTICATED

    @property
    def is_disconnected(self):
        """Returns true when the TCP connection is disconnected and idle."""
        return self._connectionStatus == API_DISCONNECTED

    def add_callback(self, method):
        """Public method to add a callback subscriber."""
        self._updateCallbacks.append(method)

    @asyncio.coroutine
    def keep_alive(self):
        """Send a keepalive command to reset it's watchdog timer."""
        yield from asyncio.sleep(10, loop=self._eventLoop)


def create_parser():
   parser = OptionParser(usage="pyintesishome [options] command [command_options] [command_args]",
        description="Commands: mode fan temp",
        version="unknown")

   parser.add_option("-u", "--user", dest="user",
                     help="username for user.intesishome.com", metavar="USER", default=None)

   parser.add_option("-p", "--password", dest="password",
                     help="password for user.intesishome.com", metavar="PASSWORD", default=None)

   parser.add_option("-i", "--id", dest="deviceid", default=None,
                     help="device id of thermostat to control")

   return parser

def help():
    print("syntax: pyintesishome [options] command [command_args]")
    print("options:")
    print("   --user <username>                 ... username on user.intesishome.com")
    print("   --password <password>             ... password on user.intesishome.com")
    print("   --id <number>                     ... specify device id of unit to control")
    print()
    print("commands: show")
    print("    show                             ... show current state")
    print()
    print("examples:")
    print("    pyintesishome.py --user joe@user.com --password swordfish show")

def main():
    parser = create_parser()
    (opts, args) = parser.parse_args()

    if (len(args)==0) or (args[0]=="help"):
        help()
        sys.exit(-1)

    if (not opts.user) or (not opts.password):
        print("how about specifying a --user and --password option next time?")
        sys.exit(-1)

    controller = IntesisHome(opts.user,opts.password)
    controller.poll_status()

    cmd = args[0]

    if cmd == "show":
        print(repr(controller.get_devices()))
    else:
        if not opts.deviceid:
            print("Please specify a device ID with --id")
            sys.exit(-1)
        if not opts.deviceid in controller.get_devices().keys():
            print("Invalid device ID")
            sys.exit(-1)

        if (cmd == "show"):
            print("Internal state from get_devices():")
            print(repr(controller.get_devices()))
        else:
            print("misunderstood command:", cmd)
            print("do 'pyintesishome.py help' for help")
            sys.exit(-1)

        # Could add command handlers for controlling device but requires adding an event loop.

if __name__=="__main__":
   main()