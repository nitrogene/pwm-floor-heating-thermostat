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
        thermostat._cur_temp = 21.3
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 10.0
        thermostat._floor_temp = None
        thermostat._heat_loss = 15.0
        thermostat._dry_run = False

        hass.data = {
            DOMAIN: {
                "test_entry_123": thermostat
            }
        }

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry_id"] == "test_entry_123"
        assert diag["title"] == "Thermostat Salon PWM"
        assert diag["options"]["dry_run"] is False
        assert diag["thermostat_live_state"]["current_temperature"] == 21.3
        assert diag["thermostat_live_state"]["fsm_state"] == "idle"

    asyncio.run(_test())
