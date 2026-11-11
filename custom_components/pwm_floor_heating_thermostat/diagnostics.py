"""Diagnostics support for PWM Floor Heating Thermostat."""

from __future__ import annotations

from typing import Any

try:
    from homeassistant.components.diagnostics import async_redact_data
except ImportError:
    def async_redact_data(data: dict[str, Any], to_redact: list[str]) -> dict[str, Any]:
        """Transparent fallback if components.diagnostics cannot be imported directly."""
        return data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PwmThermostatCoordinator

TO_REDACT: list[str] = []


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostic data for a config entry."""
    diagnostics_data: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }

    # Retrieve live thermostat state if registered
    thermostats = hass.data.get(DOMAIN, {})
    thermostat = thermostats.get(entry.entry_id)
    if isinstance(thermostat, PwmThermostatCoordinator) and thermostat.thermostat is not None:
        thermostat = thermostat.thermostat

    if thermostat:
        hours_needed = getattr(thermostat, "_hours_needed_24h", 0.0)
        hours_done = getattr(thermostat, "_hours_run_today", 0.0)
        stagger = getattr(thermostat, "_stagger_delay", None)
        stagger_sec = int(stagger.total_seconds()) if stagger else 0
        peak_dur = getattr(thermostat, "_peak_max_run_duration", None)
        peak_dur_min = int(peak_dur.total_seconds() // 60) if peak_dur else None

        diagnostics_data["thermostat_live_state"] = {
            "name": getattr(thermostat, "_name", None),
            "unique_id": getattr(thermostat, "_unique_id", None),
            "fsm_state": getattr(thermostat, "_fsm_state", None),
            "hvac_mode": getattr(thermostat, "_hvac_mode", None),
            "preset_mode": getattr(thermostat, "_preset_mode", None),
            "target_temperature": getattr(thermostat, "_target_temp", None),
            "current_temperature": getattr(thermostat, "_cur_temp", None),
            "outdoor_temperature": getattr(thermostat, "_outdoor_temp", None),
            "floor_temperature": getattr(thermostat, "_floor_temp", None),
            "decision_reason": getattr(thermostat, "_decision_reason", None),
            "temp_derivative_hourly": getattr(thermostat, "_temp_derivative", None),
            "temp_projected_ahead": getattr(thermostat, "_temp_projected", None),
            "dead_time_hours": getattr(thermostat, "_dead_time", None),
            "effective_dead_time_hours": getattr(thermostat, "_effective_dead_time", None),
            "dead_time_measured_hours": getattr(thermostat, "_dead_time_measured_hours", None),
            "dead_time_samples_count": getattr(thermostat, "_dead_time_samples_count", None),
            "auto_calibrate_dead_time": getattr(thermostat, "_auto_calibrate_dead_time", None),
            "model_error": getattr(thermostat, "_model_error", None),
            "heat_loss_factor_wk": getattr(thermostat, "_heat_loss", None),
            "effective_heat_loss_wk": getattr(thermostat, "_effective_heat_loss", None),
            "auto_calibrate_heat_loss": getattr(thermostat, "_auto_calibrate_heat_loss", None),
            "heat_loss_confidence_samples": getattr(thermostat, "_heat_loss_confidence_samples", None),
            "wind_factor": getattr(thermostat, "_wind_factor", None),
            "wind_speed": getattr(thermostat, "_wind_speed", None),
            "compressor_power_watts": getattr(thermostat, "_power_watts", None),
            "energy_quota_24h_kwh": getattr(thermostat, "_energy_needed_kwh", None),
            "ambient_trim_ratio": getattr(thermostat, "_ambient_trim_ratio", None),
            "solar_credit_kwh": getattr(thermostat, "_solar_credit_kwh", None),
            "heating_hours_needed_24h": hours_needed,
            "heating_hours_done_today": hours_done,
            "heating_hours_remaining_24h": round(max(0.0, hours_needed - hours_done), 2),
            "daily_quota_enforced": getattr(thermostat, "_enforce_daily_quota", None),
            "daily_quota_blocked": getattr(thermostat, "_quota_blocked", None),
            "window_detection_active": getattr(thermostat, "_window_detection_enabled", None),
            "window_open_detected": getattr(thermostat, "_window_open", None),
            "heat_loss_measured_wk": getattr(thermostat, "_heat_loss_measured_wk", None),
            "heat_loss_samples_count": getattr(thermostat, "_heat_loss_samples_count", None),
            "dry_run": getattr(thermostat, "_dry_run", None),
            "simulated_heater_state": getattr(thermostat, "_simulated_heater_state", None),
            "stagger_delay_sec": stagger_sec,
            "weather_entity": getattr(thermostat, "_weather_entity", None),
            "use_weather_forecast_average": getattr(thermostat, "_use_weather_forecast_average", None),
            "forecast_outdoor_temp_24h": getattr(thermostat, "_forecast_outdoor_temp_24h", None),
            "weather_outage_fallback_active": getattr(thermostat, "_weather_outage_fallback_active", None),
            "unserved_quota_carryover_hours": getattr(thermostat, "_unserved_quota_carryover_hours", None),
            "peak_max_run_duration_min": peak_dur_min,
            "compressor_cycles_today": getattr(thermostat, "_cycles_today", None),
            "max_cycles_budget": getattr(thermostat, "_max_cycles", None),
            "extra_state_attributes": getattr(thermostat, "extra_state_attributes", {}),
        }

    return async_redact_data(diagnostics_data, TO_REDACT)
