"""Configuration pytest pour pwm_floor_heating_thermostat."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ajouter la racine du composant à sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Mock des modules Home Assistant si absents de l'environnement local (Python système)
ha_modules = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.const",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.typing",
    "homeassistant.components",
    "homeassistant.components.climate",
    "homeassistant.util",
    "homeassistant.util.dt",
    "voluptuous",
]

for mod in ha_modules:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
