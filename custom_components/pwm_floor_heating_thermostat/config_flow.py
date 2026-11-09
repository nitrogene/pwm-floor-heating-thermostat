"""Config flow for PWM Floor Heating Thermostat integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

try:
    from homeassistant.config_entries import ConfigFlowResult, OptionsFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult  # type: ignore[assignment]
    from homeassistant.data_entry_flow import FlowResult as OptionsFlowResult  # type: ignore[assignment]
from homeassistant.helpers import selector

from .const import (
    CONF_AWAY_TEMP,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_ECO_TEMP,
    CONF_ENFORCE_DAILY_QUOTA,
    CONF_FLOOR_TEMP_SENSOR,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_MAX_FLOOR_TEMP,
    CONF_MIN_FLOOR_TEMP,
    CONF_OBSERVED_HEATER,
    CONF_OFF_PEAK_SENSOR,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_STAGGER_DELAY,
    CONF_TARGET_SENSOR,
    CONF_WINDOW_DETECTION,
    CONF_WINDOW_SENSOR,
    DEFAULT_AWAY_TEMP,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_DRY_RUN,
    DEFAULT_ECO_TEMP,
    DEFAULT_ENFORCE_DAILY_QUOTA,
    DEFAULT_HEAT_LOSS,
    DEFAULT_MAX_FLOOR_TEMP,
    DEFAULT_MIN_FLOOR_TEMP,
    DEFAULT_NAME,
    DEFAULT_POWER_WATTS,
    DEFAULT_SLAB_TAU_HOURS,
    DEFAULT_WINDOW_DETECTION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PwmFloorHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PWM Floor Heating Thermostat."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            target_sensor = user_input.get(CONF_TARGET_SENSOR)
            outdoor_sensor = user_input.get(CONF_OUTDOOR_SENSOR)

            if not target_sensor:
                errors[CONF_TARGET_SENSOR] = "missing_target_sensor"
            if not outdoor_sensor:
                errors[CONF_OUTDOOR_SENSOR] = "missing_outdoor_sensor"
            if not user_input.get(CONF_DRY_RUN) and not user_input.get(CONF_HEATER):
                errors[CONF_HEATER] = "heater_required_unless_dry_run"

            if not errors:
                unique_key = (
                    f"{target_sensor}_{user_input.get(CONF_HEATER) or user_input.get(CONF_NAME, DEFAULT_NAME)}"
                )
                await self.async_set_unique_id(unique_key)
                self._abort_if_unique_id_configured()

                title = user_input.get(CONF_NAME, DEFAULT_NAME)
                return self.async_create_entry(title=title, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_TARGET_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"])
                ),
                vol.Required(CONF_OUTDOOR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"])
                ),
                vol.Optional(CONF_HEATER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean"])
                ),
                vol.Optional(CONF_OFF_PEAK_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
                ),
                vol.Required(CONF_DRY_RUN, default=DEFAULT_DRY_RUN): selector.BooleanSelector(),
                vol.Optional(CONF_OBSERVED_HEATER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean"])
                ),
                vol.Required(CONF_HEAT_LOSS, default=DEFAULT_HEAT_LOSS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0,
                        max=300.0,
                        step=0.5,
                        unit_of_measurement="W/K",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_POWER_WATTS, default=DEFAULT_POWER_WATTS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500.0,
                        max=30000.0,
                        step=10.0,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_SLAB_TIME_CONSTANT, default=DEFAULT_SLAB_TAU_HOURS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0,
                        max=60.0,
                        step=0.5,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_DEAD_TIME, default=DEFAULT_DEAD_TIME_HOURS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=10.0,
                        step=0.25,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_FLOOR_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"])
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return PwmFloorHeatingOptionsFlowHandler(config_entry)


class PwmFloorHeatingOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for PWM Floor Heating Thermostat."""

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        """Initialize options flow compatible with all Home Assistant versions."""
        if config_entry is not None:
            self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the configuration entry."""
        if hasattr(self, "_config_entry"):
            return self._config_entry
        return super().config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> OptionsFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        curr = {**self.config_entry.data, **self.config_entry.options}

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DRY_RUN,
                    default=curr.get(CONF_DRY_RUN, DEFAULT_DRY_RUN),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_OBSERVED_HEATER,
                    description={"suggested_value": curr.get(CONF_OBSERVED_HEATER)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean"])
                ),
                vol.Optional(
                    CONF_HEATER,
                    description={"suggested_value": curr.get(CONF_HEATER)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean"])
                ),
                vol.Required(
                    CONF_HEAT_LOSS,
                    default=float(curr.get(CONF_HEAT_LOSS, DEFAULT_HEAT_LOSS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0,
                        max=300.0,
                        step=0.5,
                        unit_of_measurement="W/K",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_POWER_WATTS,
                    default=float(curr.get(CONF_POWER_WATTS, DEFAULT_POWER_WATTS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500.0,
                        max=30000.0,
                        step=10.0,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SLAB_TIME_CONSTANT,
                    default=float(curr.get(CONF_SLAB_TIME_CONSTANT, DEFAULT_SLAB_TAU_HOURS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0,
                        max=60.0,
                        step=0.5,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_DEAD_TIME,
                    default=float(curr.get(CONF_DEAD_TIME, DEFAULT_DEAD_TIME_HOURS)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=10.0,
                        step=0.25,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENFORCE_DAILY_QUOTA,
                    default=bool(curr.get(CONF_ENFORCE_DAILY_QUOTA, DEFAULT_ENFORCE_DAILY_QUOTA)),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_WINDOW_DETECTION,
                    default=bool(curr.get(CONF_WINDOW_DETECTION, DEFAULT_WINDOW_DETECTION)),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_WINDOW_SENSOR,
                    description={"suggested_value": curr.get(CONF_WINDOW_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
                ),
                vol.Required(
                    CONF_ECO_TEMP,
                    default=float(curr.get(CONF_ECO_TEMP, DEFAULT_ECO_TEMP)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10.0,
                        max=22.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_AWAY_TEMP,
                    default=float(curr.get(CONF_AWAY_TEMP, DEFAULT_AWAY_TEMP)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0,
                        max=18.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_FLOOR_TEMP_SENSOR,
                    description={"suggested_value": curr.get(CONF_FLOOR_TEMP_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"])
                ),
                vol.Required(
                    CONF_MAX_FLOOR_TEMP,
                    default=float(curr.get(CONF_MAX_FLOOR_TEMP, DEFAULT_MAX_FLOOR_TEMP)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20.0,
                        max=35.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_FLOOR_TEMP,
                    default=float(curr.get(CONF_MIN_FLOOR_TEMP, DEFAULT_MIN_FLOOR_TEMP)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0,
                        max=20.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_STAGGER_DELAY,
                    default=int(
                        curr.get(CONF_STAGGER_DELAY, 0)
                        if isinstance(curr.get(CONF_STAGGER_DELAY), (int, float))
                        else 0
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=1800,
                        step=30,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
