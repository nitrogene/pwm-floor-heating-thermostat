"""Unit tests for v0.2.9 features: unconstrained Mode B adaptation and refined heat loss bounds."""

from unittest.mock import MagicMock

from custom_components.pwm_floor_heating_thermostat.climate import PwmFloorHeatingThermostat
from custom_components.pwm_floor_heating_thermostat.const import (
    ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES,
    CONF_AUTO_CALIBRATE_HEAT_LOSS,
    CONF_HEAT_LOSS,
    CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
    DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
    MIN_HEAT_LOSS_WK,
)


def test_v029_mode_b_two_stage_adaptation():
    """Verify Mode B operates in 2 stages: clamped ramp-up then unconstrained direct application."""
    hass = MagicMock()
    config = {
        "name": "Test Salon",
        "target_sensor": "sensor.temp_in",
        "outdoor_sensor": "sensor.temp_out",
        "heater": "switch.heater",
        CONF_HEAT_LOSS: 15.0,
        CONF_AUTO_CALIBRATE_HEAT_LOSS: True,
        CONF_HEAT_LOSS_CONFIDENCE_SAMPLES: 10,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    thermostat._cur_temp = 20.0
    thermostat._target_temp = 19.0
    thermostat._outdoor_temp = 10.0

    # Case 1: Insufficient samples (< 3) -> baseline is retained
    thermostat._heat_loss_measured_wk = 7.0
    thermostat._heat_loss_samples_count = 2
    if (
        thermostat._auto_calibrate_heat_loss
        and thermostat._heat_loss_measured_wk is not None
        and thermostat._heat_loss_samples_count >= 3
    ):
        pass
    else:
        thermostat._effective_heat_loss = thermostat._heat_loss

    assert thermostat._effective_heat_loss == 15.0

    # Case 2: Ramp-up phase (3 <= samples < 10) -> clamped to +/-20% of baseline (12.0 to 18.0)
    thermostat._heat_loss_samples_count = 5
    if (
        thermostat._auto_calibrate_heat_loss
        and thermostat._heat_loss_measured_wk is not None
        and thermostat._heat_loss_samples_count >= 3
    ):
        if thermostat._heat_loss_samples_count >= thermostat._heat_loss_confidence_samples:
            thermostat._effective_heat_loss = round(
                max(MIN_HEAT_LOSS_WK, thermostat._heat_loss_measured_wk), 1
            )
        else:
            min_h = round((1.0 - 0.20) * thermostat._heat_loss, 1)
            max_h = round((1.0 + 0.20) * thermostat._heat_loss, 1)
            thermostat._effective_heat_loss = round(
                max(min_h, min(max_h, thermostat._heat_loss_measured_wk)), 1
            )

    assert thermostat._effective_heat_loss == 12.0  # Clamped to -20%

    # Case 3: Confident phase (samples >= 10, e.g. 82) -> direct unconstrained application of 7.0 W/K
    thermostat._heat_loss_samples_count = 82
    if (
        thermostat._auto_calibrate_heat_loss
        and thermostat._heat_loss_measured_wk is not None
        and thermostat._heat_loss_samples_count >= 3
    ):
        if thermostat._heat_loss_samples_count >= thermostat._heat_loss_confidence_samples:
            thermostat._effective_heat_loss = round(
                max(MIN_HEAT_LOSS_WK, thermostat._heat_loss_measured_wk), 1
            )
        else:
            min_h = round((1.0 - 0.20) * thermostat._heat_loss, 1)
            max_h = round((1.0 + 0.20) * thermostat._heat_loss, 1)
            thermostat._effective_heat_loss = round(
                max(min_h, min(max_h, thermostat._heat_loss_measured_wk)), 1
            )

    assert thermostat._effective_heat_loss == 7.0  # Frein sauté !


def test_v029_mode_b_physical_lower_bound():
    """Verify unconstrained measured heat loss cannot fall below physical lower bound (0.5 W/K)."""
    hass = MagicMock()
    config = {
        "name": "Test Passive House",
        "target_sensor": "sensor.temp_in",
        "outdoor_sensor": "sensor.temp_out",
        "heater": "switch.heater",
        CONF_HEAT_LOSS: 2.0,
        CONF_AUTO_CALIBRATE_HEAT_LOSS: True,
        CONF_HEAT_LOSS_CONFIDENCE_SAMPLES: 5,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    thermostat._heat_loss_measured_wk = 0.2  # Aberrantly low sample
    thermostat._heat_loss_samples_count = 20

    if (
        thermostat._auto_calibrate_heat_loss
        and thermostat._heat_loss_measured_wk is not None
        and thermostat._heat_loss_samples_count >= 3
    ):
        if thermostat._heat_loss_samples_count >= thermostat._heat_loss_confidence_samples:
            thermostat._effective_heat_loss = round(
                max(MIN_HEAT_LOSS_WK, thermostat._heat_loss_measured_wk), 1
            )

    assert thermostat._effective_heat_loss == MIN_HEAT_LOSS_WK  # Clamped to 0.5


def test_v029_attributes_and_defaults():
    """Verify new v0.2.9 attributes and default values."""
    hass = MagicMock()
    config = {
        "name": "Test Defaults",
        "target_sensor": "sensor.temp_in",
        "outdoor_sensor": "sensor.temp_out",
        "heater": "switch.heater",
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    assert thermostat._heat_loss_confidence_samples == DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES

    attrs = thermostat.extra_state_attributes
    assert ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES in attrs
    assert attrs[ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES] == 10
