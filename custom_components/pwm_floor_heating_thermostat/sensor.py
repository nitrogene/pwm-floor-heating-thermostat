"""Support des capteurs de diagnostic pour PWM Floor Heating Thermostat."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FSM_IDLE, FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL, FSM_WAITING_MIN_OFF

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PwmSensorEntityDescription(SensorEntityDescription):
    """Description détaillée d'un capteur de diagnostic PWM."""

    value_fn: Callable[[Any], Any] = lambda x: None


SENSOR_TYPES: tuple[PwmSensorEntityDescription, ...] = (
    PwmSensorEntityDescription(
        key="temp_projected_ahead",
        translation_key="temp_projected_ahead",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: round(t._temp_projected, 2)
        if hasattr(t, "_temp_projected") and t._temp_projected is not None
        else None,
    ),
    PwmSensorEntityDescription(
        key="temp_derivative_hourly",
        translation_key="temp_derivative_hourly",
        native_unit_of_measurement=f"{UnitOfTemperature.CELSIUS}/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: round(t._temp_derivative, 3)
        if hasattr(t, "_temp_derivative") and t._temp_derivative is not None
        else None,
    ),
    PwmSensorEntityDescription(
        key="model_error",
        translation_key="model_error",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t._model_error if hasattr(t, "_model_error") else None,
    ),
    PwmSensorEntityDescription(
        key="energy_quota_24h_kwh",
        translation_key="energy_quota_24h_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: round(t._energy_needed_kwh, 2)
        if hasattr(t, "_energy_needed_kwh") and t._energy_needed_kwh is not None
        else None,
    ),
    PwmSensorEntityDescription(
        key="heating_hours_remaining_24h",
        translation_key="heating_hours_remaining_24h",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: round(max(0.0, t._hours_needed_24h - t._total_heating_hours_today), 2)
        if hasattr(t, "_hours_needed_24h") and hasattr(t, "_total_heating_hours_today")
        else None,
    ),
    PwmSensorEntityDescription(
        key="heat_loss_measured_wk",
        translation_key="heat_loss_measured_wk",
        native_unit_of_measurement="W/K",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t._heat_loss_measured_wk if hasattr(t, "_heat_loss_measured_wk") else None,
    ),
    PwmSensorEntityDescription(
        key="fsm_state",
        translation_key="fsm_state",
        device_class=SensorDeviceClass.ENUM,
        options=[FSM_IDLE, FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL, FSM_WAITING_MIN_OFF],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t._fsm_state if hasattr(t, "_fsm_state") else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialise les capteurs de diagnostic pour une entrée thermostat PWM."""
    thermostat = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not thermostat:
        # Attente brève de l'instanciation de la plateforme climate en cas de concurrence
        for _ in range(20):
            await asyncio.sleep(0.1)
            thermostat = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if thermostat:
                break

    if not thermostat:
        _LOGGER.warning("Thermostat introuvable dans hass.data pour l'entrée %s", entry.entry_id)
        return

    entities = [
        PwmDiagnosticSensor(thermostat, description, entry)
        for description in SENSOR_TYPES
    ]
    async_add_entities(entities)


class PwmDiagnosticSensor(SensorEntity):
    """Capteur compagnon de diagnostic pour le thermostat PWM."""

    _attr_has_entity_name = True
    entity_description: PwmSensorEntityDescription

    def __init__(
        self,
        thermostat: Any,
        description: PwmSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialise le capteur compagnon."""
        self._thermostat = thermostat
        self.entity_description = description
        self._entry = entry
        self._unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_unique_id = self._unique_id

    @property
    def native_value(self) -> Any:
        """Valeur calculée depuis le thermostat maître."""
        return self.entity_description.value_fn(self._thermostat)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Rattachement au même appareil DeviceInfo que le thermostat."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Nitrogene",
            model="PWM Thermodynamic Underfloor Thermostat",
            sw_version="0.2.2",
        )

    async def async_added_to_hass(self) -> None:
        """Abonnement aux notifications de mise à jour du thermostat maître."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._entry.entry_id}_update",
                self._handle_thermostat_update,
            )
        )

    @callback
    def _handle_thermostat_update(self) -> None:
        """Met à jour l'état du capteur lors d'un changement du thermostat."""
        self.async_write_ha_state()
