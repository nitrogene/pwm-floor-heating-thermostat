"""Plateforme Climate pour l'intégration PWM Floor Heating Thermostat.

Thermostat prédictif basé sur le modèle physique du bâtiment et de la dalle :
- Estimation du quota énergétique journalier à partir des déperditions (W/K) et de la météo.
- Ordonnancement prioritaire des cycles longs en Heures Creuses nocturnes (Linky TIC).
- Machine à états finis inviolable garantissant les sécurités compresseurs Danfoss (30m ON / 15m OFF).
- Recalage d'état par la sonde d'ambiance intérieure sans intégrateur divergent.
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
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_HEURES_CREUSES_SENSOR,
    CONF_MAX_CYCLES_PER_DAY,
    CONF_MIN_CYCLE_DURATION,
    CONF_MIN_OFF_CYCLE_DURATION,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_HEAT_LOSS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_CYCLE,
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
        vol.Required(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_TARGET_SENSOR): cv.entity_id,
        vol.Required(CONF_OUTDOOR_SENSOR): cv.entity_id,
        vol.Optional(CONF_HEURES_CREUSES_SENSOR): cv.entity_id,
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
    """Configuration de la plateforme Thermal Slab Thermostat."""
    async_add_entities([ThermalSlabThermostat(hass, config)])


class ThermalSlabThermostat(ClimateEntity, RestoreEntity):
    """Représentation du thermostat prédictif à dalle thermique."""

    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, hass: HomeAssistant, config: ConfigType) -> None:
        """Initialisation de l'entité."""
        self.hass = hass
        self._name = config[CONF_NAME]
        self._heater_entity = config[CONF_HEATER]
        self._target_sensor = config[CONF_TARGET_SENSOR]
        self._outdoor_sensor = config[CONF_OUTDOOR_SENSOR]
        self._hc_sensor = config.get(CONF_HEURES_CREUSES_SENSOR)

        # Paramètres thermodynamiques
        self._heat_loss = config[CONF_HEAT_LOSS]
        self._power_watts = config[CONF_POWER_WATTS]
        self._slab_tau = config[CONF_SLAB_TIME_CONSTANT]
        self._dead_time = config[CONF_DEAD_TIME]

        # Sécurités mécaniques Danfoss
        self._min_cycle_duration: timedelta = config[CONF_MIN_CYCLE_DURATION]
        self._min_off_duration: timedelta = config[CONF_MIN_OFF_CYCLE_DURATION]
        self._max_cycles_per_day: int = config[CONF_MAX_CYCLES_PER_DAY]

        # États internes
        self._target_temp: float = DEFAULT_TARGET_TEMP
        self._cur_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._hvac_mode: HVACMode = HVACMode.HEAT
        self._hvac_action: HVACAction = HVACAction.IDLE

        # Machine à états finis (FSM)
        self._fsm_state: str = FSM_IDLE
        self._last_state_change: datetime = dt_util.utcnow()
        self._cycle_start_time: datetime | None = None

        # Télémétrie et suivi d'énergie
        self._energy_needed_kwh: float = 0.0
        self._hours_needed_24h: float = 0.0
        self._hours_run_today: float = 0.0
        self._cycles_today: int = 0
        self._last_day_reset: datetime.date = dt_util.now().date()

    async def async_added_to_hass(self) -> None:
        """Enregistrement des écouteurs d'événements et restauration d'état."""
        await super().async_added_to_hass()

        # Restauration de la consigne précédente si disponible
        old_state = await self.async_get_last_state()
        if old_state is not None:
            if old_state.attributes.get(ATTR_TEMPERATURE) is not None:
                self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if old_state.state in [HVACMode.HEAT, HVACMode.OFF]:
                self._hvac_mode = HVACMode(old_state.state)

        # Écouteurs de changement de température
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
        if self._hc_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._hc_sensor], self._async_hc_changed
                )
            )

        # Boucle périodique d'évaluation thermique (toutes les 5 minutes)
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_control_heating, timedelta(minutes=5)
            )
        )

        # Initialisation immédiate des valeurs de capteurs
        self._async_read_sensors()

    @property
    def name(self) -> str:
        """Nom de l'entité."""
        return self._name

    @property
    def current_temperature(self) -> float | None:
        """Température ambiante courante."""
        return self._cur_temp

    @property
    def target_temperature(self) -> float:
        """Consigne de température."""
        return self._target_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Mode de fonctionnement actuel."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Action thermique en cours."""
        return self._hvac_action

    @property
    def min_temp(self) -> float:
        """Température minimale sélectionnable."""
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Température maximale sélectionnable."""
        return DEFAULT_MAX_TEMP

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Attributs télémétriques et thermodynamiques enrichis."""
        now = dt_util.utcnow()
        elapsed = (now - self._last_state_change).total_seconds()

        # Calcul des décomptes de sécurité Danfoss
        min_on_rem = 0
        min_off_rem = 0
        if self._fsm_state == FSM_RUNNING_MIN_LOCK:
            min_on_rem = max(0, int(self._min_cycle_duration.total_seconds() - elapsed))
        elif self._fsm_state == FSM_WAITING_MIN_OFF:
            min_off_rem = max(0, int(self._min_off_duration.total_seconds() - elapsed))

        hc_active = False
        if self._hc_sensor:
            hc_st = self.hass.states.get(self._hc_sensor)
            hc_active = hc_st is not None and hc_st.state == "on"

        return {
            "fsm_state": self._fsm_state,
            "outdoor_temperature": self._outdoor_temp,
            "heat_loss_factor_wk": self._heat_loss,
            "compressor_power_watts": self._power_watts,
            "energy_quota_24h_kwh": round(self._energy_needed_kwh, 2),
            "heating_hours_needed_24h": round(self._hours_needed_24h, 2),
            "heating_hours_done_today": round(self._hours_run_today, 2),
            "compressor_cycles_today": self._cycles_today,
            "min_cycle_lock_remaining_sec": min_on_rem,
            "min_off_lock_remaining_sec": min_off_rem,
            "heures_creuses_active": hc_active,
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
    def _async_hc_changed(self, event) -> None:
        """Bascule Heures Creuses / Heures Pleines."""
        self.hass.async_create_task(self._async_control_heating())

    def _async_read_sensors(self) -> None:
        """Lecture synchronisée des états actuels."""
        st_in = self.hass.states.get(self._target_sensor)
        if st_in and st_in.state not in ["unknown", "unavailable"]:
            try:
                self._cur_temp = float(st_in.state)
            except ValueError:
                pass

        st_out = self.hass.states.get(self._outdoor_sensor)
        if st_out and st_out.state not in ["unknown", "unavailable"]:
            try:
                self._outdoor_temp = float(st_out.state)
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

        # 1. Calcul du Quota d'Énergie Thermique requis (kWh sur 24h)
        if self._outdoor_temp is not None:
            delta_t = max(0.0, self._target_temp - self._outdoor_temp)
            # Déperditions journalières en kWh = (H * delta_t * 24h) / 1000
            self._energy_needed_kwh = (self._heat_loss * delta_t * 24.0) / 1000.0
            # Heures de fonctionnement compresseur nécessaires sur 24h
            self._hours_needed_24h = (self._energy_needed_kwh * 1000.0) / self._power_watts

        # 2. Heures Creuses actives ?
        hc_active = False
        if self._hc_sensor:
            st = self.hass.states.get(self._hc_sensor)
            hc_active = st is not None and st.state == "on"

        # 3. Stratégie d'ordonnancement prédictif
        should_heat = False

        if self._cur_temp is not None and self._outdoor_temp is not None:
            # Superviseur d'ambiance doux (sans windup)
            error = self._target_temp - self._cur_temp

            # Règle A : Priorité absolue à la charge nocturne en Heures Creuses
            if hc_active:
                # En HC, tant qu'il y a du froid dehors et qu'on ne dépasse pas consigne + 0.5°C : on précharge la dalle
                if error >= -0.5 and self._outdoor_temp <= 12.0:
                    should_heat = True

            # Règle B : En Heures Pleines, on chauffe uniquement si la dalle se décharge et que la consigne baisse
            else:
                if error > 0.2:
                    should_heat = True

            # Règle C : Garde-fou absolu contre la surchauffe (arrêt forcé dès +0.6°C au-dessus de consigne)
            if error < -0.6:
                should_heat = False

        # 4. Exécution sous contrainte stricte de la FSM
        if should_heat:
            await self._async_start_heating_safe()
        else:
            await self._async_stop_heating_safe()

        self.async_write_ha_state()

    async def _async_start_heating_safe(self) -> None:
        """Démarre le compresseur si les conditions de repos minimal sont satisfaites."""
        now = dt_util.utcnow()

        if self._fsm_state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            # Déjà en marche
            return

        if self._fsm_state == FSM_WAITING_MIN_OFF:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_off_duration.total_seconds():
                _LOGGER.debug(
                    "Démarrage différé : repos de sécurité compresseur en cours (%ds restantes)",
                    int(self._min_off_duration.total_seconds() - elapsed),
                )
                return

        # Démarrage effectif
        _LOGGER.info("Démarrage compresseur : %s", self._heater_entity)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": self._heater_entity}, blocking=True
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
            # Déjà à l'arrêt
            return

        if self._fsm_state == FSM_RUNNING_MIN_LOCK:
            elapsed = (now - self._last_state_change).total_seconds()
            if elapsed < self._min_cycle_duration.total_seconds():
                _LOGGER.debug(
                    "Arrêt différé : marche minimale compresseur en cours (%ds restantes)",
                    int(self._min_cycle_duration.total_seconds() - elapsed),
                )
                return

        # Arrêt effectif
        _LOGGER.info("Arrêt compresseur : %s", self._heater_entity)
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": self._heater_entity}, blocking=True
        )

        if self._cycle_start_time:
            run_sec = (now - self._cycle_start_time).total_seconds()
            self._hours_run_today += run_sec / 3600.0
            self._cycle_start_time = None

        self._fsm_state = FSM_WAITING_MIN_OFF
        self._last_state_change = now
        self._hvac_action = HVACAction.IDLE
