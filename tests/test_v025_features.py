"""Unit tests for v0.2.5 thermodynamic enhancements:
- Slow drift ambient supervisor (proportional trim bounded [0.80, 1.25]).
- Solar irradiance credit with inviolable morning wake-up comfort floor guard.
- Mode B soft self-adaptation of building heat loss H (clamped +/-20%).
"""

from unittest.mock import MagicMock

from custom_components.pwm_floor_heating_thermostat.const import (
    AMBIENT_TRIM_GAIN,
    AMBIENT_TRIM_MAX,
    AMBIENT_TRIM_MIN,
    ATTR_AMBIENT_TRIM_RATIO,
    ATTR_EFFECTIVE_HEAT_LOSS_WK,
    ATTR_SOLAR_CREDIT_KWH,
    AUTO_CALIBRATE_MAX_DEVIATION,
    AUTO_CALIBRATE_MIN_SAMPLES,
    SOLAR_MAX_CREDIT_RATIO,
    SOLAR_MORNING_CUTOFF_HOUR,
)


def calculate_ambient_trim(cur_temp: float | None, target_temp: float) -> float:
    """Calculate ambient trim ratio identical to climate.py."""
    if cur_temp is None:
        return 1.0
    ambient_error = target_temp - cur_temp
    return round(
        max(AMBIENT_TRIM_MIN, min(AMBIENT_TRIM_MAX, 1.0 + AMBIENT_TRIM_GAIN * ambient_error)),
        3,
    )


def calculate_effective_heat_loss(
    base_h: float,
    auto_calibrate: bool,
    measured_h: float | None,
    samples_count: int,
) -> float:
    """Calculate effective heat loss H identical to climate.py."""
    if not auto_calibrate or measured_h is None or samples_count < AUTO_CALIBRATE_MIN_SAMPLES:
        return base_h
    min_h = round((1.0 - AUTO_CALIBRATE_MAX_DEVIATION) * base_h, 1)
    max_h = round((1.0 + AUTO_CALIBRATE_MAX_DEVIATION) * base_h, 1)
    return round(max(min_h, min(max_h, measured_h)), 1)


def calculate_solar_credit(
    local_hour: int,
    off_peak_active: bool,
    cur_temp: float | None,
    target_temp: float,
    trimmed_energy_kwh: float,
    solar_val: float | None,
) -> float:
    """Calculate solar credit with morning comfort floor guard identical to climate.py."""
    comfort_guard_active = (
        local_hour < SOLAR_MORNING_CUTOFF_HOUR
        or off_peak_active
        or (cur_temp is not None and cur_temp < (target_temp - 0.3))
    )
    if comfort_guard_active or solar_val is None or solar_val <= 50.0:
        return 0.0

    solar_factor = min(1.0, max(0.0, (solar_val - 50.0) / 750.0))
    max_solar_credit = trimmed_energy_kwh * SOLAR_MAX_CREDIT_RATIO
    return round(max_solar_credit * solar_factor, 2)


def test_ambient_supervisor_scaling_and_clamping():
    """Verify ambient supervisor trim ratio scaling and strict clamping [0.80, 1.25]."""
    # 1. Nominal equilibrium (cur == target) -> 1.0
    assert calculate_ambient_trim(cur_temp=19.0, target_temp=19.0) == 1.0

    # 2. Moderate cold deficit (+0.5°C error) -> +7.5% boost
    assert calculate_ambient_trim(cur_temp=18.5, target_temp=19.0) == 1.075

    # 3. Large cold deficit (+2.5°C error) -> clamped at 1.25 (+25% max)
    assert calculate_ambient_trim(cur_temp=16.5, target_temp=19.0) == 1.25

    # 4. Moderate warm surplus (-0.5°C error) -> -7.5% reduction
    assert calculate_ambient_trim(cur_temp=19.5, target_temp=19.0) == 0.925

    # 5. Large warm surplus (-2.0°C error) -> clamped at 0.80 (-20% max)
    assert calculate_ambient_trim(cur_temp=21.0, target_temp=19.0) == 0.80

    # 6. Unknown current temperature -> fallback 1.0
    assert calculate_ambient_trim(cur_temp=None, target_temp=19.0) == 1.0


def test_morning_wake_up_comfort_guard_solar_credit():
    """Verify morning wake-up comfort guard prevents solar credit from starving nighttime/morning heating."""
    trimmed_quota = 10.0  # 10 kWh daily demand

    # 1. Early morning (07:00 AM) with bright forecasted sun (800 W/m²) -> Credit MUST be 0.0
    credit_7am = calculate_solar_credit(
        local_hour=7,
        off_peak_active=False,
        cur_temp=19.0,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=800.0,
    )
    assert credit_7am == 0.0, "Morning comfort guard must force solar credit to 0.0 before 9:00 AM"

    # 2. Nighttime off-peak recharge (02:00 AM) -> Credit MUST be 0.0
    credit_night = calculate_solar_credit(
        local_hour=2,
        off_peak_active=True,
        cur_temp=18.8,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=600.0,
    )
    assert credit_night == 0.0, "Off-peak recharge must never be reduced by solar credit"

    # 3. Afternoon (14:00) but room is uncomfortably cold (18.6°C for target 19.0°C) -> Credit MUST be 0.0
    credit_cold_room = calculate_solar_credit(
        local_hour=14,
        off_peak_active=False,
        cur_temp=18.6,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=700.0,
    )
    assert credit_cold_room == 0.0, "Solar credit must be inhibited if room temperature is below target - 0.3°C"


def test_daytime_solar_credit_application_and_clamping():
    """Verify daytime solar credit calculates proportional reduction bounded by SOLAR_MAX_CREDIT_RATIO."""
    trimmed_quota = 10.0  # 10 kWh daily demand

    # 1. Afternoon (13:00) with maximum solar irradiance (800 W/m²), room at target 19.0°C
    credit_full_sun = calculate_solar_credit(
        local_hour=13,
        off_peak_active=False,
        cur_temp=19.0,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=800.0,
    )
    # Max credit = 10.0 * 0.25 = 2.5 kWh
    assert credit_full_sun == 2.5

    # 2. Afternoon with moderate diffuse light (425 W/m²)
    # solar_factor = (425 - 50) / 750 = 375 / 750 = 0.50
    # credit = 2.5 * 0.5 = 1.25 kWh
    credit_moderate_sun = calculate_solar_credit(
        local_hour=13,
        off_peak_active=False,
        cur_temp=19.0,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=425.0,
    )
    assert credit_moderate_sun == 1.25

    # 3. Overcast / low light (40 W/m² <= 50 W/m² threshold) -> 0.0
    credit_overcast = calculate_solar_credit(
        local_hour=13,
        off_peak_active=False,
        cur_temp=19.0,
        target_temp=19.0,
        trimmed_energy_kwh=trimmed_quota,
        solar_val=40.0,
    )
    assert credit_overcast == 0.0


def test_mode_b_auto_calibration_heat_loss():
    """Verify Mode B soft self-adaptation of building heat loss H."""
    base_h = 60.0

    # 1. Mode B disabled -> stays strictly at baseline H
    assert calculate_effective_heat_loss(base_h, auto_calibrate=False, measured_h=70.0, samples_count=10) == 60.0

    # 2. Mode B enabled but insufficient samples (< 3) -> stays at baseline H
    assert calculate_effective_heat_loss(base_h, auto_calibrate=True, measured_h=70.0, samples_count=2) == 60.0

    # 3. Mode B enabled with 3+ samples and reasonable measured value (63.0 W/K) -> adapts to 63.0
    assert calculate_effective_heat_loss(base_h, auto_calibrate=True, measured_h=63.0, samples_count=5) == 63.0

    # 4. Mode B enabled with abnormally high measured value (100.0 W/K) -> clamped to +20% (72.0 W/K)
    assert calculate_effective_heat_loss(base_h, auto_calibrate=True, measured_h=100.0, samples_count=5) == 72.0

    # 5. Mode B enabled with abnormally low measured value (30.0 W/K) -> clamped to -20% (48.0 W/K)
    assert calculate_effective_heat_loss(base_h, auto_calibrate=True, measured_h=30.0, samples_count=5) == 48.0


def test_thermostat_extra_state_attributes_v025():
    """Verify climate entity exposes v0.2.5 telemetry attributes."""
    from custom_components.pwm_floor_heating_thermostat.climate import PwmFloorHeatingThermostat

    hass = MagicMock()
    config = {
        "name": "Test Thermostat",
        "target_sensor": "sensor.temp_in",
        "outdoor_sensor": "sensor.temp_out",
        "heater": "switch.heater",
        "heat_loss_wk": 50.0,
        "auto_calibrate_heat_loss": True,
        "solar_sensor": "sensor.solar_power",
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    thermostat._cur_temp = 18.5
    thermostat._outdoor_temp = 5.0
    thermostat._target_temp = 19.0
    thermostat._ambient_trim_ratio = 1.075
    thermostat._solar_credit_kwh = 1.2
    thermostat._effective_heat_loss = 52.0

    attrs = thermostat.extra_state_attributes
    assert attrs[ATTR_AMBIENT_TRIM_RATIO] == 1.075
    assert attrs[ATTR_SOLAR_CREDIT_KWH] == 1.2
    assert attrs[ATTR_EFFECTIVE_HEAT_LOSS_WK] == 52.0
    assert attrs["auto_calibrate_heat_loss"] is True
