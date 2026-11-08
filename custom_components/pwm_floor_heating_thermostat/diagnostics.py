"""Support des diagnostics pour PWM Floor Heating Thermostat."""

from __future__ import annotations

from typing import Any

try:
    from homeassistant.components.diagnostics import async_redact_data
except ImportError:
    def async_redact_data(data: dict[str, Any], to_redact: list[str]) -> dict[str, Any]:
        """Fallback transparent si components.diagnostics n'est pas importable directement."""
        return data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT: list[str] = []


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Retourne les données de diagnostic pour une entrée de configuration."""
    diagnostics_data: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }

    # Récupération de l'état en direct du thermostat si disponible
    thermostats = hass.data.get(DOMAIN, {})
    thermostat = thermostats.get(entry.entry_id)

    if thermostat:
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
            "temp_derivative_hourly": getattr(thermostat, "_temp_derivative_hourly", None),
            "temp_projected_ahead": getattr(thermostat, "_temp_projected_ahead", None),
            "model_error": getattr(thermostat, "_model_error", None),
            "heat_loss_factor_wk": getattr(thermostat, "_heat_loss", None),
            "compressor_power_watts": getattr(thermostat, "_power_watts", None),
            "energy_quota_24h_kwh": getattr(thermostat, "_energy_quota_24h_kwh", None),
            "heating_hours_needed_24h": getattr(thermostat, "_heating_hours_needed_24h", None),
            "heating_hours_done_today": getattr(thermostat, "_heating_hours_done_today", None),
            "heating_hours_remaining_24h": getattr(thermostat, "_heating_hours_remaining_24h", None),
            "daily_quota_enforced": getattr(thermostat, "_enforce_daily_quota", None),
            "daily_quota_blocked": getattr(thermostat, "_daily_quota_blocked", None),
            "window_detection_active": getattr(thermostat, "_window_detection_active", None),
            "window_open_detected": getattr(thermostat, "_window_open_detected", None),
            "heat_loss_measured_wk": getattr(thermostat, "_heat_loss_measured_wk", None),
            "heat_loss_samples_count": getattr(thermostat, "_heat_loss_samples_count", None),
            "dry_run": getattr(thermostat, "_dry_run", None),
            "simulated_heater_state": getattr(thermostat, "_simulated_heater_state", None),
            "stagger_delay_sec": getattr(thermostat, "_stagger_delay_sec", None),
            "compressor_cycles_today": getattr(thermostat, "_compressor_cycles_today", None),
        }

    return async_redact_data(diagnostics_data, TO_REDACT)
