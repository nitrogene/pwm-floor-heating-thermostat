"""DataUpdateCoordinator for PWM Floor Heating Thermostat."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PwmThermostatCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator coordinating data updates between master thermostat and sensors."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=None,  # State updates are event-driven by the master climate entity
        )
        self.entry = entry
        self.thermostat: Any | None = None

    def register_thermostat(self, thermostat: Any) -> None:
        """Register the thermostat instance and trigger initial sensor sync."""
        self.thermostat = thermostat
        self.async_update_listeners()

    def async_notify_update(self) -> None:
        """Notify all listener entities that the master thermostat state has updated."""
        self.async_update_listeners()
