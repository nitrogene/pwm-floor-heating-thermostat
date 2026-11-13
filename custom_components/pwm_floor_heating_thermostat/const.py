"""Constants for the PWM Floor Heating Thermostat integration."""

import json
from datetime import timedelta
from pathlib import Path


def get_integration_version() -> str:
    """Read version dynamically from manifest.json."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            return str(json.load(f).get("version", "0.3.0"))
    except Exception:
        return "0.3.0"


INTEGRATION_VERSION = get_integration_version()

DOMAIN = "pwm_floor_heating_thermostat"

# Entity configuration
CONF_HEATER = "heater"
CONF_TARGET_SENSOR = "target_sensor"
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_OFF_PEAK_SENSOR = "off_peak_sensor"
CONF_HEURES_CREUSES_SENSOR = "heures_creuses_sensor"  # Alias for backward compatibility

# Floor slab / hydronic loop sensor
CONF_FLOOR_TEMP_SENSOR = "floor_temp_sensor"
CONF_MAX_FLOOR_TEMP = "max_floor_temp"
CONF_MIN_FLOOR_TEMP = "min_floor_temp"

# Simulation / Shadow mode
CONF_DRY_RUN = "dry_run"
CONF_OBSERVED_HEATER = "observed_heater"

# Thermodynamic model physical parameters
CONF_HEAT_LOSS = "heat_loss_wk"          # Overall room heat loss coefficient (W/K)
CONF_POWER_WATTS = "power_watts"        # Heat pump thermal output power (W)
CONF_SLAB_TIME_CONSTANT = "slab_tau_hours"  # Slab thermal inertia time constant (hours)
CONF_DEAD_TIME = "dead_time_hours"      # Pure slab transport dead time (hours)
CONF_AUTO_CALIBRATE_HEAT_LOSS = "auto_calibrate_heat_loss"  # Mode B soft self-adaptation of heat loss
DEFAULT_AUTO_CALIBRATE_HEAT_LOSS = False
CONF_HEAT_LOSS_CONFIDENCE_SAMPLES = "heat_loss_confidence_samples"  # Min samples count for unconstrained direct application
DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES = 10  # Samples count above which measured heat loss is applied unconstrained
MIN_HEAT_LOSS_WK = 0.5  # Physical lower bound for heat loss coefficient (W/K)
CONF_AUTO_CALIBRATE_DEAD_TIME = "auto_calibrate_dead_time"  # Soft self-adaptation of dead time theta
DEFAULT_AUTO_CALIBRATE_DEAD_TIME = False
CONF_KALATA_PROCESS_NOISE = "kalata_process_noise"  # Continuous Kalata process acceleration noise (q_proc)
DEFAULT_KALATA_PROCESS_NOISE = 0.005  # Default 0.005 (°C/h)²/h for high-inertia underfloor slabs
CONF_OUTDOOR_PRECHARGE_MAX_TEMP = "outdoor_precharge_max_temp"  # Max outdoor temp for off-peak precharge
DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP = 12.0  # °C
CONF_COMFORT_SAFETY_DEFICIT = "comfort_safety_deficit"  # Room deficit overriding peak-hour quota
DEFAULT_COMFORT_SAFETY_DEFICIT = 0.8  # °C
CONF_RULE_B_MIN_THRESHOLD = "rule_b_min_threshold"  # Minimum threshold for Rule B anticipated drop trigger
DEFAULT_RULE_B_MIN_THRESHOLD = 0.25  # °C

# Environmental sensors (solar irradiance & wind convective loss)
CONF_SOLAR_SENSOR = "solar_sensor"
CONF_WIND_SENSOR = "wind_sensor"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_USE_WEATHER_FORECAST_AVERAGE = "use_weather_forecast_average"
DEFAULT_USE_WEATHER_FORECAST_AVERAGE = False

# Compressor mechanical safeties (Danfoss)
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_MIN_OFF_CYCLE_DURATION = "min_off_cycle_duration"
CONF_MAX_CYCLES_PER_DAY = "max_cycles_per_day"
CONF_PEAK_MAX_RUN_DURATION = "peak_max_run_duration"  # Adaptive PWM modulation: max continuous run in peak hours

# Daily energy budget cap (Anti-waste during peak hours)
CONF_ENFORCE_DAILY_QUOTA = "enforce_daily_quota"
CONF_ENFORCE_DAILY_QUOTA_SENSOR = "enforce_daily_quota_sensor"
DEFAULT_ENFORCE_DAILY_QUOTA = True

# Open window / ventilation detection
CONF_WINDOW_DETECTION = "window_detection"
CONF_WINDOW_DETECTION_SENSOR = "window_detection_sensor"
CONF_WINDOW_SENSOR = "window_sensor"
CONF_WINDOW_DROP_THRESHOLD = "window_drop_threshold"
CONF_WINDOW_TIMEOUT = "window_timeout"

DEFAULT_WINDOW_DETECTION = True
DEFAULT_WINDOW_DROP_THRESHOLD = 0.4  # Drop of 0.4°C in <= 15 min
DEFAULT_WINDOW_TIMEOUT = timedelta(minutes=30)

# Temperature presets (Comfort, Eco, Away)
CONF_ECO_TEMP = "eco_temp"
CONF_AWAY_TEMP = "away_temp"
CONF_COMFORT_TEMP = "comfort_temp"

DEFAULT_ECO_TEMP = 17.0
DEFAULT_AWAY_TEMP = 15.0

# Multi-Zone coordination & inrush staggering
CONF_STAGGER_DELAY = "stagger_delay"
DEFAULT_STAGGER_DELAY = timedelta(seconds=0)

# Default values
DEFAULT_NAME = "PWM Floor Heating Thermostat"
DEFAULT_TARGET_TEMP = 19.0
DEFAULT_MIN_TEMP = 16.0
DEFAULT_MAX_TEMP = 26.0
DEFAULT_DRY_RUN = False

DEFAULT_MAX_FLOOR_TEMP = 28.0          # DTU 65.14 barefoot comfort limit
DEFAULT_MIN_FLOOR_TEMP = 14.0          # Floor frost protection limit

DEFAULT_HEAT_LOSS = 60.0               # ~60 W/K for an average living room
DEFAULT_POWER_WATTS = 6500.0           # 2x Danfoss M26DX compressors (~6.5 kW th)
DEFAULT_SLAB_TAU_HOURS = 15.0          # ~15 hours slab inertia
DEFAULT_DEAD_TIME_HOURS = 2.25         # ~2h15 slab dead time

DEFAULT_MIN_CYCLE = timedelta(minutes=30)
DEFAULT_MIN_OFF = timedelta(minutes=15)
DEFAULT_PEAK_MAX_RUN_DURATION = timedelta(minutes=45)
DEFAULT_MAX_CYCLES = 6

# Finite State Machine (FSM) states
FSM_IDLE = "idle"
FSM_RUNNING_MIN_LOCK = "running_min_lock"        # Heating active, locked for Danfoss 30 min minimum runtime
FSM_RUNNING_NORMAL = "running_normal"            # Heating active, beyond 30 min minimum runtime
FSM_WAITING_MIN_OFF = "waiting_min_off"          # Heating stopped, locked for 15 min pressure equalization

# Thermodynamic operational thresholds & constants
OUTDOOR_PRECHARGE_MAX_TEMP = 12.0               # Outdoor cutoff above which off-peak precharge is inhibited (°C)
COMFORT_SAFETY_DEFICIT_OVERRIDE = 0.8           # Room deficit below target that overrides peak-hour quota block (°C)
WINDOW_DERIVATIVE_THRESHOLD = -1.5              # Negative hourly derivative threshold for rapid ventilation (°C/h)
POST_AIRING_RECOVERY_MINUTES = 30               # Post-ventilation thermal recovery damping window (minutes)
POST_AIRING_MAX_DERIVATIVE = 0.05               # Max allowed positive derivative during post-airing recovery (°C/h)
ATTR_COUNTERS_DATE = "counters_date"
ATTR_AMBIENT_TRIM_RATIO = "ambient_trim_ratio"
ATTR_SOLAR_CREDIT_KWH = "solar_credit_kwh"
ATTR_EFFECTIVE_HEAT_LOSS_WK = "effective_heat_loss_wk"
ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES = "heat_loss_confidence_samples"

# Ambient supervisor and solar parameters
AMBIENT_TRIM_MIN = 0.80                         # Max 20% quota reduction on warm rooms
AMBIENT_TRIM_MAX = 1.25                         # Max 25% quota boost on cold rooms
AMBIENT_TRIM_GAIN = 0.15                        # 15% quota trim per °C of room error
SOLAR_MORNING_CUTOFF_HOUR = 9                   # Local hour before which solar credit is strictly 0.0 (morning comfort guard)
SOLAR_MAX_CREDIT_RATIO = 0.25                   # Max 25% quota reduction from daytime solar irradiance
AUTO_CALIBRATE_MIN_SAMPLES = 3                  # Minimum validated night decay samples before engaging Mode B
AUTO_CALIBRATE_MAX_DEVIATION = 0.20             # Max +/-20% variation allowed around configured baseline H

# Wind convective amplification parameters
WIND_SPEED_CALM_THRESHOLD = 15.0                # Calm wind threshold below which forced convection is negligible (km/h)
WIND_AMPLIFICATION_GAIN = 0.005                 # +0.5% heat loss boost per km/h above calm threshold
WIND_MAX_AMPLIFICATION = 1.25                   # Maximum +25% heat loss boost from high wind
DEAD_TIME_MIN_SAMPLES = 3                       # Minimum validated cycles before soft adapting dead time
DEAD_TIME_MAX_DEVIATION = 0.25                  # Max +/-25% variation allowed around configured baseline dead time

# Wind & dead time telemetry attributes
ATTR_WIND_FACTOR = "wind_factor"
ATTR_WIND_SPEED = "wind_speed"
ATTR_DEAD_TIME_MEASURED_HOURS = "dead_time_measured_hours"
ATTR_DEAD_TIME_SAMPLES_COUNT = "dead_time_samples_count"
ATTR_EFFECTIVE_DEAD_TIME_HOURS = "effective_dead_time_hours"
ATTR_KALATA_PROCESS_NOISE = "kalata_process_noise"
ATTR_MODEL_ERROR_RMS = "model_error_rms"
ATTR_RULE_B_THRESHOLD = "rule_b_threshold"
ATTR_FORECAST_OUTDOOR_TEMP_24H = "forecast_outdoor_temp_24h"
ATTR_WEATHER_OUTAGE_FALLBACK_ACTIVE = "weather_outage_fallback_active"
ATTR_UNSERVED_QUOTA_CARRYOVER_HOURS = "unserved_quota_carryover_hours"
MAX_UNSERVED_QUOTA_CARRYOVER_HOURS = 2.0

# Sensor stale watchdog & hardware safety guards
CONF_SENSOR_STALE_TIMEOUT_MINUTES = "sensor_stale_timeout_minutes"
DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES = 90  # 90 minutes watchdog timeout
ATTR_SENSOR_STALE = "sensor_stale"

CONF_MAX_CONTINUOUS_RUN_MINUTES = "max_continuous_run_minutes"
DEFAULT_MAX_CONTINUOUS_RUN_MINUTES = 120  # Max 120 min continuous run even off-peak

CONF_THERMAL_RUNAWAY_DERIVATIVE = "thermal_runaway_derivative"
DEFAULT_THERMAL_RUNAWAY_DERIVATIVE = 1.5  # °C/h sustained positive slope cutoff

CONF_HARD_OVERSHOOT_MARGIN = "hard_overshoot_margin"
DEFAULT_HARD_OVERSHOOT_MARGIN = 1.0  # °C above target ceiling cutoff

EMERGENCY_COMFORT_DEFICIT_OVERRIDE = 1.5  # °C below target emergency bypass

# Next transition estimation
ATTR_NEXT_TRANSITION_TIME = "next_transition_time"
ATTR_NEXT_TRANSITION_TYPE = "next_transition_type"
ATTR_NEXT_TRANSITION_REASON = "next_transition_reason"
ATTR_EARLIEST_TRANSITION_TIME = "earliest_transition_time"
