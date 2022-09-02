"""Tests for pyintesishome."""
import asyncio

import aiohttp
import pytest

from pyintesishome import IntesisHome, IntesisHomeLocal
from pyintesishome.const import API_URL, DEVICE_INTESISHOME

from . import mock_aioresponse  # noqa: F401
from . import (
    MOCK_DEVICE_ID,
    MOCK_HOST,
    MOCK_PASS,
    MOCK_USER,
    MOCK_VAL_RUN_HOURS,
    cloud_api_callback,
    intesisbox_api_callback,
    local_api_callback,
)

controllers = {}


async def async_setup_controllers():
    # The aiohttp.ClientSession should be created within an async function
    session = aiohttp.ClientSession()
    loop = asyncio.get_event_loop()

    controllers["local"] = IntesisHomeLocal(
        MOCK_HOST,
        MOCK_USER,
        MOCK_PASS,
        loop=loop,
        websession=session,
    )

    # controllers["intesisbox"] = IntesisBox(
    #     MOCK_HOST,
    #     loop=loop,
    #     websession=session,
    # )

    controllers["cloud"] = IntesisHome(
        MOCK_USER,
        MOCK_PASS,
        loop=loop,
        websession=session,
        device_type=DEVICE_INTESISHOME,
    )


asyncio.run(async_setup_controllers())


@pytest.mark.parametrize("controller", controllers.values(), ids=controllers.keys())
class TestPyIntesisHome:
    @pytest.fixture(autouse=True)
    async def _setup(self, mock_aioresponse, loop):  # noqa: F811
        mock_aioresponse.post(
            f"http://{MOCK_HOST}/api.cgi",
            callback=local_api_callback,
            repeat=True,
        )

        mock_aioresponse.post(
            f"{API_URL[DEVICE_INTESISHOME]}",
            callback=cloud_api_callback,
            repeat=True,
        )

        mock_aioresponse.post(
            MOCK_HOST,
            callback=intesisbox_api_callback,
            repeat=True,
        )

    async def test_connect(self, controller):
        result = await controller.connect()
        assert result is None

    def test_get_power_state(self, controller):
        result = controller.get_power_state(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "off"

    async def test_set_power(self, controller):
        await controller.set_power_on(MOCK_DEVICE_ID)
        await controller.set_power_off(MOCK_DEVICE_ID)

    def test_get_mode(self, controller):
        result = controller.get_mode(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "cool"

    def test_get_mode_list(self, controller):
        result = controller.get_mode_list(MOCK_DEVICE_ID)
        assert isinstance(result, list)
        assert len(result)

    async def test_set_mode(self, controller):
        await controller.set_mode_heat(MOCK_DEVICE_ID)
        await controller.set_mode_cool(MOCK_DEVICE_ID)
        await controller.set_mode_fan(MOCK_DEVICE_ID)
        await controller.set_mode_auto(MOCK_DEVICE_ID)
        await controller.set_mode_dry(MOCK_DEVICE_ID)

    def test_get_fan_speed(self, controller):
        result = controller.get_fan_speed(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "quiet"

    def test_get_fan_speed_list(self, controller):
        result = controller.get_fan_speed_list(MOCK_DEVICE_ID)
        assert isinstance(result, list)
        assert len(result)

    async def test_set_fan_speed(self, controller):
        await controller.set_fan_speed(MOCK_DEVICE_ID, "high")

    def test_has_vertical_swing(self, controller):
        result = controller.has_vertical_swing(MOCK_DEVICE_ID)
        assert isinstance(result, bool)
        assert result is True

    def test_get_vertical_swing(self, controller):
        result = controller.get_vertical_swing(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "manual2"

    async def test_set_vertical_vane(self, controller):
        await controller.set_vertical_vane(MOCK_DEVICE_ID, "manual4")

    def test_has_horizontal_swing(self, controller):
        result = controller.has_horizontal_swing(MOCK_DEVICE_ID)
        assert isinstance(result, bool)
        assert result is True

    def test_get_horizontal_swing(self, controller):
        result = controller.get_horizontal_swing(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "manual3"

    async def test_set_horizontal_vane(self, controller):
        await controller.set_horizontal_vane(MOCK_DEVICE_ID, "manual4")

    def test_has_setpoint_control(self, controller):
        result = controller.has_setpoint_control(MOCK_DEVICE_ID)
        assert isinstance(result, bool)
        assert result is True

    def test_get_setpoint(self, controller):
        result = controller.get_setpoint(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 21.0

    def test_get_temperature(self, controller):
        result = controller.get_temperature(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 24.0

    async def test_set_temperature(self, controller):
        await controller.set_temperature(MOCK_DEVICE_ID, 10)

    def test_get_run_hours(self, controller):
        result = controller.get_run_hours(MOCK_DEVICE_ID)
        assert isinstance(result, int)
        assert result == MOCK_VAL_RUN_HOURS

    def test_get_error(self, controller):
        result = controller.get_error(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "H00: No abnormality detected"

    def test_get_min_setpoint(self, controller):
        result = controller.get_min_setpoint(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 18.0

    def test_get_max_setpoint(self, controller):
        result = controller.get_max_setpoint(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 30.0

    def test_get_outdoor_temperature(self, controller):
        result = controller.get_outdoor_temperature(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 26.0

    def test_get_preset_mode(self, controller):
        result = controller.get_preset_mode(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "eco"

    def test_get_devices(self, controller):
        result = controller.get_devices()
        assert isinstance(result, dict)
        assert len(result) == 1

    def test_get_device(self, controller):
        result = controller.get_device(MOCK_DEVICE_ID)
        assert isinstance(result, dict)
        assert len(result) > 20
