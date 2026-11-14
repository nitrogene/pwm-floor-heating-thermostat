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
    CONF_PEAK_MAX_RUN_DURATION,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
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


def test_f01_preserve_30min_min_lock_across_reload_and_reconciliation(reconciliation_config):
    """[F-01] Restoring FSM_RUNNING_MIN_LOCK within 30-min lock protects compressor from turn_off."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        now = datetime.now(UTC)

        # Simulate compressor started 10 minutes ago (within 30-min Danfoss oil lock)
        start_ts = now - timedelta(minutes=10)
        t._cycle_start_time = start_ts
        t._last_state_change = start_ts
        t._cycles_today = 2
        t._hours_run_today = 1.5
        t._fsm_state = FSM_RUNNING_MIN_LOCK

        # Persist and restore into a brand new instance
        persisted = t._build_persisted_state()
        assert persisted["fsm_state"] == FSM_RUNNING_MIN_LOCK
        assert persisted["cycle_start_time"] is not None

        t2 = _create_thermostat(reconciliation_config)
        # Physical switch is currently ON
        heater_mock = MagicMock()
        heater_mock.state = "on"
        t2.hass.states.get.return_value = heater_mock

        t2._state_store = MagicMock()
        t2._state_store.async_load = AsyncMock(return_value=persisted)
        await t2._async_restore_persisted_store()

        assert t2._fsm_state == FSM_RUNNING_MIN_LOCK
        assert t2._cycles_today == 2

        # Even if _async_stop_heating_safe is called while within 30-min lock, it must NOT turn off
        await t2._async_stop_heating_safe()
        t2.hass.services.async_call.assert_not_called()
        assert t2._fsm_state == FSM_RUNNING_MIN_LOCK

        # Even if FSM was somehow IDLE while cycle_start_time is 10 min ago and switch is ON,
        # reconciliation in _async_stop_heating_safe must promote back to FSM_RUNNING_MIN_LOCK
        t2._fsm_state = FSM_IDLE
        await t2._async_stop_heating_safe()
        t2.hass.services.async_call.assert_not_called()
        assert t2._fsm_state == FSM_RUNNING_MIN_LOCK

    asyncio.run(_test())


def test_f03_peak_max_run_duration_numeric_minutes_unit(reconciliation_config):
    """[F-03] Numeric CONF_PEAK_MAX_RUN_DURATION from OptionsFlow is parsed in minutes, not seconds."""
    cfg = dict(reconciliation_config)
    cfg[CONF_PEAK_MAX_RUN_DURATION] = 45  # 45 minutes from OptionsFlow NumberSelector
    t = _create_thermostat(cfg)

    assert t._peak_max_run_duration == timedelta(minutes=45)
    assert t.extra_state_attributes["peak_max_run_duration_min"] == 45

    # Also test string numeric "60" and dict {"minutes": 30}
    cfg2 = dict(reconciliation_config)
    cfg2[CONF_PEAK_MAX_RUN_DURATION] = "60"
    t2 = _create_thermostat(cfg2)
    assert t2._peak_max_run_duration == timedelta(minutes=60)

    cfg3 = dict(reconciliation_config)
    cfg3[CONF_PEAK_MAX_RUN_DURATION] = {"minutes": 30}
    t3 = _create_thermostat(cfg3)
    assert t3._peak_max_run_duration == timedelta(minutes=30)


def test_f02_closed_loop_heater_rejection_reverts_to_idle_and_rolls_back_cycle(
    reconciliation_config,
):
    """[F-02] If hardware rejects turn_on (switch stays 'off'), revert to IDLE without phantom run hours."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        now = datetime.now(UTC)

        # Simulate start_heating_safe called 90 seconds ago, but hardware stayed OFF (e.g. Guition MANUAL)
        t._fsm_state = FSM_RUNNING_MIN_LOCK
        t._last_state_change = now - timedelta(seconds=90)
        t._cycle_start_time = now - timedelta(seconds=90)
        t._cycles_today = 1
        t._hours_run_today = 0.0

        heater_mock = MagicMock()
        heater_mock.state = "off"
        t.hass.states.get.return_value = heater_mock

        # Next evaluation calls _async_start_heating_safe while still demanding heat
        await t._async_start_heating_safe()

        assert t._fsm_state == FSM_IDLE
        assert t._cycles_today == 0
        assert t._hours_run_today == 0.0
        assert t._cycle_start_time is None

    asyncio.run(_test())


def test_f02_external_stop_mid_cycle_transitions_to_waiting_min_off(reconciliation_config):
    """[F-02] If heater is turned off externally after running >= 5 min, record actual runtime and lock off."""
    async def _test():
        t = _create_thermostat(reconciliation_config)
        now = datetime.now(UTC)

        # Compressor ran for 36 minutes (past 30-min lock), then was turned off externally
        t._fsm_state = FSM_RUNNING_NORMAL
        t._last_state_change = now - timedelta(minutes=36)
        t._cycle_start_time = now - timedelta(minutes=36)
        t._cycles_today = 1
        t._hours_run_today = 0.0

        new_state_mock = MagicMock()
        new_state_mock.state = "off"
        event = MagicMock()
        event.data = {"new_state": new_state_mock}
        t.hass.states.get.return_value = new_state_mock

        t._async_heater_entity_changed(event)

        assert t._fsm_state == FSM_WAITING_MIN_OFF
        assert t._cycles_today == 1
        assert pytest.approx(t._hours_run_today, rel=0.05) == 0.6  # 36 min = 0.6 h
        assert t._cycle_start_time is None

    asyncio.run(_test())

