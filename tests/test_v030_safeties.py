"""Unit tests for v0.3.0 hardware safety guards and sensor watchdog features."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import MockConfigEntry
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.config_flow import (
    PwmFloorHeatingConfigFlow,
    PwmFloorHeatingOptionsFlowHandler,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    ATTR_SENSOR_STALE,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HARD_OVERSHOOT_MARGIN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_MAX_CONTINUOUS_RUN_MINUTES,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SENSOR_STALE_TIMEOUT_MINUTES,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    CONF_THERMAL_RUNAWAY_DERIVATIVE,
    FSM_RUNNING_NORMAL,
)


@pytest.fixture
def base_config():
    """Create minimal thermostat configuration for safety testing."""
    return {
        CONF_NAME: "Safety Thermostat Test",
        CONF_TARGET_SENSOR: "sensor.room_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.heater",
        CONF_HEAT_LOSS: 15.0,
        CONF_POWER_WATTS: 3000.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_DRY_RUN: True,
        CONF_SENSOR_STALE_TIMEOUT_MINUTES: 90,
        CONF_MAX_CONTINUOUS_RUN_MINUTES: 120,
        CONF_THERMAL_RUNAWAY_DERIVATIVE: 1.5,
        CONF_HARD_OVERSHOOT_MARGIN: 1.0,
    }


def test_stale_sensor_watchdog_cutoff_and_recovery(base_config):
    """Verify stale sensor triggers fail-safe shutdown and recovers upon fresh update."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp = 18.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 2.0
        thermostat._temp_projected = 17.5
        thermostat._hvac_mode = HVACMode.HEAT

        # Sensor was updated 95 minutes ago (> 90 min timeout)
        thermostat._cur_temp_ts = t0 - timedelta(minutes=95)

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert thermostat._sensor_stale is True
            assert thermostat.extra_state_attributes[ATTR_SENSOR_STALE] is True
            assert "Fail-safe shutdown: ambient sensor stale for 95 min" in thermostat._decision_reason

        # Fresh reading arrives (5 minutes ago)
        thermostat._cur_temp_ts = t0 - timedelta(minutes=5)
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert thermostat._sensor_stale is False
            assert thermostat.extra_state_attributes[ATTR_SENSOR_STALE] is False
            assert "Fail-safe shutdown" not in thermostat._decision_reason

    asyncio.run(_test())


def test_hard_ambient_overshoot_ceiling_cutoff(base_config):
    """Verify heating is unconditionally stopped when room exceeds target + margin."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp_ts = t0
        thermostat._target_temp = 19.0
        thermostat._hard_overshoot_margin = 1.0
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._outdoor_temp = 2.0

        # Room temperature reaches 20.2°C >= 19.0 + 1.0°C
        thermostat._cur_temp = 20.2
        thermostat._temp_projected = 18.5  # Even if projection falsely claimed drop

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert "Hard overshoot ceiling cutoff: curr 20.2°C >= target 19.0°C + 1.0°C" in thermostat._decision_reason

    asyncio.run(_test())


def test_max_continuous_run_cap_shutdown(base_config):
    """Verify global continuous run cap cuts off heating after 120 minutes across all tariffs."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 10, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp_ts = t0
        thermostat._cur_temp = 18.5
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 0.0
        thermostat._temp_projected = 17.5
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_RUNNING_NORMAL

        # Simulate Off-Peak tariff (where Rule G peak cap does not apply, but global 120 min cap must apply)
        thermostat._off_peak_sensor = "binary_sensor.off_peak"
        mock_op = MagicMock()
        mock_op.state = "on"
        hass.states.get.return_value = mock_op

        # Simulate heater running since 2 hours and 5 minutes (125 minutes)
        t_active = t0 + timedelta(minutes=125)
        thermostat._cycle_start_time = t0
        thermostat._cur_temp_ts = t_active

        with patch("homeassistant.util.dt.utcnow", return_value=t_active):
            await thermostat._async_control_heating(now=t_active)
            assert "Maximum continuous run duration reached (125 min >= 120 min)" in thermostat._decision_reason

    asyncio.run(_test())


def test_thermal_runaway_cutoff(base_config):
    """Verify emergency thermal runaway shutdown when dT/dt > 1.5°C/h sustained for > 30 min."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 10, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp_ts = t0
        thermostat._cur_temp = 18.5
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 5.0
        thermostat._temp_projected = 18.8
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._fsm_state = FSM_RUNNING_NORMAL

        # Excessive slope (+1.8°C/h)
        thermostat._derivative_smooth = 1.8
        thermostat._observer_last_update = t0

        # 1. Slope high for only 10 minutes -> no trip yet
        thermostat._thermal_runaway_start_time = t0 - timedelta(minutes=10)
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert "thermal runaway detected" not in thermostat._decision_reason

        # 2. Slope high for 35 minutes (> 30 min threshold) -> emergency trip!
        thermostat._thermal_runaway_start_time = t0 - timedelta(minutes=35)
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert "Emergency cutoff: thermal runaway detected" in thermostat._decision_reason

    asyncio.run(_test())


def test_emergency_comfort_deficit_bypass(base_config):
    """Verify severe cold deficit overrides daily quota blocks."""
    async def _test():
        hass = MagicMock()
        t0 = datetime(2026, 11, 13, 14, 0, 0, tzinfo=UTC)

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp_ts = t0
        thermostat._outdoor_temp = 0.0
        thermostat._target_temp = 19.0
        # Deficit is 2.0°C >= 1.5°C
        thermostat._cur_temp = 17.0
        thermostat._temp_projected = 16.5
        thermostat._hvac_mode = HVACMode.HEAT

        # Quota is exhausted
        thermostat._enforce_daily_quota = True
        thermostat._daily_energy_kwh = 25.0
        thermostat._daily_quota_kwh = 15.0

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            # Must NOT be blocked by quota
            assert "Daily thermal quota exhausted" not in thermostat._decision_reason
            assert "Emergency comfort deficit bypass" in thermostat._decision_reason

    asyncio.run(_test())


def test_v030_config_flow_and_options_flow():
    """Verify v0.3.0 options and config flow defaults and validation."""
    async def _test():
        # Verify Config Flow accepts safety options
        flow = PwmFloorHeatingConfigFlow()
        user_input = {
            CONF_NAME: "Config Test",
            CONF_TARGET_SENSOR: "sensor.room_temp",
            CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
            CONF_DRY_RUN: True,
            CONF_SENSOR_STALE_TIMEOUT_MINUTES: 120,
            CONF_MAX_CONTINUOUS_RUN_MINUTES: 180,
            CONF_THERMAL_RUNAWAY_DERIVATIVE: 2.0,
            CONF_HARD_OVERSHOOT_MARGIN: 1.5,
        }
        result = await flow.async_step_user(user_input=user_input)
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data[CONF_SENSOR_STALE_TIMEOUT_MINUTES] == 120
        assert data[CONF_MAX_CONTINUOUS_RUN_MINUTES] == 180
        assert data[CONF_THERMAL_RUNAWAY_DERIVATIVE] == 2.0
        assert data[CONF_HARD_OVERSHOOT_MARGIN] == 1.5

        # Verify Options Flow handles and returns updated options
        entry = MockConfigEntry(
            entry_id="test_safety_entry",
            title="Safety Thermostat",
            data=dict(data),
            options={},
        )

        options_flow = PwmFloorHeatingOptionsFlowHandler(entry)
        options_result = await options_flow.async_step_init(user_input=None)
        assert options_result["type"] == "form"
        assert options_result["step_id"] == "init"

        # Save new values via options flow
        updated_options = {
            CONF_SENSOR_STALE_TIMEOUT_MINUTES: 60,
            CONF_MAX_CONTINUOUS_RUN_MINUTES: 90,
            CONF_THERMAL_RUNAWAY_DERIVATIVE: 1.2,
            CONF_HARD_OVERSHOOT_MARGIN: 0.8,
        }
        options_save = await options_flow.async_step_init(user_input=updated_options)
        assert options_save["type"] == "create_entry"
        assert options_save["data"][CONF_SENSOR_STALE_TIMEOUT_MINUTES] == 60
        assert options_save["data"][CONF_MAX_CONTINUOUS_RUN_MINUTES] == 90
        assert options_save["data"][CONF_THERMAL_RUNAWAY_DERIVATIVE] == 1.2
        assert options_save["data"][CONF_HARD_OVERSHOOT_MARGIN] == 0.8

    asyncio.run(_test())
