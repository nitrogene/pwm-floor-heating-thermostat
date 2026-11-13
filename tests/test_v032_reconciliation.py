"""Unit tests for v0.3.2 active reconciliation guard and anti-hijack safety."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
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
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_WAITING_MIN_OFF,
)


@pytest.fixture
def reconciliation_config():
    """Create minimal thermostat configuration for reconciliation testing."""
    return {
        CONF_NAME: "Reconciliation Test Thermostat",
        CONF_TARGET_SENSOR: "sensor.room_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.real_compressor",
        CONF_HEAT_LOSS: 15.0,
        CONF_POWER_WATTS: 3000.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_DRY_RUN: False,
    }


def _create_thermostat(config):
    """Instantiate thermostat entity with mock hass environment."""
    hass = MagicMock()
    hass.states.get.return_value = None
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    t = PwmFloorHeatingThermostat(hass, config)
    t._last_state_change = datetime.now(UTC) - timedelta(hours=1)
    return t


def test_reconciliation_in_idle_forces_turn_off(reconciliation_config):
    """When FSM is IDLE but physical heater is ON, _async_stop_heating_safe must call turn_off."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        t._fsm_state = FSM_IDLE

        # Mock physical heater state as "on"
        heater_mock = MagicMock()
        heater_mock.state = "on"
        t.hass.states.get.return_value = heater_mock

        await t._async_stop_heating_safe()

        t.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.real_compressor"}, blocking=False
        )

    asyncio.run(_test())


def test_reconciliation_in_waiting_min_off_forces_turn_off(reconciliation_config):
    """When FSM is WAITING_MIN_OFF and physical heater is ON, turn_off must be called."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        t._fsm_state = FSM_WAITING_MIN_OFF

        heater_mock = MagicMock()
        heater_mock.state = "on"
        t.hass.states.get.return_value = heater_mock

        await t._async_stop_heating_safe()

        t.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.real_compressor"}, blocking=False
        )

    asyncio.run(_test())


def test_reconciliation_in_idle_does_nothing_if_already_off(reconciliation_config):
    """When FSM is IDLE and physical heater is already OFF, turn_off should not be called."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        t._fsm_state = FSM_IDLE

        heater_mock = MagicMock()
        heater_mock.state = "off"
        t.hass.states.get.return_value = heater_mock

        await t._async_stop_heating_safe()

        t.hass.services.async_call.assert_not_called()

    asyncio.run(_test())


def test_heater_entity_changed_callback_triggers_stop(reconciliation_config):
    """Unexpected physical ON event while IDLE triggers reconciliation task."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        t._fsm_state = FSM_IDLE

        new_state_mock = MagicMock()
        new_state_mock.state = "on"
        event = MagicMock()
        event.data = {"new_state": new_state_mock}

        # Physical heater state mock
        t.hass.states.get.return_value = new_state_mock

        t._async_heater_entity_changed(event)
        await asyncio.sleep(0.01)

        t.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.real_compressor"}, blocking=False
        )

    asyncio.run(_test())


def test_heater_entity_changed_ignored_during_active_heating(reconciliation_config):
    """Physical ON event during authorized RUNNING_MIN_LOCK is ignored."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        t._fsm_state = FSM_RUNNING_MIN_LOCK

        new_state_mock = MagicMock()
        new_state_mock.state = "on"
        event = MagicMock()
        event.data = {"new_state": new_state_mock}

        t._async_heater_entity_changed(event)
        await asyncio.sleep(0.01)

        t.hass.services.async_call.assert_not_called()

    asyncio.run(_test())
