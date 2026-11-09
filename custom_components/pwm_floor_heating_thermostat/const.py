"""Constants for the PWM Floor Heating Thermostat integration."""

from datetime import timedelta

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

# Compressor mechanical safeties (Danfoss)
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_MIN_OFF_CYCLE_DURATION = "min_off_cycle_duration"
CONF_MAX_CYCLES_PER_DAY = "max_cycles_per_day"

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
