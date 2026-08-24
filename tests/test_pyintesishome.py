"""Tests for pyintesishome."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock, patch

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
from pyintesishome.const import (
    API_URL,
    DEVICE_INTESISHOME,
    POLL_INTERVAL_MIN,
    PORTAL_URL,
)

from . import (
    LOCAL_DEVICE_STATE,
    MOCK_DEVICE_ID,
    MOCK_DEVICE_ID_2,
    MOCK_HOST,
    MOCK_PASS,
    MOCK_UNREACHABLE_HOST,
    MOCK_USER,
    MOCK_VAL_RUN_HOURS,
    FakeWMPServer,
    cloud_api_callback,
    local_api_callback,
    mock_aioresponse,  # noqa: F401
    reset_local_device_state,
)


class _FakeResponse:
    """Stand-in for an aiohttp response, for payloads aioresponses can't
    easily express because the autouse mock already claims the URL."""

    def __init__(self, payload):
        self._payload = payload
        # Real aiohttp responses always carry this (empty when the response
        # sets no Set-Cookie header); pyintesishome reads it on every poll.
        self.cookies = SimpleCookie()

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _json_response(payload):
    return _FakeResponse(payload)


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
        # connect() starts the state poller; stop() is what reaps it.
        await controller.stop()


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
    # The local mock is a single unit; the cloud mock is a two-device
    # installation, so multi-device handling stays covered.
    assert MOCK_DEVICE_ID in result


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


# --- Optional socket / HTTP fallback polling -------------------------------
#
# The cloud mock's serverPort 19999 is never listening, so every
# cloud_controller has already been through the "socket failed" path by the
# time a test sees it. That is exactly the state these tests care about.


@pytest.mark.asyncio
async def test_cloud_is_available_without_socket(cloud_controller):
    """The whole point of the change: a failed socket must not make the
    controller look dead when HTTP polling is working fine."""
    assert cloud_controller.is_connected is False
    assert cloud_controller.is_available is True
    assert cloud_controller.get_device(MOCK_DEVICE_ID) is not None


@pytest.mark.asyncio
async def test_cloud_is_available_goes_false_when_state_is_stale(cloud_controller):
    """Availability is time-boxed: state that stopped refreshing is not
    trustworthy just because it was once fetched successfully."""
    cloud_controller._last_successful_update = datetime.now(timezone.utc) - timedelta(
        seconds=cloud_controller._stale_after + 1
    )
    assert cloud_controller.is_available is False


@pytest.mark.asyncio
async def test_cloud_is_available_false_before_first_update():
    """No successful update yet means unavailable, not available-by-default."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(MOCK_USER, MOCK_PASS, websession=session)
        assert controller.is_available is False
        await controller.stop()


@pytest.mark.asyncio
async def test_connect_starts_polling(cloud_controller):
    """State comes from the poller, so connect() must start it."""
    assert cloud_controller._poll_task is not None
    assert not cloud_controller._poll_task.done()


@pytest.mark.asyncio
async def test_connect_does_not_open_a_socket():
    """Start-up must not depend on a high port being reachable. The socket
    is opened lazily by the first command, not by connect()."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(MOCK_USER, MOCK_PASS, websession=session)
        with patch("asyncio.open_connection") as open_connection:
            await controller.connect()

        open_connection.assert_not_called()
        assert controller.is_connected is False
        assert controller.is_available is True
        assert controller.get_device(MOCK_DEVICE_ID) is not None
        await controller.stop()


@pytest.mark.asyncio
async def test_polls_are_skipped_while_the_socket_is_up(cloud_controller):
    """A live socket already carries state, so polling stands down. The
    task stays alive, ready to resume the moment the socket goes."""
    polls = []

    async def counting_poll(sendcallback=False):
        polls.append(1)

    with patch.object(cloud_controller, "poll_status", counting_poll):
        await cloud_controller._parse_response(
            '{"command":"connect_rsp","data":{"status":"ok"}}'
        )
        assert cloud_controller.is_connected is True

        # Restart the poller so it picks up the short interval - the
        # running one is already inside a wait on the old one, and
        # changing the attribute alone would make this test vacuous.
        await cloud_controller._cancel_task_if_exists(cloud_controller._poll_task)
        cloud_controller._poll_task = None
        cloud_controller._poll_interval = 0.05
        cloud_controller._start_poller()

        await asyncio.sleep(0.3)
        assert polls == [], "must not poll while push is carrying state"
        assert not cloud_controller._poll_task.done()

        # ...and it resumes the moment the socket is gone.
        cloud_controller._connected = False
        await wait_until(lambda: len(polls) >= 1, timeout=2.0)


@pytest.mark.asyncio
async def test_disconnect_triggers_an_immediate_poll(cloud_controller):
    """Polling is suppressed while the socket is up, so a drop must pull
    the next poll forward. Waiting out the interval would flap
    is_available false in the gap."""
    cloud_controller._poll_interval = 30  # long enough that a scheduled poll won't fire
    polls = []

    async def counting_poll(sendcallback=False):
        polls.append(1)

    with patch.object(cloud_controller, "poll_status", counting_poll):
        await cloud_controller._parse_response(
            '{"command":"connect_rsp","data":{"status":"ok"}}'
        )
        await asyncio.sleep(0.05)
        assert polls == []

        cloud_controller._connected = False
        await cloud_controller._handle_disconnect()
        await wait_until(lambda: len(polls) == 1, timeout=2.0)


@pytest.mark.asyncio
async def test_disconnect_does_not_reconnect(cloud_controller):
    """A dropped socket is not an error to recover from - it is reopened
    by the next command, and polling carries state meanwhile."""
    cloud_controller._connected = False
    await cloud_controller._handle_disconnect()

    # Nothing schedules a reconnect any more.
    assert not hasattr(cloud_controller, "_reconnect_task")
    assert not cloud_controller._poll_task.done()
    assert cloud_controller.is_available is True


@pytest.mark.asyncio
async def test_stop_completes_when_a_disconnect_races_it(cloud_controller):
    """stop() must not wait on a poller that outlived its cancellation.

    _handle_disconnect() wakes the poller, and stop() cancels it in the same
    loop iteration. Pinning the invariant _cancel_task_if_exists rests on:
    one cancel() has to reap the task. Python < 3.12 broke it outright -
    wait_for discarded a cancel delivered while the future it was waiting on
    had already completed - and while 3.12 propagates it correctly, nothing
    about the loop guarantees that on its own.
    """
    # Exactly what stop() does, in one loop iteration and with no await
    # between: a disconnect has already woken the poller, and the cancel
    # lands before it has run.
    cloud_controller._stopping = True
    cloud_controller._poll_wakeup.set()
    cloud_controller._poll_task.cancel()

    for _ in range(10):
        if cloud_controller._poll_task.done():
            break
        await asyncio.sleep(0)

    assert cloud_controller._poll_task.done(), (
        "the poller survived the single cancel() that stop() relies on"
    )


@pytest.mark.asyncio
async def test_opening_a_socket_starts_a_keepalive(cloud_controller):
    """A live socket is kept healthy: the keepalive is what turns a
    half-dead connection into a noticed disconnect."""
    reader, writer = asyncio.StreamReader(), MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()

    async def fake_send_command(_command, wait_for_response=True):
        # Stand in for the server's connect_rsp.
        cloud_controller._connected = True

    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        with patch.object(cloud_controller, "_send_command", fake_send_command):
            assert await cloud_controller._ensure_socket() is True

    assert cloud_controller._keepalive_task is not None
    assert not cloud_controller._keepalive_task.done()
    await cloud_controller._cancel_task_if_exists(cloud_controller._keepalive_task)
    cloud_controller._keepalive_task = None


@pytest.mark.asyncio
async def test_dead_socket_is_not_reopened_until_a_command(cloud_controller):
    """The socket must not resurrect itself. Polling covers the gap."""
    cloud_controller._connected = False
    with patch("asyncio.open_connection") as open_connection:
        await cloud_controller._handle_disconnect()
        await asyncio.sleep(0.05)
        open_connection.assert_not_called()

    assert cloud_controller.is_available is True
    assert not cloud_controller._poll_task.done()


@pytest.mark.asyncio
async def test_set_opens_the_socket_on_demand(cloud_controller):
    """Commands are what open the socket, and a live one is reused."""
    calls = []

    async def fake_ensure():
        calls.append(1)
        cloud_controller._connected = True
        return True

    with patch.object(cloud_controller, "_ensure_socket", fake_ensure):
        with patch.object(cloud_controller, "_send_command", return_value=None):
            cloud_controller._set_ack_timeout = 0.05
            await cloud_controller.set_power_on(MOCK_DEVICE_ID)
            await cloud_controller.set_power_off(MOCK_DEVICE_ID)

    # Once per command; _ensure_socket itself short-circuits when up.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_use_socket_false_never_opens_a_socket():
    """With the socket disabled the controller must still come up fully
    populated, on HTTP alone."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER, MOCK_PASS, websession=session, use_socket=False
        )
        with patch("asyncio.open_connection") as open_connection:
            await controller.connect()

        open_connection.assert_not_called()
        assert controller.is_connected is False
        assert controller.is_available is True
        assert controller.get_device(MOCK_DEVICE_ID) is not None
        assert controller._poll_task is not None
        await controller.stop()


@pytest.mark.asyncio
async def test_poll_interval_is_clamped_to_floor():
    """Consumers must not be able to hammer a third-party cloud API."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER, MOCK_PASS, websession=session, poll_interval=5
        )
        assert controller._poll_interval == POLL_INTERVAL_MIN
        await controller.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", [0, None])
async def test_poll_interval_none_disables_the_poller(disabled):
    """Opting out of polling entirely must leave no poll task behind."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER, MOCK_PASS, websession=session, poll_interval=disabled
        )
        assert controller._poll_interval is None
        await controller.connect()
        assert controller._poll_task is None
        await controller.stop()


@pytest.mark.asyncio
async def test_poll_status_fires_a_callback_per_device(cloud_controller):
    """A status list spanning several devices must notify for each. Firing
    only for the last one leaves every other device showing stale state."""
    received = []

    async def callback(device_id=None):
        received.append(device_id)

    cloud_controller.add_update_callback(callback)
    await cloud_controller.poll_status(sendcallback=True)

    assert sorted(received) == sorted([MOCK_DEVICE_ID, MOCK_DEVICE_ID_2])


@pytest.mark.asyncio
async def test_poll_status_survives_response_without_config(cloud_controller):
    """The poller calls this on a loop, so a response missing the config
    block must not take the whole poll down."""
    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response({"status": {"status": []}}),
    ):
        await cloud_controller.poll_status()

    assert cloud_controller.is_available is True


@pytest.mark.asyncio
async def test_stop_leaves_no_poll_task(cloud_controller):
    """stop() must reap the poller before the web session closes."""
    poll_task = cloud_controller._poll_task
    await cloud_controller.stop()

    assert poll_task.done()
    assert cloud_controller._poll_task is None


@pytest.mark.asyncio
async def test_set_returns_false_when_socket_is_unavailable(cloud_controller):
    """SETs need the socket - the cloud HTTP API is read-only. Without one,
    say so honestly rather than hanging until the ack timeout."""
    assert cloud_controller.is_connected is False

    result = await cloud_controller.set_power_on(MOCK_DEVICE_ID)

    assert result is False


@pytest.mark.asyncio
async def test_set_with_use_socket_false_does_not_attempt_connect():
    """A read-only controller must fail the SET outright, not try to open
    the socket the caller explicitly disabled."""
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER, MOCK_PASS, websession=session, use_socket=False
        )
        await controller.connect()

        with patch("asyncio.open_connection") as open_connection:
            result = await controller.set_power_on(MOCK_DEVICE_ID)

        assert result is False
        open_connection.assert_not_called()
        await controller.stop()


@pytest.mark.asyncio
async def test_offline_device_does_not_count_as_a_successful_update(cloud_controller):
    """An account whose devices are all offline still answers 200 with a
    full config block and an empty status list (confirmed against a real
    capture). That must not keep is_available pinned True forever."""
    # Shape taken from a Proxyman capture of AC Cloud 3.3.3 against an
    # account whose only device was offline.
    offline_payload = {
        "config": {
            "token": 1228523849,
            "serverIP": "212.92.41.143",
            "serverPort": 5210,
            "inst": [
                {
                    "id": 1,
                    "name": "First installation",
                    "devices": [
                        {
                            "id": MOCK_DEVICE_ID,
                            "name": "Manuka",
                            "modelId": 137,
                            "widgets": [15, 3, 5, 7, 9, 11, 42, 44, 13, 47, 49, 52],
                        }
                    ],
                }
            ],
        },
        "status": {"hash": "97d170e1550eee4afc0af065b78cda302a97674c", "status": []},
    }

    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(offline_payload),
    ):
        await cloud_controller.poll_status()

    # The device is still registered from config...
    assert cloud_controller.get_device(MOCK_DEVICE_ID) is not None
    # ...but the poll taught us nothing about it, so it must not refresh
    # the availability clock.
    cloud_controller._last_successful_update = datetime.now(timezone.utc) - timedelta(
        seconds=cloud_controller._stale_after + 1
    )
    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(offline_payload),
    ):
        await cloud_controller.poll_status()

    assert cloud_controller.is_available is False


# ---------------------------------------------------------------------------
# IntesisBox (WMP local protocol) against a fake TCP device
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wmp_server():
    """Start a fake WMP device on a random local port."""
    server = FakeWMPServer()
    await server.start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def intesisbox_controller(wmp_server):
    """Create and connect an IntesisBox controller to the fake device."""
    controller = IntesisBox("127.0.0.1", loop=asyncio.get_running_loop())
    controller._port = wmp_server.port
    # Keep the reconnect tests fast; production defaults are 15/300s.
    controller._reconnect_delay_initial = 0.1
    controller._reconnect_delay_max = 0.1
    await controller.connect()
    yield controller
    await controller.stop()


@pytest.mark.asyncio
async def test_intesisbox_connect(intesisbox_controller, wmp_server):
    """Connect initialises despite an unanswered LIMITS:VANELR query."""
    controller = intesisbox_controller
    assert controller.is_connected

    device = controller._devices[FakeWMPServer.MAC]
    assert device["temperature"] == "250"
    assert device["mode_list"] == ["auto", "heat", "dry", "fan", "cool"]
    assert "hvane_list" not in device  # LIMITS:VANELR was never answered

    # Every command must be CR-terminated or the device never parses it;
    # the fake server only records complete CR-terminated lines.
    assert "ID" in wmp_server.received
    assert "LIMITS:VANELR" in wmp_server.received
    assert "GET,1:AMBTEMP" in wmp_server.received


@pytest.mark.asyncio
async def test_intesisbox_starts_keepalive(intesisbox_controller):
    """connect() starts the keepalive task that guards the idle socket."""
    task = intesisbox_controller._keepalive_task
    assert task is not None
    assert not task.done()


@pytest.mark.asyncio
async def test_intesisbox_set_commands_return_ack(intesisbox_controller, wmp_server):
    """set_* methods report the device's acknowledgement as a boolean."""
    controller = intesisbox_controller

    assert await controller.set_power_on() is True
    assert wmp_server.state["ONOFF"] == "ON"

    assert await controller.set_mode(FakeWMPServer.MAC, "heat") is True
    assert wmp_server.state["MODE"] == "HEAT"

    assert await controller.set_fan_speed(FakeWMPServer.MAC, "3") is True
    assert wmp_server.state["FANSP"] == "3"

    # A mode the map doesn't know is rejected without touching the device.
    assert await controller.set_mode(FakeWMPServer.MAC, "bogus") is False
    assert wmp_server.state["MODE"] == "HEAT"


@pytest.mark.asyncio
async def test_intesisbox_unanswered_set_returns_false(
    intesisbox_controller, wmp_server
):
    """A device that stops answering makes set_* report failure."""
    controller = intesisbox_controller
    wmp_server.silent = True

    assert await controller.set_power_on() is False

    # Stop before the fixture teardown so the reconnect loop (kicked off by
    # the timeout closing the socket) doesn't spin against a silent server.
    await controller.stop()


@pytest.mark.asyncio
async def test_intesisbox_reconnects_after_connection_loss(
    intesisbox_controller, wmp_server
):
    """A dropped socket is re-established and the controller re-initialises."""
    controller = intesisbox_controller

    await wmp_server.drop_clients()
    await wait_until(lambda: not controller.is_connected)

    await wait_until(lambda: controller.is_connected)
    assert await controller.set_power_on() is True


@pytest.mark.asyncio
async def test_intesisbox_stop_suppresses_reconnect(intesisbox_controller, wmp_server):
    """An intentional stop() must not resurrect the connection."""
    controller = intesisbox_controller

    await controller.stop()
    await wait_until(lambda: not controller.is_connected)
    # Give a (fast) reconnect loop every chance to fire if one were started.
    await asyncio.sleep(0.5)

    assert not controller.is_connected
    assert controller._reconnect_task is None or controller._reconnect_task.done()


@pytest.mark.asyncio
async def test_set_value_falls_back_to_portal_when_socket_is_down(
    cloud_controller,
    mock_aioresponse,  # noqa: F811
):
    """With the command socket unreachable, SETs go through the web portal.

    The mocked cloud config points the socket at 127.0.0.1:19999 where
    nothing listens, so _ensure_socket fails naturally and _set_value
    takes the portal path: form login (CSRF token from the login page,
    userId from the post-login panel), then POST /device/setVal.
    """
    portal = PORTAL_URL[DEVICE_INTESISHOME]
    mock_aioresponse.get(
        f"{portal}/login",
        body='<input type="hidden" name="signin[_csrf_token]" '
        'value="tok123" id="signin__csrf_token" />',
        repeat=True,
    )
    mock_aioresponse.post(f"{portal}/login", body="", repeat=True)
    mock_aioresponse.get(
        f"{portal}/panel/headers",
        body="url: '/device/setVal?id=' + deviceId + '&uid=' + uid"
        " + '&value=' + value + '&userId=4242',",
        repeat=True,
    )
    mock_aioresponse.post(
        re.compile(re.escape(f"{portal}/device/setVal") + r"\?.*userId=4242.*"),
        body="OK",
        repeat=True,
    )

    assert await cloud_controller._set_value(MOCK_DEVICE_ID, 9, 220) is True


@pytest.mark.asyncio
async def test_portal_fallback_failure_reports_set_as_failed(
    cloud_controller,
    mock_aioresponse,  # noqa: F811
):
    """A portal that rejects the login must fail the SET, not raise."""
    portal = PORTAL_URL[DEVICE_INTESISHOME]
    mock_aioresponse.get(f"{portal}/login", body="maintenance page", repeat=True)

    assert await cloud_controller._set_value(MOCK_DEVICE_ID, 9, 220) is False


def _mock_working_portal(mock_aioresponse):  # noqa: F811
    """Register a portal that would happily accept any SET."""
    portal = PORTAL_URL[DEVICE_INTESISHOME]
    mock_aioresponse.get(
        f"{portal}/login",
        body='<input type="hidden" name="signin[_csrf_token]" value="tok123" />',
        repeat=True,
    )
    mock_aioresponse.post(f"{portal}/login", body="", repeat=True)
    mock_aioresponse.get(f"{portal}/panel/headers", body="userId=4242,", repeat=True)
    mock_aioresponse.post(
        re.compile(re.escape(f"{portal}/device/setVal") + r"\?.*"),
        body="OK",
        repeat=True,
    )


@pytest.mark.asyncio
async def test_use_socket_false_does_not_use_the_portal_fallback(
    mock_aioresponse,  # noqa: F811
):
    """use_socket=False means read-only, and the portal must not undo that.

    The portal here would accept the SET, so a controller that reaches it
    returns True. A read-only controller has to return False without ever
    logging in.
    """
    _mock_working_portal(mock_aioresponse)
    async with aiohttp.ClientSession() as session:
        controller = IntesisHome(
            MOCK_USER, MOCK_PASS, websession=session, use_socket=False
        )
        await controller.connect()

        assert await controller._set_value(MOCK_DEVICE_ID, 9, 220) is False
        assert controller._portal_session is None
        assert controller._portal_user_id is None

        await controller.stop()


@pytest.mark.asyncio
async def test_stop_clears_the_cached_portal_login(
    cloud_controller,
    mock_aioresponse,  # noqa: F811
):
    """stop() closes the portal session, so the cached userId must go too.

    Keeping it would send the next SET straight to _portal_post_set with
    no session behind it, raising out of a path documented never to raise.
    """
    _mock_working_portal(mock_aioresponse)

    assert await cloud_controller._set_value(MOCK_DEVICE_ID, 9, 220) is True
    assert cloud_controller._portal_user_id == "4242"

    await cloud_controller.stop()
    assert cloud_controller._portal_session is None
    assert cloud_controller._portal_user_id is None

    # The next SET must log in again rather than post through the session
    # stop() disposed of, which used to raise AttributeError.
    assert await cloud_controller._set_value(MOCK_DEVICE_ID, 9, 220) is True
    assert cloud_controller._portal_session is not None


@pytest.mark.asyncio
async def test_transient_api_error_does_not_retire_the_poller(cloud_controller):
    """The cloud reports every failure as a 200 with an errorCode, so a
    backend hiccup used to be indistinguishable from bad credentials - and
    the poller retired on both, leaving the controller dead until the
    consumer restarted."""
    error_payload = {"errorCode": 20, "errorMessage": "INTERNAL_SERVER_ERROR"}

    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(error_payload),
    ):
        with pytest.raises(IHConnectionError):
            await cloud_controller.poll_status()

    assert cloud_controller.authentication_failed is False
    # A transient error is one the poller rides out, so it must still be
    # running and must not have declared an unrecoverable failure.
    assert not cloud_controller._poll_task.done()
    assert cloud_controller.error_message == "INTERNAL_SERVER_ERROR"


@pytest.mark.asyncio
async def test_rejected_credentials_are_reported_as_authentication_failure(
    cloud_controller,
):
    """Bad credentials are the one failure a retry cannot survive, so they
    have to reach the consumer as something it can act on rather than as
    another unavailable controller."""
    # Shape taken from a real /api.php/get/control response to a bad
    # password.
    error_payload = {"errorCode": 3, "errorMessage": "WRONG_USERNAME_PASSWORD"}

    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(error_payload),
    ):
        with pytest.raises(IHAuthenticationError):
            await cloud_controller.poll_status()

    assert cloud_controller.authentication_failed is True
    # Cached state is still fresh, but nothing will refresh it again until
    # the credentials are fixed, so the controller must not claim to be
    # available on the strength of it.
    assert cloud_controller.is_available is False


@pytest.mark.asyncio
async def test_a_working_poll_clears_an_earlier_authentication_failure(
    cloud_controller,
):
    """Reauthentication normally rebuilds the controller, but credentials
    can also start working again on their own (an account restored at the
    far end). A stale flag would pin the controller unavailable forever."""
    cloud_controller._authentication_failed = True
    assert cloud_controller.is_available is False

    await cloud_controller.poll_status()

    assert cloud_controller.authentication_failed is False
    assert cloud_controller.is_available is True


@pytest.mark.asyncio
async def test_credential_rejection_retires_the_poller(cloud_controller):
    """Retiring is still right for real credential failures - it stops the
    controller hammering the API with a password it knows is wrong."""
    error_payload = {"errorCode": 3, "errorMessage": "WRONG_USERNAME_PASSWORD"}

    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(error_payload),
    ):
        cloud_controller._poll_interval = 0.05
        await cloud_controller._cancel_task_if_exists(cloud_controller._poll_task)
        cloud_controller._poll_task = None
        cloud_controller._start_poller()

        await wait_until(lambda: cloud_controller._poll_task.done(), timeout=2.0)

    assert cloud_controller.authentication_failed is True
    assert cloud_controller.is_available is False


@pytest.mark.asyncio
async def test_error_classification_reads_the_code_not_the_message(cloud_controller):
    """errorMessage is a human-facing label and not something to branch
    on. An unrecognised code stays transient however much its text sounds
    like an auth failure, because retiring the poller in error is the
    expensive mistake and only the code can be checked reliably."""
    # Synthetic: no such response has been observed. It exists to pin the
    # classification to the code, so a future change cannot quietly go
    # back to matching text.
    error_payload = {
        "errorCode": 99,
        "errorMessage": "PASSWORD_SERVICE_TEMPORARILY_UNAVAILABLE",
    }

    with patch.object(
        cloud_controller._web_session,
        "post",
        return_value=_json_response(error_payload),
    ):
        with pytest.raises(IHConnectionError):
            await cloud_controller.poll_status()

    assert cloud_controller.authentication_failed is False
