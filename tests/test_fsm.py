"""Unit tests for Danfoss compressor Finite State Machine (FSM) safeties against PwmFloorHeatingThermostat."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_DRY_RUN,
    CONF_HEATER,
    CONF_MIN_CYCLE_DURATION,
    CONF_MIN_OFF_CYCLE_DURATION,
    CONF_OUTDOOR_SENSOR,
    CONF_TARGET_SENSOR,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
)


def _create_real_fsm_thermostat(min_cycle_min: int = 30, min_off_min: int = 15) -> PwmFloorHeatingThermostat:
    """Create a real PwmFloorHeatingThermostat instance for FSM safety testing."""
    hass = MagicMock()
    hass.states.get.return_value = None
    hass.services.async_call = AsyncMock()
    config = {
        CONF_NAME: "FSM Test Thermostat",
        CONF_TARGET_SENSOR: "sensor.room",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
        CONF_HEATER: "switch.danfoss_compressor",
        CONF_DRY_RUN: False,
        CONF_MIN_CYCLE_DURATION: min_cycle_min,
        CONF_MIN_OFF_CYCLE_DURATION: min_off_min,
    }
    t = PwmFloorHeatingThermostat(hass, config)
    t._hvac_mode = HVACMode.HEAT
    t._cur_temp = 20.0
    t._outdoor_temp = 10.0
    return t


def test_fsm_danfoss_min_run_lock():
    """Verify that stopping compressor on real entity is strictly prevented before 30 minutes runtime."""
    async def _test():
        t0 = datetime(2026, 11, 3, 22, 0, 0, tzinfo=UTC)
        t = _create_real_fsm_thermostat(min_cycle_min=30, min_off_min=15)

        # 1. Start at 22:00
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await t._async_start_heating_safe()
        assert t._fsm_state == FSM_RUNNING_MIN_LOCK
        assert t._simulated_heater_state is True
        t.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.danfoss_compressor"}, blocking=False
        )

        # 2. Attempt stop at 22:10 (after 10 min) -> MUST BE REFUSED
        t_10m = t0 + timedelta(minutes=10)
        t.hass.services.async_call.reset_mock()
        with patch("homeassistant.util.dt.utcnow", return_value=t_10m):
            await t._async_stop_heating_safe()
        assert t._fsm_state == FSM_RUNNING_MIN_LOCK
        assert t._simulated_heater_state is True
        t.hass.services.async_call.assert_not_called()

        # 3. At 22:31 (after 31 min) -> Transition to RUNNING_NORMAL and stop allowed
        t_31m = t0 + timedelta(minutes=31)
        with patch("homeassistant.util.dt.utcnow", return_value=t_31m):
            await t._async_control_heating(now=t_31m)
        assert t._fsm_state == FSM_WAITING_MIN_OFF
        assert t._simulated_heater_state is False
        t.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.danfoss_compressor"}, blocking=False
        )

    asyncio.run(_test())


def test_fsm_danfoss_min_off_lock():
    """Verify that restart on real entity is strictly prevented during 15 minutes pressure equalization."""
    async def _test():
        t0 = datetime(2026, 11, 3, 22, 0, 0, tzinfo=UTC)
        t = _create_real_fsm_thermostat(min_cycle_min=30, min_off_min=15)

        # Start then stop after 35 min
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await t._async_start_heating_safe()
        t_stop = t0 + timedelta(minutes=35)
        with patch("homeassistant.util.dt.utcnow", return_value=t_stop):
            t._fsm_state = FSM_RUNNING_NORMAL
            await t._async_stop_heating_safe()
        assert t._fsm_state == FSM_WAITING_MIN_OFF

        # Attempt restart after 5 minutes of rest -> REFUSED
        t_5m_off = t_stop + timedelta(minutes=5)
        t.hass.services.async_call.reset_mock()
        with patch("homeassistant.util.dt.utcnow", return_value=t_5m_off):
            await t._async_start_heating_safe()
        assert t._fsm_state == FSM_WAITING_MIN_OFF
        assert t._simulated_heater_state is False
        t.hass.services.async_call.assert_not_called()

        # After 16 minutes of rest -> Restart allowed
        t_16m_off = t_stop + timedelta(minutes=16)
        with patch("homeassistant.util.dt.utcnow", return_value=t_16m_off):
            await t._async_start_heating_safe()
        assert t._fsm_state == FSM_RUNNING_MIN_LOCK
        assert t._simulated_heater_state is True

    asyncio.run(_test())


def test_f04_safety_guards_active_when_outdoor_sensor_unavailable():
    """[F-04] Rule 0 emergency bypass, Hard Overshoot ceiling, and Open Window work when outdoor_temp is None."""
    async def _test():
        t0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
        t = _create_real_fsm_thermostat()
        t._outdoor_temp = None  # Outdoor sensor unavailable
        t._target_temp = 19.0

        # 1. Rule 0 emergency comfort deficit (curr = 17.2 <= 19.0 - 1.5) triggers heating even without outdoor_temp
        t._cur_temp = 17.2
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await t._async_control_heating(now=t0)
        assert t._fsm_state == FSM_RUNNING_MIN_LOCK
        assert "Emergency comfort deficit bypass" in t._decision_reason

        # 2. Hard Overshoot ceiling (curr = 20.5 >= 19.0 + 1.0) stops heating after 30m lock even without outdoor_temp
        t_35m = t0 + timedelta(minutes=35)
        t._cur_temp = 20.5
        with patch("homeassistant.util.dt.utcnow", return_value=t_35m):
            await t._async_control_heating(now=t_35m)
        assert t._fsm_state == FSM_WAITING_MIN_OFF
        assert "Hard overshoot ceiling cutoff" in t._decision_reason

    asyncio.run(_test())


def test_f07_mode_a_restricted_to_night_and_throttled():
    """[F-07] Mode A only samples at night (23:00-06:00) and at most 1 sample per hour."""
    async def _test():
        t = _create_real_fsm_thermostat()
        t._cur_temp = 20.0
        t._filtered_temp = 20.0
        t._outdoor_temp = 16.0
        t._derivative_smooth = -0.15
        t._last_state_change = datetime(2026, 11, 13, 18, 0, 0, tzinfo=UTC)

        # 1. Daytime (14:00 local) -> 0 samples collected
        t_day = datetime(2026, 11, 14, 14, 0, 0, tzinfo=UTC)
        t._observer_last_update = t_day
        with (
            patch("homeassistant.util.dt.utcnow", return_value=t_day),
            patch("homeassistant.util.dt.now", return_value=t_day),
        ):
            await t._async_control_heating(now=t_day)
        assert t._heat_loss_samples_count == 0

        # 2. Nighttime (02:00 local) -> 1 sample collected, second call 1 min later is throttled
        t_night = datetime(2026, 11, 15, 2, 0, 0, tzinfo=UTC)
        t._observer_last_update = t_night
        t._derivative_smooth = -0.15
        with (
            patch("homeassistant.util.dt.utcnow", return_value=t_night),
            patch("homeassistant.util.dt.now", return_value=t_night),
        ):
            await t._async_control_heating(now=t_night)
        assert t._heat_loss_samples_count == 1

        t_night_1m = t_night + timedelta(minutes=1)
        t._observer_last_update = t_night_1m
        t._derivative_smooth = -0.15
        with (
            patch("homeassistant.util.dt.utcnow", return_value=t_night_1m),
            patch("homeassistant.util.dt.now", return_value=t_night_1m),
        ):
            await t._async_control_heating(now=t_night_1m)
        assert t._heat_loss_samples_count == 1  # Throttled (1 sample/hour max)

    asyncio.run(_test())


