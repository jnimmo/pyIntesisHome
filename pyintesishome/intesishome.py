""" Main submodule for pyintesishome """
import asyncio
from asyncio import queues
from asyncio.streams import StreamReader, StreamWriter
import json
import logging
import socket
from datetime import datetime
from typing import List

import aiohttp
from asyncio.exceptions import IncompleteReadError

from .const import (
    API_URL,
    API_VER,
    COMMAND_MAP,
    CONFIG_MODE_BITS,
    DEVICE_INTESISBOX,
    DEVICE_INTESISHOME,
    ERROR_MAP,
    INTESIS_CMD_STATUS,
    INTESIS_MAP,
    INTESIS_NULL,
    INTESISBOX_CMD_FANSP,
    INTESISBOX_CMD_GET_AVAIL_DP,
    INTESISBOX_CMD_MODE,
    INTESISBOX_CMD_ONOFF,
    INTESISBOX_CMD_SETPOINT,
    INTESISBOX_CMD_VANELR,
    INTESISBOX_CMD_VANEUD,
    INTESISBOX_INIT,
    INTESISBOX_MAP,
    INTESISBOX_MODE_MAP,
    LOCAL_CMD_GET_AVAIL_DP,
    LOCAL_CMD_GET_DP_VALUE,
    LOCAL_CMD_GET_INFO,
    LOCAL_CMD_LOGIN,
    LOCAL_CMD_SET_DP_VALUE,
    OPERATING_MODE_BITS,
)
from .exceptions import IHAuthenticationError, IHConnectionError
from .helpers import twos_complement_16bit, uint32
from .intesisbase import IntesisBase

_LOGGER = logging.getLogger("pyintesishome")


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
        self._api_url = API_URL[device_type]
        self._api_ver = API_VER[device_type]
        self._cmd_server = None
        self._cmd_server_port = None
        self._auth_token = None
        self._send_queue = asyncio.Queue()
        self._send_queue_task = None
        self._keepalive_task = None
        self._reader = None
        self._writer = None
        self._reconnection_attempt = 0
        self._last_message_received = 0

        super().__init__(
            username=username,
            password=password,
            loop=loop,
            websession=websession,
            device_type=device_type,
        )

    async def _parse_api_messages(self, message):
        _LOGGER.debug("%s API Received: %s", self._device_type, message)
        self._last_message_received = datetime.now()
        resp = json.loads(message)
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
        while True:
            await asyncio.sleep(240)
            _LOGGER.debug("sending keepalive to {self._device_type}")
            device_id = str(next(iter(self._devices)))
            message = f'{{"command":"get","data":{{"deviceId":{device_id},"uid":10}}}}'
            await self._send_queue.put(message)

    async def _handle_packets(self):
        data = True
        while data:
            try:
                data = await self._reader.readuntil(b"}}")
                if not data:
                    break
                message = data.decode("ascii")
                await self._parse_api_messages(message)

            except (
                asyncio.IncompleteReadError,
                TimeoutError,
                ConnectionResetError,
                OSError,
            ) as exc:
                _LOGGER.error(
                    "pyIntesisHome lost connection to the %s server. Exception: %s",
                    self._device_type,
                    exc,
                )
                break

        self._connected = False
        self._connecting = False
        self._auth_token = None
        self._reader = None
        self._writer = None
        self._send_queue_task.cancel()
        await self._send_update_callback()
        return

    async def _run_send_queue(self):
        while self._connected or self._connecting:
            data = await self._send_queue.get()
            try:
                self._writer.write(data.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Sent command %s", data)
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Exception: %s", exc)
                return

    async def connect(self):
        """Public method for connecting to IntesisHome/Airconwithme API"""
        if not self._connected and not self._connecting:
            self._connecting = True
            self._connection_retries = 0

            # Get authentication token over HTTP POST
            while not self._auth_token:
                if self._connection_retries:
                    _LOGGER.debug(
                        "Couldn't get API details, retrying in %i minutes",
                        self._connection_retries,
                    )
                    await asyncio.sleep(self._connection_retries * 60)
                try:
                    self._auth_token = await self.poll_status()
                except IHConnectionError as ex:
                    _LOGGER.error(
                        "Error connecting to the %s server: %s", self._device_type, ex
                    )
                self._connection_retries += 1

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

                # Set socket timeout
                if self._reader._transport._sock:  # pylint: disable=protected-access
                    self._reader._transport._sock.settimeout(  # pylint: disable=protected-access
                        60
                    )
                    try:
                        self._reader._transport._sock.setsockopt(  # pylint: disable=protected-access
                            socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60 * 1000
                        )
                        self._reader._transport._sock.setsockopt(  # pylint: disable=protected-access
                            socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 60 * 1000
                        )
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.debug(
                            "Exception setting TCP_USER_TIMEOUT or SO_KEEPALIVE,"
                            "you can probably ignore this"
                        )

                # Authenticate
                auth_msg = '{"command":"connect_req","data":{"token":%s}}' % (
                    self._auth_token
                )
                # Clear the OTP
                self._auth_token = None
                self._writer.write(auth_msg.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Data sent: %s", auth_msg)
                _LOGGER.debug(
                    "Socket timeout is %s",
                    self._reader._transport._sock.gettimeout(),  # pylint: disable=protected-access
                )

                self._event_loop.create_task(self._handle_packets())
                self._keepalive_task = self._event_loop.create_task(
                    self._send_keepalive()
                )
                self._send_queue_task = self._event_loop.create_task(
                    self._run_send_queue()
                )

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
                await self._send_update_callback()

    async def stop(self):
        """Public method for shutting down connectivity with the envisalink."""
        self._connected = False
        if self._writer:
            self._writer._transport.close()  # pylint: disable=protected-access

        if self._reader:
            self._reader._transport.close()  # pylint: disable=protected-access

        if self._own_session:
            await self._web_session.close()

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

    async def _set_value(self, device_id, uid, value):
        """Internal method to send a command to the API (and connect if necessary)"""
        message = (
            '{"command":"set","data":{"deviceId":%s,"uid":%i,"value":%i,"seqNo":0}}'
            % (device_id, uid, value)
        )
        self._send_queue.put_nowait(message)

    def _get_fan_map(self, device_id):
        return self.get_device_property(device_id, "config_fan_map")
