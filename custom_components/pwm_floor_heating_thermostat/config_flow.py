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
    CONF_AUTO_CALIBRATE_DEAD_TIME,
    CONF_AUTO_CALIBRATE_HEAT_LOSS,
    CONF_AWAY_TEMP,
    CONF_COMFORT_SAFETY_DEFICIT,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_ECO_TEMP,
    CONF_ENFORCE_DAILY_QUOTA,
    CONF_FLOOR_TEMP_SENSOR,
    CONF_HARD_OVERSHOOT_MARGIN,
    CONF_HEAT_LOSS,
    CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
    CONF_HEATER,
    CONF_KALATA_PROCESS_NOISE,
    CONF_MAX_CONTINUOUS_RUN_MINUTES,
    CONF_MAX_FLOOR_TEMP,
    CONF_MIN_FLOOR_TEMP,
    CONF_OBSERVED_HEATER,
    CONF_OFF_PEAK_SENSOR,
    CONF_OUTDOOR_PRECHARGE_MAX_TEMP,
    CONF_OUTDOOR_SENSOR,
    CONF_PEAK_MAX_RUN_DURATION,
    CONF_POWER_WATTS,
    CONF_RULE_B_MIN_THRESHOLD,
    CONF_SENSOR_STALE_TIMEOUT_MINUTES,
    CONF_SLAB_TIME_CONSTANT,
    CONF_SOLAR_SENSOR,
    CONF_STAGGER_DELAY,
    CONF_TARGET_SENSOR,
    CONF_THERMAL_RUNAWAY_DERIVATIVE,
    CONF_USE_WEATHER_FORECAST_AVERAGE,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    CONF_WINDOW_DETECTION,
    CONF_WINDOW_SENSOR,
    DEFAULT_AUTO_CALIBRATE_DEAD_TIME,
    DEFAULT_AUTO_CALIBRATE_HEAT_LOSS,
    DEFAULT_AWAY_TEMP,
    DEFAULT_COMFORT_SAFETY_DEFICIT,
    DEFAULT_DEAD_TIME_HOURS,
    DEFAULT_DRY_RUN,
    DEFAULT_ECO_TEMP,
    DEFAULT_ENFORCE_DAILY_QUOTA,
    DEFAULT_HARD_OVERSHOOT_MARGIN,
    DEFAULT_HEAT_LOSS,
    DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
    DEFAULT_KALATA_PROCESS_NOISE,
    DEFAULT_MAX_CONTINUOUS_RUN_MINUTES,
    DEFAULT_MAX_FLOOR_TEMP,
    DEFAULT_MIN_FLOOR_TEMP,
    DEFAULT_NAME,
    DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP,
    DEFAULT_POWER_WATTS,
    DEFAULT_RULE_B_MIN_THRESHOLD,
    DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES,
    DEFAULT_SLAB_TAU_HOURS,
    DEFAULT_THERMAL_RUNAWAY_DERIVATIVE,
    DEFAULT_USE_WEATHER_FORECAST_AVERAGE,
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
                        min=1.0,
                        max=300.0,
                        step=0.1,
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
                vol.Optional(CONF_SOLAR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"])
                ),
                vol.Optional(CONF_WIND_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"])
                ),
                vol.Optional(
                    CONF_AUTO_CALIBRATE_HEAT_LOSS,
                    default=DEFAULT_AUTO_CALIBRATE_HEAT_LOSS,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
                    default=DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=3,
                        max=100,
                        step=1,
                        unit_of_measurement="samples",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_AUTO_CALIBRATE_DEAD_TIME,
                    default=DEFAULT_AUTO_CALIBRATE_DEAD_TIME,
                ): selector.BooleanSelector(),
                vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["weather"])
                ),
                vol.Optional(
                    CONF_USE_WEATHER_FORECAST_AVERAGE,
                    default=DEFAULT_USE_WEATHER_FORECAST_AVERAGE,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_SENSOR_STALE_TIMEOUT_MINUTES,
                    default=DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=360,
                        step=15,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_MAX_CONTINUOUS_RUN_MINUTES,
                    default=DEFAULT_MAX_CONTINUOUS_RUN_MINUTES,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=240,
                        step=15,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_THERMAL_RUNAWAY_DERIVATIVE,
                    default=DEFAULT_THERMAL_RUNAWAY_DERIVATIVE,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=3.0,
                        step=0.1,
                        unit_of_measurement="°C/h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_HARD_OVERSHOOT_MARGIN,
                    default=DEFAULT_HARD_OVERSHOOT_MARGIN,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.3,
                        max=2.5,
                        step=0.1,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
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
        if hasattr(config_entries.OptionsFlow, "config_entry"):
            return PwmFloorHeatingOptionsFlowHandler()
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
                        min=1.0,
                        max=300.0,
                        step=0.1,
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
                vol.Optional(
                    CONF_SOLAR_SENSOR,
                    description={"suggested_value": curr.get(CONF_SOLAR_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"])
                ),
                vol.Optional(
                    CONF_WIND_SENSOR,
                    description={"suggested_value": curr.get(CONF_WIND_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"])
                ),
                vol.Required(
                    CONF_AUTO_CALIBRATE_HEAT_LOSS,
                    default=bool(
                        curr.get(
                            CONF_AUTO_CALIBRATE_HEAT_LOSS,
                            DEFAULT_AUTO_CALIBRATE_HEAT_LOSS,
                        )
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
                    default=int(
                        curr.get(
                            CONF_HEAT_LOSS_CONFIDENCE_SAMPLES,
                            DEFAULT_HEAT_LOSS_CONFIDENCE_SAMPLES,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=3,
                        max=100,
                        step=1,
                        unit_of_measurement="samples",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_AUTO_CALIBRATE_DEAD_TIME,
                    default=bool(
                        curr.get(
                            CONF_AUTO_CALIBRATE_DEAD_TIME,
                            DEFAULT_AUTO_CALIBRATE_DEAD_TIME,
                        )
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_PEAK_MAX_RUN_DURATION,
                    default=int(
                        curr.get(CONF_PEAK_MAX_RUN_DURATION, 45)
                        if isinstance(curr.get(CONF_PEAK_MAX_RUN_DURATION), (int, float))
                        else 45
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=180,
                        step=5,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_KALATA_PROCESS_NOISE,
                    default=float(
                        curr.get(
                            CONF_KALATA_PROCESS_NOISE,
                            DEFAULT_KALATA_PROCESS_NOISE,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.001,
                        max=0.100,
                        step=0.001,
                        unit_of_measurement="(°C/h)²/h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_OUTDOOR_PRECHARGE_MAX_TEMP,
                    default=float(
                        curr.get(
                            CONF_OUTDOOR_PRECHARGE_MAX_TEMP,
                            DEFAULT_OUTDOOR_PRECHARGE_MAX_TEMP,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0,
                        max=20.0,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_COMFORT_SAFETY_DEFICIT,
                    default=float(
                        curr.get(
                            CONF_COMFORT_SAFETY_DEFICIT,
                            DEFAULT_COMFORT_SAFETY_DEFICIT,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.3,
                        max=2.5,
                        step=0.1,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_RULE_B_MIN_THRESHOLD,
                    default=float(
                        curr.get(
                            CONF_RULE_B_MIN_THRESHOLD,
                            DEFAULT_RULE_B_MIN_THRESHOLD,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.10,
                        max=1.00,
                        step=0.05,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_WEATHER_ENTITY,
                    description={"suggested_value": curr.get(CONF_WEATHER_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["weather"])
                ),
                vol.Required(
                    CONF_USE_WEATHER_FORECAST_AVERAGE,
                    default=bool(
                        curr.get(
                            CONF_USE_WEATHER_FORECAST_AVERAGE,
                            DEFAULT_USE_WEATHER_FORECAST_AVERAGE,
                        )
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SENSOR_STALE_TIMEOUT_MINUTES,
                    default=int(
                        curr.get(
                            CONF_SENSOR_STALE_TIMEOUT_MINUTES,
                            DEFAULT_SENSOR_STALE_TIMEOUT_MINUTES,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=360,
                        step=15,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAX_CONTINUOUS_RUN_MINUTES,
                    default=int(
                        curr.get(
                            CONF_MAX_CONTINUOUS_RUN_MINUTES,
                            DEFAULT_MAX_CONTINUOUS_RUN_MINUTES,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=240,
                        step=15,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_THERMAL_RUNAWAY_DERIVATIVE,
                    default=float(
                        curr.get(
                            CONF_THERMAL_RUNAWAY_DERIVATIVE,
                            DEFAULT_THERMAL_RUNAWAY_DERIVATIVE,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=3.0,
                        step=0.1,
                        unit_of_measurement="°C/h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_HARD_OVERSHOOT_MARGIN,
                    default=float(
                        curr.get(
                            CONF_HARD_OVERSHOOT_MARGIN,
                            DEFAULT_HARD_OVERSHOOT_MARGIN,
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.3,
                        max=2.5,
                        step=0.1,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
