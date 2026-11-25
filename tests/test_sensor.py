"""Unit tests for sensor platform in PWM Floor Heating Thermostat."""

import asyncio
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EntityCategory

from custom_components.pwm_floor_heating_thermostat.const import DECISION_IDLE, DOMAIN, FSM_IDLE
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
    t._forecast_energy_need_24h_kwh = 4.25
    t._slab_energy_in_transit_kwh = 1.15
    t._planned_heating_hours = 0.81
    t._heat_loss_measured_wk = 13.8
    t._fsm_state = FSM_IDLE
    t._decision_key = DECISION_IDLE
    t._decision_reason = "Idle (stable trajectory)"
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

        # 11 diagnostic sensors expected
        assert len(added_entities) == len(SENSOR_TYPES)
        assert len(added_entities) == 11

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

        # 5. 24h forecast energy need
        s_need = sensor_map["forecast_energy_need_24h_kwh"]
        assert s_need.native_value == 4.25

        # 6. Slab energy in transit
        s_transit = sensor_map["slab_energy_in_transit_kwh"]
        assert s_transit.native_value == 1.15

        # 7. Planned heating hours
        s_hours = sensor_map["planned_heating_hours"]
        assert s_hours.native_value == 0.81

        # 6. Measured heat loss
        s_hl = sensor_map["heat_loss_measured_wk"]
        assert s_hl.native_value == 13.8

        # 7. FSM state
        s_fsm = sensor_map["fsm_state"]
        assert s_fsm.native_value == FSM_IDLE

        # 8. Decision enum & detail attribute
        s_dec = sensor_map["decision"]
        assert s_dec.native_value == DECISION_IDLE
        assert s_dec.extra_state_attributes == {"detail": "Idle (stable trajectory)"}

    asyncio.run(_test())


def test_sensor_update_callback(mock_thermostat, mock_entry):
    """Verify sensor state update through callback trigger."""
    description = SENSOR_TYPES[0]  # temp_projected_ahead
    sensor = PwmDiagnosticSensor(mock_thermostat, description, mock_entry)
    sensor.async_write_ha_state = MagicMock()

    # Trigger coordinator update notification callback
    sensor._handle_coordinator_update()
    sensor.async_write_ha_state.assert_called_once()
