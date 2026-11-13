"""End-to-End Real Entity Unit Testing for PwmFloorHeatingThermostat.

Tests Danfoss compressor FSM, thermodynamic rules (A, B, C, D, E, F, G),
and Mode A/B self-adaptation directly on the live PwmFloorHeatingThermostat instance.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import HVACAction, HVACMode

from custom_components.pwm_floor_heating_thermostat.climate import PwmFloorHeatingThermostat
from custom_components.pwm_floor_heating_thermostat.const import (
    ATTR_EFFECTIVE_HEAT_LOSS_WK,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_WAITING_MIN_OFF,
)


@pytest.fixture
def base_config():
    """Return default configuration for real entity testing."""
    return {
        "name": "E2E Real Thermostat",
        "target_sensor": "sensor.living_room_temp",
        "outdoor_sensor": "sensor.outdoor_temp",
        "heater": "switch.danfoss_compressor",
        "off_peak_sensor": "binary_sensor.off_peak",
        "heat_loss_wk": 15.0,
        "power_watts": 6500.0,
        "slab_tau_hours": 15.0,
        "dead_time_hours": 2.25,
        "min_cycle_duration": "00:30:00",
        "min_off_cycle_duration": "00:15:00",
        "max_cycles_per_day": 6,
        "floor_temp_sensor": "sensor.floor_return_temp",
        "max_floor_temp": 28.0,
        "min_floor_temp": 14.0,
        "dry_run": False,
        "auto_calibrate_heat_loss": True,
        "heat_loss_confidence_samples": 10,
    }


@pytest.fixture
def mock_hass():
    """Return a mock HomeAssistant instance with async services."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def test_e2e_danfoss_fsm_lifecycle_and_safety_locks(mock_hass, base_config):
    """Verify Danfoss FSM lifecycle on real PwmFloorHeatingThermostat instance with time warping."""

    async def _test():
        thermostat = PwmFloorHeatingThermostat(mock_hass, base_config)
        thermostat._cur_temp = 18.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 5.0
        thermostat._hvac_mode = HVACMode.HEAT

        t0 = datetime(2026, 11, 11, 2, 0, 0, tzinfo=UTC)

        # 1. Initial State: IDLE
        assert thermostat._fsm_state == FSM_IDLE
        assert thermostat._hvac_action == HVACAction.IDLE

        # 2. Start heating safely at t0
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_start_heating_safe()

        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK
        assert thermostat._hvac_action == HVACAction.HEATING
        assert thermostat._cycles_today == 1
        mock_hass.services.async_call.assert_called_with(
            "switch", "turn_on", {"entity_id": "switch.danfoss_compressor"}, blocking=False
        )

        # 3. Early Stop Attempt at t0 + 10 min -> MUST BE REFUSED (Danfoss 30 min oil return lock)
        t_10m = t0 + timedelta(minutes=10)
        with patch("homeassistant.util.dt.utcnow", return_value=t_10m):
            await thermostat._async_stop_heating_safe()

        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK  # Locked ON!
        assert thermostat._hvac_action == HVACAction.HEATING

        # 4. Stop Attempt at t0 + 31 min -> ACCEPTED (Oil return satisfied)
        t_31m = t0 + timedelta(minutes=31)
        with patch("homeassistant.util.dt.utcnow", return_value=t_31m):
            await thermostat._async_stop_heating_safe()

        assert thermostat._fsm_state == FSM_WAITING_MIN_OFF
        assert thermostat._hvac_action == HVACAction.IDLE
        mock_hass.services.async_call.assert_called_with(
            "switch", "turn_off", {"entity_id": "switch.danfoss_compressor"}, blocking=False
        )

        # 5. Early Restart Attempt at t0 + 36 min (only 5 min off) -> MUST BE REFUSED (Pressure balance lock)
        t_36m = t0 + timedelta(minutes=36)
        with patch("homeassistant.util.dt.utcnow", return_value=t_36m):
            await thermostat._async_start_heating_safe()

        assert thermostat._fsm_state == FSM_WAITING_MIN_OFF  # Locked OFF!
        assert thermostat._hvac_action == HVACAction.IDLE

        # 6. Restart Attempt at t0 + 47 min (16 min off >= 15 min) -> ACCEPTED
        t_47m = t0 + timedelta(minutes=47)
        with patch("homeassistant.util.dt.utcnow", return_value=t_47m):
            await thermostat._async_start_heating_safe()

        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK
        assert thermostat._hvac_action == HVACAction.HEATING
        assert thermostat._cycles_today == 2

    asyncio.run(_test())


def test_e2e_dtu_max_floor_cutoff_and_freeze_safeties(mock_hass, base_config):
    """Verify DTU 65.14 slab water loop safeguards on real entity."""

    async def _test():
        thermostat = PwmFloorHeatingThermostat(mock_hass, base_config)
        thermostat._cur_temp = 18.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 2.0
        thermostat._temp_projected = 16.5
        thermostat._hvac_mode = HVACMode.HEAT

        t0 = datetime(2026, 11, 11, 14, 0, 0, tzinfo=UTC)

        # Normal state: floor return at 22°C -> heating allowed
        thermostat._floor_temp = 22.0
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert thermostat._decision_reason is not None
            assert "Anticipated thermal drop" in thermostat._decision_reason

        # Slab overheat: floor return reaches 28.5°C >= 28.0°C -> immediate cutoff
        thermostat._floor_temp = 28.5
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert "Floor protection cutoff" in thermostat._decision_reason
            assert "exceeds slab maximum 28.0°C" in thermostat._decision_reason

        # Slab freeze: floor return drops to 12.0°C <= 14.0°C -> emergency freeze heating
        thermostat._floor_temp = 12.0
        thermostat._cur_temp = 22.0  # Even if ambient room is warm
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
            assert "Floor freeze protection" in thermostat._decision_reason

    asyncio.run(_test())


def test_e2e_rule_g_peak_hour_run_cap(mock_hass, base_config):
    """Verify Rule G peak-hour run duration cap on real entity."""

    async def _test():
        base_config["peak_max_run_duration"] = "00:45:00"
        base_config["enforce_daily_quota"] = False
        thermostat = PwmFloorHeatingThermostat(mock_hass, base_config)
        thermostat._cur_temp = 18.5
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 5.0
        thermostat._temp_projected = 18.0
        thermostat._hvac_mode = HVACMode.HEAT

        t0 = datetime(2026, 11, 11, 8, 0, 0, tzinfo=UTC)

        # Start compressor in peak hour at t0
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_start_heating_safe()

        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK

        # At t0 + 50 min (> 45 min cap): compressor should stop via Rule G
        t_50m = t0 + timedelta(minutes=50)
        with patch("homeassistant.util.dt.utcnow", return_value=t_50m):
            await thermostat._async_control_heating(now=t_50m)

        assert thermostat._fsm_state == FSM_WAITING_MIN_OFF
        assert "Peak-hour top-up cycle completed" in thermostat._decision_reason

    asyncio.run(_test())


def test_e2e_mode_b_unconstrained_transition(mock_hass, base_config):
    """Verify real entity adopts unconstrained measured heat loss once confidence threshold is reached."""

    async def _test():
        thermostat = PwmFloorHeatingThermostat(mock_hass, base_config)
        thermostat._cur_temp = 20.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 10.0
        thermostat._hvac_mode = HVACMode.HEAT

        t0 = datetime(2026, 11, 11, 3, 0, 0, tzinfo=UTC)

        # Set measured heat loss to 7.0 W/K (baseline is 15.0 W/K)
        thermostat._heat_loss_measured_wk = 7.0

        # Stage 1: Only 5 samples (< 10) -> Clamped to +/-20% of 15.0 = 12.0 W/K
        thermostat._heat_loss_samples_count = 5
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        assert thermostat._effective_heat_loss == 12.0
        assert thermostat.extra_state_attributes[ATTR_EFFECTIVE_HEAT_LOSS_WK] == 12.0

        # Stage 2: 12 samples (>= 10) -> Unconstrained direct adoption = 7.0 W/K
        thermostat._heat_loss_samples_count = 12
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        assert thermostat._effective_heat_loss == 7.0
        assert thermostat.extra_state_attributes[ATTR_EFFECTIVE_HEAT_LOSS_WK] == 7.0

    asyncio.run(_test())
