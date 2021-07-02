"""Tests for pyintesishome."""
import asyncio

import pytest

from pyintesishome import IntesisHome, IntesisHomeLocal
from pyintesishome.const import API_URL, DEVICE_INTESISHOME, DEVICE_INTESISHOME_LOCAL

from . import (
    MOCK_DEVICE_ID,
    MOCK_HOST,
    MOCK_PASS,
    MOCK_USER,
    MOCK_VAL_RUN_HOURS,
    cloud_api_callback,
    local_api_callback,
    mock_aioresponse,  # noqa: F401
)

controllers = {}
loop = asyncio.get_event_loop()


async def async_setup_controllers():
    # The aiohttp.ClientSession should be created within an async function
    controllers["local"] = IntesisHomeLocal(
        MOCK_HOST,
        MOCK_USER,
        MOCK_PASS,
        loop=loop,
        device_type=DEVICE_INTESISHOME_LOCAL,
    )

    controllers["cloud"] = IntesisHome(
        MOCK_USER,
        MOCK_PASS,
        loop=loop,
        device_type=DEVICE_INTESISHOME,
    )


loop.run_until_complete(async_setup_controllers())


@pytest.mark.parametrize("controller", controllers.values(), ids=controllers.keys())
class TestPyIntesisHome:
    @pytest.fixture(autouse=True)
    async def _setup(self, mock_aioresponse):
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

    async def test_connect(self, controller):
        result = await controller.connect()
        assert result == None

    def test_get_power_state(self, controller):
        result = controller.get_power_state(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "off"

    def test_get_mode(self, controller):
        result = controller.get_mode(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "cool"

    def test_get_fan_speed(self, controller):
        result = controller.get_fan_speed(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "quiet"

    def test_get_vertical_swing(self, controller):
        result = controller.get_vertical_swing(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "manual2"

    def test_get_horizontal_swing(self, controller):
        result = controller.get_horizontal_swing(MOCK_DEVICE_ID)
        assert isinstance(result, str)
        assert result == "manual3"

    def test_get_setpoint(self, controller):
        result = controller.get_setpoint(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 21.0

    def test_get_temperature(self, controller):
        result = controller.get_temperature(MOCK_DEVICE_ID)
        assert isinstance(result, float)
        assert result == 24.0

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
