""" Main submodule for pyintesishome """
import asyncio
import json
import logging
import socket

import aiohttp

from .const import API_URL, API_VER, DEVICE_INTESISHOME, INTESIS_CMD_STATUS
from .exceptions import IHAuthenticationError, IHConnectionError
from .intesisbase import IntesisBase

_LOGGER = logging.getLogger("pyintesishome")


# pylint: disable=too-many-instance-attributes, too-many-arguments, too-many-public-methods
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
        return

    async def _send_keepalive(self):
        try:
            while True:
                await asyncio.sleep(240)
                _LOGGER.debug("sending keepalive to {self._device_type}")
                device_id = str(next(iter(self._devices)))
                message = (
                    f'{{"command":"get","data":{{"deviceId":{device_id},"uid":10}}}}'
                )
                await self._send_command(message)
        except asyncio.CancelledError:
            _LOGGER.debug("Cancelled the keepalive task")

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._connection_retries = 0

            self._devices = {}
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

                # pylint: disable=C0209
                auth_msg = '{"command":"connect_req","data":{"token":%s}}' % (
                    self._auth_token
                )
                await self._send_command(auth_msg)
                # Clear the OTP
                self._auth_token = None
                self._receive_task = self._event_loop.create_task(self._data_received())
                self._keepalive_task = self._event_loop.create_task(
                    self._send_keepalive()
                )
            # Get authentication token over HTTP POST
            except (  # pylint: disable=broad-except
                ConnectionRefusedError,
                Exception,
            ) as exc:
                _LOGGER.error(
                    "Connection to %s:%s failed with exception %s",
                    self._cmd_server,
                    self._cmd_server_port,
                    exc,
                )
            self._connected = False
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
        except (aiohttp.client_exceptions.ClientConnectorError) as exc:
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
            for installation in config.get("inst"):
                for device in installation.get("devices"):
                    self._devices[device["id"]] = {
                        "name": device["name"],
                        "widgets": device["widgets"],
                        "model": device["modelId"],
                    }
                    _LOGGER.debug(repr(self._devices))

            # Update device status
            for status in status_response["status"]["status"]:
                device_id = str(status["deviceId"])

                # Handle devices which don't appear in installation
                if device_id not in self._devices:
                    self._devices[device_id] = {
                        "name": "Device " + device_id,
                        "widgets": [42],
                    }

                self._update_device_state(device_id, status["uid"], status["value"])

            if sendcallback:
                await self._send_update_callback(device_id=str(device_id))

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
