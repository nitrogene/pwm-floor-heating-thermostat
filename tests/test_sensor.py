"""Unit tests for sensor platform in PWM Floor Heating Thermostat."""

import asyncio
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EntityCategory

from custom_components.pwm_floor_heating_thermostat.const import DOMAIN, FSM_IDLE
from custom_components.pwm_floor_heating_thermostat.sensor import (
    SENSOR_TYPES,
    PwmDiagnosticSensor,
    async_setup_entry,
)


@pytest.fixture
def mock_thermostat():
    """Create a mock instance of PwmFloorHeatingThermostat."""
    t = MagicMock()
    t._temp_projected = 21.45
    t._temp_derivative = 0.352
    t._model_error = 0.08
    t._model_error_rms = 0.12
    t._energy_needed_kwh = 4.25
    t._hours_needed_24h = 1.31
    t._total_heating_hours_today = 0.50
    t._heat_loss_measured_wk = 13.8
    t._fsm_state = FSM_IDLE
    return t


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_pwm_123"
    entry.title = "Thermostat Salon PWM"
    return entry


def test_sensor_setup_entry(mock_thermostat, mock_entry):
    """Verify async_setup_entry creates all diagnostic sensors."""
    async def _test():
        hass = MagicMock()
        hass.data = {DOMAIN: {mock_entry.entry_id: mock_thermostat}}

        added_entities = []

        def mock_add_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, mock_entry, mock_add_entities)

        # 9 diagnostic sensors expected
        assert len(added_entities) == len(SENSOR_TYPES)
        assert len(added_entities) == 9

        # Validate instantiated sensor properties
        sensor_map = {s.entity_description.key: s for s in added_entities}

        # 1. Projected temperature
        s_proj = sensor_map["temp_projected_ahead"]
        assert s_proj.native_value == 21.45
        assert s_proj.unique_id == f"{mock_entry.entry_id}_temp_projected_ahead"
        assert s_proj.entity_description.entity_category == EntityCategory.DIAGNOSTIC

        # 2. Hourly derivative
        s_deriv = sensor_map["temp_derivative_hourly"]
        assert s_deriv.native_value == 0.352

        # 3. Model error
        s_err = sensor_map["model_error"]
        assert s_err.native_value == 0.08

        # 4. Model error RMS
        s_rms = sensor_map["model_error_rms"]
        assert s_rms.native_value == 0.12

        # 4. 24h energy quota
        s_quota = sensor_map["energy_quota_24h_kwh"]
        assert s_quota.native_value == 4.25

        # 5. Remaining hours (1.31 - 0.50 = 0.81h)
        s_hours = sensor_map["heating_hours_remaining_24h"]
        assert s_hours.native_value == 0.81

        # 6. Measured heat loss
        s_hl = sensor_map["heat_loss_measured_wk"]
        assert s_hl.native_value == 13.8

        # 7. FSM state
        s_fsm = sensor_map["fsm_state"]
        assert s_fsm.native_value == FSM_IDLE

    asyncio.run(_test())


def test_sensor_update_callback(mock_thermostat, mock_entry):
    """Verify sensor state update through callback trigger."""
    description = SENSOR_TYPES[0]  # temp_projected_ahead
    sensor = PwmDiagnosticSensor(mock_thermostat, description, mock_entry)
    sensor.async_write_ha_state = MagicMock()

    # Trigger coordinator update notification callback
    sensor._handle_coordinator_update()
    sensor.async_write_ha_state.assert_called_once()
