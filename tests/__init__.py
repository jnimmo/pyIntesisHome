"""Tests for pyintesishome."""

import asyncio

import pytest
from aioresponses import CallbackResult, aioresponses

MOCK_HOST = "1.1.1.1"
# A host with no mocked endpoint registered by default, used to simulate a
# device that never answers.
MOCK_UNREACHABLE_HOST = "1.1.1.2"
MOCK_PASS = "password"
MOCK_USER = "admin"
MOCK_DEVICE_ID = "12345"
MOCK_DEVICE_ID_2 = "67890"

MOCK_VAL_POWER_STATE = 0
MOCK_VAL_MODE = 4
MOCK_VAL_FAN_SPEED = 1
MOCK_VAL_VVANE = 2
MOCK_VAL_HVANE = 3
MOCK_VAL_SETPOINT = 210
MOCK_VAL_TEMP = 240
MOCK_VAL_RUN_HOURS = 567
MOCK_VAL_ERROR = 0
MOCK_VAL_MIN_SET = 180
MOCK_VAL_MAX_SET = 300
MOCK_VAL_OUT_TEMP = 260
MOCK_VAL_PRESET = 1

# Mutable switches letting a test change how the mocked local device behaves
# part way through a run. local_api_callback consults them on every request.
LOCAL_DEVICE_STATE = {"failing": False, "reject_auth": False}


def reset_local_device_state():
    """Return the mocked local device to answering normally."""
    LOCAL_DEVICE_STATE.update(failing=False, reject_auth=False)


@pytest.fixture
def mock_aioresponse():
    """Yield a mock aioresponses."""
    with aioresponses() as m:
        yield m


class FakeWMPServer:
    """Minimal WMP (IntesisBox) TCP device for tests.

    Speaks the ASCII protocol on a random local port: commands are
    CR-terminated, replies are CRLF-terminated, SETs are answered with an
    ACK plus a CHN push. Mirrors a quirk observed on real hardware (an
    MH-RC-WMP-1 on a ducted unit): a feature the unit does not have gets
    no reply at all to its LIMITS query, not an ERR. ``silent`` lets a
    test simulate a device that stops answering entirely.
    """

    MAC = "AABBCCDDEEFF"

    def __init__(self):
        self.port = None
        self.received = []
        self.raw = b""
        self.silent = False
        self.state = {
            "ONOFF": "OFF",
            "MODE": "AUTO",
            "AMBTEMP": "250",
            "SETPTEMP": "230",
            "FANSP": "2",
            "VANEUD": "1",
        }
        self._server = None
        self._writers = []

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        await self.drop_clients()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def drop_clients(self):
        """Close all connected clients, simulating a connection loss."""
        writers, self._writers = self._writers, []
        for writer in writers:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass

    async def _handle(self, reader, writer):
        self._writers.append(writer)
        buffer = b""
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    break
                self.raw += chunk
                buffer += chunk
                while b"\r" in buffer:
                    line, buffer = buffer.split(b"\r", 1)
                    command = line.decode("ascii").strip()
                    if not command:
                        continue
                    self.received.append(command)
                    reply = self._reply(command)
                    if reply and not self.silent:
                        writer.write(reply.encode("ascii"))
                        await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _reply(self, command):
        if command == "ID":
            return (
                f"ID:MH-RC-WMP-1,{self.MAC},127.0.0.1,ASCII,"
                "v1.3.3,-51,WMP_TEST,N,1\r\n"
            )
        if command.startswith("LIMITS:"):
            return {
                "LIMITS:SETPTEMP": "LIMITS:SETPTEMP,[180,300]\r\n",
                "LIMITS:FANSP": "LIMITS:FANSP,[AUTO,1,2,3,4]\r\n",
                "LIMITS:MODE": "LIMITS:MODE,[AUTO,HEAT,DRY,FAN,COOL]\r\n",
                "LIMITS:VANEUD": "LIMITS:VANEUD,[1,2,3,4,SWING]\r\n",
                # LIMITS:VANELR deliberately absent: silence, like the
                # real ducted unit.
            }.get(command)
        if command.startswith("GET,1:"):
            function = command.split(":", 1)[1]
            value = self.state.get(function)
            if value is None:
                return None
            return f"CHN,1:{function},{value}\r\n"
        if command.startswith("SET,1:"):
            function, value = command.split(":", 1)[1].split(",", 1)
            self.state[function] = value
            return f"ACK\r\nCHN,1:{function},{value}\r\n"
        return None


def local_api_callback(url, **kwargs):
    if LOCAL_DEVICE_STATE["failing"]:
        # A device that has stopped answering usefully. 500 surfaces as an
        # IHConnectionError out of _request without exercising the retry
        # loop's timeout, keeping tests fast.
        return CallbackResult(status=500)

    if LOCAL_DEVICE_STATE["reject_auth"]:
        # Credentials no longer accepted, e.g. changed on the device. Error
        # code 5 makes _request clear the session and re-authenticate, and
        # the login then fails the same way.
        return CallbackResult(
            status=200,
            payload={
                "success": False,
                "data": None,
                "error": {"code": 5, "message": "Incorrect User name or password"},
            },
        )

    req_json = kwargs.pop("json")
    req_cmd = req_json["command"]
    req_data = req_json["data"]

    if req_cmd == "login":
        assert "username" in req_data
        assert "password" in req_data

        if req_data["username"] == MOCK_USER and req_data["password"] == MOCK_PASS:
            return CallbackResult(
                status=200,
                payload={
                    "success": True,
                    "data": {"id": {"sessionID": "lf1XbgHmapgwEjvpc2m8joB4KmREqkm"}},
                },
            )
        else:
            return CallbackResult(
                status=200,
                payload={
                    "success": False,
                    "data": None,
                    "error": {"code": 5, "message": "Incorrect User name or password"},
                },
            )

    if req_cmd == "getinfo":
        return CallbackResult(
            status=200,
            payload={
                "success": True,
                "data": {
                    "info": {
                        "wlanSTAMAC": "CC:3F:1D:12:34:56",
                        "wlanAPMAC": "CE:3F:1D:12:34:56",
                        "ownSSID": "DEVICE_123456",
                        "fwVersion": "1.4.7; 1.3.3; 1.5; 1.0.1.0",
                        "wlanFwVersion": "1.2.0",
                        "acStatus": 0,
                        "wlanLNK": 1,
                        "ssid": "My SSID",
                        "rssi": -53,
                        "tcpServerLNK": 1,
                        "localdatetime": "Fri Jul 02 12:01:12 +2:00 2021 DST",
                        "powerStatus": 78,
                        "wifiTxPower": 78,
                        "lastconfigdatetime": 0,
                        "deviceModel": "MH-AC-WIFI-1",
                        "sn": MOCK_DEVICE_ID,
                        "lastError": 0,
                    }
                },
            },
        )

    if req_cmd == "getavailabledatapoints":
        assert "sessionID" in req_data

        return CallbackResult(
            status=200,
            payload={
                "success": True,
                "data": {
                    "dp": {
                        "datapoints": [
                            {
                                "uid": 1,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 2, "states": [0, 1]},
                            },
                            {
                                "uid": 2,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 5, "states": [0, 1, 2, 3, 4]},
                            },
                            {
                                "uid": 4,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 4, "states": [1, 2, 3, 4]},
                            },
                            {
                                "uid": 5,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 5, "states": [1, 2, 3, 4, 10]},
                            },
                            {
                                "uid": 6,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 5, "states": [1, 2, 3, 4, 10]},
                            },
                            {
                                "uid": 9,
                                "rw": "rw",
                                "type": 2,
                                "descr": {"maxValue": 300, "minValue": 180},
                            },
                            {
                                "uid": 10,
                                "rw": "r",
                                "type": 2,
                                "descr": {"maxValue": 500, "minValue": -100},
                            },
                            {
                                "uid": 12,
                                "rw": "rw",
                                "type": 1,
                                "descr": {"numStates": 2, "states": [0, 1]},
                            },
                            {"uid": 13, "rw": "rw", "type": 0, "descr": {}},
                            {
                                "uid": 14,
                                "rw": "r",
                                "type": 1,
                                "descr": {"numStates": 2, "states": [0, 1]},
                            },
                            {"uid": 15, "rw": "r", "type": 3, "descr": {}},
                            {
                                "uid": 35,
                                "rw": "r",
                                "type": 2,
                                "descr": {"maxValue": 300, "minValue": 180},
                            },
                            {
                                "uid": 36,
                                "rw": "r",
                                "type": 2,
                                "descr": {"maxValue": 300, "minValue": 180},
                            },
                            {
                                "uid": 37,
                                "rw": "r",
                                "type": 2,
                                "descr": {"maxValue": 430, "minValue": -250},
                            },
                            {
                                "uid": 42,
                                "rw": "r",
                                "type": 1,
                                "descr": {"numStates": 3, "states": [0, 1, 2]},
                            },
                            {"uid": 181, "rw": "rw", "type": 0, "descr": {}},
                            {"uid": 182, "rw": "rw", "type": 0, "descr": {}},
                            {"uid": 183, "rw": "rw", "type": 0, "descr": {}},
                            {"uid": 184, "rw": "rw", "type": 0, "descr": {}},
                        ]
                    }
                },
            },
        )

    if req_cmd == "getdatapointvalue":
        assert "sessionID" in req_data
        assert "uid" in req_data
        assert isinstance(req_data["uid"], int) or "all"

        return CallbackResult(
            status=200,
            payload={
                "success": True,
                "data": {
                    "dpval": [
                        {"uid": 1, "value": MOCK_VAL_POWER_STATE, "status": 0},
                        {"uid": 2, "value": MOCK_VAL_MODE, "status": 0},
                        {"uid": 4, "value": MOCK_VAL_FAN_SPEED, "status": 0},
                        {"uid": 5, "value": MOCK_VAL_VVANE, "status": 0},
                        {"uid": 6, "value": MOCK_VAL_HVANE, "status": 0},
                        {"uid": 9, "value": MOCK_VAL_SETPOINT, "status": 0},
                        {"uid": 10, "value": MOCK_VAL_TEMP, "status": 0},
                        {"uid": 12, "value": 0, "status": 0},
                        {"uid": 13, "value": MOCK_VAL_RUN_HOURS, "status": 0},
                        {"uid": 14, "value": 0, "status": 0},
                        {"uid": 15, "value": MOCK_VAL_ERROR, "status": 0},
                        {"uid": 35, "value": MOCK_VAL_MIN_SET, "status": 0},
                        {"uid": 36, "value": MOCK_VAL_MAX_SET, "status": 0},
                        {"uid": 37, "value": MOCK_VAL_OUT_TEMP, "status": 0},
                        {"uid": 42, "value": MOCK_VAL_PRESET, "status": 0},
                        {"uid": 181, "value": 0, "status": 0},
                        {"uid": 182, "value": 0, "status": 0},
                        {"uid": 183, "value": 0, "status": 0},
                        {"uid": 184, "value": 0, "status": 0},
                    ]
                },
            },
        )

    if req_cmd == "setdatapointvalue":
        assert "sessionID" in req_data
        assert "uid" in req_data
        assert "value" in req_data
        assert isinstance(req_data["uid"], int)
        assert isinstance(req_data["value"], int)

        return CallbackResult(
            status=200,
            payload={
                "success": True,
                "data": None,
            },
        )

    return CallbackResult(status=500)


def cloud_api_callback(url, **kwargs):
    req_data = kwargs["data"]
    req_cmd = req_data["cmd"]

    payload = {}

    if "status" in req_cmd:
        payload["status"] = {
            "hash": "7398e787639ab87c431f77b96e4a1590f16a4384",
            "status": [
                {"deviceId": MOCK_DEVICE_ID, "uid": 1, "value": MOCK_VAL_POWER_STATE},
                {"deviceId": MOCK_DEVICE_ID, "uid": 2, "value": MOCK_VAL_MODE},
                {"deviceId": MOCK_DEVICE_ID, "uid": 4, "value": MOCK_VAL_FAN_SPEED},
                {"deviceId": MOCK_DEVICE_ID, "uid": 5, "value": MOCK_VAL_VVANE},
                {"deviceId": MOCK_DEVICE_ID, "uid": 6, "value": MOCK_VAL_HVANE},
                {"deviceId": MOCK_DEVICE_ID, "uid": 9, "value": MOCK_VAL_SETPOINT},
                {"deviceId": MOCK_DEVICE_ID, "uid": 10, "value": MOCK_VAL_TEMP},
                {"deviceId": MOCK_DEVICE_ID, "uid": 12, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 13, "value": MOCK_VAL_RUN_HOURS},
                {"deviceId": MOCK_DEVICE_ID, "uid": 14, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 15, "value": MOCK_VAL_ERROR},
                {"deviceId": MOCK_DEVICE_ID, "uid": 34, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 35, "value": MOCK_VAL_MIN_SET},
                {"deviceId": MOCK_DEVICE_ID, "uid": 36, "value": MOCK_VAL_MAX_SET},
                {"deviceId": MOCK_DEVICE_ID, "uid": 37, "value": MOCK_VAL_OUT_TEMP},
                {"deviceId": MOCK_DEVICE_ID, "uid": 42, "value": MOCK_VAL_PRESET},
                {"deviceId": MOCK_DEVICE_ID, "uid": 54, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 61, "value": 63},
                {"deviceId": MOCK_DEVICE_ID, "uid": 62, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 63, "value": 1054},
                {"deviceId": MOCK_DEVICE_ID, "uid": 64, "value": 1054},
                {"deviceId": MOCK_DEVICE_ID, "uid": 65, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 66, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 67, "value": 30},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50000, "value": 1},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50001, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50002, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50003, "value": 0},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50004, "value": 240},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50005, "value": 280},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50006, "value": 190},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50007, "value": 230},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50008, "value": 1},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50009, "value": 3},
                {"deviceId": MOCK_DEVICE_ID, "uid": 50010, "value": 255},
                {"deviceId": MOCK_DEVICE_ID, "uid": 60002, "value": 204},
                # A second device, so tests can cover multi-device
                # installations. Deliberately absent from the "inst" block
                # below, which also exercises the unregistered-device path.
                {"deviceId": MOCK_DEVICE_ID_2, "uid": 1, "value": MOCK_VAL_POWER_STATE},
                {"deviceId": MOCK_DEVICE_ID_2, "uid": 10, "value": MOCK_VAL_TEMP},
            ],
        }
    if "config" in req_cmd:
        payload["config"] = {
            "token": 1234567890,
            "pushToken": "channel-0123456789",
            "lastAppVersion": "1.8.1",
            "forceUpdate": 0,
            "setDelay": 0.7,
            "serverIP": "127.0.0.1",
            "serverPort": 19999,
            "hash": "ea4b71bd4e8ba5ad045e6bbbb4118d2816efbcb5",
            "inst": [
                {
                    "id": 1,
                    "order": 1,
                    "name": "First installation",
                    "devices": [
                        {
                            "id": MOCK_DEVICE_ID,
                            "name": "MOCK DEVICE",
                            "familyId": 4864,
                            "modelId": 550,
                            "installationId": 20151,
                            "zoneId": 20168,
                            "order": 1,
                            "widgets": [15, 3, 5, 7, 17, 9, 13],
                        },
                    ],
                },
            ],
        }

    if payload:
        return CallbackResult(status=200, payload=payload)
    else:
        return CallbackResult(status=500)
