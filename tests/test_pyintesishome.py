"""Tests for pyintesishome."""

import asyncio

import aiohttp
import pytest
import pytest_asyncio

from pyintesishome import (
    IHAuthenticationError,
    IHConnectionError,
    IntesisBox,
    IntesisHome,
    IntesisHomeLocal,
)
from pyintesishome.const import API_URL, DEVICE_INTESISHOME

from . import (
    LOCAL_DEVICE_STATE,
    MOCK_DEVICE_ID,
    MOCK_HOST,
    MOCK_PASS,
    MOCK_UNREACHABLE_HOST,
    MOCK_USER,
    MOCK_VAL_RUN_HOURS,
    cloud_api_callback,
    intesisbox_api_callback,
    local_api_callback,
    mock_aioresponse,  # noqa: F401
    reset_local_device_state,
)


async def wait_until(predicate, timeout=5.0):
    """Poll until predicate() is true, or fail the test."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Condition not met within {timeout}s")


@pytest.fixture(autouse=True)
def setup_mocks(mock_aioresponse):  # noqa: F811
    """Register mock HTTP endpoints for all tests."""
    reset_local_device_state()
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


@pytest.mark.asyncio
async def test_local_poll_status_unreachable_raises(mock_aioresponse):  # noqa: F811
    """Regression test for #79 - an unreachable device must surface as an
    IHConnectionError, not as a silent success leaving a phantom device keyed
    by an empty string and an unset controller_id."""
    mock_aioresponse.post(
        f"http://{MOCK_UNREACHABLE_HOST}/api.cgi",
        exception=aiohttp.ServerTimeoutError("Connection timeout to host"),
        repeat=True,
    )

    async with aiohttp.ClientSession() as session:
        controller = IntesisHomeLocal(
            MOCK_UNREACHABLE_HOST,
            MOCK_USER,
            MOCK_PASS,
            websession=session,
        )

        with pytest.raises(IHConnectionError):
            await controller.poll_status()

        assert controller.get_devices() == {}

        with pytest.raises(IHConnectionError):
            await controller.connect()


@pytest.mark.asyncio
async def test_local_poll_status_bad_credentials_raises():
    """Rejected credentials must raise IHAuthenticationError rather than being
    logged and reported as a connection problem."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHomeLocal(
            MOCK_HOST,
            MOCK_USER,
            "not-the-password",
            websession=session,
        )

        with pytest.raises(IHAuthenticationError):
            await controller.poll_status()

        assert controller.get_devices() == {}


@pytest.mark.asyncio
async def test_local_controller_id(local_controller):
    """A successful poll must set the controller id."""
    assert local_controller.controller_id == MOCK_DEVICE_ID.lower()


@pytest_asyncio.fixture
async def fast_local_controller():
    """A connected local controller with the updater timings compressed.

    The intervals are set before connect() so the updater task never sleeps
    for the production interval.
    """
    async with aiohttp.ClientSession() as session:
        controller = IntesisHomeLocal(
            MOCK_HOST,
            MOCK_USER,
            MOCK_PASS,
            websession=session,
        )
        controller._scan_interval = 0.01
        controller._max_scan_interval = 0.01
        controller._unavailable_after = 0.05
        await controller.connect()
        yield controller
        await controller.stop()


@pytest.mark.asyncio
async def test_local_reports_disconnected_then_recovers(fast_local_controller):
    """Regression test for #80 - a device that stops answering after setup
    must be reported as disconnected once the grace period lapses, and must
    recover by itself when it starts answering again."""
    controller = fast_local_controller
    assert controller.is_connected is True

    LOCAL_DEVICE_STATE["failing"] = True
    await wait_until(lambda: controller.is_connected is False)
    assert controller.error_message is not None
    # The updater must survive the outage, otherwise recovery is impossible.
    assert not controller._update_task.done()

    LOCAL_DEVICE_STATE["failing"] = False
    await wait_until(lambda: controller.is_connected is True)
    assert controller.error_message is None


@pytest.mark.asyncio
async def test_local_updates_last_successful_update(fast_local_controller):
    """last_successful_update advances while healthy and freezes once the
    device stops answering."""
    controller = fast_local_controller
    first = controller.last_successful_update
    assert first is not None

    await wait_until(lambda: controller.last_successful_update > first)

    LOCAL_DEVICE_STATE["failing"] = True
    await wait_until(lambda: controller.is_connected is False)
    frozen = controller.last_successful_update
    await asyncio.sleep(0.05)
    assert controller.last_successful_update == frozen


@pytest.mark.asyncio
async def test_local_stops_updater_when_credentials_rejected(fast_local_controller):
    """Rejected credentials are not transient, so the updater gives up
    rather than retrying forever."""
    controller = fast_local_controller

    LOCAL_DEVICE_STATE["reject_auth"] = True
    await wait_until(lambda: controller.is_connected is False)
    await wait_until(lambda: controller._update_task.done())
    assert controller.error_message is not None


@pytest.mark.asyncio
async def test_local_backs_off_while_failing(fast_local_controller):
    """The poll interval grows while the device is failing, so a struggling
    unit is not hammered at the full rate."""
    controller = fast_local_controller
    controller._max_scan_interval = 30
    assert controller._current_scan_interval() == controller._scan_interval

    controller._consecutive_failures = 1
    assert controller._current_scan_interval() == controller._scan_interval
    controller._consecutive_failures = 3
    assert controller._current_scan_interval() == controller._scan_interval * 4
    controller._consecutive_failures = 500
    assert controller._current_scan_interval() == 30


@pytest.mark.asyncio
async def test_intesisbox_state_change_fires_update_callback():
    """A CHN,1 push from the box must notify subscribers, not just update
    internal state silently - otherwise consumers relying purely on the
    callback (should_poll=False) never see the change."""
    box = IntesisBox(MOCK_HOST)
    box._device_id = MOCK_DEVICE_ID
    box._devices[MOCK_DEVICE_ID] = {}

    received = []

    async def callback(device_id=None):
        received.append(device_id)

    box.add_update_callback(callback)

    await box._parse_response("CHN,1:AMBTEMP,215\r")

    assert received == [MOCK_DEVICE_ID]
    await box.stop()
