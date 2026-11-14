"""Climate platform for the PWM Floor Heating Thermostat integration.

Thermodynamic model-based predictive thermostat for heavy underfloor heating:
- Daily thermal energy budget estimation from building heat loss (W/K) and outdoor forecast.
- Priority scheduling for continuous long heating cycles during Off-Peak tariff windows (Linky TIC / Off-Peak).
- Strict Finite State Machine (FSM) enforcing Danfoss compressor safeties (30m min ON / 15m min OFF).
- Dead-time predictive engine: continuous-discrete state observer (Kalman 1D / alpha-beta) and projection at t + theta.
- Hydronic underfloor loop / slab sensor support with DTU 65.14 barefoot comfort and freeze protection limits.
- Simulation / Shadow Mode (dry_run: true) for benchmark validation without hardware relay switching.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_STOP,
    PRECISION_TENTHS,
    UnitOfTemperature,
)

try:
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
except ImportError:
    from homeassistant.const import EVENT_HOMEASSISTANT_START as EVENT_HOMEASSISTANT_STARTED  # type: ignore[no-redef]
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    AMBIENT_TRIM_GAIN,
    AMBIENT_TRIM_MAX,
    AMBIENT_TRIM_MIN,
    ATTR_AMBIENT_TRIM_RATIO,
    ATTR_COUNTERS_DATE,
    ATTR_DEAD_TIME_MEASURED_HOURS,
    ATTR_DEAD_TIME_SAMPLES_COUNT,
    ATTR_EARLIEST_TRANSITION_TIME,
    ATTR_EFFECTIVE_DEAD_TIME_HOURS,
    ATTR_EFFECTIVE_HEAT_LOSS_WK,
    ATTR_FORECAST_OUTDOOR_TEMP_24H,
    ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES,
    ATTR_KALATA_PROCESS_NOISE,
    ATTR_MODEL_ERROR_RMS,
    ATTR_NEXT_TRANSITION_REASON,
    ATTR_NEXT_TRANSITION_TIME,
    ATTR_NEXT_TRANSITION_TYPE,
    ATTR_RULE_B_THRESHOLD,
    ATTR_SENSOR_STALE,
    ATTR_SOLAR_CREDIT_KWH,
    ATTR_UNSERVED_QUOTA_CARRYOVER_HOURS,
    ATTR_WEATHER_OUTAGE_FALLBACK_ACTIVE,
    ATTR_WIND_FACTOR,
    ATTR_WIND_SPEED,
    AUTO_CALIBRATE_MAX_DEVIATION,
    AUTO_CALIBRATE_MIN_SAMPLES,
    CONF_AUTO_CALIBRATE_DEAD_TIME,
    CONF_AUTO_CALIBRATE_HEAT_LOSS,
    CONF_AWAY_TEMP,
    CONF_COMFORT_SAFETY_DEFICIT,
    CONF_COMFORT_TEMP,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_ECO_TEMP,
    CONF_ENFORCE_DAILY_QUOTA,
    CONF_ENFORCE_DAILY_QUOTA_SENSOR,
    CONF_FLOOR_TEMP_SENSOR,
    CONF_HARD_OVERSHOOT_MARGIN,
    CONF_HEAT_LOSS,
    CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
    CONF_HEATER,
    CONF_HEURES_CREUSES_SENSOR,
    CONF_KALATA_PROCESS_NOISE,
    CONF_MAX_CONTINUOUS_RUN_MINUTES,
    CONF_MAX_CYCLES_PER_DAY,
    CONF_MAX_FLOOR_TEMP,
    CONF_MIN_CYCLE_DURATION,
    CONF_MIN_FLOOR_TEMP,
    CONF_MIN_OFF_CYCLE_DURATION,
    CONF_OBSERVED_HEATER,
    CONF_OFF_PEAK_SENSOR,
    CONF_OFF_PEAK_START_ENTITY,
    CONF_OUTDOOR_PRECHARGE_MAX_TEMP,
    CONF_OUTDOOR_SENSOR,
    CONF_PEAK_MAX_RUN_DURATION,
    CONF_POWER_WATTS,
    CONF_RULE_B_MIN_THRESHOLD,
    CONF_SENSOR_STALE_TIMEOUT_MINUTES,
    CONF_SLAB_TIME_CONSTANT,
    CONF_SOLAR_SENSOR,
    CONF_STAGGER_DELAY,
    CONF_TARGET_SENSOR,
    CONF_THERMAL_RUNAWAY_DERIVATIVE,
    CONF_USE_WEATHER_FORECAST_AVERAGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    CONF_WINDOW_DETECTION,
    CONF_WINDOW_DETECTION_SENSOR,
    CONF_WINDOW_DROP_THRESHOLD,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_TIMEOUT,
    DEAD_TIME_MAX_DEVIATION,
    DEAD_TIME_MIN_SAMPLES,
    DEFAULT_AUTO_CALIBRATE_DEAD_TIME,
    DEFAULT_AUTO_CALIBRATE_HEAT_LOSS,
    DEFAULT_AWAY_TEMP,
    DEFAULT_COMFORT_SAFETY_DEFICIT,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_DRY_RUN,
    DEFAULT_ECO_TEMP,
    DEFAULT_ENFORCE_DAILY_QUOTA,
    DEFAULT_HARD_OVERSHOOT_MARGIN,
    DEFAULT_HEAT_LOSS,
    DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
    DEFAULT_KALATA_PROCESS_NOISE,
    DEFAULT_MAX_CONTINUOUS_RUN_MINUTES,
    DEFAULT_MAX_CYCLES,
    DEFAULT_MAX_FLOOR_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_CYCLE,
    DEFAULT_MIN_FLOOR_TEMP,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP,
    DEFAULT_PEAK_MAX_RUN_DURATION,
    DEFAULT_POWER_WATTS,
    DEFAULT_RULE_B_MIN_THRESHOLD,
    DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES,
    DEFAULT_SLAB_TAU_HOURS,
    DEFAULT_STAGGER_DELAY,
    DEFAULT_TARGET_TEMP,
    DEFAULT_THERMAL_RUNAWAY_DERIVATIVE,
    DEFAULT_USE_WEATHER_FORECAST_AVERAGE,
    DEFAULT_WINDOW_DETECTION,
    DEFAULT_WINDOW_DROP_THRESHOLD,
    DEFAULT_WINDOW_TIMEOUT,
    DOMAIN,
    EMERGENCY_COMFORT_DEFICIT_OVERRIDE,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
    INTEGRATION_VERSION,
    MAX_RULE_B_THRESHOLD,
    MAX_UNSERVED_QUOTA_CARRYOVER_HOURS,
    MIN_HEAT_LOSS_RATIO,
    MIN_HEAT_LOSS_WK,
    POST_AIRING_MAX_DERIVATIVE,
    POST_AIRING_RECOVERY_MINUTES,
    SOLAR_MAX_CREDIT_RATIO,
    SOLAR_MORNING_CUTOFF_HOUR,
    WEATHER_FORECAST_CACHE_TTL_SECONDS,
    WIND_AMPLIFICATION_GAIN,
    WIND_MAX_AMPLIFICATION,
    WIND_SPEED_CALM_THRESHOLD,
    WINDOW_DERIVATIVE_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_SAVE_DELAY_SECONDS = 60.0

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_TARGET_SENSOR): cv.entity_id,
        vol.Required(CONF_OUTDOOR_SENSOR): cv.entity_id,
        vol.Optional(CONF_OFF_PEAK_SENSOR): cv.entity_id,
        vol.Optional(CONF_OFF_PEAK_START_ENTITY): cv.entity_id,
        vol.Optional(CONF_HEURES_CREUSES_SENSOR): cv.entity_id,
        vol.Optional(CONF_FLOOR_TEMP_SENSOR): cv.entity_id,
        vol.Optional(CONF_MAX_FLOOR_TEMP, default=DEFAULT_MAX_FLOOR_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_FLOOR_TEMP, default=DEFAULT_MIN_FLOOR_TEMP): vol.Coerce(float),
        vol.Optional(CONF_DRY_RUN, default=DEFAULT_DRY_RUN): cv.boolean,
        vol.Optional(CONF_OBSERVED_HEATER): cv.entity_id,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_HEAT_LOSS, default=DEFAULT_HEAT_LOSS): vol.Coerce(float),
        vol.Optional(CONF_POWER_WATTS, default=DEFAULT_POWER_WATTS): vol.Coerce(float),
        vol.Optional(CONF_SLAB_TIME_CONSTANT, default=DEFAULT_SLAB_TAU_HOURS): vol.Coerce(float),
        vol.Optional(CONF_DEAD_TIME, default=DEFAULT_DEAD_TIME_HOURS): vol.Coerce(float),
        vol.Optional(CONF_MIN_CYCLE_DURATION, default=DEFAULT_MIN_CYCLE): cv.time_period,
        vol.Optional(CONF_MIN_OFF_CYCLE_DURATION, default=DEFAULT_MIN_OFF): cv.time_period,
        vol.Optional(CONF_MAX_CYCLES_PER_DAY, default=DEFAULT_MAX_CYCLES): vol.Coerce(int),
        vol.Optional(CONF_ENFORCE_DAILY_QUOTA, default=DEFAULT_ENFORCE_DAILY_QUOTA): cv.boolean,
        vol.Optional(CONF_ENFORCE_DAILY_QUOTA_SENSOR): cv.entity_id,
        vol.Optional(CONF_WINDOW_DETECTION, default=DEFAULT_WINDOW_DETECTION): cv.boolean,
        vol.Optional(CONF_WINDOW_DETECTION_SENSOR): cv.entity_id,
        vol.Optional(CONF_WINDOW_SENSOR): cv.entity_id,
        vol.Optional(CONF_WINDOW_DROP_THRESHOLD, default=DEFAULT_WINDOW_DROP_THRESHOLD): vol.Coerce(float),
        vol.Optional(CONF_WINDOW_TIMEOUT, default=DEFAULT_WINDOW_TIMEOUT): cv.time_period,
        vol.Optional(CONF_ECO_TEMP, default=DEFAULT_ECO_TEMP): vol.Coerce(float),
        vol.Optional(CONF_AWAY_TEMP, default=DEFAULT_AWAY_TEMP): vol.Coerce(float),
        vol.Optional(CONF_COMFORT_TEMP): vol.Coerce(float),
        vol.Optional(CONF_STAGGER_DELAY, default=DEFAULT_STAGGER_DELAY): cv.time_period,
        vol.Optional(CONF_SOLAR_SENSOR): cv.entity_id,
        vol.Optional(CONF_WIND_SENSOR): cv.entity_id,
        vol.Optional(
            CONF_AUTO_CALIBRATE_HEAT_LOSS, default=DEFAULT_AUTO_CALIBRATE_HEAT_LOSS
        ): cv.boolean,
        vol.Optional(
            CONF_HEAT_LOSS_CONFIDENCE_SAMPLES, default=DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES
        ): cv.positive_int,
        vol.Optional(
            CONF_AUTO_CALIBRATE_DEAD_TIME, default=DEFAULT_AUTO_CALIBRATE_DEAD_TIME
        ): cv.boolean,
        vol.Optional(
            CONF_PEAK_MAX_RUN_DURATION, default=DEFAULT_PEAK_MAX_RUN_DURATION
        ): cv.time_period,
        vol.Optional(
            CONF_KALATA_PROCESS_NOISE, default=DEFAULT_KALATA_PROCESS_NOISE
        ): vol.Coerce(float),
        vol.Optional(
            CONF_OUTDOOR_PRECHARGE_MAX_TEMP, default=DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP
        ): vol.Coerce(float),
        vol.Optional(
            CONF_COMFORT_SAFETY_DEFICIT, default=DEFAULT_COMFORT_SAFETY_DEFICIT
        ): vol.Coerce(float),
        vol.Optional(
            CONF_RULE_B_MIN_THRESHOLD, default=DEFAULT_RULE_B_MIN_THRESHOLD
        ): vol.Coerce(float),
        vol.Optional(CONF_WEATHER_ENTITY): cv.entity_id,
        vol.Optional(
            CONF_USE_WEATHER_FORECAST_AVERAGE, default=DEFAULT_USE_WEATHER_FORECAST_AVERAGE
        ): cv.boolean,
        vol.Optional(
            CONF_SENSOR_STALE_TIMEOUT_MINUTES, default=DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES
        ): cv.positive_int,
        vol.Optional(
            CONF_MAX_CONTINUOUS_RUN_MINUTES, default=DEFAULT_MAX_CONTINUOUS_RUN_MINUTES
        ): cv.positive_int,
        vol.Optional(
            CONF_THERMAL_RUNAWAY_DERIVATIVE, default=DEFAULT_THERMAL_RUNAWAY_DERIVATIVE
        ): vol.Coerce(float),
        vol.Optional(
            CONF_HARD_OVERSHOOT_MARGIN, default=DEFAULT_HARD_OVERSHOOT_MARGIN
        ): vol.Coerce(float),
    }
)


def _parse_timedelta(
    val: Any, default: timedelta, numeric_unit: str = "seconds"
) -> timedelta:
    """Convert input duration (string, dict, numeric seconds/minutes, timedelta) to timedelta."""
    if val is None:
        return default
    if isinstance(val, timedelta):
        return val
    if isinstance(val, dict):
        try:
            return timedelta(
                **{
                    k: float(v)
                    for k, v in val.items()
                    if k in ("days", "hours", "minutes", "seconds", "milliseconds")
                }
            )
        except Exception:
            return default
    if isinstance(val, (int, float)):
        if numeric_unit == "minutes":
            return timedelta(minutes=float(val))
        return timedelta(seconds=float(val))
    if isinstance(val, str):
        if ":" not in val:
            try:
                num = float(val.strip())
                if numeric_unit == "minutes":
                    return timedelta(minutes=num)
                return timedelta(seconds=num)
            except Exception:
                pass
        try:
            return cv.time_period(val)
        except Exception:
            try:
                num = float(val)
                if numeric_unit == "minutes":
                    return timedelta(minutes=num)
                return timedelta(seconds=num)
            except Exception:
                pass
    return default


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the PWM Floor Heating Thermostat platform (via YAML)."""
    async_add_entities([PwmFloorHeatingThermostat(hass, config)])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PWM Floor Heating Thermostat platform (via UI Config Entry)."""
    config = {**entry.data, **entry.options}
    config[CONF_UNIQUE_ID] = entry.entry_id
    if CONF_NAME not in config:
        config[CONF_NAME] = entry.title
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entity = PwmFloorHeatingThermostat(hass, config, entry=entry, coordinator=coordinator)
    if coordinator and hasattr(coordinator, "register_thermostat"):
        coordinator.register_thermostat(entity)
    else:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entity
    async_add_entities([entity])


class PwmFloorHeatingThermostat(ClimateEntity, RestoreEntity):
    """Predictive thermodynamic underfloor heating thermostat entity."""

    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigType,
        entry: ConfigEntry | None = None,
        coordinator: Any | None = None,
    ) -> None:
        """Initialize the thermostat entity."""
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._name = config.get(CONF_NAME, DEFAULT_NAME)
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._heater_entity = config.get(CONF_HEATER)
        self._target_sensor = config[CONF_TARGET_SENSOR]
        self._outdoor_sensor = config[CONF_OUTDOOR_SENSOR]
        self._off_peak_sensor = config.get(CONF_OFF_PEAK_SENSOR) or config.get(CONF_HEURES_CREUSES_SENSOR)
        self._off_peak_start_entity = config.get(CONF_OFF_PEAK_START_ENTITY)
        self._dry_run = bool(config.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
        self._observed_heater = config.get(CONF_OBSERVED_HEATER)
        self._weather_entity = config.get(CONF_WEATHER_ENTITY)
        self._use_weather_forecast_average = bool(
            config.get(CONF_USE_WEATHER_FORECAST_AVERAGE, DEFAULT_USE_WEATHER_FORECAST_AVERAGE)
        )
        self._forecast_outdoor_temp_24h: float | None = None
        self._weather_forecast_cache_avg: float | None = None
        self._weather_forecast_cache_ts: datetime | None = None
        self._weather_outage_fallback_active: bool = False
        self._unserved_quota_carryover_hours: float = 0.0
        self._prev_day_energy_quota_kwh: float | None = None

        # Floor slab / hydronic loop sensor
        self._floor_temp_sensor = config.get(CONF_FLOOR_TEMP_SENSOR)
        self._max_floor_temp = float(config.get(CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP))
        self._min_floor_temp = float(config.get(CONF_MIN_FLOOR_TEMP, DEFAULT_MIN_FLOOR_TEMP))
        self._floor_temp: float | None = None

        # Thermodynamic model parameters
        self._heat_loss = float(config.get(CONF_HEAT_LOSS, DEFAULT_HEAT_LOSS))
        self._power_watts = float(config.get(CONF_POWER_WATTS, DEFAULT_POWER_WATTS))
        self._slab_tau = float(config.get(CONF_SLAB_TIME_CONSTANT, DEFAULT_SLAB_TAU_HOURS))
        self._dead_time = float(config.get(CONF_DEAD_TIME, DEFAULT_DEAD_TIME_HOURS))

        # Danfoss compressor safeties
        self._min_cycle_duration = _parse_timedelta(
            config.get(CONF_MIN_CYCLE_DURATION), DEFAULT_MIN_CYCLE, numeric_unit="minutes"
        )
        self._min_off_duration = _parse_timedelta(
            config.get(CONF_MIN_OFF_CYCLE_DURATION), DEFAULT_MIN_OFF, numeric_unit="minutes"
        )
        self._max_cycles = int(config.get(CONF_MAX_CYCLES_PER_DAY, DEFAULT_MAX_CYCLES))
        self._peak_max_run_duration = _parse_timedelta(
            config.get(CONF_PEAK_MAX_RUN_DURATION),
            DEFAULT_PEAK_MAX_RUN_DURATION,
            numeric_unit="minutes",
        )

        # Daily thermal energy quota cap (Peak-hours anti-waste)
        self._enforce_daily_quota = bool(config.get(CONF_ENFORCE_DAILY_QUOTA, DEFAULT_ENFORCE_DAILY_QUOTA))
        self._enforce_daily_quota_sensor = config.get(CONF_ENFORCE_DAILY_QUOTA_SENSOR)
        self._quota_blocked = False

        # Open window / ventilation detection
        self._window_detection_enabled = bool(config.get(CONF_WINDOW_DETECTION, DEFAULT_WINDOW_DETECTION))
        self._window_detection_sensor = config.get(CONF_WINDOW_DETECTION_SENSOR)
        self._window_sensor = config.get(CONF_WINDOW_SENSOR)
        self._window_drop_threshold = float(config.get(CONF_WINDOW_DROP_THRESHOLD, DEFAULT_WINDOW_DROP_THRESHOLD))
        self._window_timeout = _parse_timedelta(config.get(CONF_WINDOW_TIMEOUT), DEFAULT_WINDOW_TIMEOUT)
        self._window_open = False
        self._window_open_time: datetime | None = None

        # Continuous passive calibration of heat loss H (Mode A)
        self._heat_loss_measured_wk: float | None = None
        self._heat_loss_samples_count: int = 0

        # Mode B soft self-adaptation of heat loss H
        self._auto_calibrate_heat_loss = bool(
            config.get(CONF_AUTO_CALIBRATE_HEAT_LOSS, DEFAULT_AUTO_CALIBRATE_HEAT_LOSS)
        )
        self._heat_loss_confidence_samples: int = int(
            config.get(
                CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
                DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
            )
        )
        self._effective_heat_loss: float = self._heat_loss

        # Daytime solar irradiance sensor
        self._solar_sensor = config.get(CONF_SOLAR_SENSOR)
        self._solar_credit_kwh: float = 0.0

        # Wind convective loss amplification
        self._wind_sensor = config.get(CONF_WIND_SENSOR)
        self._wind_speed: float | None = None
        self._wind_factor: float = 1.0

        # Dead time theta calibration & identification
        self._auto_calibrate_dead_time = bool(
            config.get(CONF_AUTO_CALIBRATE_DEAD_TIME, DEFAULT_AUTO_CALIBRATE_DEAD_TIME)
        )
        self._effective_dead_time: float = self._dead_time
        self._dead_time_measured_hours: float | None = None
        self._dead_time_samples_count: int = 0
        self._heating_start_derivative: float | None = None

        # Slow drift ambient supervisor
        self._ambient_trim_ratio: float = 1.0

        # Temperature presets
        self._eco_temp = float(config.get(CONF_ECO_TEMP, DEFAULT_ECO_TEMP))
        self._away_temp = float(config.get(CONF_AWAY_TEMP, DEFAULT_AWAY_TEMP))
        self._comfort_temp = float(config.get(CONF_COMFORT_TEMP, DEFAULT_TARGET_TEMP))
        self._preset_mode: str = PRESET_COMFORT

        # Multi-Zone coordination & inrush staggering
        self._stagger_delay = _parse_timedelta(config.get(CONF_STAGGER_DELAY), DEFAULT_STAGGER_DELAY)
        self._demand_start_time: datetime | None = None

        # Live state
        self._cur_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._target_temp: float = DEFAULT_TARGET_TEMP
        self._hvac_mode = HVACMode.HEAT
        self._hvac_action = HVACAction.IDLE

        # Finite State Machine (FSM)
        self._fsm_state = FSM_IDLE
        self._last_state_change = dt_util.utcnow()
        self._cycle_start_time: datetime | None = None
        self._cycles_today = 0
        self._hours_run_today = 0.0
        self._last_day_reset = dt_util.now().date()

        # Predictive engine & continuous-discrete state observer (Kalman 1D alpha-beta)
        self._kalata_process_noise: float = float(
            config.get(CONF_KALATA_PROCESS_NOISE, DEFAULT_KALATA_PROCESS_NOISE)
        )
        self._outdoor_precharge_max_temp: float = float(
            config.get(CONF_OUTDOOR_PRECHARGE_MAX_TEMP, DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP)
        )
        self._comfort_safety_deficit: float = float(
            config.get(CONF_COMFORT_SAFETY_DEFICIT, DEFAULT_COMFORT_SAFETY_DEFICIT)
        )
        self._rule_b_min_threshold: float = float(
            config.get(CONF_RULE_B_MIN_THRESHOLD, DEFAULT_RULE_B_MIN_THRESHOLD)
        )
        self._current_rule_b_threshold: float = self._rule_b_min_threshold
        self._temp_history: list[tuple[datetime, float]] = []
        self._filtered_temp: float | None = None
        self._temp_derivative: float = 0.0
        self._derivative_smooth: float = 0.0
        self._temp_projected: float | None = None
        self._observer_last_update: datetime | None = None
        self._projection_history: list[tuple[datetime, float]] = []
        self._model_error: float | None = None
        self._model_error_rms: float | None = None
        self._model_error_history: list[tuple[datetime, float]] = []
        self._was_window_open: bool = False
        self._window_recovery_until: datetime | None = None

        # Telemetry & simulation
        self._simulated_heater_state = False
        self._decision_reason = "Model initializing"
        self._energy_needed_kwh = 0.0
        self._hours_needed_24h = 0.0

        # Stale sensor watchdog & hardware safety guards
        self._cur_temp_ts: datetime | None = None
        self._outdoor_temp_ts: datetime | None = None
        self._outdoor_sensor_stale: bool = False
        self._last_heat_loss_sample_ts: datetime | None = None
        self._sensor_stale: bool = False
        self._sensor_stale_timeout_minutes: int = int(
            config.get(CONF_SENSOR_STALE_TIMEOUT_MINUTES, DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES)
        )
        self._max_continuous_run_minutes: int = int(
            config.get(CONF_MAX_CONTINUOUS_RUN_MINUTES, DEFAULT_MAX_CONTINUOUS_RUN_MINUTES)
        )
        self._thermal_runaway_derivative: float = float(
            config.get(CONF_THERMAL_RUNAWAY_DERIVATIVE, DEFAULT_THERMAL_RUNAWAY_DERIVATIVE)
        )
        self._thermal_runaway_start_time: datetime | None = None
        self._hard_overshoot_margin: float = float(
            config.get(CONF_HARD_OVERSHOOT_MARGIN, DEFAULT_HARD_OVERSHOOT_MARGIN)
        )

        # Next transition estimation (v0.3.1)
        self._next_transition_time: datetime | None = None
        self._next_transition_type: str = "none"
        self._next_transition_reason: str = "Model initializing"
        self._earliest_transition_time: datetime | None = None
        self._state_store: Store[dict[str, Any]] | None = None

    def _get_state_store(self) -> Store[dict[str, Any]]:
        """Return the persistent JSON store for this thermostat instance."""
        if self._state_store is None:
            raw_id = self._unique_id or self._name.lower().replace(" ", "_")
            safe_id = "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in raw_id)
            self._state_store = Store(self.hass, STORAGE_VERSION, f"{DOMAIN}.{safe_id}")
        return self._state_store

    def _build_persisted_state(self) -> dict[str, Any]:
        """Serialize internal histories, FSM lock state, and observer state for persistent storage."""
        return {
            "fsm_state": self._fsm_state,
            "last_state_change": self._last_state_change.isoformat() if self._last_state_change else None,
            "cycle_start_time": self._cycle_start_time.isoformat() if self._cycle_start_time else None,
            "cycles_today": self._cycles_today,
            "hours_run_today": round(self._hours_run_today, 4),
            "counters_date": str(self._last_day_reset),
            "projection_history": [[t.isoformat(), v] for t, v in self._projection_history],
            "model_error_history": [[t.isoformat(), v] for t, v in self._model_error_history],
            "filtered_temp": self._filtered_temp,
            "temp_derivative": self._temp_derivative,
            "derivative_smooth": self._derivative_smooth,
            "observer_last_update": self._observer_last_update.isoformat() if self._observer_last_update else None,
            "cur_temp_ts": self._cur_temp_ts.isoformat() if self._cur_temp_ts else None,
            "outdoor_temp_ts": self._outdoor_temp_ts.isoformat() if self._outdoor_temp_ts else None,
            "last_heat_loss_sample_ts": (
                self._last_heat_loss_sample_ts.isoformat() if self._last_heat_loss_sample_ts else None
            ),
            "heat_loss_samples_count": self._heat_loss_samples_count,
            "heat_loss_measured_wk": self._heat_loss_measured_wk,
            "dead_time_samples_count": self._dead_time_samples_count,
            "dead_time_measured_hours": self._dead_time_measured_hours,
        }

    def _schedule_state_save(self) -> None:
        """Schedule a debounced save of internal model state to disk."""
        if self.hass is not None:
            self._get_state_store().async_delay_save(self._build_persisted_state, STORAGE_SAVE_DELAY_SECONDS)

    async def _async_save_state_now(self, _event: Any = None) -> None:
        """Immediately flush internal model state to persistent storage."""
        if self.hass is not None:
            await self._get_state_store().async_save(self._build_persisted_state())

    @staticmethod
    def _parse_iso_history(raw_items: Any, cutoff: datetime) -> list[tuple[datetime, float]]:
        """Parse and prune timestamped float history entries from JSON storage."""
        parsed: list[tuple[datetime, float]] = []
        if not isinstance(raw_items, list):
            return parsed
        for item in raw_items:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                ts = datetime.fromisoformat(str(item[0]))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                val = float(item[1])
                if ts >= cutoff:
                    parsed.append((ts, val))
            except (ValueError, TypeError):
                continue
        return parsed

    async def _async_restore_persisted_store(self) -> None:
        """Restore internal histories and observer state from Home Assistant storage."""
        if self.hass is None:
            return
        data = await self._get_state_store().async_load()
        if not isinstance(data, dict):
            return

        now = dt_util.utcnow()
        proj_cutoff = now - timedelta(hours=max(4.0, (self._effective_dead_time * 2.0) + 1.0))
        rms_cutoff = now - timedelta(hours=24)

        proj_hist = self._parse_iso_history(data.get("projection_history"), proj_cutoff)
        if proj_hist:
            self._projection_history = proj_hist

        err_hist = self._parse_iso_history(data.get("model_error_history"), rms_cutoff)
        if err_hist:
            self._model_error_history = err_hist
            sum_sq = sum(err ** 2 for _, err in self._model_error_history)
            self._model_error_rms = round(math.sqrt(sum_sq / len(self._model_error_history)), 2)

        for attr_name, key, caster in (
            ("_filtered_temp", "filtered_temp", float),
            ("_temp_derivative", "temp_derivative", float),
            ("_derivative_smooth", "derivative_smooth", float),
            ("_heat_loss_samples_count", "heat_loss_samples_count", int),
            ("_heat_loss_measured_wk", "heat_loss_measured_wk", float),
            ("_dead_time_samples_count", "dead_time_samples_count", int),
            ("_dead_time_measured_hours", "dead_time_measured_hours", float),
        ):
            val = data.get(key)
            if val is not None:
                try:
                    setattr(self, attr_name, caster(val))
                except (ValueError, TypeError):
                    pass

        for attr_name, key in (
            ("_observer_last_update", "observer_last_update"),
            ("_last_state_change", "last_state_change"),
            ("_cycle_start_time", "cycle_start_time"),
            ("_cur_temp_ts", "cur_temp_ts"),
            ("_outdoor_temp_ts", "outdoor_temp_ts"),
            ("_last_heat_loss_sample_ts", "last_heat_loss_sample_ts"),
        ):
            raw_ts = data.get(key)
            if raw_ts is not None:
                try:
                    parsed_ts = datetime.fromisoformat(str(raw_ts))
                    if parsed_ts.tzinfo is None:
                        parsed_ts = parsed_ts.replace(tzinfo=UTC)
                    setattr(self, attr_name, parsed_ts)
                except (ValueError, TypeError):
                    pass

        today_str = str(dt_util.now().date())
        if data.get("counters_date") == today_str:
            if data.get("cycles_today") is not None:
                try:
                    self._cycles_today = int(data["cycles_today"])
                except (ValueError, TypeError):
                    pass
            if data.get("hours_run_today") is not None:
                try:
                    self._hours_run_today = float(data["hours_run_today"])
                except (ValueError, TypeError):
                    pass

        stored_fsm = data.get("fsm_state")
        if stored_fsm in [FSM_IDLE, FSM_WAITING_MIN_OFF, FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            self._reconcile_restored_fsm(stored_fsm, now)

    def _reconcile_restored_fsm(self, restored_fsm: str, now: datetime) -> None:
        """Safely restore FSM state across restarts/reloads while preserving Danfoss 30-min runtime lock."""
        if restored_fsm in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            st_heater = self.hass.states.get(self._heater_entity) if (self.hass and self._heater_entity) else None
            heater_state = getattr(st_heater, "state", None) if st_heater is not None else None
            ref_start = self._cycle_start_time or self._last_state_change
            within_min_lock = (
                self._cycle_start_time is not None
                and (now - self._cycle_start_time) < self._min_cycle_duration
            )

            if heater_state == "on" or (within_min_lock and heater_state != "off"):
                start_ts = ref_start or now
                self._cycle_start_time = start_ts
                self._last_state_change = start_ts
                if (now - start_ts) < self._min_cycle_duration:
                    self._fsm_state = FSM_RUNNING_MIN_LOCK
                else:
                    self._fsm_state = FSM_RUNNING_NORMAL
                self._hvac_action = HVACAction.HEATING
                self._simulated_heater_state = True
                _LOGGER.info(
                    "Thermostat %s restored active compressor cycle in %s (started at %s) to preserve Danfoss oil return.",
                    self.name,
                    self._fsm_state,
                    start_ts.isoformat(),
                )
            else:
                self._fsm_state = FSM_WAITING_MIN_OFF
                self._last_state_change = now
                self._cycle_start_time = None
                self._hvac_action = HVACAction.IDLE
                self._simulated_heater_state = False
                _LOGGER.warning(
                    "Thermostat %s restored after reboot with heater OFF. "
                    "Safely transitioned to WAITING_MIN_OFF to enforce Danfoss pressure equalization.",
                    self.name,
                )
        else:
            self._fsm_state = restored_fsm

    async def async_added_to_hass(self) -> None:
        """Register event listeners and restore previous state."""
        await super().async_added_to_hass()

        # Restore previous state
        if old_state := await self.async_get_last_state():
            if old_target := old_state.attributes.get(ATTR_TEMPERATURE):
                try:
                    self._target_temp = float(old_target)
                except ValueError:
                    pass
            if old_state.state in [HVACMode.HEAT, HVACMode.OFF]:
                self._hvac_mode = HVACMode(old_state.state)

            old_attrs = old_state.attributes
            restored_fsm = old_attrs.get("fsm_state", FSM_IDLE)
            self._reconcile_restored_fsm(restored_fsm, dt_util.utcnow())

            saved_date = old_attrs.get(ATTR_COUNTERS_DATE)
            today_str = str(dt_util.now().date())
            if saved_date == today_str:
                self._cycles_today = old_attrs.get("compressor_cycles_today", 0)
                self._hours_run_today = old_attrs.get("heating_hours_done_today", 0.0)
            else:
                self._cycles_today = 0
                self._hours_run_today = 0.0
            if "temp_derivative_hourly" in old_attrs and old_attrs["temp_derivative_hourly"] is not None:
                try:
                    self._temp_derivative = float(old_attrs["temp_derivative_hourly"])
                    self._derivative_smooth = self._temp_derivative
                except (ValueError, TypeError):
                    pass
            if "temp_projected_ahead" in old_attrs and old_attrs["temp_projected_ahead"] is not None:
                try:
                    self._temp_projected = float(old_attrs["temp_projected_ahead"])
                except (ValueError, TypeError):
                    pass
            if "heat_loss_measured_wk" in old_attrs and old_attrs["heat_loss_measured_wk"] is not None:
                try:
                    self._heat_loss_measured_wk = float(old_attrs["heat_loss_measured_wk"])
                except (ValueError, TypeError):
                    pass
            if "heat_loss_samples_count" in old_attrs and old_attrs["heat_loss_samples_count"] is not None:
                try:
                    self._heat_loss_samples_count = int(old_attrs["heat_loss_samples_count"])
                except (ValueError, TypeError):
                    pass
            if "dead_time_measured_hours" in old_attrs and old_attrs["dead_time_measured_hours"] is not None:
                try:
                    self._dead_time_measured_hours = float(old_attrs["dead_time_measured_hours"])
                except (ValueError, TypeError):
                    pass
            if "dead_time_samples_count" in old_attrs and old_attrs["dead_time_samples_count"] is not None:
                try:
                    self._dead_time_samples_count = int(old_attrs["dead_time_samples_count"])
                except (ValueError, TypeError):
                    pass
            if "model_error" in old_attrs and old_attrs["model_error"] is not None:
                try:
                    self._model_error = float(old_attrs["model_error"])
                except (ValueError, TypeError):
                    pass
            if "model_error_rms" in old_attrs and old_attrs["model_error_rms"] is not None:
                try:
                    self._model_error_rms = float(old_attrs["model_error_rms"])
                except (ValueError, TypeError):
                    pass
            if old_preset := old_attrs.get("preset_mode"):
                if old_preset in [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY, PRESET_NONE]:
                    self._preset_mode = old_preset
            if old_comfort := old_attrs.get("comfort_temp"):
                try:
                    self._comfort_temp = float(old_comfort)
                except (ValueError, TypeError):
                    pass
            if "unserved_quota_carryover_hours" in old_attrs and old_attrs["unserved_quota_carryover_hours"] is not None:
                try:
                    self._unserved_quota_carryover_hours = float(old_attrs["unserved_quota_carryover_hours"])
                except (ValueError, TypeError):
                    pass
            if "energy_quota_24h_kwh" in old_attrs and old_attrs["energy_quota_24h_kwh"] is not None:
                try:
                    self._prev_day_energy_quota_kwh = float(old_attrs["energy_quota_24h_kwh"])
                except (ValueError, TypeError):
                    pass

        # Restore internal histories and observer state from self-contained HA Store
        await self._async_restore_persisted_store()

        # Flush internal state on Home Assistant shutdown
        self.async_on_remove(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_save_state_now)
        )

        # Track state changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._target_sensor], self._async_target_sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._outdoor_sensor], self._async_outdoor_sensor_changed
            )
        )
        if self._off_peak_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._off_peak_sensor], self._async_off_peak_sensor_changed
                )
            )

        if self._floor_temp_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._floor_temp_sensor], self._async_floor_temp_changed
                )
            )

        if self._observed_heater:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._observed_heater], self._async_observed_heater_changed
                )
            )

        if self._enforce_daily_quota_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._enforce_daily_quota_sensor], self._async_quota_sensor_changed
                )
            )

        if self._window_detection_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._window_detection_sensor], self._async_window_detection_sensor_changed
                )
            )

        if self._window_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._window_sensor], self._async_window_sensor_changed
                )
            )

        if self._solar_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._solar_sensor], self._async_solar_sensor_changed
                )
            )

        if self._wind_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._wind_sensor], self._async_wind_sensor_changed
                )
            )

        if self._weather_entity:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._weather_entity], self._async_weather_entity_changed
                )
            )

        if self._heater_entity and not self._dry_run:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._heater_entity], self._async_heater_entity_changed
                )
            )

        # Periodic control loop (every minute)
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_control_heating, timedelta(minutes=1)
            )
        )

        @callback
        def _async_startup(*_) -> None:
            """Initial sensor synchronization once Home Assistant is fully started."""
            self._async_read_sensors()
            self.hass.async_create_task(self._async_control_heating())

        if self.hass.is_running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_startup)

    async def async_will_remove_from_hass(self) -> None:
        """Persist internal model state before entity removal or reload."""
        await self._async_save_state_now()
        await super().async_will_remove_from_hass()

    @property
    def unique_id(self) -> str | None:
        """Return unique ID of the entity."""
        return self._unique_id

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device registry info for Home Assistant."""
        if self._unique_id:
            return DeviceInfo(
                identifiers={(DOMAIN, self._unique_id)},
                name=self._name,
                manufacturer="Nitrogene",
                model="PWM Thermodynamic Underfloor Thermostat",
                sw_version=INTEGRATION_VERSION,
            )
        return None

    @property
    def name(self) -> str:
        """Return name of the entity."""
        return self._name

    @callback
    def async_write_ha_state(self) -> None:
        """Write state and dispatch update signal to companion sensors."""
        super().async_write_ha_state()
        if self._coordinator:
            self._coordinator.async_notify_update()

    @property
    def current_temperature(self) -> float | None:
        """Return measured room ambient temperature."""
        return self._cur_temp

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return self._target_temp

    @property
    def preset_mode(self) -> str | None:
        """Return active preset mode."""
        return self._preset_mode

    @property
    def preset_modes(self) -> list[str]:
        """Return available preset modes."""
        return [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch active preset mode (Comfort, Eco, Away)."""
        if preset_mode == self._preset_mode:
            return

        if preset_mode == PRESET_ECO:
            self._comfort_temp = self._target_temp
            self._target_temp = self._eco_temp
            self._preset_mode = PRESET_ECO
        elif preset_mode == PRESET_AWAY:
            self._comfort_temp = self._target_temp
            self._target_temp = self._away_temp
            self._preset_mode = PRESET_AWAY
        elif preset_mode in [PRESET_COMFORT, PRESET_NONE]:
            self._target_temp = self._comfort_temp
            self._preset_mode = PRESET_COMFORT
        else:
            _LOGGER.warning("Unrecognized preset mode: %s", preset_mode)
            return

        await self._async_control_heating()
        self.async_write_ha_state()

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return current thermodynamic action."""
        return self._hvac_action

    @property
    def extra_state_attributes(self) -> dict:
        """Return telemetry and diagnostic state attributes."""
        now = dt_util.utcnow()
        elapsed = (now - self._last_state_change).total_seconds()
        min_on_rem = 0
        min_off_rem = 0
        if self._fsm_state == FSM_RUNNING_MIN_LOCK:
            min_on_rem = max(0, int(self._min_cycle_duration.total_seconds() - elapsed))
        elif self._fsm_state == FSM_WAITING_MIN_OFF:
            min_off_rem = max(0, int(self._min_off_duration.total_seconds() - elapsed))

        off_peak_active = False
        if self._off_peak_sensor:
            st = self.hass.states.get(self._off_peak_sensor)
            off_peak_active = st is not None and st.state == "on"

        quota_enforcement_active = self._enforce_daily_quota
        if self._enforce_daily_quota_sensor:
            st_q = self.hass.states.get(self._enforce_daily_quota_sensor)
            if st_q and st_q.state not in ["unknown", "unavailable"]:
                quota_enforcement_active = st_q.state == "on"

        window_detection_active = self._window_detection_enabled
        if self._window_detection_sensor:
            st_w = self.hass.states.get(self._window_detection_sensor)
            if st_w and st_w.state not in ["unknown", "unavailable"]:
                window_detection_active = st_w.state == "on"

        run_hours = self._total_heating_hours_today

        return {
            "dry_run": self._dry_run,
            "simulated_heater_state": self._simulated_heater_state,
            "decision_reason": self._decision_reason,
            "observed_heater": self._observed_heater,
            "fsm_state": self._fsm_state,
            "outdoor_temperature": self._outdoor_temp,
            "floor_temperature": self._floor_temp,
            "max_floor_temperature": self._max_floor_temp if self._floor_temp_sensor else None,
            "min_floor_temperature": self._min_floor_temp if self._floor_temp_sensor else None,
            "dead_time_hours": self._dead_time,
            ATTR_EFFECTIVE_DEAD_TIME_HOURS: self._effective_dead_time,
            ATTR_DEAD_TIME_MEASURED_HOURS: self._dead_time_measured_hours,
            ATTR_DEAD_TIME_SAMPLES_COUNT: self._dead_time_samples_count,
            "auto_calibrate_dead_time": self._auto_calibrate_dead_time,
            ATTR_KALATA_PROCESS_NOISE: self._kalata_process_noise,
            "outdoor_precharge_max_temp": self._outdoor_precharge_max_temp,
            "comfort_safety_deficit": self._comfort_safety_deficit,
            "temp_derivative_hourly": round(self._derivative_smooth, 3),
            "temp_projected_ahead": (
                round(self._temp_projected, 2) if self._temp_projected is not None else None
            ),
            "model_error": self._model_error,
            ATTR_MODEL_ERROR_RMS: self._model_error_rms,
            ATTR_RULE_B_THRESHOLD: self._current_rule_b_threshold,
            "rule_b_min_threshold": self._rule_b_min_threshold,
            "heat_loss_factor_wk": self._heat_loss,
            ATTR_EFFECTIVE_HEAT_LOSS_WK: self._effective_heat_loss,
            "auto_calibrate_heat_loss": self._auto_calibrate_heat_loss,
            ATTR_HEAT_LOSS_CONFIDENCE_SAMPLES: self._heat_loss_confidence_samples,
            ATTR_WIND_FACTOR: self._wind_factor,
            ATTR_WIND_SPEED: self._wind_speed,
            "compressor_power_watts": self._power_watts,
            "energy_quota_24h_kwh": round(self._energy_needed_kwh, 2),
            ATTR_AMBIENT_TRIM_RATIO: self._ambient_trim_ratio,
            ATTR_SOLAR_CREDIT_KWH: self._solar_credit_kwh,
            "heating_hours_needed_24h": round(self._hours_needed_24h, 2),
            "heating_hours_done_today": round(run_hours, 2),
            "heating_hours_remaining_24h": round(max(0.0, self._hours_needed_24h - run_hours), 2),
            "daily_quota_enforced": quota_enforcement_active,
            "daily_quota_blocked": self._quota_blocked,
            "window_detection_active": window_detection_active,
            "window_open_detected": self._window_open,
            "heat_loss_measured_wk": self._heat_loss_measured_wk,
            "heat_loss_samples_count": self._heat_loss_samples_count,
            "comfort_temp": self._comfort_temp,
            "eco_temp": self._eco_temp,
            "away_temp": self._away_temp,
            "stagger_delay_sec": int(self._stagger_delay.total_seconds()),
            "peak_max_run_duration_min": int(self._peak_max_run_duration.total_seconds() // 60),
            "compressor_cycles_today": self._cycles_today,
            "max_cycles_budget": self._max_cycles,
            ATTR_COUNTERS_DATE: str(dt_util.now().date()),
            "min_cycle_lock_remaining_sec": min_on_rem,
            "min_off_lock_remaining_sec": min_off_rem,
            "off_peak_active": off_peak_active,
            "heures_creuses_active": off_peak_active,
            CONF_WEATHER_ENTITY: self._weather_entity,
            CONF_USE_WEATHER_FORECAST_AVERAGE: self._use_weather_forecast_average,
            ATTR_FORECAST_OUTDOOR_TEMP_24H: (
                round(self._forecast_outdoor_temp_24h, 2)
                if self._forecast_outdoor_temp_24h is not None
                else None
            ),
            ATTR_WEATHER_OUTAGE_FALLBACK_ACTIVE: self._weather_outage_fallback_active,
            ATTR_UNSERVED_QUOTA_CARRYOVER_HOURS: round(self._unserved_quota_carryover_hours, 2),
            ATTR_SENSOR_STALE: self._sensor_stale,
            CONF_SENSOR_STALE_TIMEOUT_MINUTES: self._sensor_stale_timeout_minutes,
            CONF_MAX_CONTINUOUS_RUN_MINUTES: self._max_continuous_run_minutes,
            CONF_THERMAL_RUNAWAY_DERIVATIVE: self._thermal_runaway_derivative,
            CONF_HARD_OVERSHOOT_MARGIN: self._hard_overshoot_margin,
            ATTR_NEXT_TRANSITION_TIME: (
                self._next_transition_time.isoformat() if self._next_transition_time else None
            ),
            ATTR_NEXT_TRANSITION_TYPE: self._next_transition_type,
            ATTR_NEXT_TRANSITION_REASON: self._next_transition_reason,
            ATTR_EARLIEST_TRANSITION_TIME: (
                self._earliest_transition_time.isoformat() if self._earliest_transition_time else None
            ),
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Adjust target temperature setpoint."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._target_temp = float(temp)
            if self._preset_mode in [PRESET_COMFORT, PRESET_NONE]:
                self._comfort_temp = self._target_temp
            await self._async_control_heating()
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change HVAC mode (Heat / Off)."""
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            await self._async_stop_heating_safe()
        else:
            await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    def _async_target_sensor_changed(self, event) -> None:
        """Handle ambient temperature sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ["unknown", "unavailable"]:
            return
        try:
            self._cur_temp = float(new_state.state)
            now_utc = dt_util.utcnow()
            lu = getattr(new_state, "last_updated", None)
            self._cur_temp_ts = lu if isinstance(lu, datetime) else now_utc
            self._update_trajectory_projection(now_utc)
            self._check_window_open_state(now_utc)
            self._schedule_state_save()
            self.async_write_ha_state()
        except (ValueError, TypeError):
            pass

    @callback
    def _async_outdoor_sensor_changed(self, event) -> None:
        """Handle outdoor temperature / weather forecast sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or getattr(new_state, "state", None) in ["unknown", "unavailable"]:
            return
        try:
            self._outdoor_temp = float(new_state.state)
            lu = getattr(new_state, "last_updated", None)
            self._outdoor_temp_ts = lu if isinstance(lu, datetime) else dt_util.utcnow()
            self._schedule_state_save()
            self.async_write_ha_state()
        except (ValueError, TypeError):
            pass

    @callback
    def _async_off_peak_sensor_changed(self, event) -> None:
        """Handle Off-Peak tariff sensor state change."""
        self.async_write_ha_state()

    @callback
    def _async_floor_temp_changed(self, event) -> None:
        """Handle floor slab / hydronic loop sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ["unknown", "unavailable"]:
            return
        try:
            self._floor_temp = float(new_state.state)
            self.async_write_ha_state()
        except ValueError:
            pass

    @callback
    def _async_observed_heater_changed(self, event) -> None:
        """Passive listener for observed heater state in Shadow / Digital Twin Mode."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "[SHADOW OBSERVER] Observed heater %s changed to %s",
                self._observed_heater,
                new_state.state,
            )

    @callback
    def _async_heater_entity_changed(self, event) -> None:
        """Handle physical heater switch state change for active reconciliation."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == "on" and self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF]:
            _LOGGER.warning(
                "Thermostat %s: heater entity %s turned ON unexpectedly while FSM state is %s. Scheduling reconciliation cutoff.",
                self._name,
                self._heater_entity,
                self._fsm_state,
            )
            self.hass.async_create_task(self._async_stop_heating_safe())
        elif new_state.state == "off" and self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            if self._reconcile_rejected_or_stopped_heater(dt_util.utcnow(), force=True):
                self.async_write_ha_state()

    def _reconcile_rejected_or_stopped_heater(self, now: datetime, force: bool = False) -> bool:
        """Reconcile FSM if the physical heater rejected a turn_on command or turned off externally."""
        if self._dry_run or not self._heater_entity:
            return False
        if self._fsm_state not in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            return False

        if not force:
            st = self.hass.states.get(self._heater_entity) if self.hass else None
            if st is None or getattr(st, "state", None) != "off":
                return False

        ref_start = self._cycle_start_time or self._last_state_change
        elapsed_run = (now - ref_start).total_seconds()
        if not force and elapsed_run < 5.0:
            return False

        if elapsed_run < 300.0:
            # Command rejected by hardware local guard or manual override before 5-min minimum run
            if self._cycles_today > 0:
                self._cycles_today -= 1
            self._cycle_start_time = None
            self._fsm_state = FSM_IDLE
            self._hvac_action = HVACAction.IDLE
            self._simulated_heater_state = False
            self._schedule_state_save()
            _LOGGER.warning(
                "Actuator confirmation failed for %s: %s is OFF %.0fs after turn_on (hardware guard or manual override). "
                "Reconciled FSM back to IDLE without counting cycle.",
                self._name,
                self._heater_entity,
                elapsed_run,
            )
        else:
            # Heater ran and was turned off externally: record actual runtime and enforce 15-min rest
            if self._cycle_start_time is not None:
                self._hours_run_today += elapsed_run / 3600.0
                self._cycle_start_time = None
            self._fsm_state = FSM_WAITING_MIN_OFF
            self._last_state_change = now
            self._hvac_action = HVACAction.IDLE
            self._simulated_heater_state = False
            self._schedule_state_save()
            _LOGGER.warning(
                "Heater %s for %s turned OFF externally after %.1f min. Transitioned FSM to WAITING_MIN_OFF.",
                self._heater_entity,
                self._name,
                elapsed_run / 60.0,
            )
        return True

    @callback
    def _async_quota_sensor_changed(self, event) -> None:
        """Immediate reaction to daily quota enforcement switch toggle."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "Daily quota enforcement switch %s toggled to %s",
                self._enforce_daily_quota_sensor,
                new_state.state,
            )
            self.hass.async_create_task(self._async_control_heating())

    @callback
    def _async_window_detection_sensor_changed(self, event) -> None:
        """Immediate reaction to window detection master switch toggle."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "Window detection switch %s toggled to %s",
                self._window_detection_sensor,
                new_state.state,
            )
            if new_state.state != "on":
                self._window_open = False
                self._window_open_time = None
            self.hass.async_create_task(self._async_control_heating())

    @callback
    def _async_window_sensor_changed(self, event) -> None:
        """Immediate reaction to physical contact window sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            self._window_open = new_state.state == "on"
            self._window_open_time = dt_util.utcnow() if self._window_open else None
            _LOGGER.info(
                "Physical window sensor %s : %s",
                self._window_sensor,
                "OPEN" if self._window_open else "CLOSED",
            )
            self.hass.async_create_task(self._async_control_heating())

    @callback
    def _async_solar_sensor_changed(self, event: Any) -> None:
        """Handle solar irradiance sensor state change."""
        self.async_write_ha_state()

    @callback
    def _async_wind_sensor_changed(self, event: Any) -> None:
        """Handle wind speed sensor state change."""
        self.async_write_ha_state()

    @callback
    def _async_weather_entity_changed(self, event: Any) -> None:
        """Handle weather entity state change, invalidate forecast cache, and trigger regulation."""
        self._weather_forecast_cache_ts = None
        self.hass.async_create_task(self._async_control_heating())

    async def _async_get_weather_forecast_24h_average(self) -> float | None:
        """Fetch rolling 24-hour hourly forecast average from weather service (with 15-min TTL cache)."""
        if not self._weather_entity:
            return None
        st_weather = self.hass.states.get(self._weather_entity)
        if not st_weather or st_weather.state in ["unknown", "unavailable"]:
            self._weather_forecast_cache_ts = None
            _LOGGER.warning(
                "Weather entity %s is %s; cannot compute 24h forecast average",
                self._weather_entity,
                st_weather.state if st_weather else "missing",
            )
            return None

        now_utc = dt_util.utcnow()
        if (
            self._weather_forecast_cache_ts is not None
            and self._weather_forecast_cache_avg is not None
            and (now_utc - self._weather_forecast_cache_ts).total_seconds() < WEATHER_FORECAST_CACHE_TTL_SECONDS
        ):
            return self._weather_forecast_cache_avg

        forecast_list: list[dict[str, Any]] = []
        if self.hass.services.has_service("weather", "get_forecasts"):
            try:
                response = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": self._weather_entity, "type": "hourly"},
                    blocking=True,
                    return_response=True,
                )
                if response and self._weather_entity in response:
                    forecast_list = response[self._weather_entity].get("forecast") or []
            except Exception as err:
                _LOGGER.debug("weather.get_forecasts call failed: %s", err)

        if not forecast_list and "forecast" in st_weather.attributes:
            forecast_list = st_weather.attributes.get("forecast") or []

        if not forecast_list:
            return None

        temps: list[float] = []
        now_dt = dt_util.now()
        horizon_dt = now_dt + timedelta(hours=24)

        for entry in forecast_list:
            if "temperature" not in entry or entry["temperature"] is None:
                continue
            entry_time = entry.get("datetime")
            if entry_time is not None:
                parsed_time = dt_util.parse_datetime(str(entry_time))
                if parsed_time is not None:
                    if parsed_time < now_dt - timedelta(hours=1) or parsed_time > horizon_dt:
                        continue
            temps.append(float(entry["temperature"]))
            if len(temps) >= 24:
                break

        if not temps:
            temps = [
                float(e["temperature"])
                for e in forecast_list[:24]
                if "temperature" in e and e["temperature"] is not None
            ]

        if temps:
            avg = round(sum(temps) / len(temps), 2)
            self._weather_forecast_cache_avg = avg
            self._weather_forecast_cache_ts = now_utc
            return avg
        return None

    @property
    def _total_heating_hours_today(self) -> float:
        """Total cumulative heating run hours today (including active cycle)."""
        total = self._hours_run_today
        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL] and self._cycle_start_time:
            total += (dt_util.utcnow() - self._cycle_start_time).total_seconds() / 3600.0
        return total

    def _check_window_open_state(self, now_utc: datetime) -> None:
        """Evaluate open window / ventilation detection state."""
        window_detection_active = self._window_detection_enabled
        if self._window_detection_sensor:
            st_w = self.hass.states.get(self._window_detection_sensor)
            if st_w and st_w.state not in ["unknown", "unavailable"]:
                window_detection_active = st_w.state == "on"

        if not window_detection_active:
            self._window_open = False
            self._window_open_time = None
            return

        if self._window_sensor:
            st_ws = self.hass.states.get(self._window_sensor)
            if st_ws and st_ws.state not in ["unknown", "unavailable"]:
                self._window_open = st_ws.state == "on"
                if self._window_open and self._window_open_time is None:
                    self._window_open_time = now_utc
                elif not self._window_open:
                    self._window_open_time = None
        else:
            # Automatic thermal drop detection (using smoothed derivative _derivative_smooth)
            if self._window_open:
                if self._window_open_time and (now_utc - self._window_open_time) >= self._window_timeout:
                    _LOGGER.info(
                        "Window open timeout reached (%s). Resuming heating operation.",
                        self._window_timeout,
                    )
                    self._window_open = False
                    self._window_open_time = None
                elif self._derivative_smooth > 0.2:
                    _LOGGER.info(
                        "Window closed: temperature recovery observed (+%.2f°C/h). Resuming operation.",
                        self._derivative_smooth,
                    )
                    self._window_open = False
                    self._window_open_time = None
            else:
                cutoff_15m = now_utc - timedelta(minutes=15)
                recent_temps = [v for t, v in self._temp_history if t >= cutoff_15m]
                if recent_temps and self._cur_temp is not None:
                    max_recent = max(recent_temps)
                    drop = max_recent - self._cur_temp
                    if drop >= self._window_drop_threshold or (
                        self._derivative_smooth <= WINDOW_DERIVATIVE_THRESHOLD and drop >= 0.2
                    ):
                        self._window_open = True
                        self._window_open_time = now_utc
                        _LOGGER.warning(
                            "Rapid thermal drop detected (drop %.2f°C in <= 15 min, slope %.2f°C/h). Suspending heating.",
                            drop,
                            self._derivative_smooth,
                        )

    def _update_trajectory_projection(self, now: datetime) -> None:
        """Estimate filtered state and project slab trajectory at t + theta using continuous-discrete alpha-beta observer."""
        if self._cur_temp is None:
            return

        # Deduplication guard: ignore sub-second duplicate calls (< 1 second)
        if self._observer_last_update is not None:
            if (now - self._observer_last_update).total_seconds() < 1.0:
                return

        # Maintain 15-minute history window for rapid thermal drop / ventilation detection
        self._temp_history.append((now, self._cur_temp))
        cutoff_15m = now - timedelta(minutes=15)
        self._temp_history = [(t, v) for t, v in self._temp_history if t >= cutoff_15m]

        # Detect window closure transition to initiate thermal rebound damping
        if self._was_window_open and not self._window_open:
            self._window_recovery_until = now + timedelta(minutes=POST_AIRING_RECOVERY_MINUTES)
            # Reset derivative on window closure: air warming back against slab is not slab overheating
            self._temp_derivative = 0.0
            self._derivative_smooth = 0.0
        self._was_window_open = self._window_open

        # Clean filter initialization on first reading (prevents startup spike to 19°C)
        if self._filtered_temp is None or self._observer_last_update is None:
            self._filtered_temp = self._cur_temp
            self._temp_derivative = 0.0
            self._derivative_smooth = 0.0
            self._observer_last_update = now
            self._temp_projected = self._cur_temp
            self._projection_history.append((now, self._temp_projected))
            return

        dt = (now - self._observer_last_update).total_seconds() / 3600.0  # in hours

        if dt > 0:
            if dt > 2.0:
                # Large time gap (e.g. extended HA shutdown) -> realign state immediately
                self._filtered_temp = self._cur_temp
                self._temp_derivative = 0.0
                self._derivative_smooth = 0.0
            else:
                # 1. State prediction
                t_pred = self._filtered_temp + (dt * self._temp_derivative)
                v_pred = self._temp_derivative

                # 2. Innovation (residual)
                innov = self._cur_temp - t_pred

                # 3. Continuous-discrete Kalata tracking gains
                # Measurement quantization noise variance for 0.1°C resolution: R = sigma_v^2 = 0.1^2 / 12 ~= 0.0008333
                # Process noise parameter q_proc: configurable via options (default 0.005 (°C/h)^2/h)
                var_r = 0.0008333
                sigma_v = math.sqrt(var_r)
                q_proc = max(0.0001, self._kalata_process_noise)
                omega_0 = (q_proc / (sigma_v ** 2)) ** 0.25
                K_p = math.sqrt(2.0) * omega_0
                K_v = omega_0 ** 2

                alpha = min(0.5, K_p * dt)
                beta_over_dt = K_v * dt

                # 4. State correction
                self._filtered_temp = t_pred + (alpha * innov)
                self._temp_derivative = max(-2.5, min(2.5, v_pred + (beta_over_dt * innov)))

                # 5. Low-pass filter on derivative (tau_v = 1.0 hour) to eradicate Zigbee stair-step noise
                tau_v = 1.0  # 1 hour thermal velocity time constant
                alpha_v = min(1.0, dt / tau_v)
                self._derivative_smooth += alpha_v * (self._temp_derivative - self._derivative_smooth)
                self._derivative_smooth = max(-2.5, min(2.5, self._derivative_smooth))

            self._observer_last_update = now

        # Ventilation freeze & post-airing rebound damping
        in_recovery = self._window_recovery_until is not None and now < self._window_recovery_until
        if self._window_open:
            # Active window opening: slab has not lost heat like room air, freeze derivative
            effective_deriv = 0.0
        elif in_recovery:
            # Post-airing rebound: cold air warms back against warm surfaces, clamp positive derivative
            effective_deriv = min(POST_AIRING_MAX_DERIVATIVE, max(-0.5, self._derivative_smooth))
        else:
            effective_deriv = self._derivative_smooth

        # Projected trajectory at t + theta (computed from filtered temperature & smoothed derivative)
        self._temp_projected = self._filtered_temp + (self._effective_dead_time * effective_deriv)

        # Record projection for continuous model error evaluation
        self._projection_history.append((now, self._temp_projected))

        # Prune projection history (retain up to 2 * dead_time + 1h)
        cutoff_proj = now - timedelta(hours=max(4.0, (self._effective_dead_time * 2.0) + 1.0))
        self._projection_history = [(t, v) for t, v in self._projection_history if t >= cutoff_proj]

        # Evaluate model error: e_model(t) = T_measured(t) - T_projected(t - theta)
        target_time = now - timedelta(hours=self._effective_dead_time)
        past_proj: float | None = None
        for i in range(len(self._projection_history) - 1):
            t1, p1 = self._projection_history[i]
            t2, p2 = self._projection_history[i + 1]
            if t1 <= target_time <= t2:
                dt_span = (t2 - t1).total_seconds()
                if dt_span > 0:
                    fraction = (target_time - t1).total_seconds() / dt_span
                    past_proj = p1 + fraction * (p2 - p1)
                else:
                    past_proj = p1
                break

        if past_proj is not None:
            self._model_error = round(self._cur_temp - past_proj, 2)
            # Only accumulate RMS history during passive cooling / resting regimes to avoid
            # inflating Rule B threshold during active heating or solar gain ramps (F-08)
            if self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF] and self._derivative_smooth <= 0.05:
                self._model_error_history.append((now, self._model_error))

            # Prune error history to rolling 24-hour window
            cutoff_rms = now - timedelta(hours=24)
            self._model_error_history = [
                (t, err) for t, err in self._model_error_history if t >= cutoff_rms
            ]

            # Compute RMS over rolling 24h window
            if self._model_error_history:
                sum_sq = sum(err ** 2 for _, err in self._model_error_history)
                self._model_error_rms = round(
                    math.sqrt(sum_sq / len(self._model_error_history)), 2
                )

        self._schedule_state_save()

    def _async_read_sensors(self) -> None:
        """Synchronize states from configured sensors."""
        st_in = self.hass.states.get(self._target_sensor)
        if st_in and getattr(st_in, "state", None) not in ["unknown", "unavailable"]:
            try:
                self._cur_temp = float(st_in.state)
                now_utc = dt_util.utcnow()
                if self._cur_temp_ts is None:
                    lu = getattr(st_in, "last_updated", None)
                    self._cur_temp_ts = lu if isinstance(lu, datetime) else now_utc
                self._update_trajectory_projection(now_utc)
                self._check_window_open_state(now_utc)
            except (ValueError, TypeError):
                pass

        st_out = self.hass.states.get(self._outdoor_sensor)
        if st_out and getattr(st_out, "state", None) not in ["unknown", "unavailable"]:
            try:
                self._outdoor_temp = float(st_out.state)
                if self._outdoor_temp_ts is None:
                    lu = getattr(st_out, "last_updated", None)
                    self._outdoor_temp_ts = lu if isinstance(lu, datetime) else dt_util.utcnow()
            except (ValueError, TypeError):
                pass

        if self._floor_temp_sensor:
            st_floor = self.hass.states.get(self._floor_temp_sensor)
            if st_floor and st_floor.state not in ["unknown", "unavailable"]:
                try:
                    self._floor_temp = float(st_floor.state)
                except ValueError:
                    pass

    async def _async_control_heating(self, now: datetime | None = None) -> None:
        """Main algorithmic loop: thermodynamic energy balance and model-based scheduling."""
        now_utc = dt_util.utcnow()

        # Midnight daily counter reset (evaluated unconditionally regardless of mode)
        today = dt_util.now().date()
        if today != self._last_day_reset:
            unserved_hours = max(0.0, self._hours_needed_24h - self._total_heating_hours_today)
            self._unserved_quota_carryover_hours = round(
                min(MAX_UNSERVED_QUOTA_CARRYOVER_HOURS, unserved_hours), 2
            )
            self._prev_day_energy_quota_kwh = self._energy_needed_kwh
            self._hours_run_today = 0.0
            self._cycles_today = 0
            self._last_day_reset = today
            _LOGGER.info(
                "Midnight daily counters reset for %s (carryover: %.2fh, saved prev quota: %.2f kWh)",
                self.name,
                self._unserved_quota_carryover_hours,
                self._prev_day_energy_quota_kwh or 0.0,
            )

        if self._hvac_mode == HVACMode.OFF:
            # If compressor is in running state, ensure safe shutdown once min cycle is fulfilled
            if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
                await self._async_stop_heating_safe()
                self.async_write_ha_state()
            return

        # Update FSM state transitions based on elapsed lock durations
        elapsed = (now_utc - self._last_state_change).total_seconds()
        if self._fsm_state == FSM_RUNNING_MIN_LOCK and elapsed >= self._min_cycle_duration.total_seconds():
            self._fsm_state = FSM_RUNNING_NORMAL

        if self._fsm_state == FSM_WAITING_MIN_OFF and elapsed >= self._min_off_duration.total_seconds():
            self._fsm_state = FSM_IDLE

        # Check Stale Sensor Watchdog (Indoor & Outdoor)
        self._sensor_stale = False
        self._outdoor_sensor_stale = False
        if self._sensor_stale_timeout_minutes > 0:
            if self._cur_temp_ts is None and self._target_sensor:
                st_target = self.hass.states.get(self._target_sensor)
                if st_target:
                    lu = getattr(st_target, "last_updated", None)
                    if isinstance(lu, datetime):
                        self._cur_temp_ts = lu
            if self._cur_temp_ts is not None and isinstance(self._cur_temp_ts, datetime):
                elapsed_stale_sec = (now_utc - self._cur_temp_ts).total_seconds()
                if isinstance(elapsed_stale_sec, (int, float)) and elapsed_stale_sec >= (
                    self._sensor_stale_timeout_minutes * 60
                ):
                    self._sensor_stale = True

            if self._outdoor_temp_ts is None and self._outdoor_sensor:
                st_out = self.hass.states.get(self._outdoor_sensor)
                if st_out:
                    lu_out = getattr(st_out, "last_updated", None)
                    if isinstance(lu_out, datetime):
                        self._outdoor_temp_ts = lu_out
            if self._outdoor_temp_ts is not None and isinstance(self._outdoor_temp_ts, datetime):
                elapsed_out_sec = (now_utc - self._outdoor_temp_ts).total_seconds()
                if isinstance(elapsed_out_sec, (int, float)) and elapsed_out_sec >= (
                    self._sensor_stale_timeout_minutes * 60
                ):
                    self._outdoor_sensor_stale = True

        # 1. Evaluate effective dead time theta (Soft Self-Adaptation)
        self._effective_dead_time = self._dead_time
        if (
            self._auto_calibrate_dead_time
            and self._dead_time_measured_hours is not None
            and self._dead_time_samples_count >= DEAD_TIME_MIN_SAMPLES
        ):
            min_d = round((1.0 - DEAD_TIME_MAX_DEVIATION) * self._dead_time, 2)
            max_d = round((1.0 + DEAD_TIME_MAX_DEVIATION) * self._dead_time, 2)
            self._effective_dead_time = round(
                max(min_d, min(max_d, self._dead_time_measured_hours)), 2
            )

        # 2. Update state observer and slab trajectory projection at t + theta_effective
        self._update_trajectory_projection(now_utc)

        # 3. Evaluate ventilation / window open state (using updated _temp_history and _derivative_smooth)
        self._check_window_open_state(now_utc)

        # 4. Mode B Soft Self-Adaptation: evaluate effective heat loss H
        self._effective_heat_loss = self._heat_loss
        if (
            self._auto_calibrate_heat_loss
            and self._heat_loss_measured_wk is not None
            and self._heat_loss_samples_count >= AUTO_CALIBRATE_MIN_SAMPLES
        ):
            if self._heat_loss_samples_count >= self._heat_loss_confidence_samples:
                # Enforce realistic lower bound (>= 50% of configured baseline H, and >= MIN_HEAT_LOSS_WK)
                min_h_floor = max(MIN_HEAT_LOSS_WK, round(MIN_HEAT_LOSS_RATIO * self._heat_loss, 1))
                self._effective_heat_loss = round(
                    max(min_h_floor, self._heat_loss_measured_wk), 1
                )
            else:
                # Soft progressive adaptation (clamped within +/-20% of baseline)
                min_h = round((1.0 - AUTO_CALIBRATE_MAX_DEVIATION) * self._heat_loss, 1)
                max_h = round((1.0 + AUTO_CALIBRATE_MAX_DEVIATION) * self._heat_loss, 1)
                self._effective_heat_loss = round(
                    max(min_h, min(max_h, self._heat_loss_measured_wk)), 1
                )

        # 5. Wind convective heat loss amplification
        self._wind_factor = 1.0
        self._wind_speed = None
        if self._wind_sensor:
            st_w = self.hass.states.get(self._wind_sensor)
            if st_w and st_w.state not in ["unknown", "unavailable"]:
                try:
                    if st_w.domain == "weather" and "wind_speed" in st_w.attributes:
                        self._wind_speed = float(st_w.attributes["wind_speed"])
                    else:
                        self._wind_speed = float(st_w.state)
                    if self._wind_speed > WIND_SPEED_CALM_THRESHOLD:
                        excess_wind = self._wind_speed - WIND_SPEED_CALM_THRESHOLD
                        self._wind_factor = round(
                            min(WIND_MAX_AMPLIFICATION, 1.0 + WIND_AMPLIFICATION_GAIN * excess_wind),
                            3,
                        )
                except (ValueError, TypeError):
                    pass

        # 6. Check Off-Peak tariff active state
        off_peak_active = False
        if self._off_peak_sensor:
            st = self.hass.states.get(self._off_peak_sensor)
            off_peak_active = st is not None and st.state == "on"

        # 7. Calculate 24h thermal energy quota (kWh) with Wind, Rolling Weather Forecast & Slow Drift Ambient Supervisor
        effective_outdoor: float | None = self._outdoor_temp
        self._forecast_outdoor_temp_24h = None
        self._weather_outage_fallback_active = False
        weather_fallback_quota_kwh: float | None = None

        if self._use_weather_forecast_average and self._weather_entity:
            forecast_avg = await self._async_get_weather_forecast_24h_average()
            if forecast_avg is not None:
                effective_outdoor = forecast_avg
                self._forecast_outdoor_temp_24h = forecast_avg
            else:
                self._weather_outage_fallback_active = True
                if self._prev_day_energy_quota_kwh is not None and self._prev_day_energy_quota_kwh > 0.0:
                    weather_fallback_quota_kwh = round(self._prev_day_energy_quota_kwh * 1.05, 2)
                    _LOGGER.warning(
                        "Weather forecast unavailable for %s; falling back to previous day's quota +5%% (%.2f kWh)",
                        self.name,
                        weather_fallback_quota_kwh,
                    )

        if weather_fallback_quota_kwh is not None:
            base_energy_kwh = weather_fallback_quota_kwh
            trimmed_energy_kwh = base_energy_kwh
            self._energy_needed_kwh = base_energy_kwh
            self._hours_needed_24h = round(
                (self._energy_needed_kwh * 1000.0) / self._power_watts + self._unserved_quota_carryover_hours,
                2,
            )
        elif effective_outdoor is not None:
            delta_t = max(0.0, self._target_temp - effective_outdoor)
            base_energy_kwh = (
                self._effective_heat_loss * self._wind_factor * delta_t * 24.0
            ) / 1000.0

            # Ambient supervisor: gentle proportional trim eliminating persistent offset without integral windup
            if self._cur_temp is not None:
                ambient_error = self._target_temp - self._cur_temp
                self._ambient_trim_ratio = round(
                    max(AMBIENT_TRIM_MIN, min(AMBIENT_TRIM_MAX, 1.0 + AMBIENT_TRIM_GAIN * ambient_error)),
                    3,
                )
            else:
                self._ambient_trim_ratio = 1.0

            trimmed_energy_kwh = base_energy_kwh * self._ambient_trim_ratio

            # 6. Solar gain integration with inviolable Morning Wake-Up Comfort Guard
            self._solar_credit_kwh = 0.0
            if self._solar_sensor:
                local_now = dt_util.now()
                # Comfort Guard 1: Before 09:00 AM local time or during off-peak night recharge,
                # solar credit is strictly 0.0 to prevent under-heating at morning wake-up.
                # Comfort Guard 2: If current temperature is already below comfort setpoint (>0.3°C drop),
                # solar credit is completely inhibited.
                comfort_guard_active = (
                    local_now.hour < SOLAR_MORNING_CUTOFF_HOUR
                    or off_peak_active
                    or (self._cur_temp is not None and self._cur_temp < (self._target_temp - 0.3))
                )

                if not comfort_guard_active:
                    st_solar = self.hass.states.get(self._solar_sensor)
                    if st_solar and st_solar.state not in ["unknown", "unavailable"]:
                        try:
                            solar_val = float(st_solar.state)
                            if solar_val > 50.0:  # Active solar irradiance threshold (W/m² or equivalent)
                                # Scale between 50 W/m² (diffuse) and 800 W/m² (bright direct sun)
                                solar_factor = min(1.0, max(0.0, (solar_val - 50.0) / 750.0))
                                max_solar_credit = trimmed_energy_kwh * SOLAR_MAX_CREDIT_RATIO
                                self._solar_credit_kwh = round(max_solar_credit * solar_factor, 2)
                        except (ValueError, TypeError):
                            pass

            self._energy_needed_kwh = max(0.0, round(trimmed_energy_kwh - self._solar_credit_kwh, 2))
            # Required compressor operating hours over 24h + unserved carry-over
            self._hours_needed_24h = round(
                (self._energy_needed_kwh * 1000.0) / self._power_watts + self._unserved_quota_carryover_hours,
                2,
            )

        # 5. Model-based predictive scheduling strategy
        should_heat = False
        outdoor_ref = (
            self._outdoor_temp
            if (self._outdoor_temp is not None and not self._outdoor_sensor_stale)
            else effective_outdoor
        )

        if self._cur_temp is not None:
            error = self._target_temp - self._cur_temp
            proj_val = self._temp_projected if self._temp_projected is not None else self._cur_temp
            projected_error = self._target_temp - proj_val

            # Rule 0: Emergency comfort deficit bypass (unconditional heating if room falls >= 1.5°C below target,
            # independent of outdoor sensor availability - F-04)
            if error >= EMERGENCY_COMFORT_DEFICIT_OVERRIDE:
                should_heat = True
                self._decision_reason = (
                    f"Emergency comfort deficit bypass: curr {self._cur_temp}°C <= target {self._target_temp}°C - "
                    f"{EMERGENCY_COMFORT_DEFICIT_OVERRIDE}°C (quota bypassed)"
                )
            # Rule A: Priority thermal precharge during Off-Peak hours
            elif off_peak_active and outdoor_ref is not None:
                if error >= -0.5 and outdoor_ref <= self._outdoor_precharge_max_temp:
                    should_heat = True
                    self._decision_reason = (
                        f"Off-peak thermal precharge (ext: {outdoor_ref}°C, "
                        f"curr: {self._cur_temp}°C, proj: {round(proj_val, 2)}°C in {self._dead_time}h)"
                    )
            # Rule B: Peak hours heating only on anticipated trajectory drop
            elif not off_peak_active and outdoor_ref is not None:
                effective_rms = self._model_error_rms if self._model_error_rms is not None else 0.10
                rule_b_threshold = min(
                    MAX_RULE_B_THRESHOLD,
                    max(
                        self._rule_b_min_threshold,
                        round(2.0 * effective_rms, 2),
                    ),
                )
                self._current_rule_b_threshold = rule_b_threshold

                if projected_error > rule_b_threshold or error > self._rule_b_min_threshold:
                    should_heat = True
                    self._decision_reason = (
                        f"Anticipated thermal drop: projected {round(proj_val, 2)}°C in {self._dead_time}h "
                        f"(slope: {round(self._derivative_smooth, 3)}°C/h, threshold: {rule_b_threshold}°C, "
                        f"below target {self._target_temp}°C)"
                    )

            # Rule C: Surface and ambient overshoot protection (+0.6°C real or projected > target + 0.8°C)
            if error < -0.6 or (projected_error < -0.8 and self._cur_temp >= self._target_temp):
                should_heat = False
                self._decision_reason = (
                    f"Overshoot prevention cutoff: curr {self._cur_temp}°C, "
                    f"projected {round(proj_val, 2)}°C (target: {self._target_temp}°C)"
                )
            elif not should_heat:
                self._decision_reason = (
                    f"Idle (stable trajectory: curr {self._cur_temp}°C, "
                    f"projected {round(proj_val, 2)}°C in {self._dead_time}h)"
                )

            # Hard Ambient Overshoot Ceiling cutoff: unconditional immediate stop if room exceeds target + margin
            if self._hard_overshoot_margin > 0 and self._cur_temp >= (self._target_temp + self._hard_overshoot_margin):
                should_heat = False
                self._decision_reason = (
                    f"Hard overshoot ceiling cutoff: curr {self._cur_temp}°C >= "
                    f"target {self._target_temp}°C + {self._hard_overshoot_margin}°C"
                )

            # Rule D: Daily thermal quota enforcement during Peak hours
            quota_enforcement_active = self._enforce_daily_quota
            if self._enforce_daily_quota_sensor:
                st_q = self.hass.states.get(self._enforce_daily_quota_sensor)
                if st_q and st_q.state not in ["unknown", "unavailable"]:
                    quota_enforcement_active = st_q.state == "on"

            run_hours = self._total_heating_hours_today
            quota_exceeded = (self._hours_needed_24h > 0.0) and (run_hours >= self._hours_needed_24h)
            self._quota_blocked = False

            if should_heat and not off_peak_active and quota_enforcement_active and quota_exceeded:
                if error < self._comfort_safety_deficit:
                    should_heat = False
                    self._quota_blocked = True
                    self._decision_reason = (
                        f"Daily quota fulfilled ({round(run_hours, 2)}h / {round(self._hours_needed_24h, 2)}h done). "
                        f"Peak-hour cycle inhibited by quota enforcement (switch ON)."
                    )

        # Stale Sensor Watchdog Fail-Safe cutoff (unconditional even if outdoor sensor is unavailable - F-04)
        if self._sensor_stale:
            should_heat = False
            stale_min = (
                int((now_utc - self._cur_temp_ts).total_seconds() // 60)
                if self._cur_temp_ts
                else self._sensor_stale_timeout_minutes
            )
            self._decision_reason = (
                f"Fail-safe shutdown: ambient sensor stale for {stale_min} min "
                f"(timeout: {self._sensor_stale_timeout_minutes} min)"
            )

        # Rule E: Open window / ventilation detection (unconditional - F-04)
        if self._window_open:
            should_heat = False
            self._decision_reason = "Open window / ventilation detected. Heating suspended."

        # Rule F: Multi-Zone startup staggering
        stagger_remaining_sec = 0
        if should_heat and self._fsm_state == FSM_IDLE and self._stagger_delay.total_seconds() > 0:
            if self._demand_start_time is None:
                self._demand_start_time = now_utc
            demand_elapsed = (now_utc - self._demand_start_time).total_seconds()
            if demand_elapsed < self._stagger_delay.total_seconds():
                stagger_remaining_sec = int(self._stagger_delay.total_seconds() - demand_elapsed)
                should_heat = False
                self._decision_reason = (
                    f"Staggered startup delay ({stagger_remaining_sec}s remaining, anti inrush peak protection)"
                )
        elif not should_heat:
            self._demand_start_time = None

        # Rule G: Peak-hour top-up run duration cap (Adaptive PWM period modulation)
        # In peak hours, avoid deep continuous gavage at expensive grid tariffs. Once top-up reaches
        # peak_max_run_duration (default 45 min, >= 30 min Danfoss min runtime), stop to let heat pulse diffuse.
        if (
            should_heat
            and not off_peak_active
            and self._peak_max_run_duration.total_seconds() > 0
            and self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]
            and self._cycle_start_time
        ):
            active_run_sec = (now_utc - self._cycle_start_time).total_seconds()
            is_freeze_emergency = self._floor_temp is not None and self._floor_temp <= self._min_floor_temp
            is_comfort_emergency = (
                self._cur_temp is not None
                and (self._target_temp - self._cur_temp) >= self._comfort_safety_deficit
            )
            if (
                active_run_sec >= self._peak_max_run_duration.total_seconds()
                and not is_freeze_emergency
                and not is_comfort_emergency
            ):
                should_heat = False
                self._decision_reason = (
                    f"Peak-hour top-up cycle completed ({int(active_run_sec // 60)} min run cap reached, "
                    f"allowing slab thermal diffusion)"
                )

        # Global Maximum Continuous Run Cap (mandatory slab diffusion pause across all tariffs)
        if (
            should_heat
            and self._max_continuous_run_minutes > 0
            and self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]
            and self._cycle_start_time
        ):
            active_run_sec = (now_utc - self._cycle_start_time).total_seconds()
            is_freeze_emergency = self._floor_temp is not None and self._floor_temp <= self._min_floor_temp
            if active_run_sec >= (self._max_continuous_run_minutes * 60) and not is_freeze_emergency:
                should_heat = False
                self._decision_reason = (
                    f"Maximum continuous run duration reached ({int(active_run_sec // 60)} min >= "
                    f"{self._max_continuous_run_minutes} min): enforcing thermal diffusion pause"
                )

        # Thermal Runaway Cutoff (abnormal heating rate dT/dt > threshold sustained for >30min)
        if (
            should_heat
            and self._thermal_runaway_derivative > 0
            and self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]
        ):
            if self._derivative_smooth is not None and self._derivative_smooth > self._thermal_runaway_derivative:
                if self._thermal_runaway_start_time is None:
                    self._thermal_runaway_start_time = now_utc
                elif (now_utc - self._thermal_runaway_start_time).total_seconds() >= 1800:
                    should_heat = False
                    self._decision_reason = (
                        f"Emergency cutoff: thermal runaway detected (dT/dt = "
                        f"{round(self._derivative_smooth, 2)}°C/h > {self._thermal_runaway_derivative}°C/h for >30m)"
                    )
            else:
                self._thermal_runaway_start_time = None
        else:
            self._thermal_runaway_start_time = None

        # 6. Hydronic floor loop safeties (if sensor configured)
        if self._floor_temp is not None:
            if self._floor_temp >= self._max_floor_temp:
                should_heat = False
                self._decision_reason = (
                    f"Floor protection cutoff: water temp {self._floor_temp}°C "
                    f"exceeds slab maximum {self._max_floor_temp}°C (DTU 65.14)"
                )
            elif self._floor_temp <= self._min_floor_temp:
                should_heat = True
                self._decision_reason = (
                    f"Floor freeze protection: water temp {self._floor_temp}°C "
                    f"below floor minimum {self._min_floor_temp}°C"
                )

        # 7. Execute heating decision under strict FSM constraints
        if should_heat:
            await self._async_start_heating_safe()
        else:
            await self._async_stop_heating_safe()

        # 8. Passive continuous calibration of heat loss factor (Mode A - Night-time cooling only, F-07)
        local_hour = dt_util.now().hour
        is_night_window = local_hour >= 23 or local_hour < 6
        sample_throttled = (
            self._last_heat_loss_sample_ts is not None
            and (now_utc - self._last_heat_loss_sample_ts).total_seconds() < 3600.0
        )
        if (
            is_night_window
            and not sample_throttled
            and self._solar_credit_kwh == 0.0
            and self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF]
            and not self._window_open
            and self._cur_temp is not None
            and self._outdoor_temp is not None
        ):
            time_since_stop = (now_utc - self._last_state_change).total_seconds()
            required_rest = 2.0 * self._dead_time * 3600.0  # Relaxed slab (> 2 * theta)
            delta_t = self._cur_temp - self._outdoor_temp

            if time_since_stop >= required_rest and delta_t >= 3.0 and self._derivative_smooth < -0.05:
                # C_eff = slab_tau_hours * heat_loss_wk (in Wh/K)
                c_eff = self._slab_tau * self._heat_loss
                p_loss = -c_eff * self._derivative_smooth  # Watts
                sample_ua = p_loss / delta_t

                # Disturbance filter: sample within [0.3 * H, 3.0 * H]
                if 0.3 * self._heat_loss <= sample_ua <= 3.0 * self._heat_loss:
                    if self._heat_loss_measured_wk is None:
                        self._heat_loss_measured_wk = round(sample_ua, 1)
                    else:
                        self._heat_loss_measured_wk = round(
                            0.98 * self._heat_loss_measured_wk + 0.02 * sample_ua, 1
                        )
                    self._heat_loss_samples_count += 1
                    self._last_heat_loss_sample_ts = now_utc
                    self._schedule_state_save()

        # 9. Experimental identification of slab transport dead time theta (inflection point)
        if (
            self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]
            and self._cycle_start_time
            and self._heating_start_derivative is not None
            and self._heating_start_derivative <= 0.0
        ):
            if self._derivative_smooth >= 0.05:
                # Slope reversed from cooling/flat to active warming: heat wave has traversed the slab
                measured_theta = (now_utc - self._cycle_start_time).total_seconds() / 3600.0
                if 0.5 <= measured_theta <= 5.0:
                    if self._dead_time_measured_hours is None:
                        self._dead_time_measured_hours = round(measured_theta, 2)
                    else:
                        self._dead_time_measured_hours = round(
                            0.90 * self._dead_time_measured_hours + 0.10 * measured_theta, 2
                        )
                    self._dead_time_samples_count += 1
                self._heating_start_derivative = None  # Measure once per cycle

        # 10. Next transition time estimation (v0.3.1)
        self._update_next_transition_estimate(now_utc)

        self.async_write_ha_state()

    def _find_scheduled_off_peak_start(self, now: datetime) -> datetime | None:
        """Attempt to resolve the next scheduled off-peak slot start timestamp."""
        if not self.hass or not hasattr(self.hass, "states") or not self.hass.states:
            return None

        # 1. Check attributes on off_peak_sensor
        if self._off_peak_sensor:
            st = self.hass.states.get(self._off_peak_sensor)
            if st and hasattr(st, "attributes") and isinstance(st.attributes, dict):
                for attr_key in ["next_start", "next_slot", "start_time", "start"]:
                    val = st.attributes.get(attr_key)
                    if isinstance(val, datetime):
                        return val.astimezone(UTC) if val.tzinfo else val.replace(tzinfo=UTC)
                    if isinstance(val, str):
                        try:
                            parsed = datetime.fromisoformat(val)
                            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                        except (ValueError, TypeError):
                            pass

        # 2. Check optional configured off_peak_start_entity (e.g. input_datetime or timestamp sensor)
        if self._off_peak_start_entity:
            st_start = self.hass.states.get(self._off_peak_start_entity)
            if st_start and getattr(st_start, "state", None) not in [None, "unknown", "unavailable", "none"]:
                state_str = str(st_start.state).strip()
                parts = state_str.split(":")
                if len(parts) >= 2:
                    try:
                        h = int(parts[0])
                        m = int(parts[1])
                        s = int(parts[2]) if len(parts) > 2 else 0
                        now_local = now.astimezone() if now.tzinfo else now
                        today_local = now_local.replace(hour=h, minute=m, second=s, microsecond=0)
                        if today_local <= now_local:
                            slot_local = today_local + timedelta(days=1)
                        else:
                            slot_local = today_local
                        return slot_local.astimezone(UTC)
                    except (ValueError, TypeError):
                        pass

        return None

    def _update_next_transition_estimate(self, now: datetime) -> None:
        """Estimate the timestamp, type and rationale of the next FSM transition."""
        # 1. When heating is ACTIVE (running_min_lock or running_normal) -> next transition is turn_off
        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            self._next_transition_type = "turn_off"
            cycle_start = self._cycle_start_time or now
            t_min = cycle_start + self._min_cycle_duration
            self._earliest_transition_time = t_min

            off_peak_active = False
            if self._off_peak_sensor:
                st = self.hass.states.get(self._off_peak_sensor)
                off_peak_active = st is not None and getattr(st, "state", None) == "on"

            if not off_peak_active:
                # Peak hours: Rule G run duration cap
                t_peak_cap = cycle_start + self._peak_max_run_duration
                if t_peak_cap >= t_min:
                    self._next_transition_time = t_peak_cap
                    self._next_transition_reason = (
                        f"Peak-hour top-up run cap reached ({int(self._peak_max_run_duration.total_seconds() // 60)} min)"
                    )
                else:
                    self._next_transition_time = t_min
                    self._next_transition_reason = (
                        f"Danfoss minimum runtime lock ({int(self._min_cycle_duration.total_seconds() // 60)} min)"
                    )
            else:
                # Off-peak hours: remaining thermal quota or continuous run cap
                elapsed_cycle_hours = max(0.0, (now - cycle_start).total_seconds() / 3600.0)
                total_hours_so_far = self._hours_run_today + elapsed_cycle_hours
                remaining_hours = max(0.0, self._hours_needed_24h - total_hours_so_far)
                t_quota = now + timedelta(hours=remaining_hours)
                t_max_run = (
                    cycle_start + timedelta(minutes=self._max_continuous_run_minutes)
                    if self._max_continuous_run_minutes > 0
                    else None
                )

                if t_max_run and t_max_run < t_quota:
                    t_target = t_max_run
                    reason = f"Max continuous run cap ({self._max_continuous_run_minutes} min thermal diffusion pause)"
                else:
                    t_target = t_quota
                    reason = "Daily thermal quota completion"

                if t_target < t_min:
                    self._next_transition_time = t_min
                    self._next_transition_reason = (
                        f"Danfoss minimum runtime lock ({int(self._min_cycle_duration.total_seconds() // 60)} min)"
                    )
                else:
                    self._next_transition_time = t_target
                    self._next_transition_reason = reason
            return

        # 2. When heating is INACTIVE (idle or waiting_min_off) -> next transition is turn_on
        self._next_transition_type = "turn_on"
        t_min = now
        if self._fsm_state == FSM_WAITING_MIN_OFF and self._last_state_change:
            t_min = self._last_state_change + self._min_off_duration
        self._earliest_transition_time = t_min

        # Inhibit prediction if sensors are stale or window open
        if self._sensor_stale:
            self._next_transition_time = None
            self._next_transition_reason = "Suspended: ambient sensor stale"
            return
        if self._window_open:
            self._next_transition_time = None
            self._next_transition_reason = "Suspended: window open"
            return

        # Attempt to resolve scheduled Off-Peak start time
        t_off_peak: datetime | None = None
        off_peak_start_time = self._find_scheduled_off_peak_start(now)
        if off_peak_start_time is not None:
            t_off_peak = off_peak_start_time + self._stagger_delay

        # Evaluate cooling trajectory in Peak hours (Rule B anticipated drop)
        t_drop: datetime | None = None
        drop_hours: float | None = None
        v = self._derivative_smooth
        if v is not None and v < -0.01 and self._cur_temp is not None:
            threshold = (
                self._current_rule_b_threshold
                if self._current_rule_b_threshold is not None
                else self._rule_b_min_threshold
            )
            proj = self._temp_projected if self._temp_projected is not None else self._cur_temp
            delta_drop = proj - (self._target_temp - threshold)
            if delta_drop > 0:
                drop_hours = delta_drop / abs(v)
                t_drop = now + timedelta(hours=drop_hours)

        stagger_m = int(self._stagger_delay.total_seconds() // 60)
        stagger_suffix = f" (+{stagger_m}m stagger)" if stagger_m > 0 else ""

        if t_off_peak is not None and (t_drop is None or t_off_peak <= t_drop):
            self._next_transition_time = max(t_min, t_off_peak)
            self._next_transition_reason = f"Off-peak precharge scheduled{stagger_suffix}"
        elif t_drop is not None:
            self._next_transition_time = max(t_min, t_drop)
            self._next_transition_reason = (
                f"Anticipated thermal drop below target in {round(drop_hours, 1)}h (cooling at {round(abs(v), 2)}°C/h)"
            )
        elif t_off_peak is not None:
            self._next_transition_time = max(t_min, t_off_peak)
            self._next_transition_reason = f"Off-peak precharge scheduled{stagger_suffix}"
        else:
            self._next_transition_time = None
            self._next_transition_reason = "Idle (stable trajectory, no heating demand predicted)"

    async def _async_start_heating_safe(self) -> None:
        """Start compressor if minimum off-cycle safety conditions are satisfied."""
        now = dt_util.utcnow()

        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            self._reconcile_rejected_or_stopped_heater(now)
            return

        # Check daily compressor cycle budget (Danfoss anti-fatigue)
        is_freeze_emergency = self._floor_temp is not None and self._floor_temp <= self._min_floor_temp
        if self._cycles_today >= self._max_cycles and not is_freeze_emergency:
            _LOGGER.info(
                "Start denied: daily compressor cycle budget exhausted (%d / %d). Next budget at midnight.",
                self._cycles_today,
                self._max_cycles,
            )
            self._decision_reason = (
                f"Daily cycle budget exhausted ({self._cycles_today}/{self._max_cycles}). "
                "Next budget at midnight."
            )
            return

        if self._fsm_state == FSM_WAITING_MIN_OFF:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_off_duration.total_seconds():
                _LOGGER.debug(
                    "Startup deferred: compressor minimum off safety in progress (%ds remaining)",
                    int(self._min_off_duration.total_seconds() - elapsed),
                )
                return

        # Start heating (physical or simulated)
        self._simulated_heater_state = True
        if self._dry_run:
            _LOGGER.info(
                "[DRY-RUN / SHADOW MODE] Simulated compressor start for %s (Reason: %s)",
                self._name,
                self._decision_reason,
            )
            if self._heater_entity and self._heater_entity.startswith("input_boolean."):
                await self.hass.services.async_call(
                    "input_boolean", "turn_on", {"entity_id": self._heater_entity}, blocking=False
                )
        else:
            if self._heater_entity:
                domain = self._heater_entity.split(".")[0]
                _LOGGER.info("Physical compressor start: %s", self._heater_entity)
                try:
                    await self.hass.services.async_call(
                        domain, "turn_on", {"entity_id": self._heater_entity}, blocking=False
                    )
                except Exception as err:
                    _LOGGER.error("Failed to turn on heater entity %s: %s", self._heater_entity, err)
                    return

        self._fsm_state = FSM_RUNNING_MIN_LOCK
        self._last_state_change = now
        self._cycle_start_time = now
        self._heating_start_derivative = self._derivative_smooth
        self._demand_start_time = None
        self._hvac_action = HVACAction.HEATING
        self._cycles_today += 1
        self._schedule_state_save()

    async def _async_stop_heating_safe(self) -> None:
        """Stop compressor if and only if minimum runtime safety is satisfied."""
        now = dt_util.utcnow()

        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            if self._reconcile_rejected_or_stopped_heater(now):
                return

        if self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF]:
            # Reconciliation guard: Ensure physical heater is strictly OFF when FSM is resting
            if not self._dry_run and self._heater_entity:
                st = self.hass.states.get(self._heater_entity)
                if st is not None and st.state == "on":
                    # Never interrupt an active compressor within its Danfoss 30-min minimum runtime lock
                    if (
                        self._cycle_start_time is not None
                        and (now - self._cycle_start_time) < self._min_cycle_duration
                    ):
                        _LOGGER.warning(
                            "Reconciliation cutoff deferred for %s: compressor is within Danfoss 30-min runtime lock "
                            "(%ds remaining). Restoring FSM to RUNNING_MIN_LOCK.",
                            self._heater_entity,
                            int((self._min_cycle_duration - (now - self._cycle_start_time)).total_seconds()),
                        )
                        self._fsm_state = FSM_RUNNING_MIN_LOCK
                        self._last_state_change = self._cycle_start_time
                        self._hvac_action = HVACAction.HEATING
                        self._simulated_heater_state = True
                        self._schedule_state_save()
                        return

                    domain = self._heater_entity.split(".")[0]
                    _LOGGER.warning(
                        "Reconciliation cutoff: heater entity %s is ON while FSM state is %s. Forcing turn_off.",
                        self._heater_entity,
                        self._fsm_state,
                    )
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off", {"entity_id": self._heater_entity}, blocking=False
                        )
                    except Exception as err:
                        _LOGGER.error(
                            "Failed to turn off heater entity %s during reconciliation: %s",
                            self._heater_entity,
                            err,
                        )
            return

        if self._fsm_state == FSM_RUNNING_MIN_LOCK:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_cycle_duration.total_seconds():
                _LOGGER.debug(
                    "Stop deferred: compressor minimum runtime safety in progress (%ds remaining)",
                    int(self._min_cycle_duration.total_seconds() - elapsed),
                )
                return

        # Stop heating (physical or simulated)
        self._simulated_heater_state = False
        if self._dry_run:
            _LOGGER.info(
                "[DRY-RUN / SHADOW MODE] Simulated compressor stop for %s (Reason: %s)",
                self._name,
                self._decision_reason,
            )
            if self._heater_entity and self._heater_entity.startswith("input_boolean."):
                await self.hass.services.async_call(
                    "input_boolean", "turn_off", {"entity_id": self._heater_entity}, blocking=False
                )
        else:
            if self._heater_entity:
                domain = self._heater_entity.split(".")[0]
                _LOGGER.info("Physical compressor stop: %s", self._heater_entity)
                try:
                    await self.hass.services.async_call(
                        domain, "turn_off", {"entity_id": self._heater_entity}, blocking=False
                    )
                except Exception as err:
                    _LOGGER.error("Failed to turn off heater entity %s: %s", self._heater_entity, err)

        if self._cycle_start_time:
            run_sec = (now - self._cycle_start_time).total_seconds()
            self._hours_run_today += run_sec / 3600.0
            self._cycle_start_time = None

        self._fsm_state = FSM_WAITING_MIN_OFF
        self._last_state_change = now
        self._hvac_action = HVACAction.IDLE
        self._schedule_state_save()
        self._thermal_runaway_start_time = None
