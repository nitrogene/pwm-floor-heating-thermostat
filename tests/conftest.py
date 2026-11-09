"""pytest configuration and mocks for pwm_floor_heating_thermostat."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Add project paths to sys.path
root_dir = Path(__file__).resolve().parent.parent
for p in [root_dir, root_dir / "custom_components", root_dir / "custom_components" / "pwm_floor_heating_thermostat"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Mock Home Assistant modules if not present in the local environment
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
    "homeassistant.helpers.dispatcher",
    "homeassistant.components",
    "homeassistant.components.climate",
    "homeassistant.components.diagnostics",
    "homeassistant.components.sensor",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.util",
    "homeassistant.util.dt",
    "voluptuous",
]

for mod in ha_modules:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Link sub-modules to parent modules so 'from a.b import c' works seamlessly
for mod_name in ha_modules:
    parts = mod_name.split(".")
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        sub_name = ".".join(parts[: i + 1])
        child_attr = parts[i]
        setattr(sys.modules[parent_name], child_attr, sys.modules[sub_name])


# Core decorators
def mock_callback(func):
    """Transparent callback decorator."""
    return func


import homeassistant.core as ha_core  # noqa: E402

ha_core.callback = mock_callback
sys.modules["homeassistant.core"].callback = mock_callback
sys.modules["homeassistant"].core.callback = mock_callback

# Diagnostics mock
sys.modules["homeassistant.components.diagnostics"].async_redact_data.side_effect = lambda data, to_redact: data


# Base entity classes to avoid metaclass conflicts with MagicMock
class MockEntity:
    """Home Assistant mock Entity."""

    def __init__(self, *args, **kwargs):
        pass

    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    @property
    def has_entity_name(self) -> bool:
        return getattr(self, "_attr_has_entity_name", False)

    def async_on_remove(self, func):
        pass

    async def async_added_to_hass(self):
        pass

    def async_write_ha_state(self):
        pass


class MockClimateEntity(MockEntity):
    """Mock ClimateEntity."""


class MockSensorEntity(MockEntity):
    """Mock SensorEntity."""


class MockRestoreEntity(MockEntity):
    """Mock RestoreEntity."""

    async def async_get_last_state(self):
        return None


import homeassistant.components.climate as climate_mod  # noqa: E402
import homeassistant.components.sensor as sensor_mod  # noqa: E402
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


@dataclass(frozen=True, kw_only=True)
class MockSensorEntityDescription:
    """Mock SensorEntityDescription."""

    key: str
    device_class: Any = None
    state_class: Any = None
    entity_category: Any = None
    native_unit_of_measurement: str | None = None
    translation_key: str | None = None
    options: list[str] | None = None


sensor_mod.SensorEntity = MockSensorEntity
sensor_mod.SensorEntityDescription = MockSensorEntityDescription
sensor_mod.SensorDeviceClass = MagicMock()
sensor_mod.SensorDeviceClass.TEMPERATURE = "temperature"
sensor_mod.SensorDeviceClass.ENERGY = "energy"
sensor_mod.SensorDeviceClass.DURATION = "duration"
sensor_mod.SensorDeviceClass.ENUM = "enum"
sensor_mod.SensorStateClass = MagicMock()
sensor_mod.SensorStateClass.MEASUREMENT = "measurement"

restore_mod.RestoreEntity = MockRestoreEntity

# Standard Home Assistant constants and types
import homeassistant.const as ha_const  # noqa: E402

ha_const.Platform = MagicMock()
ha_const.Platform.CLIMATE = "climate"
ha_const.Platform.SENSOR = "sensor"
ha_const.EntityCategory = MagicMock()
ha_const.EntityCategory.DIAGNOSTIC = "diagnostic"
ha_const.CONF_NAME = "name"
ha_const.CONF_UNIQUE_ID = "unique_id"
ha_const.ATTR_TEMPERATURE = "temperature"
ha_const.EVENT_HOMEASSISTANT_START = "homeassistant_start"
ha_const.PRECISION_TENTHS = 0.1
ha_const.UnitOfTemperature = MagicMock()
ha_const.UnitOfTemperature.CELSIUS = "°C"
ha_const.UnitOfEnergy = MagicMock()
ha_const.UnitOfEnergy.KILO_WATT_HOUR = "kWh"
ha_const.UnitOfTime = MagicMock()
ha_const.UnitOfTime.HOURS = "h"

# Home Assistant selectors
import homeassistant.helpers.selector as selector  # noqa: E402


class MockSelector:
    """Generic mock for Home Assistant UI selectors."""

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
    """Mock ConfigFlow for unit testing."""

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
    """Mock OptionsFlow for unit testing."""

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
    """Mock ConfigEntry representing a configured integration instance."""

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
