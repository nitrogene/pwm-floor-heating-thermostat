"""Plateforme Climate pour l'intégration PWM Floor Heating Thermostat.

Thermostat prédictif basé sur le modèle physique du bâtiment et de la dalle :
- Estimation du quota énergétique journalier à partir des déperditions (W/K) et de la météo.
- Ordonnancement prioritaire des cycles longs en Heures Creuses nocturnes (Linky TIC / Off-Peak tariff).
- Machine à états finis inviolable garantissant les sécurités compresseurs Danfoss (30m ON / 15m OFF).
- Moteur prédictif à temps mort : calcul de pente filtrée dT/dt (°C/h) et projection à t + theta.
- Support des sondes de boucle d'eau / dalle (planchers hydrauliques) avec garde-fou DTU 65.14.
- Mode simulation / Shadow Mode (dry_run: true) pour validation comparée sans pilotage physique.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
    EVENT_HOMEASSISTANT_START,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_TEMP,
    CONF_COMFORT_TEMP,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_ECO_TEMP,
    CONF_ENFORCE_DAILY_QUOTA,
    CONF_ENFORCE_DAILY_QUOTA_SENSOR,
    CONF_FLOOR_TEMP_SENSOR,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_HEURES_CREUSES_SENSOR,
    CONF_MAX_CYCLES_PER_DAY,
    CONF_MAX_FLOOR_TEMP,
    CONF_MIN_CYCLE_DURATION,
    CONF_MIN_FLOOR_TEMP,
    CONF_MIN_OFF_CYCLE_DURATION,
    CONF_OBSERVED_HEATER,
    CONF_OFF_PEAK_SENSOR,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_STAGGER_DELAY,
    CONF_TARGET_SENSOR,
    CONF_WINDOW_DETECTION,
    CONF_WINDOW_DETECTION_SENSOR,
    CONF_WINDOW_DROP_THRESHOLD,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_TIMEOUT,
    DEFAULT_AWAY_TEMP,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_DRY_RUN,
    DEFAULT_ECO_TEMP,
    DEFAULT_ENFORCE_DAILY_QUOTA,
    DEFAULT_HEAT_LOSS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_MAX_FLOOR_TEMP,
    DEFAULT_MIN_CYCLE,
    DEFAULT_MIN_FLOOR_TEMP,
    DEFAULT_MIN_OFF,
    DEFAULT_NAME,
    DEFAULT_POWER_WATTS,
    DEFAULT_SLAB_TAU_HOURS,
    DEFAULT_STAGGER_DELAY,
    DEFAULT_TARGET_TEMP,
    DEFAULT_WINDOW_DETECTION,
    DEFAULT_WINDOW_DROP_THRESHOLD,
    DEFAULT_WINDOW_TIMEOUT,
    DOMAIN,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_TARGET_SENSOR): cv.entity_id,
        vol.Required(CONF_OUTDOOR_SENSOR): cv.entity_id,
        vol.Optional(CONF_OFF_PEAK_SENSOR): cv.entity_id,
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
    }
)


def _parse_timedelta(val: Any, default: timedelta) -> timedelta:
    """Convertit une durée (chaîne, secondes, timedelta) en timedelta."""
    if val is None:
        return default
    if isinstance(val, timedelta):
        return val
    if isinstance(val, (int, float)):
        return timedelta(seconds=val)
    if isinstance(val, str):
        try:
            return cv.time_period(val)
        except Exception:
            try:
                return timedelta(seconds=float(val))
            except Exception:
                pass
    return default


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Configuration de la plateforme PWM Floor Heating Thermostat (via YAML)."""
    async_add_entities([PwmFloorHeatingThermostat(hass, config)])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configuration de la plateforme PWM Floor Heating Thermostat (via UI Config Entry)."""
    config = {**entry.data, **entry.options}
    config[CONF_UNIQUE_ID] = entry.entry_id
    if CONF_NAME not in config:
        config[CONF_NAME] = entry.title
    entity = PwmFloorHeatingThermostat(hass, config, entry=entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entity
    async_add_entities([entity])


class PwmFloorHeatingThermostat(ClimateEntity, RestoreEntity):
    """Représentation du thermostat prédictif à dalle thermique."""

    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]

    def __init__(self, hass: HomeAssistant, config: ConfigType, entry: ConfigEntry | None = None) -> None:
        """Initialisation de l'entité."""
        self.hass = hass
        self._entry = entry
        self._name = config.get(CONF_NAME, DEFAULT_NAME)
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._heater_entity = config.get(CONF_HEATER)
        self._target_sensor = config[CONF_TARGET_SENSOR]
        self._outdoor_sensor = config[CONF_OUTDOOR_SENSOR]
        self._off_peak_sensor = config.get(CONF_OFF_PEAK_SENSOR) or config.get(CONF_HEURES_CREUSES_SENSOR)
        self._dry_run = bool(config.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
        self._observed_heater = config.get(CONF_OBSERVED_HEATER)

        # Sonde de dalle / boucle d'eau (hydraulique)
        self._floor_temp_sensor = config.get(CONF_FLOOR_TEMP_SENSOR)
        self._max_floor_temp = float(config.get(CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP))
        self._min_floor_temp = float(config.get(CONF_MIN_FLOOR_TEMP, DEFAULT_MIN_FLOOR_TEMP))
        self._floor_temp: float | None = None

        # Paramètres thermodynamiques
        self._heat_loss = float(config.get(CONF_HEAT_LOSS, DEFAULT_HEAT_LOSS))
        self._power_watts = float(config.get(CONF_POWER_WATTS, DEFAULT_POWER_WATTS))
        self._slab_tau = float(config.get(CONF_SLAB_TIME_CONSTANT, DEFAULT_SLAB_TAU_HOURS))
        self._dead_time = float(config.get(CONF_DEAD_TIME, DEFAULT_DEAD_TIME_HOURS))

        # Sécurités Danfoss
        self._min_cycle_duration = _parse_timedelta(config.get(CONF_MIN_CYCLE_DURATION), DEFAULT_MIN_CYCLE)
        self._min_off_duration = _parse_timedelta(config.get(CONF_MIN_OFF_CYCLE_DURATION), DEFAULT_MIN_OFF)
        self._max_cycles = int(config.get(CONF_MAX_CYCLES_PER_DAY, DEFAULT_MAX_CYCLES))

        # Plafonnement du budget thermique journalier (Anti-Gaspillage Heures Pleines)
        self._enforce_daily_quota = bool(config.get(CONF_ENFORCE_DAILY_QUOTA, DEFAULT_ENFORCE_DAILY_QUOTA))
        self._enforce_daily_quota_sensor = config.get(CONF_ENFORCE_DAILY_QUOTA_SENSOR)
        self._quota_blocked = False

        # Détection d'aération / Fenêtre ouverte
        self._window_detection_enabled = bool(config.get(CONF_WINDOW_DETECTION, DEFAULT_WINDOW_DETECTION))
        self._window_detection_sensor = config.get(CONF_WINDOW_DETECTION_SENSOR)
        self._window_sensor = config.get(CONF_WINDOW_SENSOR)
        self._window_drop_threshold = float(config.get(CONF_WINDOW_DROP_THRESHOLD, DEFAULT_WINDOW_DROP_THRESHOLD))
        self._window_timeout = _parse_timedelta(config.get(CONF_WINDOW_TIMEOUT), DEFAULT_WINDOW_TIMEOUT)
        self._window_open = False
        self._window_open_time: datetime | None = None

        # Auto-calibrage continu de la déperdition H (Mode A passif)
        self._heat_loss_measured_wk: float | None = None
        self._heat_loss_samples_count: int = 0

        # Presets de température
        self._eco_temp = float(config.get(CONF_ECO_TEMP, DEFAULT_ECO_TEMP))
        self._away_temp = float(config.get(CONF_AWAY_TEMP, DEFAULT_AWAY_TEMP))
        self._comfort_temp = float(config.get(CONF_COMFORT_TEMP, DEFAULT_TARGET_TEMP))
        self._preset_mode: str = PRESET_COMFORT

        # Coordination Multi-Zones & Déphasage Anti-Pic de démarrage
        self._stagger_delay = _parse_timedelta(config.get(CONF_STAGGER_DELAY), DEFAULT_STAGGER_DELAY)
        self._demand_start_time: datetime | None = None

        # État courant
        self._cur_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._target_temp: float = DEFAULT_TARGET_TEMP
        self._hvac_mode = HVACMode.HEAT
        self._hvac_action = HVACAction.IDLE

        # Machine à états finis (FSM)
        self._fsm_state = FSM_IDLE
        self._last_state_change = dt_util.utcnow()
        self._cycle_start_time: datetime | None = None
        self._cycles_today = 0
        self._hours_run_today = 0.0
        self._last_day_reset = dt_util.now().date()

        # Moteur prédictif et historique de dérivée
        self._temp_history: list[tuple[datetime, float]] = []
        self._temp_derivative: float = 0.0
        self._temp_projected: float = DEFAULT_TARGET_TEMP

        # Télémétrie et simulation
        self._simulated_heater_state = False
        self._decision_reason = "Model initializing"
        self._energy_needed_kwh = 0.0
        self._hours_needed_24h = 0.0

    async def async_added_to_hass(self) -> None:
        """Enregistrement des écouteurs d'événements et restauration d'état."""
        await super().async_added_to_hass()

        # Restauration de l'état précédent
        if old_state := await self.async_get_last_state():
            if old_target := old_state.attributes.get(ATTR_TEMPERATURE):
                try:
                    self._target_temp = float(old_target)
                except ValueError:
                    pass
            if old_state.state in [HVACMode.HEAT, HVACMode.OFF]:
                self._hvac_mode = HVACMode(old_state.state)

            old_attrs = old_state.attributes
            self._fsm_state = old_attrs.get("fsm_state", FSM_IDLE)
            self._cycles_today = old_attrs.get("compressor_cycles_today", 0)
            self._hours_run_today = old_attrs.get("heating_hours_done_today", 0.0)
            if "temp_derivative_hourly" in old_attrs:
                try:
                    self._temp_derivative = float(old_attrs["temp_derivative_hourly"])
                except (ValueError, TypeError):
                    pass
            if "heat_loss_measured_wk" in old_attrs and old_attrs["heat_loss_measured_wk"] is not None:
                try:
                    self._heat_loss_measured_wk = float(old_attrs["heat_loss_measured_wk"])
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

        # Écouteurs de changement d'état
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

        # Boucle d'évaluation périodique (toutes les minutes)
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_control_heating, timedelta(minutes=1)
            )
        )

        @callback
        def _async_startup(*_) -> None:
            """Synchronisation initiale une fois Home Assistant complètement démarré."""
            self._async_read_sensors()
            self.hass.async_create_task(self._async_control_heating())

        if self.hass.is_running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    @property
    def unique_id(self) -> str | None:
        """Identifiant unique de l'entité."""
        return self._unique_id

    @property
    def device_info(self) -> DeviceInfo | None:
        """Informations sur l'appareil pour Home Assistant."""
        if self._unique_id:
            return DeviceInfo(
                identifiers={(DOMAIN, self._unique_id)},
                name=self._name,
                manufacturer="Nitrogene",
                model="PWM Thermodynamic Underfloor Thermostat",
                sw_version="0.2.1",
            )
        return None

    @property
    def name(self) -> str:
        """Nom de l'entité."""
        return self._name

    @property
    def current_temperature(self) -> float | None:
        """Température ambiante mesurée."""
        return self._cur_temp

    @property
    def target_temperature(self) -> float | None:
        """Consigne de température."""
        return self._target_temp

    @property
    def preset_mode(self) -> str | None:
        """Mode preset actif."""
        return self._preset_mode

    @property
    def preset_modes(self) -> list[str]:
        """Modes presets disponibles."""
        return [PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Bascule du mode preset (Comfort, Eco, Away)."""
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
            _LOGGER.warning("Preset mode non reconnu : %s", preset_mode)
            return

        await self._async_control_heating()
        self.async_write_ha_state()

    @property
    def hvac_mode(self) -> HVACMode:
        """Mode de fonctionnement actuel."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Action thermodynamique en cours."""
        return self._hvac_action

    @property
    def extra_state_attributes(self) -> dict:
        """Attributs télémétriques pour diagnostic et calage IA."""
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
            "temp_derivative_hourly": round(self._temp_derivative, 3),
            "temp_projected_ahead": round(self._temp_projected, 2),
            "heat_loss_factor_wk": self._heat_loss,
            "compressor_power_watts": self._power_watts,
            "energy_quota_24h_kwh": round(self._energy_needed_kwh, 2),
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
            "compressor_cycles_today": self._cycles_today,
            "min_cycle_lock_remaining_sec": min_on_rem,
            "min_off_lock_remaining_sec": min_off_rem,
            "off_peak_active": off_peak_active,
            "heures_creuses_active": off_peak_active,
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Ajustement de la consigne de température."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._target_temp = float(temp)
            if self._preset_mode in [PRESET_COMFORT, PRESET_NONE]:
                self._comfort_temp = self._target_temp
            await self._async_control_heating()
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Changement du mode (Chauffage / Arrêt)."""
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            await self._async_stop_heating_safe()
        else:
            await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    def _async_target_sensor_changed(self, event) -> None:
        """Mise à jour de la sonde d'ambiance."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ["unknown", "unavailable"]:
            return
        try:
            self._cur_temp = float(new_state.state)
            self._update_trajectory_projection(dt_util.utcnow())
            self.async_write_ha_state()
        except ValueError:
            pass

    @callback
    def _async_outdoor_sensor_changed(self, event) -> None:
        """Mise à jour de la sonde extérieure / météo anticipée."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ["unknown", "unavailable"]:
            return
        try:
            self._outdoor_temp = float(new_state.state)
            self.async_write_ha_state()
        except ValueError:
            pass

    @callback
    def _async_off_peak_sensor_changed(self, event) -> None:
        """Mise à jour de l'état des Heures Creuses / Off-peak tariff."""
        self.async_write_ha_state()

    @callback
    def _async_floor_temp_changed(self, event) -> None:
        """Mise à jour de la sonde de dalle / boucle d'eau."""
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
        """Écoute passive du vrai relais en mode Shadow / Digital Twin."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "[SHADOW OBSERVER] Observed heater %s changed to %s",
                self._observed_heater,
                new_state.state,
            )

    @callback
    def _async_quota_sensor_changed(self, event) -> None:
        """Réaction dynamique immédiate au basculement de l'interrupteur de plafonnement UI."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "Interrupteur de plafonnement de quota journalier %s basculé sur %s",
                self._enforce_daily_quota_sensor,
                new_state.state,
            )
            self.hass.async_create_task(self._async_control_heating())

    @callback
    def _async_window_detection_sensor_changed(self, event) -> None:
        """Réaction dynamique immédiate au basculement de l'interrupteur UI de détection de fenêtre."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            _LOGGER.debug(
                "Interrupteur de détection de fenêtre %s basculé sur %s",
                self._window_detection_sensor,
                new_state.state,
            )
            if new_state.state != "on":
                self._window_open = False
                self._window_open_time = None
            self.hass.async_create_task(self._async_control_heating())

    @callback
    def _async_window_sensor_changed(self, event) -> None:
        """Réaction immédiate à l'ouverture/fermeture d'un capteur physique de fenêtre."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            self._window_open = new_state.state == "on"
            self._window_open_time = dt_util.utcnow() if self._window_open else None
            _LOGGER.info(
                "Capteur physique de fenêtre %s : %s",
                self._window_sensor,
                "OUVERTE" if self._window_open else "FERMÉE",
            )
            self.hass.async_create_task(self._async_control_heating())

    @property
    def _total_heating_hours_today(self) -> float:
        """Heures totales de chauffe cumulées aujourd'hui (incluant le cycle actif)."""
        total = self._hours_run_today
        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL] and self._cycle_start_time:
            total += (dt_util.utcnow() - self._cycle_start_time).total_seconds() / 3600.0
        return total

    def _update_trajectory_projection(self, now: datetime) -> None:
        """Calcule la pente filtrée dT/dt (°C/h) et projette la température à t + theta."""
        if self._cur_temp is None:
            return

        self._temp_history.append((now, self._cur_temp))

        # Élagage de la fenêtre glissante (60 minutes)
        cutoff = now - timedelta(minutes=60)
        self._temp_history = [(t, v) for t, v in self._temp_history if t >= cutoff]

        # Régression linéaire sur la fenêtre si au moins 2 points espacés de 5 minutes
        if len(self._temp_history) >= 2:
            dt_span = (self._temp_history[-1][0] - self._temp_history[0][0]).total_seconds()
            if dt_span >= 300:  # >= 5 minutes
                t0 = self._temp_history[0][0]
                t_hours = [(t - t0).total_seconds() / 3600.0 for t, _ in self._temp_history]
                temps = [v for _, v in self._temp_history]

                n = len(t_hours)
                mean_t = sum(t_hours) / n
                mean_temp = sum(temps) / n

                denom = sum((t - mean_t) ** 2 for t in t_hours)
                if denom > 1e-6:
                    raw_slope = (
                        sum((t - mean_t) * (v - mean_temp) for t, v in zip(t_hours, temps, strict=True)) / denom
                    )
                    # Borne physique de pente [-3.0, +3.0] °C/h
                    self._temp_derivative = max(-3.0, min(3.0, raw_slope))
                else:
                    self._temp_derivative = 0.0

        # Trajectoire projetée à t + theta
        self._temp_projected = self._cur_temp + (self._dead_time * self._temp_derivative)

    def _async_read_sensors(self) -> None:
        """Lecture synchronisée des états actuels."""
        st_in = self.hass.states.get(self._target_sensor)
        if st_in and st_in.state not in ["unknown", "unavailable"]:
            try:
                self._cur_temp = float(st_in.state)
                self._update_trajectory_projection(dt_util.utcnow())
            except ValueError:
                pass

        st_out = self.hass.states.get(self._outdoor_sensor)
        if st_out and st_out.state not in ["unknown", "unavailable"]:
            try:
                self._outdoor_temp = float(st_out.state)
            except ValueError:
                pass

        if self._floor_temp_sensor:
            st_floor = self.hass.states.get(self._floor_temp_sensor)
            if st_floor and st_floor.state not in ["unknown", "unavailable"]:
                try:
                    self._floor_temp = float(st_floor.state)
                except ValueError:
                    pass

    async def _async_control_heating(self, now: datetime | None = None) -> None:
        """Cœur algorithmique : Bilan thermodynamique et commande par modèle."""
        if self._hvac_mode == HVACMode.OFF:
            return

        now_utc = dt_util.utcnow()

        # Reset journalier des compteurs à minuit local
        today = dt_util.now().date()
        if today != self._last_day_reset:
            self._hours_run_today = 0.0
            self._cycles_today = 0
            self._last_day_reset = today

        # Mise à jour des durées de fonctionnement en cours
        elapsed = (now_utc - self._last_state_change).total_seconds()
        if self._fsm_state == FSM_RUNNING_MIN_LOCK and elapsed >= self._min_cycle_duration.total_seconds():
            self._fsm_state = FSM_RUNNING_NORMAL

        if self._fsm_state == FSM_WAITING_MIN_OFF and elapsed >= self._min_off_duration.total_seconds():
            self._fsm_state = FSM_IDLE

        # 1. Mise à jour de la projection de trajectoire
        self._update_trajectory_projection(now_utc)

        # Détection d'aération / Fenêtre ouverte
        window_detection_active = self._window_detection_enabled
        if self._window_detection_sensor:
            st_w = self.hass.states.get(self._window_detection_sensor)
            if st_w and st_w.state not in ["unknown", "unavailable"]:
                window_detection_active = st_w.state == "on"

        if window_detection_active:
            if self._window_sensor:
                st_ws = self.hass.states.get(self._window_sensor)
                if st_ws and st_ws.state not in ["unknown", "unavailable"]:
                    self._window_open = st_ws.state == "on"
                    if self._window_open and self._window_open_time is None:
                        self._window_open_time = now_utc
                    elif not self._window_open:
                        self._window_open_time = None
            else:
                # Détection automatique de chute rapide de température
                if self._window_open:
                    if self._window_open_time and (now_utc - self._window_open_time) >= self._window_timeout:
                        _LOGGER.info(
                            "Fenêtre ouverte : délai d'aération maximal atteint (%s). Reprise automatique.",
                            self._window_timeout,
                        )
                        self._window_open = False
                        self._window_open_time = None
                    elif self._temp_derivative > 0.2:
                        _LOGGER.info(
                            "Fenêtre refermée : remontée de température observée (+%.2f°C/h). Reprise.",
                            self._temp_derivative,
                        )
                        self._window_open = False
                        self._window_open_time = None
                else:
                    cutoff_15m = now_utc - timedelta(minutes=15)
                    recent_temps = [v for t, v in self._temp_history if t >= cutoff_15m]
                    if recent_temps and self._cur_temp is not None:
                        max_recent = max(recent_temps)
                        drop = max_recent - self._cur_temp
                        if drop >= self._window_drop_threshold or (self._temp_derivative <= -1.5 and drop >= 0.2):
                            self._window_open = True
                            self._window_open_time = now_utc
                            _LOGGER.warning(
                                "Aération détectée (chute de %.2f°C en <= 15 min, pente %.2f°C/h). Suspension de la chauffe.",
                                drop,
                                self._temp_derivative,
                            )
        else:
            self._window_open = False
            self._window_open_time = None

        # 2. Calcul du Quota d'Énergie Thermique requis (kWh sur 24h)
        if self._outdoor_temp is not None:
            delta_t = max(0.0, self._target_temp - self._outdoor_temp)
            # Déperditions journalières en kWh = (H * delta_t * 24h) / 1000
            self._energy_needed_kwh = (self._heat_loss * delta_t * 24.0) / 1000.0
            # Heures de fonctionnement compresseur nécessaires sur 24h
            self._hours_needed_24h = (self._energy_needed_kwh * 1000.0) / self._power_watts

        # 3. Heures Creuses / Off-peak actives ?
        off_peak_active = False
        if self._off_peak_sensor:
            st = self.hass.states.get(self._off_peak_sensor)
            off_peak_active = st is not None and st.state == "on"

        # 4. Stratégie d'ordonnancement prédictif par modèle
        should_heat = False

        if self._cur_temp is not None and self._outdoor_temp is not None:
            error = self._target_temp - self._cur_temp
            projected_error = self._target_temp - self._temp_projected

            # Règle A : Priorité absolue à la charge nocturne en Heures Creuses / Off-Peak
            if off_peak_active:
                if error >= -0.5 and self._outdoor_temp <= 12.0:
                    should_heat = True
                    self._decision_reason = (
                        f"Off-peak thermal precharge (ext: {self._outdoor_temp}°C, "
                        f"curr: {self._cur_temp}°C, proj: {round(self._temp_projected, 2)}°C in {self._dead_time}h)"
                    )
            # Règle B : En Heures Pleines / Peak, allumage anticipé si la trajectoire décroche
            else:
                if projected_error > 0.15 or error > 0.2:
                    should_heat = True
                    self._decision_reason = (
                        f"Anticipated thermal drop: projected {round(self._temp_projected, 2)}°C in {self._dead_time}h "
                        f"(slope: {round(self._temp_derivative, 3)}°C/h, below target {self._target_temp}°C)"
                    )

            # Règle C : Garde-fou de surface et ambiance (+0.6°C réel ou projection > consigne + 0.8°C)
            if error < -0.6 or (projected_error < -0.8 and self._cur_temp >= self._target_temp):
                should_heat = False
                self._decision_reason = (
                    f"Overshoot prevention cutoff: curr {self._cur_temp}°C, "
                    f"projected {round(self._temp_projected, 2)}°C (target: {self._target_temp}°C)"
                )
            elif not should_heat:
                self._decision_reason = (
                    f"Idle (stable trajectory: curr {self._cur_temp}°C, "
                    f"projected {round(self._temp_projected, 2)}°C in {self._dead_time}h)"
                )

            # Règle D : Plafonnement du Quota Journalier en Heures Pleines (Anti-Gaspillage)
            quota_enforcement_active = self._enforce_daily_quota
            if self._enforce_daily_quota_sensor:
                st_q = self.hass.states.get(self._enforce_daily_quota_sensor)
                if st_q and st_q.state not in ["unknown", "unavailable"]:
                    quota_enforcement_active = st_q.state == "on"

            run_hours = self._total_heating_hours_today
            quota_exceeded = (self._hours_needed_24h > 0.0) and (run_hours >= self._hours_needed_24h)
            self._quota_blocked = False

            if should_heat and not off_peak_active and quota_enforcement_active and quota_exceeded:
                if error < 0.8:
                    should_heat = False
                    self._quota_blocked = True
                    self._decision_reason = (
                        f"Daily quota fulfilled ({round(run_hours, 2)}h / {round(self._hours_needed_24h, 2)}h done). "
                        f"Peak-hour cycle inhibited by quota enforcement (switch ON)."
                    )

            # Règle E : Détection de fenêtre ouverte / aération
            if self._window_open:
                should_heat = False
                self._decision_reason = "Open window / ventilation detected. Heating suspended."

        # Règle F : Déphasage anti-pic de démarrage multi-zones
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

        # 5. Garde-fous plancher chauffant / boucle d'eau (si capteur configuré)
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

        # 6. Exécution sous contrainte stricte de la FSM
        if should_heat:
            await self._async_start_heating_safe()
        else:
            await self._async_stop_heating_safe()

        # 7. Auto-étalonnage passif de la déperdition thermique (Mode A - Conseiller Télémétrique)
        if (
            self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF]
            and not self._window_open
            and self._cur_temp is not None
            and self._outdoor_temp is not None
        ):
            time_since_stop = (now_utc - self._last_state_change).total_seconds()
            required_rest = 2.0 * self._dead_time * 3600.0  # Dalle relaxée (> 2 * theta)
            delta_t = self._cur_temp - self._outdoor_temp

            if time_since_stop >= required_rest and delta_t >= 3.0 and self._temp_derivative < -0.05:
                # C_eff = slab_tau_hours * heat_loss_wk (en Wh/K)
                c_eff = self._slab_tau * self._heat_loss
                p_loss = -c_eff * self._temp_derivative  # Watts
                sample_ua = p_loss / delta_t

                # Filtrage des perturbations : sample dans [0.3 * H, 3.0 * H]
                if 0.3 * self._heat_loss <= sample_ua <= 3.0 * self._heat_loss:
                    if self._heat_loss_measured_wk is None:
                        self._heat_loss_measured_wk = round(sample_ua, 1)
                    else:
                        self._heat_loss_measured_wk = round(
                            0.98 * self._heat_loss_measured_wk + 0.02 * sample_ua, 1
                        )
                    self._heat_loss_samples_count += 1

        self.async_write_ha_state()

    async def _async_start_heating_safe(self) -> None:
        """Démarre le compresseur si les conditions de repos minimal sont satisfaites."""
        now = dt_util.utcnow()

        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            return

        if self._fsm_state == FSM_WAITING_MIN_OFF:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_off_duration.total_seconds():
                _LOGGER.debug(
                    "Démarrage différé : repos de sécurité compresseur en cours (%ds restantes)",
                    int(self._min_off_duration.total_seconds() - elapsed),
                )
                return

        # Démarrage effectif ou simulé
        self._simulated_heater_state = True
        if self._dry_run:
            _LOGGER.info(
                "[DRY-RUN / SHADOW MODE] Démarrage simulé compresseur %s (Raison: %s)",
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
                _LOGGER.info("Démarrage physique compresseur : %s", self._heater_entity)
                await self.hass.services.async_call(
                    domain, "turn_on", {"entity_id": self._heater_entity}, blocking=True
                )

        self._fsm_state = FSM_RUNNING_MIN_LOCK
        self._last_state_change = now
        self._cycle_start_time = now
        self._demand_start_time = None
        self._hvac_action = HVACAction.HEATING
        self._cycles_today += 1

    async def _async_stop_heating_safe(self) -> None:
        """Arrête le compresseur si et seulement si la durée minimale de marche est respectée."""
        now = dt_util.utcnow()

        if self._fsm_state in [FSM_IDLE, FSM_WAITING_MIN_OFF]:
            return

        if self._fsm_state == FSM_RUNNING_MIN_LOCK:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_cycle_duration.total_seconds():
                _LOGGER.debug(
                    "Arrêt différé : marche minimale compresseur en cours (%ds restantes)",
                    int(self._min_cycle_duration.total_seconds() - elapsed),
                )
                return

        # Arrêt effectif ou simulé
        self._simulated_heater_state = False
        if self._dry_run:
            _LOGGER.info(
                "[DRY-RUN / SHADOW MODE] Arrêt simulé compresseur %s (Raison: %s)",
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
                _LOGGER.info("Arrêt physique compresseur : %s", self._heater_entity)
                await self.hass.services.async_call(
                    domain, "turn_off", {"entity_id": self._heater_entity}, blocking=True
                )

        if self._cycle_start_time:
            run_sec = (now - self._cycle_start_time).total_seconds()
            self._hours_run_today += run_sec / 3600.0
            self._cycle_start_time = None

        self._fsm_state = FSM_WAITING_MIN_OFF
        self._last_state_change = now
        self._hvac_action = HVACAction.IDLE
