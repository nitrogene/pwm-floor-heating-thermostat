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
    CONF_OFF_PEAK_COMFORT_MARGIN,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    CONF_WEATHER_ENTITY,
    DEMAND_CURVE_TIER_OUTDOOR_PERSISTENCE,
    DEMAND_CURVE_TIER_WEATHER_API,
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
    """Verify rolling 24h weather forecast curve computation and forecast energy need."""
    async def _test():
        hass = MagicMock()
        config = dict(base_config)
        config[CONF_WEATHER_ENTITY] = "weather.home"

        thermostat = PwmFloorHeatingThermostat(hass, config)
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 5.0  # Instantaneous sensor says 5°C

        # Mock weather entity and hourly forecasts
        weather_state = MagicMock()
        weather_state.state = "cloudy"
        weather_state.attributes = {}

        # 24 forecast entries averaging exactly 10.0°C (alternating 9°C and 11°C)
        now = dt_util.utcnow()
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

        # Average outdoor temperature should be 10.0°C (Tier 1 weather_api)
        assert thermostat._forecast_outdoor_temp_24h == 10.0
        assert thermostat._weather_outage_fallback_active is False
        assert thermostat._demand_curve_tier == DEMAND_CURVE_TIER_WEATHER_API

        # Delta T = 19.0 - 10.0 = 9.0 K -> (15.0 W/K * 9.0 K * 24h) / 1000 = 3.24 kWh
        assert thermostat._forecast_energy_need_24h_kwh == 3.24

        attrs = thermostat.extra_state_attributes
        assert attrs["forecast_outdoor_temp_24h"] == 10.0
        assert attrs["weather_outage_fallback_active"] is False
        assert attrs["forecast_energy_need_24h_kwh"] == 3.24

    asyncio.run(_test())


def test_weather_outage_fallback_to_outdoor_persistence(base_config):
    """Verify graceful fallback to Tier 2 outdoor_sensor persistence when weather API fails."""
    async def _test():
        hass = MagicMock()
        config = dict(base_config)
        config[CONF_WEATHER_ENTITY] = "weather.home"

        thermostat = PwmFloorHeatingThermostat(hass, config)
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 8.0

        # Weather entity is unavailable
        st_unavailable = MagicMock()
        st_unavailable.state = "unavailable"
        hass.states.get = MagicMock(return_value=st_unavailable)

        await thermostat._async_control_heating()

        # Tier 2 fallback: (15.0 W/K * (19.0 - 8.0) * 24h) / 1000 = 3.96 kWh
        assert thermostat._weather_outage_fallback_active is True
        assert thermostat._demand_curve_tier == DEMAND_CURVE_TIER_OUTDOOR_PERSISTENCE
        assert thermostat._forecast_outdoor_temp_24h == 8.0
        assert thermostat._forecast_energy_need_24h_kwh == 3.96

        attrs = thermostat.extra_state_attributes
        assert attrs["weather_outage_fallback_active"] is True
        assert attrs["forecast_energy_need_24h_kwh"] == 3.96

    asyncio.run(_test())


def test_midnight_cycle_counter_reset(base_config):
    """Verify midnight resets daily mechanical cycle counters without legacy carryover."""
    async def _test():
        hass = MagicMock()
        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hours_run_today = 1.5
        thermostat._cycles_today = 4
        thermostat._outdoor_temp = 10.0
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0

        # Simulate date roll (midnight transition)
        today = dt_util.now().date()
        thermostat._last_day_reset = today - timedelta(days=1)

        await thermostat._async_control_heating()

        assert thermostat._hours_run_today == 0.0
        assert thermostat._cycles_today == 0

    asyncio.run(_test())


def test_config_flow_and_options_flow_weather_options(base_config):
    """Verify mandatory weather_entity and off_peak_comfort_margin in config and options flows."""
    async def _test():
        flow = PwmFloorHeatingConfigFlow()
        flow.hass = MagicMock()

        user_input = dict(base_config)
        user_input[CONF_WEATHER_ENTITY] = "weather.home"
        user_input[CONF_OFF_PEAK_COMFORT_MARGIN] = 0.3

        res = await flow.async_step_user(user_input)
        assert res["type"] == "create_entry"
        assert res["data"][CONF_WEATHER_ENTITY] == "weather.home"
        assert res["data"][CONF_OFF_PEAK_COMFORT_MARGIN] == 0.3

        # Test options flow
        entry = MagicMock()
        entry.data = dict(user_input)
        entry.options = {}

        options_flow = PwmFloorHeatingOptionsFlowHandler(entry)
        options_flow.hass = MagicMock()

        opt_input = dict(user_input)
        opt_input[CONF_OFF_PEAK_COMFORT_MARGIN] = 0.25
        res_opt = await options_flow.async_step_init(opt_input)
        assert res_opt["type"] == "create_entry"
        assert res_opt["data"][CONF_OFF_PEAK_COMFORT_MARGIN] == 0.25

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
        thermostat = PwmFloorHeatingThermostat(hass, config)

        # First call fetches from service
        curve1 = await thermostat._async_get_weather_hourly_forecast(t0)
        assert len(curve1) == 6
        assert curve1[0][1] == 10.0
        assert hass.services.async_call.await_count == 1

        # Second call within TTL hits cache without calling service again
        curve2 = await thermostat._async_get_weather_hourly_forecast(t0 + timedelta(minutes=5))
        assert len(curve2) == 6
        assert hass.services.async_call.await_count == 1

        # State change invalidates cache
        thermostat.hass = hass
        thermostat._async_weather_entity_changed(None)
        curve3 = await thermostat._async_get_weather_hourly_forecast(t0 + timedelta(minutes=6))
        assert len(curve3) == 6
        assert hass.services.async_call.await_count == 2

    asyncio.run(_test())
