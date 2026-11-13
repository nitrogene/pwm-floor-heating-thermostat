"""Diagnostic sensor platform support for PWM Floor Heating Thermostat."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_EARLIEST_TRANSITION_TIME,
    ATTR_NEXT_TRANSITION_REASON,
    ATTR_NEXT_TRANSITION_TYPE,
    DOMAIN,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
    FSM_WAITING_MIN_OFF,
    INTEGRATION_VERSION,
)
from .coordinator import PwmThermostatCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PwmSensorEntityDescription(SensorEntityDescription):
    """Detailed description of a PWM diagnostic sensor."""

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
        key="model_error_rms",
        translation_key="model_error_rms",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t._model_error_rms if hasattr(t, "_model_error_rms") else None,
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
    PwmSensorEntityDescription(
        key="next_transition_time",
        translation_key="next_transition_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t._next_transition_time if hasattr(t, "_next_transition_time") else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensors for a PWM thermostat entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data:
        _LOGGER.warning("Coordinator not found in hass.data for entry %s", entry.entry_id)
        return

    if isinstance(data, PwmThermostatCoordinator):
        coordinator = data
    else:
        # Wrap legacy thermostat mock into coordinator for compatibility
        coordinator = PwmThermostatCoordinator(hass, entry)
        coordinator.register_thermostat(data)

    entities = [
        PwmDiagnosticSensor(coordinator, description, entry)
        for description in SENSOR_TYPES
    ]
    async_add_entities(entities)


class PwmDiagnosticSensor(CoordinatorEntity[PwmThermostatCoordinator], SensorEntity):
    """Diagnostic companion sensor for PWM thermostat."""

    _attr_has_entity_name = True
    entity_description: PwmSensorEntityDescription

    def __init__(
        self,
        coordinator: PwmThermostatCoordinator,
        description: PwmSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the companion sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_unique_id = self._unique_id

    @property
    def native_value(self) -> Any:
        """Return native value computed from master thermostat."""
        t = self.coordinator.thermostat
        if t is None:
            return None
        return self.entity_description.value_fn(t)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for diagnostic sensors."""
        t = self.coordinator.thermostat
        if t is None:
            return {}
        if self.entity_description.key == "next_transition_time":
            earliest = getattr(t, "_earliest_transition_time", None)
            return {
                ATTR_NEXT_TRANSITION_TYPE: getattr(t, "_next_transition_type", "none"),
                ATTR_NEXT_TRANSITION_REASON: getattr(t, "_next_transition_reason", "none"),
                ATTR_EARLIEST_TRANSITION_TIME: (
                    earliest.isoformat() if isinstance(earliest, datetime) else None
                ),
            }
        return {}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Attach to the same device as the master thermostat."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Nitrogene",
            model="PWM Thermodynamic Underfloor Thermostat",
            sw_version=INTEGRATION_VERSION,
        )

    @callback
    def _handle_thermostat_update(self) -> None:
        """Update sensor state when master thermostat dispatches an update."""
        self.async_write_ha_state()
