"""Tests for pyintesishome."""
import pytest
from aioresponses import CallbackResult, aioresponses

MOCK_HOST = "1.1.1.1"
MOCK_PASS = "password"
MOCK_USER = "admin"
MOCK_DEVICE_ID = "mock_dev_id"

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


@pytest.fixture
def mock_aioresponse():
    """Yield a mock aioresponses."""
    with aioresponses() as m:
        yield m


def local_api_callback(url, **kwargs):
    req_json = kwargs.pop("json")
    req_cmd = req_json["command"]
    req_data = req_json["data"]

    if req_cmd == "login":
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
                        "ssid": "Klomp IOT",
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

    return CallbackResult(status=500)


def cloud_api_callback(url, **kwargs):
    req_data = kwargs["data"]
    req_cmd = req_data["cmd"]
    print(req_cmd)

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
                {"deviceId": MOCK_DEVICE_ID, "uid": 63, "value": 0},
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
            ],
        }
    if "config" in req_cmd:
        payload["config"] = {
            "token": 1234567890,
            "pushToken": "channel-0123456789",
            "lastAppVersion": "1.8.1",
            "forceUpdate": 0,
            "setDelay": 0.7,
            "serverIP": "212.92.35.33",
            "serverPort": 8210,
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
