"""Intégration PWM Floor Heating Thermostat pour Home Assistant."""

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialisation du composant pwm_floor_heating_thermostat."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info("PWM Floor Heating Thermostat initialisé avec succès.")
    return True
