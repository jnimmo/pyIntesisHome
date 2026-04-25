"""Tests for pyintesishome."""

import asyncio

import aiohttp
import pytest
import pytest_asyncio

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


@pytest.fixture(autouse=True)
def setup_mocks(mock_aioresponse):  # noqa: F811
    """Register mock HTTP endpoints for all tests."""
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


@pytest_asyncio.fixture
async def local_controller():
    """Create and connect an IntesisHomeLocal controller."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHomeLocal(
            MOCK_HOST,
            MOCK_USER,
            MOCK_PASS,
            websession=session,
        )
        await controller.connect()
        # Allow the background updater task one iteration to populate device state.
        await asyncio.sleep(0.05)
        yield controller
        await controller.stop()


@pytest_asyncio.fixture
async def cloud_controller():
    """Create and connect a cloud IntesisHome controller."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER,
            MOCK_PASS,
            websession=session,
            device_type=DEVICE_INTESISHOME,
        )
        await controller.connect()
        yield controller


@pytest.fixture(params=["local", "cloud"])
def controller(request):
    """Parametrized fixture returning either controller type via indirect dispatch."""
    return request.getfixturevalue(f"{request.param}_controller")


@pytest.mark.asyncio
async def test_connect_local(local_controller):
    assert local_controller is not None


@pytest.mark.asyncio
async def test_connect_cloud(cloud_controller):
    assert cloud_controller is not None


@pytest.mark.asyncio
async def test_get_power_state(controller):
    result = controller.get_power_state(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "off"


@pytest.mark.asyncio
async def test_set_power(controller):
    await controller.set_power_on(MOCK_DEVICE_ID)
    await controller.set_power_off(MOCK_DEVICE_ID)


@pytest.mark.asyncio
async def test_get_mode(controller):
    result = controller.get_mode(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "cool"


@pytest.mark.asyncio
async def test_get_mode_list(controller):
    result = controller.get_mode_list(MOCK_DEVICE_ID)
    assert isinstance(result, list)
    assert len(result)


@pytest.mark.asyncio
async def test_get_mode_list_none_map(cloud_controller):
    """Regression test for HA issue #167474 — None mode_map must not raise TypeError."""
    device = cloud_controller.get_device(MOCK_DEVICE_ID)
    saved_config = device.pop("config_mode_map", None)
    device.pop("config_operating_mode", None)
    result = cloud_controller.get_mode_list(MOCK_DEVICE_ID)
    assert isinstance(result, list)
    assert result == []
    if saved_config is not None:
        device["config_mode_map"] = saved_config


@pytest.mark.asyncio
async def test_set_mode(controller):
    await controller.set_mode_heat(MOCK_DEVICE_ID)
    await controller.set_mode_cool(MOCK_DEVICE_ID)
    await controller.set_mode_fan(MOCK_DEVICE_ID)
    await controller.set_mode_auto(MOCK_DEVICE_ID)
    await controller.set_mode_dry(MOCK_DEVICE_ID)


@pytest.mark.asyncio
async def test_get_fan_speed(controller):
    result = controller.get_fan_speed(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "quiet"


@pytest.mark.asyncio
async def test_get_fan_speed_list(controller):
    result = controller.get_fan_speed_list(MOCK_DEVICE_ID)
    assert isinstance(result, list)
    assert len(result)


@pytest.mark.asyncio
async def test_set_fan_speed(controller):
    await controller.set_fan_speed(MOCK_DEVICE_ID, "high")


@pytest.mark.asyncio
async def test_has_vertical_swing(controller):
    result = controller.has_vertical_swing(MOCK_DEVICE_ID)
    assert isinstance(result, bool)
    assert result is True


@pytest.mark.asyncio
async def test_get_vertical_swing(controller):
    result = controller.get_vertical_swing(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "manual2"


@pytest.mark.asyncio
async def test_get_vertical_swing_list(controller):
    result = controller.get_vertical_swing_list(MOCK_DEVICE_ID)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_set_vertical_vane(controller):
    await controller.set_vertical_vane(MOCK_DEVICE_ID, "manual4")


@pytest.mark.asyncio
async def test_has_horizontal_swing(controller):
    result = controller.has_horizontal_swing(MOCK_DEVICE_ID)
    assert isinstance(result, bool)
    assert result is True


@pytest.mark.asyncio
async def test_get_horizontal_swing(controller):
    result = controller.get_horizontal_swing(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "manual3"


@pytest.mark.asyncio
async def test_get_horizontal_swing_list(controller):
    result = controller.get_horizontal_swing_list(MOCK_DEVICE_ID)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_set_horizontal_vane(controller):
    await controller.set_horizontal_vane(MOCK_DEVICE_ID, "manual4")


@pytest.mark.asyncio
async def test_has_setpoint_control(controller):
    result = controller.has_setpoint_control(MOCK_DEVICE_ID)
    assert isinstance(result, bool)
    assert result is True


@pytest.mark.asyncio
async def test_get_setpoint(controller):
    result = controller.get_setpoint(MOCK_DEVICE_ID)
    assert isinstance(result, float)
    assert result == 21.0


@pytest.mark.asyncio
async def test_get_temperature(controller):
    result = controller.get_temperature(MOCK_DEVICE_ID)
    assert isinstance(result, float)
    assert result == 24.0


@pytest.mark.asyncio
async def test_set_temperature(controller):
    await controller.set_temperature(MOCK_DEVICE_ID, 10)


@pytest.mark.asyncio
async def test_get_run_hours(controller):
    result = controller.get_run_hours(MOCK_DEVICE_ID)
    assert isinstance(result, int)
    assert result == MOCK_VAL_RUN_HOURS


@pytest.mark.asyncio
async def test_get_error(controller):
    result = controller.get_error(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "H00: No abnormality detected"


@pytest.mark.asyncio
async def test_get_min_setpoint(controller):
    result = controller.get_min_setpoint(MOCK_DEVICE_ID)
    assert isinstance(result, float)
    assert result == 18.0


@pytest.mark.asyncio
async def test_get_max_setpoint(controller):
    result = controller.get_max_setpoint(MOCK_DEVICE_ID)
    assert isinstance(result, float)
    assert result == 30.0


@pytest.mark.asyncio
async def test_get_outdoor_temperature(controller):
    result = controller.get_outdoor_temperature(MOCK_DEVICE_ID)
    assert isinstance(result, float)
    assert result == 26.0


@pytest.mark.asyncio
async def test_get_preset_mode(controller):
    result = controller.get_preset_mode(MOCK_DEVICE_ID)
    assert isinstance(result, str)
    assert result == "eco"


@pytest.mark.asyncio
async def test_get_devices(controller):
    result = controller.get_devices()
    assert isinstance(result, dict)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_device(controller):
    result = controller.get_device(MOCK_DEVICE_ID)
    assert isinstance(result, dict)
    assert len(result) > 20
