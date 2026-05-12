"""Main submodule for pyintesishome"""

import asyncio
import json
import logging
import socket

import aiohttp

from .const import API_URL, API_VER, DEVICE_INTESISHOME, INTESIS_CMD_STATUS
from .exceptions import IHAuthenticationError, IHConnectionError
from .intesisbase import IntesisBase

_LOGGER = logging.getLogger("pyintesishome")


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-positional-arguments, too-many-public-methods
class IntesisHome(IntesisBase):
    """pyintesishome cloud class"""

    def __init__(
        self,
        username,
        password,
        loop=None,
        websession=None,
        device_type=DEVICE_INTESISHOME,
    ):
        super().__init__(
            device_type=device_type,
            username=username,
            loop=loop,
            password=password,
            websession=websession,
        )
        self._api_url = API_URL[device_type]
        self._api_ver = API_VER[device_type]
        self._cmd_server = None
        self._cmd_server_port = None
        self._auth_token = None
        self._controller_id = username
        self._should_reconnect = True
        self._reconnect_task: asyncio.Task = None
        self._reconnect_delay_initial = 5
        self._reconnect_delay_max = 300

    async def _parse_response(self, decoded_data):
        _LOGGER.debug("%s API Received: %s", self._device_type, decoded_data)
        resp = json.loads(decoded_data)
        # Parse response
        if resp["command"] == "connect_rsp":
            # New connection success
            if resp["data"]["status"] == "ok":
                _LOGGER.info("%s successfully authenticated", self._device_type)
                self._connected = True
                self._connecting = False
                self._connection_retries = 0
                await self._send_update_callback()
        elif resp["command"] == "status":
            # Value has changed
            self._update_device_state(
                resp["data"]["deviceId"],
                resp["data"]["uid"],
                resp["data"]["value"],
            )
            if resp["data"]["uid"] != 60002:
                await self._send_update_callback(
                    device_id=str(resp["data"]["deviceId"])
                )
        elif resp["command"] == "rssi":
            # Wireless strength has changed
            self._update_rssi(resp["data"]["deviceId"], resp["data"]["value"])
        else:
            _LOGGER.debug("Unexpected command received: %s", resp["command"])
        # Ensure the _received_response event is set
        if not self._received_response.is_set():
            _LOGGER.debug("Setting _received_response event")
            self._received_response.set()
        return

    async def _send_keepalive(self):
        try:
            while True:
                await asyncio.sleep(120)
                _LOGGER.debug("sending keepalive to %s", self._device_type)
                device_id = str(next(iter(self._devices)))
                message = (
                    f'{{"command":"get","data":{{"deviceId":{device_id},"uid":10}}}}'
                )
                # Fire and forget. The cloud doesn't appear to emit a
                # synthetic response to a get, so waiting on
                # _received_response would always time out and tear the
                # socket down. The actual purpose of the keepalive is to
                # keep bytes flowing; the server's eventual status frame
                # arrives via _data_received like any other state push.
                await self._send_command(message, wait_for_response=False)
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the keepalive task")

    async def _handle_disconnect(self):
        """Schedule a reconnect attempt unless we've been intentionally stopped."""
        if not self._should_reconnect:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self._event_loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Retry connect() with exponential backoff until reconnected or stopped."""
        delay = self._reconnect_delay_initial
        while self._should_reconnect and not self._connected:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if not self._should_reconnect:
                return
            _LOGGER.info("Reconnecting to %s API", self._device_type)
            try:
                await self.connect()
            except IHAuthenticationError as exc:
                _LOGGER.error(
                    "Authentication failure during reconnect to %s; "
                    "stopping retries: %s",
                    self._device_type,
                    exc,
                )
                self._should_reconnect = False
                return
            except IHConnectionError as exc:
                _LOGGER.warning(
                    "Reconnect to %s failed: %s", self._device_type, exc
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "Unexpected error reconnecting to %s: %s",
                    self._device_type,
                    exc,
                )
            if self._connected:
                _LOGGER.info("Reconnected to %s API", self._device_type)
                return
            delay = min(delay * 2, self._reconnect_delay_max)

    async def stop(self):
        """Disable reconnect and shut the controller down fully."""
        self._should_reconnect = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        await super().stop()

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._should_reconnect = True
            try:
                self._connection_retries = 0

                # Don't wipe self._devices here. poll_status() overwrites
                # entries in place and the brief reset-then-repopulate window
                # is a race against any concurrent consumer that reads
                # get_devices() while we are awaiting poll_status.
                await self._cancel_task_if_exists(self._receive_task)

                try:
                    self._auth_token = await self.poll_status()
                except IHAuthenticationError as exc:
                    _LOGGER.error("Error connecting to IntesisHome API: %s", exc)
                    raise IHAuthenticationError from exc
                except IHConnectionError as exc:
                    _LOGGER.error("Error connecting to IntesisHome API: %s", exc)
                    raise IHConnectionError from exc

                _LOGGER.debug(
                    "Opening connection to %s API at %s:%i",
                    self._device_type,
                    self._cmd_server,
                    self._cmd_server_port,
                )
                try:
                    # Create asyncio socket
                    self._reader, self._writer = await asyncio.open_connection(
                        self._cmd_server, self._cmd_server_port
                    )
                except OSError as exc:
                    _LOGGER.warning(
                        "Connection to %s:%s failed: %s; auto-reconnect will retry",
                        self._cmd_server,
                        self._cmd_server_port,
                        exc,
                    )
                    self._connected = False
                    await self._handle_disconnect()
                    return

                auth_msg = json.dumps(
                    {"command": "connect_req", "data": {"token": self._auth_token}}
                )
                self._receive_task = self._event_loop.create_task(self._data_received())
                await self._send_command(auth_msg)
                # Clear the OTP
                self._auth_token = None

                if not self._connected:
                    _LOGGER.warning(
                        "Did not receive connect_rsp from %s API; "
                        "auto-reconnect will retry",
                        self._device_type,
                    )
                    # Close the socket so _data_received exits and triggers
                    # the disconnect hook (which schedules reconnect).
                    self._close_writer()
                    return

                self._keepalive_task = self._event_loop.create_task(
                    self._send_keepalive()
                )
            finally:
                self._connecting = False

    async def poll_status(self, sendcallback=False):
        """Public method to query IntesisHome for state of device.
        Notifies subscribers if sendCallback True."""
        get_status = {
            "username": self._username,
            "password": self._password,
            "cmd": INTESIS_CMD_STATUS,
            "version": self._api_ver,
        }

        status_response = None
        try:
            async with self._web_session.post(
                url=self._api_url, data=get_status
            ) as resp:
                status_response = await resp.json(content_type=None)
                _LOGGER.debug(status_response)
        except aiohttp.client_exceptions.ClientConnectorError as exc:
            raise IHConnectionError from exc
        except (aiohttp.client_exceptions.ClientError, socket.gaierror) as exc:
            self._error_message = f"Error connecting to {self._device_type} API: {exc}"
            _LOGGER.error("%s Exception. %s / %s", type(exc), repr(exc.args), exc)
            raise IHConnectionError from exc

        if status_response:
            if "errorCode" in status_response:
                self._error_message = status_response["errorMessage"]
                _LOGGER.error("Error from API %s", repr(self._error_message))
                raise IHAuthenticationError()

            config = status_response.get("config")
            if config:
                self._cmd_server = config.get("serverIP")
                self._cmd_server_port = config.get("serverPort")
                self._auth_token = config.get("token")

                _LOGGER.debug(
                    "Server: %s:%i, Token: %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    self._auth_token,
                )

            # Setup devices
            for installation in config.get("inst") or []:
                for device in installation.get("devices") or []:
                    self._devices[device["id"]] = {
                        "name": device["name"],
                        "widgets": device["widgets"],
                        "model": device["modelId"],
                    }
                    _LOGGER.debug(repr(self._devices))

            # Update device status
            device_id = None
            for status in status_response["status"]["status"]:
                device_id = str(status["deviceId"])

                # Handle devices which don't appear in installation
                if device_id not in self._devices:
                    self._devices[device_id] = {
                        "name": "Device " + device_id,
                        "widgets": [42],
                    }

                self._update_device_state(device_id, status["uid"], status["value"])

            if sendcallback and device_id is not None:
                await self._send_update_callback(device_id=device_id)

        return self._auth_token

    # pylint: disable=C0209
    async def _set_value(self, device_id, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = (
            '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}'
            % (device_id, uid, value)
        )
        await self._send_command(message)

    def _get_fan_map(self, device_id):
        return self.get_device_property(device_id, "config_fan_map")
