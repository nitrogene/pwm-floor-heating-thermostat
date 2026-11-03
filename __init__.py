"""Intégration PWM Floor Heating Thermostat pour Home Assistant."""

import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialisation du composant pwm_floor_heating_thermostat depuis le fichier YAML."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info("PWM Floor Heating Thermostat initialisé avec succès.")
    return True
