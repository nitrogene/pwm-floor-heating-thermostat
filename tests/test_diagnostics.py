"""Tests for diagnostics module."""

import asyncio
from unittest.mock import MagicMock

from custom_components.pwm_floor_heating_thermostat.const import DOMAIN
from custom_components.pwm_floor_heating_thermostat.diagnostics import async_get_config_entry_diagnostics


def test_diagnostics_returns_sanitized_data():
    """Verify diagnostics dump returns sanitized config and live state."""
    async def _test():
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry_123"
        entry.title = "Thermostat Salon PWM"
        entry.data = {"target_sensor": "sensor.temperature_salon"}
        entry.options = {"dry_run": False, "heat_loss_wk": 15.0}

        thermostat = MagicMock()
        thermostat._name = "Thermostat Salon PWM"
        thermostat._unique_id = "test_entry_123"
        thermostat._fsm_state = "idle"
        thermostat._hvac_mode = "heat"
        thermostat._preset_mode = "comfort"
        thermostat._cur_temp = 21.3
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 10.0
        thermostat._floor_temp = None
        thermostat._decision_reason = "Idle"
        thermostat._temp_derivative = -0.15
        thermostat._temp_projected = 20.95
        thermostat._model_error = 0.05
        thermostat._heat_loss = 15.0
        thermostat._effective_heat_loss = 14.8
        thermostat._auto_calibrate_heat_loss = True
        thermostat._power_watts = 3250.0
        thermostat._energy_needed_kwh = 3.6
        thermostat._ambient_trim_ratio = 1.0
        thermostat._solar_credit_kwh = 0.5
        thermostat._hours_needed_24h = 1.11
        thermostat._hours_run_today = 0.5
        thermostat._enforce_daily_quota = True
        thermostat._quota_blocked = False
        thermostat._window_detection_enabled = True
        thermostat._window_open = False
        thermostat._heat_loss_measured_wk = 14.8
        thermostat._heat_loss_samples_count = 3
        thermostat._dry_run = False
        thermostat._simulated_heater_state = False
        thermostat._stagger_delay = None
        thermostat._cycles_today = 2
        thermostat._max_cycles = 6
        thermostat.extra_state_attributes = {"counters_date": "2026-11-09"}

        hass.data = {
            DOMAIN: {
                "test_entry_123": thermostat
            }
        }

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry_id"] == "test_entry_123"
        assert diag["title"] == "Thermostat Salon PWM"
        assert diag["options"]["dry_run"] is False

        live = diag["thermostat_live_state"]
        assert live["current_temperature"] == 21.3
        assert live["fsm_state"] == "idle"
        assert live["temp_derivative_hourly"] == -0.15
        assert live["temp_projected_ahead"] == 20.95
        assert live["energy_quota_24h_kwh"] == 3.6
        assert live["heating_hours_needed_24h"] == 1.11
        assert live["heating_hours_done_today"] == 0.5
        assert live["heating_hours_remaining_24h"] == 0.61
        assert live["heat_loss_factor_wk"] == 15.0
        assert live["effective_heat_loss_wk"] == 14.8
        assert live["auto_calibrate_heat_loss"] is True
        assert live["ambient_trim_ratio"] == 1.0
        assert live["solar_credit_kwh"] == 0.5
        assert live["compressor_cycles_today"] == 2
        assert live["max_cycles_budget"] == 6
        assert live["extra_state_attributes"]["counters_date"] == "2026-11-09"

    asyncio.run(_test())
