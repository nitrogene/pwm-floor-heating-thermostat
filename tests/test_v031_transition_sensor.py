"""Unit tests for v0.3.1 next transition companion sensor and FSM lookahead."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    ATTR_EARLIEST_TRANSITION_TIME,
    ATTR_NEXT_TRANSITION_REASON,
    ATTR_NEXT_TRANSITION_TYPE,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_MAX_CONTINUOUS_RUN_MINUTES,
    CONF_OUTDOOR_SENSOR,
    CONF_PEAK_MAX_RUN_DURATION,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_STAGGER_DELAY,
    CONF_TARGET_SENSOR,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
)
from custom_components.pwm_floor_heating_thermostat.sensor import (
    SENSOR_TYPES,
    PwmDiagnosticSensor,
)


@pytest.fixture
def base_config():
    """Create minimal thermostat configuration for transition testing."""
    return {
        CONF_NAME: "Transition Test Thermostat",
        CONF_TARGET_SENSOR: "sensor.room_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.heater",
        CONF_HEAT_LOSS: 15.0,
        CONF_POWER_WATTS: 3000.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_DRY_RUN: True,
        CONF_PEAK_MAX_RUN_DURATION: timedelta(minutes=45),
        CONF_MAX_CONTINUOUS_RUN_MINUTES: 120,
    }


def test_next_transition_when_running_in_peak_hours(base_config):
    """Verify turn_off prediction during peak-hour top-up with Danfoss minimum runtime lock."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 14, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_RUNNING_MIN_LOCK
        thermostat._cycle_start_time = t0
        thermostat._last_state_change = t0

        # Peak hours (no off-peak)
        thermostat._off_peak_sensor = "binary_sensor.off_peak"
        mock_st = MagicMock()
        mock_st.state = "off"
        hass.states.get.return_value = mock_st

        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_type == "turn_off"
        # Earliest must respect 30 min Danfoss minimum runtime
        assert thermostat._earliest_transition_time == t0 + timedelta(minutes=30)
        # Expected stop is Rule G peak-hour cap (45 min)
        assert thermostat._next_transition_time == t0 + timedelta(minutes=45)
        assert "Peak-hour top-up run cap reached" in thermostat._next_transition_reason

    asyncio.run(_test())


def test_next_transition_when_running_in_off_peak_hours(base_config):
    """Verify turn_off prediction during off-peak precharge based on remaining quota and max run cap."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 23, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_RUNNING_NORMAL
        thermostat._cycle_start_time = t0
        thermostat._last_state_change = t0

        # Off-peak hours active
        thermostat._off_peak_sensor = "binary_sensor.off_peak"
        mock_st = MagicMock()
        mock_st.state = "on"
        hass.states.get.return_value = mock_st

        # 1. Quota of 90 minutes remaining (< 120 min max continuous run)
        thermostat._hours_needed_24h = 2.0
        thermostat._hours_run_today = 0.5  # 1.5h remaining (90 min)
        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_type == "turn_off"
        assert thermostat._next_transition_time == t0 + timedelta(minutes=90)
        assert "Daily thermal quota completion" in thermostat._next_transition_reason

        # 2. Quota of 3 hours remaining -> capped by 120 min max continuous run
        thermostat._hours_needed_24h = 4.0
        thermostat._hours_run_today = 1.0  # 3.0h remaining
        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_time == t0 + timedelta(minutes=120)
        assert "Max continuous run cap" in thermostat._next_transition_reason

    asyncio.run(_test())


def test_next_transition_when_idle_waiting_min_off(base_config):
    """Verify turn_on prediction respects 15 min Danfoss pressure equalization rest."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 15, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_WAITING_MIN_OFF
        # Stopped 5 minutes ago
        thermostat._last_state_change = t0 - timedelta(minutes=5)

        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_type == "turn_on"
        # Must wait remaining 10 min to satisfy 15 min minimum off lock
        assert thermostat._earliest_transition_time == (t0 - timedelta(minutes=5)) + timedelta(minutes=15)
        assert thermostat._earliest_transition_time == t0 + timedelta(minutes=10)

    asyncio.run(_test())


def test_next_transition_scheduled_off_peak_with_stagger(base_config):
    """Verify turn_on estimation schedules off-peak precharge with zone stagger delay."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 20, 0, 0, tzinfo=UTC)

        base_config[CONF_STAGGER_DELAY] = 300  # 5 min stagger
        base_config["off_peak_start_entity"] = "input_datetime.off_peak_start"
        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_IDLE
        thermostat._cur_temp = 19.5
        thermostat._target_temp = 19.0

        # Configured off-peak start helper entity at 22:06:00
        mock_helper = MagicMock()
        mock_helper.state = "22:06:00"

        def mock_get(entity_id):
            if entity_id == "input_datetime.off_peak_start":
                return mock_helper
            return None

        hass.states.get.side_effect = mock_get

        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_type == "turn_on"
        assert thermostat._next_transition_time is not None
        # Must land on local 22:06 + 5 min stagger = 22:11
        local_target = thermostat._next_transition_time.astimezone()
        assert local_target.hour == 22
        assert local_target.minute == 11
        assert "Off-peak precharge scheduled (+5m stagger)" in thermostat._next_transition_reason

    asyncio.run(_test())


def test_next_transition_anticipated_thermal_drop(base_config):
    """Verify turn_on estimation projects cooling trajectory intersection with Rule B threshold."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 10, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_IDLE
        thermostat._target_temp = 19.0
        thermostat._current_rule_b_threshold = 0.25
        thermostat._cur_temp = 19.2
        # Room cooling at -0.10 °C/h
        thermostat._derivative_smooth = -0.10
        # Projected at t + theta = 19.0°C (0.25°C above trigger threshold 18.75°C)
        thermostat._temp_projected = 19.0

        # delta_drop = 19.0 - (19.0 - 0.25) = 0.25°C. Time to drop = 0.25 / 0.10 = 2.5 hours.
        thermostat._update_next_transition_estimate(t0)

        assert thermostat._next_transition_type == "turn_on"
        assert thermostat._next_transition_time == t0 + timedelta(hours=2.5)
        assert "Anticipated thermal drop below target in 2.5h" in thermostat._next_transition_reason

    asyncio.run(_test())


def test_next_transition_sensor_companion_entity(base_config):
    """Verify PwmDiagnosticSensor correctly exposes next_transition_time and extra attributes."""
    coordinator = MagicMock()
    thermostat = MagicMock()
    coordinator.thermostat = thermostat

    t_next = datetime(2026, 11, 13, 22, 11, 0, tzinfo=UTC)
    t_earliest = datetime(2026, 11, 13, 20, 15, 0, tzinfo=UTC)
    thermostat._next_transition_time = t_next
    thermostat._next_transition_type = "turn_on"
    thermostat._next_transition_reason = "Off-peak precharge scheduled (+5m stagger)"
    thermostat._earliest_transition_time = t_earliest

    desc = next(d for d in SENSOR_TYPES if d.key == "next_transition_time")
    entry = MagicMock()
    entry.entry_id = "test_entry"

    sensor = PwmDiagnosticSensor(coordinator, desc, entry)

    assert sensor.native_value == t_next
    attrs = sensor.extra_state_attributes
    assert attrs[ATTR_NEXT_TRANSITION_TYPE] == "turn_on"
    assert attrs[ATTR_NEXT_TRANSITION_REASON] == "Off-peak precharge scheduled (+5m stagger)"
    assert attrs[ATTR_EARLIEST_TRANSITION_TIME] == t_earliest.isoformat()
