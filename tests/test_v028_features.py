"""Unit tests for v0.2.8 features: rolling 24h weather forecast average, carry-over, and coordinator."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.util import dt as dt_util

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.config_flow import (
    PwmFloorHeatingConfigFlow,
    PwmFloorHeatingOptionsFlowHandler,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    CONF_USE_WEATHER_FORECAST_AVERAGE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from custom_components.pwm_floor_heating_thermostat.coordinator import (
    PwmThermostatCoordinator,
)
from custom_components.pwm_floor_heating_thermostat.sensor import (
    SENSOR_TYPES,
)
from custom_components.pwm_floor_heating_thermostat.sensor import (
    async_setup_entry as sensor_async_setup_entry,
)


@pytest.fixture
def base_config():
    """Create minimal thermostat configuration."""
    return {
        CONF_NAME: "Thermostat Test PWM",
        CONF_TARGET_SENSOR: "sensor.room_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.heater",
        CONF_HEAT_LOSS: 15.0,
        CONF_POWER_WATTS: 3000.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_DRY_RUN: True,
    }


def test_coordinator_initialization_and_sensor_sync(base_config):
    """Verify PwmThermostatCoordinator cleanly connects thermostat and companion sensors."""
    async def _test():
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_coord_entry"
        entry.title = "Test Thermostat"
        entry.data = dict(base_config)
        entry.options = {}

        coordinator = PwmThermostatCoordinator(hass, entry)
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}

        # Instantiate thermostat
        thermostat = PwmFloorHeatingThermostat(hass, base_config, entry=entry, coordinator=coordinator)
        coordinator.register_thermostat(thermostat)

        # Setup sensors
        added_sensors = []
        def mock_add(entities):
            added_sensors.extend(entities)

        await sensor_async_setup_entry(hass, entry, mock_add)
        assert len(added_sensors) == len(SENSOR_TYPES)

        # Verify initial sensor value reading through coordinator
        thermostat._temp_projected = 20.5
        sensor_proj = next(s for s in added_sensors if s.entity_description.key == "temp_projected_ahead")
        assert sensor_proj.native_value == 20.5

        # Verify coordinator notification triggers sensor update
        await sensor_proj.async_added_to_hass()
        mock_write = MagicMock()
        sensor_proj.async_write_ha_state = mock_write
        coordinator.async_notify_update()
        mock_write.assert_called_once()

    asyncio.run(_test())


def test_weather_forecast_24h_average(base_config):
    """Verify rolling 24h weather forecast average computation and quota calculation."""
    async def _test():
        hass = MagicMock()
        config = dict(base_config)
        config[CONF_WEATHER_ENTITY] = "weather.home"
        config[CONF_USE_WEATHER_FORECAST_AVERAGE] = True

        thermostat = PwmFloorHeatingThermostat(hass, config)
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 5.0  # Instantaneous sensor says 5°C

        # Mock weather entity and hourly forecasts
        weather_state = MagicMock()
        weather_state.state = "cloudy"
        weather_state.attributes = {}

        # 24 forecast entries averaging exactly 10.0°C (alternating 9°C and 11°C)
        now = dt_util.now()
        forecasts = []
        for i in range(24):
            forecasts.append({
                "datetime": (now + timedelta(hours=i)).isoformat(),
                "temperature": 9.0 if i % 2 == 0 else 11.0,
            })

        hass.states.get = MagicMock(side_effect=lambda entity_id: weather_state if entity_id == "weather.home" else None)
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock(return_value={"weather.home": {"forecast": forecasts}})

        await thermostat._async_control_heating()

        # Average outdoor temperature should be 10.0°C
        assert thermostat._forecast_outdoor_temp_24h == 10.0
        assert thermostat._weather_outage_fallback_active is False

        # Delta T = 19.0 - 10.0 = 9.0 K (instead of 19.0 - 5.0 = 14.0 K)
        # base_energy = (15.0 W/K * 1.0 * 9.0 K * 24h) / 1000 = 3.24 kWh
        assert thermostat._energy_needed_kwh == 3.24

        attrs = thermostat.extra_state_attributes
        assert attrs["forecast_outdoor_temp_24h"] == 10.0
        assert attrs["weather_outage_fallback_active"] is False

    asyncio.run(_test())


def test_weather_outage_fallback_with_previous_day_quota(base_config):
    """Verify graceful fallback to previous day quota +5% when weather entity fails."""
    async def _test():
        hass = MagicMock()
        config = dict(base_config)
        config[CONF_WEATHER_ENTITY] = "weather.home"
        config[CONF_USE_WEATHER_FORECAST_AVERAGE] = True

        thermostat = PwmFloorHeatingThermostat(hass, config)
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 8.0
        thermostat._prev_day_energy_quota_kwh = 10.0  # Previous day was 10.0 kWh

        # Weather entity is unavailable
        st_unavailable = MagicMock()
        st_unavailable.state = "unavailable"
        hass.states.get = MagicMock(return_value=st_unavailable)

        await thermostat._async_control_heating()

        # Should fall back to 10.0 * 1.05 = 10.5 kWh
        assert thermostat._weather_outage_fallback_active is True
        assert thermostat._forecast_outdoor_temp_24h is None
        assert thermostat._energy_needed_kwh == 10.5

        attrs = thermostat.extra_state_attributes
        assert attrs["weather_outage_fallback_active"] is True
        assert attrs["energy_quota_24h_kwh"] == 10.5

    asyncio.run(_test())


def test_unserved_quota_carryover_at_midnight(base_config):
    """Verify unserved quota is carried over to the next day at midnight reset."""
    async def _test():
        hass = MagicMock()
        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hours_needed_24h = 4.0
        thermostat._hours_run_today = 1.5
        thermostat._energy_needed_kwh = 12.0
        thermostat._outdoor_temp = 10.0
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0

        # Simulate date roll (midnight transition)
        today = dt_util.now().date()
        thermostat._last_day_reset = today - timedelta(days=1)

        await thermostat._async_control_heating()

        # Unserved was 4.0 - 1.5 = 2.5h, capped at MAX_UNSERVED_QUOTA_CARRYOVER_HOURS (2.0h)
        assert thermostat._unserved_quota_carryover_hours == 2.0
        assert thermostat._prev_day_energy_quota_kwh == 12.0
        assert thermostat._hours_run_today == 0.0

        attrs = thermostat.extra_state_attributes
        assert attrs["unserved_quota_carryover_hours"] == 2.0

    asyncio.run(_test())


def test_config_flow_and_options_flow_weather_options(base_config):
    """Verify weather forecast options in config flow and options flow."""
    async def _test():
        flow = PwmFloorHeatingConfigFlow()
        flow.hass = MagicMock()

        user_input = dict(base_config)
        user_input[CONF_WEATHER_ENTITY] = "weather.home"
        user_input[CONF_USE_WEATHER_FORECAST_AVERAGE] = True

        res = await flow.async_step_user(user_input)
        assert res["type"] == "create_entry"
        assert res["data"][CONF_WEATHER_ENTITY] == "weather.home"
        assert res["data"][CONF_USE_WEATHER_FORECAST_AVERAGE] is True

        # Test options flow
        entry = MagicMock()
        entry.data = dict(user_input)
        entry.options = {}

        options_flow = PwmFloorHeatingOptionsFlowHandler(entry)
        options_flow.hass = MagicMock()

        opt_input = dict(user_input)
        opt_input[CONF_USE_WEATHER_FORECAST_AVERAGE] = False
        res_opt = await options_flow.async_step_init(opt_input)
        assert res_opt["type"] == "create_entry"
        assert res_opt["data"][CONF_USE_WEATHER_FORECAST_AVERAGE] is False

    asyncio.run(_test())


def test_weather_forecast_cache_ttl(base_config):
    """Verify weather.get_forecasts is cached for 15 minutes and invalidated on state change."""
    async def _test():
        hass = MagicMock()
        st_weather = MagicMock()
        st_weather.state = "cloudy"
        st_weather.attributes = {}
        hass.states.get.return_value = st_weather
        hass.services.has_service.return_value = True

        t0 = dt_util.utcnow()
        forecast_data = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 10.0}
            for i in range(6)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.home": {"forecast": forecast_data}}
        )

        config = dict(base_config)
        config[CONF_WEATHER_ENTITY] = "weather.home"
        config[CONF_USE_WEATHER_FORECAST_AVERAGE] = True
        thermostat = PwmFloorHeatingThermostat(hass, config)

        # First call fetches from service
        avg1 = await thermostat._async_get_weather_forecast_24h_average()
        assert avg1 == 10.0
        assert hass.services.async_call.await_count == 1

        # Second call within TTL hits cache without calling service again
        avg2 = await thermostat._async_get_weather_forecast_24h_average()
        assert avg2 == 10.0
        assert hass.services.async_call.await_count == 1

        # State change invalidates cache
        thermostat.hass = hass
        thermostat._async_weather_entity_changed(None)
        avg3 = await thermostat._async_get_weather_forecast_24h_average()
        assert avg3 == 10.0
        assert hass.services.async_call.await_count == 2

    asyncio.run(_test())
