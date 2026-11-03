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
import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
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
    CONF_TARGET_SENSOR,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_DRY_RUN,
    DEFAULT_HEAT_LOSS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_MAX_FLOOR_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_CYCLE,
    DEFAULT_MIN_FLOOR_TEMP,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_POWER_WATTS,
    DEFAULT_SLAB_TAU_HOURS,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
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
    }
)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Configuration de la plateforme PWM Floor Heating Thermostat."""
    async_add_entities([PwmFloorHeatingThermostat(hass, config)])


class PwmFloorHeatingThermostat(ClimateEntity, RestoreEntity):
    """Représentation du thermostat prédictif à dalle thermique."""

    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, hass: HomeAssistant, config: ConfigType) -> None:
        """Initialisation de l'entité."""
        self.hass = hass
        self._name = config[CONF_NAME]
        self._heater_entity = config.get(CONF_HEATER)
        self._target_sensor = config[CONF_TARGET_SENSOR]
        self._outdoor_sensor = config[CONF_OUTDOOR_SENSOR]
        self._off_peak_sensor = config.get(CONF_OFF_PEAK_SENSOR) or config.get(CONF_HEURES_CREUSES_SENSOR)
        self._dry_run = config[CONF_DRY_RUN]
        self._observed_heater = config.get(CONF_OBSERVED_HEATER)

        # Sonde de dalle / boucle d'eau (hydraulique)
        self._floor_temp_sensor = config.get(CONF_FLOOR_TEMP_SENSOR)
        self._max_floor_temp = config[CONF_MAX_FLOOR_TEMP]
        self._min_floor_temp = config[CONF_MIN_FLOOR_TEMP]
        self._floor_temp: float | None = None

        # Paramètres thermodynamiques
        self._heat_loss = config[CONF_HEAT_LOSS]
        self._power_watts = config[CONF_POWER_WATTS]
        self._slab_tau = config[CONF_SLAB_TIME_CONSTANT]
        self._dead_time = config[CONF_DEAD_TIME]

        # Sécurités Danfoss
        self._min_cycle_duration = config[CONF_MIN_CYCLE_DURATION]
        self._min_off_duration = config[CONF_MIN_OFF_CYCLE_DURATION]
        self._max_cycles = config[CONF_MAX_CYCLES_PER_DAY]

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
            "heating_hours_done_today": round(self._hours_run_today, 2),
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
                    raw_slope = sum((t - mean_t) * (v - mean_temp) for t, v in zip(t_hours, temps)) / denom
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
