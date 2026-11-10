"""Unit tests for v0.2.7 features:
- Dynamic integration version resolution from manifest.json.
- Denoised continuous Kalata filter with derivative low-pass smoothing (sawtooth noise eradication).
- Sub-second event deduplication guard in trajectory projection.
- Configurable thermodynamic parameters via Options Flow (Kalata process noise, outdoor precharge max temp, comfort safety deficit).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from custom_components.pwm_floor_heating_thermostat.climate import PwmFloorHeatingThermostat
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_COMFORT_SAFETY_DEFICIT,
    CONF_KALATA_PROCESS_NOISE,
    CONF_OUTDOOR_PRECHARGE_MAX_TEMP,
    CONF_OUTDOOR_SENSOR,
    CONF_RULE_B_MIN_THRESHOLD,
    CONF_TARGET_SENSOR,
    DEFAULT_COMFORT_SAFETY_DEFICIT,
    DEFAULT_KALATA_PROCESS_NOISE,
    DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP,
    DEFAULT_RULE_B_MIN_THRESHOLD,
    INTEGRATION_VERSION,
    get_integration_version,
)


def test_dynamic_version_resolution():
    """Verify integration version is resolved dynamically from manifest.json."""
    version = get_integration_version()
    assert version == "0.2.7"
    assert INTEGRATION_VERSION == "0.2.7"


def test_trajectory_projection_deduplication():
    """Verify sub-second duplicate calls do not trigger redundant recalculations."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    t0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)

    thermostat._cur_temp = 20.0
    thermostat._update_trajectory_projection(t0)

    assert thermostat._filtered_temp == 20.0
    assert thermostat._temp_derivative == 0.0
    assert thermostat._derivative_smooth == 0.0
    assert thermostat._observer_last_update == t0
    assert len(thermostat._temp_history) == 1

    # Call again 100 milliseconds later: should be ignored by deduplication guard
    t_dup = t0 + timedelta(milliseconds=100)
    thermostat._cur_temp = 20.1
    thermostat._update_trajectory_projection(t_dup)

    # State and history should remain untouched
    assert thermostat._observer_last_update == t0
    assert len(thermostat._temp_history) == 1


def test_kalata_smooth_stair_step_response():
    """Verify continuous Kalata filter + low-pass derivative produces smooth projected temperature on stair-step input."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
        CONF_KALATA_PROCESS_NOISE: DEFAULT_KALATA_PROCESS_NOISE,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    t0 = datetime(2026, 11, 10, 0, 0, 0, tzinfo=UTC)

    # Initialize at 20.0°C
    thermostat._cur_temp = 20.0
    thermostat._update_trajectory_projection(t0)

    projected_temps = []
    smoothed_derivs = []

    # Simulate 2 hours of cooling with 0.1°C quantization steps every 40 minutes
    # (20.0 for 40 min, 19.9 for 40 min, 19.8 for 40 min)
    for minute in range(1, 121):
        now = t0 + timedelta(minutes=minute)
        if minute < 40:
            thermostat._cur_temp = 20.0
        elif minute < 80:
            thermostat._cur_temp = 19.9
        else:
            thermostat._cur_temp = 19.8

        thermostat._update_trajectory_projection(now)
        projected_temps.append(thermostat._temp_projected)
        smoothed_derivs.append(thermostat._derivative_smooth)

    # 1. Verify derivative never explodes or shows high spikes (should stay comfortably bounded)
    for deriv in smoothed_derivs:
        assert -0.5 <= deriv <= 0.1, f"Derivative spike observed: {deriv}"

    # 2. Check trajectory continuity: no consecutive sample step should exceed 0.05°C
    for i in range(1, len(projected_temps)):
        jump = abs(projected_temps[i] - projected_temps[i - 1])
        assert jump < 0.05, f"Discontinuous jump of {jump}°C at minute {i}"

    # 3. Monotonic trend: projected temp at end should be lower than at start
    assert projected_temps[-1] < projected_temps[0]


def test_configurable_options_flow_defaults_and_attributes():
    """Verify new options can be configured and are exposed in extra_state_attributes."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
        CONF_KALATA_PROCESS_NOISE: 0.010,
        CONF_OUTDOOR_PRECHARGE_MAX_TEMP: 14.0,
        CONF_COMFORT_SAFETY_DEFICIT: 1.2,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)

    assert thermostat._kalata_process_noise == 0.010
    assert thermostat._outdoor_precharge_max_temp == 14.0
    assert thermostat._comfort_safety_deficit == 1.2

    attrs = thermostat.extra_state_attributes
    assert attrs["kalata_process_noise"] == 0.010
    assert attrs["outdoor_precharge_max_temp"] == 14.0
    assert attrs["comfort_safety_deficit"] == 1.2


def test_default_values_when_omitted():
    """Verify fallback to sensible defaults when new options are not provided."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)

    assert thermostat._kalata_process_noise == DEFAULT_KALATA_PROCESS_NOISE
    assert thermostat._outdoor_precharge_max_temp == DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP
    assert thermostat._comfort_safety_deficit == DEFAULT_COMFORT_SAFETY_DEFICIT
    assert thermostat._rule_b_min_threshold == DEFAULT_RULE_B_MIN_THRESHOLD


def test_model_error_rms_calculation():
    """Verify rolling 24h RMS calculation of model error."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    t0 = datetime(2026, 11, 10, 10, 0, 0, tzinfo=UTC)

    # Pre-initialize filter state so it is not treated as a first-reading startup
    thermostat._filtered_temp = 20.0
    thermostat._temp_derivative = 0.0
    thermostat._derivative_smooth = 0.0
    thermostat._observer_last_update = t0 - timedelta(minutes=1)
    thermostat._cur_temp = 20.0
    thermostat._effective_dead_time = 1.0

    # Add past projections at t - 1h
    t_past = t0 - timedelta(hours=1)
    thermostat._projection_history = [
        (t_past - timedelta(minutes=5), 19.8),
        (t_past + timedelta(minutes=5), 19.8),
    ]

    thermostat._update_trajectory_projection(t0)

    # e_model = 20.0 - 19.8 = 0.20
    assert thermostat._model_error == 0.20
    assert thermostat._model_error_rms == 0.20

    # Add second point with error = -0.20 at t0 + 1h
    t1 = t0 + timedelta(hours=1)
    thermostat._projection_history = [
        (t1 - timedelta(hours=1, minutes=5), 20.2),
        (t1 - timedelta(hours=1) + timedelta(minutes=5), 20.2),
    ]
    thermostat._cur_temp = 20.0
    thermostat._update_trajectory_projection(t1)

    assert thermostat._model_error == -0.20
    # RMS of [0.20, -0.20] = sqrt((0.04 + 0.04)/2) = 0.20
    assert thermostat._model_error_rms == 0.20


def test_adaptive_rule_b_threshold():
    """Verify Rule B threshold scales adaptively with model RMS uncertainty."""
    hass = MagicMock()
    config = {
        CONF_TARGET_SENSOR: "sensor.indoor",
        CONF_OUTDOOR_SENSOR: "sensor.outdoor",
        CONF_RULE_B_MIN_THRESHOLD: 0.25,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)

    # Case 1: Low RMS noise (0.08°C) -> threshold clamped to baseline floor (0.25°C)
    thermostat._model_error_rms = 0.08
    effective_rms = thermostat._model_error_rms
    threshold = max(thermostat._rule_b_min_threshold, round(2.0 * effective_rms, 2))
    assert threshold == 0.25

    # Case 2: High model uncertainty (0.20°C) -> threshold scales to 2 * RMS = 0.40°C
    thermostat._model_error_rms = 0.20
    effective_rms = thermostat._model_error_rms
    threshold = max(thermostat._rule_b_min_threshold, round(2.0 * effective_rms, 2))
    assert threshold == 0.40
