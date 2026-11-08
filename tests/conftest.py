"""Configuration pytest pour pwm_floor_heating_thermostat."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ajouter les chemins à sys.path
root_dir = Path(__file__).resolve().parent.parent
for p in [root_dir, root_dir / "custom_components", root_dir / "custom_components" / "pwm_floor_heating_thermostat"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

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
    "homeassistant.helpers.selector",
    "homeassistant.helpers.device_registry",
    "homeassistant.components",
    "homeassistant.components.climate",
    "homeassistant.components.diagnostics",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.util",
    "homeassistant.util.dt",
    "voluptuous",
]

for mod in ha_modules:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Lier les sous-modules aux modules parents pour que les imports de type 'from a.b import c' fonctionnent
for mod_name in ha_modules:
    parts = mod_name.split(".")
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        sub_name = ".".join(parts[: i + 1])
        child_attr = parts[i]
        setattr(sys.modules[parent_name], child_attr, sys.modules[sub_name])


# Core decorators
def mock_callback(func):
    """Décorateur callback transparent."""
    return func


import homeassistant.core as ha_core  # noqa: E402

ha_core.callback = mock_callback
sys.modules["homeassistant.core"].callback = mock_callback
sys.modules["homeassistant"].core.callback = mock_callback

# Diagnostics mock
sys.modules["homeassistant.components.diagnostics"].async_redact_data.side_effect = lambda data, to_redact: data


# Classes de base pour éviter le conflit de métaclasse avec MagicMock
class MockEntity:
    """Mock Entity Home Assistant."""

    def __init__(self, *args, **kwargs):
        pass

    def async_on_remove(self, func):
        pass


class MockClimateEntity(MockEntity):
    """Mock ClimateEntity."""


class MockRestoreEntity(MockEntity):
    """Mock RestoreEntity."""

    async def async_get_last_state(self):
        return None


import homeassistant.components.climate as climate_mod  # noqa: E402
import homeassistant.helpers.restore_state as restore_mod  # noqa: E402

climate_mod.ClimateEntity = MockClimateEntity
climate_mod.PLATFORM_SCHEMA = MagicMock()
climate_mod.PLATFORM_SCHEMA.extend = MagicMock(return_value=MagicMock())
climate_mod.ClimateEntityFeature = MagicMock()
climate_mod.ClimateEntityFeature.TARGET_TEMPERATURE = 1
climate_mod.ClimateEntityFeature.PRESET_MODE = 2
climate_mod.HVACMode = MagicMock()
climate_mod.HVACMode.HEAT = "heat"
climate_mod.HVACMode.OFF = "off"
climate_mod.HVACAction = MagicMock()
climate_mod.HVACAction.HEATING = "heating"
climate_mod.HVACAction.IDLE = "idle"
climate_mod.HVACAction.OFF = "off"
climate_mod.PRESET_AWAY = "away"
climate_mod.PRESET_COMFORT = "comfort"
climate_mod.PRESET_ECO = "eco"
climate_mod.PRESET_NONE = "none"

restore_mod.RestoreEntity = MockRestoreEntity

# Constantes et types standard Home Assistant
import homeassistant.const as ha_const  # noqa: E402

ha_const.Platform = MagicMock()
ha_const.Platform.CLIMATE = "climate"
ha_const.CONF_NAME = "name"
ha_const.CONF_UNIQUE_ID = "unique_id"
ha_const.ATTR_TEMPERATURE = "temperature"
ha_const.EVENT_HOMEASSISTANT_START = "homeassistant_start"
ha_const.PRECISION_TENTHS = 0.1
ha_const.UnitOfTemperature = MagicMock()
ha_const.UnitOfTemperature.CELSIUS = "°C"

# Sélecteurs Home Assistant
import homeassistant.helpers.selector as selector  # noqa: E402


class MockSelector:
    """Mock générique pour les sélecteurs UI de Home Assistant."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


selector.EntitySelector = MockSelector
selector.EntitySelectorConfig = MockSelector
selector.NumberSelector = MockSelector
selector.NumberSelectorConfig = MockSelector
selector.NumberSelectorMode = MagicMock()
selector.NumberSelectorMode.BOX = "box"
selector.NumberSelectorMode.SLIDER = "slider"
selector.BooleanSelector = MockSelector
selector.TextSelector = MockSelector

# Device Registry
import homeassistant.helpers.device_registry as dr  # noqa: E402

dr.DeviceInfo = MagicMock

# Config Entries Mocks
import homeassistant.config_entries as ce  # noqa: E402


class MockConfigFlow:
    """Mock ConfigFlow pour tests unitaires."""

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    def __init__(self):
        self.unique_id = None
        self._configured_ids = set()

    async def async_set_unique_id(self, unique_id: str):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if self.unique_id in self._configured_ids:
            raise Exception("already_configured")

    def async_create_entry(self, *, title: str, data: dict):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }


class MockOptionsFlow:
    """Mock OptionsFlow pour tests unitaires."""

    def __init__(self, config_entry=None):
        self.config_entry = config_entry

    def async_create_entry(self, *, title: str = "", data: dict):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }


class MockConfigEntry:
    """Mock ConfigEntry représentant une instance configurée."""

    def __init__(self, entry_id: str, title: str, data: dict, options: dict | None = None):
        self.entry_id = entry_id
        self.title = title
        self.data = dict(data)
        self.options = dict(options) if options else {}
        self.update_listeners = []

    def add_update_listener(self, listener):
        self.update_listeners.append(listener)
        return lambda: self.update_listeners.remove(listener)

    def async_on_unload(self, callback):
        pass


ce.ConfigFlow = MockConfigFlow
ce.OptionsFlow = MockOptionsFlow
ce.ConfigEntry = MockConfigEntry
ce.MockConfigEntry = MockConfigEntry
sys.modules["homeassistant.config_entries"].ConfigEntry = MockConfigEntry
sys.modules["homeassistant.config_entries"].MockConfigEntry = MockConfigEntry
sys.modules["homeassistant"].config_entries.ConfigEntry = MockConfigEntry
sys.modules["homeassistant"].config_entries.MockConfigEntry = MockConfigEntry
