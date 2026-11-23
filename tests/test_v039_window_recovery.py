"""Tests for Kalata observer freeze and passive rebound handling during/after window airing."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import PwmFloorHeatingThermostat
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_COMFORT_TEMP,
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_OUTDOOR_SENSOR,
    CONF_POST_AIRING_RECOVERY_MINUTES,
    CONF_POST_AIRING_RECOVERY_TOLERANCE,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    CONF_WINDOW_DETECTION,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_TIMEOUT,
    DECISION_IDLE,
    DECISION_WINDOW_OPEN,
)


def _make_thermostat(hass, extra_config=None):
    config = {
        CONF_NAME: "Test Chambre",
        CONF_TARGET_SENSOR: "sensor.chambre_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.chambre_heater",
        CONF_WINDOW_SENSOR: "binary_sensor.chambre_window",
        CONF_WINDOW_DETECTION: True,
        CONF_HEAT_LOSS: 8.5,
        CONF_POWER_WATTS: 3250.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_COMFORT_TEMP: 19.0,
        CONF_DRY_RUN: False,
    }
    if extra_config:
        config.update(extra_config)
    t = PwmFloorHeatingThermostat(hass, config)
    t._hvac_mode = HVACMode.HEAT
    t._target_temp = 19.0
    t._outdoor_temp = 9.0
    t.async_write_ha_state = MagicMock()
    return t


def test_observer_frozen_during_airing_and_passive_recovery():
    """Verify Kalata observer freezes during window open and 30-min passive rebound without false heating."""

    async def _test():
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.data = {}

        win_state = MagicMock()
        win_state.state = "off"
        ext_state = MagicMock()
        ext_state.state = "9.0"

        def get_state(eid):
            if eid == "binary_sensor.chambre_window":
                return win_state
            if eid == "sensor.ext_temp":
                return ext_state
            return None

        hass.states.get.side_effect = get_state
        t = _make_thermostat(hass)

        t0 = datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC)

        # 1. Room steady at 19.4°C before window opens
        t._cur_temp = 19.4
        t._cur_temp_ts = t0
        t._update_trajectory_projection(t0)
        assert t._filtered_temp == 19.4
        assert t._temp_projected == 19.4

        # 2. Window opens for 20 min, air drops to 15.4°C
        win_state.state = "on"
        for step, temp in enumerate([18.4, 16.9, 15.4], start=1):
            now = t0 + timedelta(minutes=5 * step)
            t._cur_temp = temp
            t._cur_temp_ts = now
            with patch("homeassistant.util.dt.utcnow", return_value=now):
                t._check_window_open_state(now)
                t._update_trajectory_projection(now)
                await t._async_control_heating(now=now)
            assert t._window_open is True
            assert t._decision_key == DECISION_WINDOW_OPEN
            # Pre-airing slab temperature and projection remain intact
            assert t._filtered_temp == 19.4
            assert t._temp_projected == 19.4
            assert t._derivative_smooth == 0.0

        # 3. Window closes at t0 + 20m; air rebounds passively 15.4 -> 18.5°C over 25 min
        win_state.state = "off"
        t_close = t0 + timedelta(minutes=20)
        for step, temp in enumerate([15.9, 16.9, 17.8, 18.5], start=0):
            now = t_close + timedelta(minutes=7 * step)
            t._cur_temp = temp
            t._cur_temp_ts = now
            with patch("homeassistant.util.dt.utcnow", return_value=now):
                t._check_window_open_state(now)
                t._update_trajectory_projection(now)
                await t._async_control_heating(now=now)
            assert t._window_open is False
            assert t._temp_projected == 19.4
            assert t._derivative_smooth == 0.0
            assert t._decision_key == DECISION_IDLE
            assert t._simulated_heater_state is False

        # 4. After 45-min default recovery window, observer realigns cleanly on stabilized room air (18.9°C)
        t_after = t_close + timedelta(minutes=46)
        t._cur_temp = 18.9
        t._cur_temp_ts = t_after
        with patch("homeassistant.util.dt.utcnow", return_value=t_after):
            t._update_trajectory_projection(t_after)
        assert t._window_recovery_until is None
        assert t._filtered_temp == 18.9
        assert t._temp_projected == 18.9
        assert t._derivative_smooth == 0.0

    asyncio.run(_test())


def test_post_airing_recovery_early_exit_and_timeout_transition():
    """Verify early exit within tolerance and immediate recovery arming on software timeout."""

    async def _test():
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.data = {}
        ext_state = MagicMock()
        ext_state.state = "6.0"
        hass.states.get.side_effect = lambda eid: ext_state if eid == "sensor.ext_temp" else None

        # Software window detection (no binary_sensor) with custom 60-min recovery & 0.2°C tolerance
        t = _make_thermostat(
            hass,
            {
                CONF_WINDOW_SENSOR: None,
                CONF_WINDOW_TIMEOUT: timedelta(minutes=30),
                CONF_POST_AIRING_RECOVERY_MINUTES: 60,
                CONF_POST_AIRING_RECOVERY_TOLERANCE: 0.2,
            },
        )
        t0 = datetime(2026, 11, 23, 17, 0, 0, tzinfo=UTC)

        # Steady at 19.0°C
        t._cur_temp = 19.0
        t._cur_temp_ts = t0
        t._update_trajectory_projection(t0)

        # Sudden drop to 17.0°C triggers window_open (deficit = 2.0°C >= emergency 1.5°C)
        t_drop = t0 + timedelta(minutes=5)
        t._cur_temp = 17.0
        t._cur_temp_ts = t_drop
        with patch("homeassistant.util.dt.utcnow", return_value=t_drop):
            t._update_trajectory_projection(t_drop)
            t._check_window_open_state(t_drop)
            await t._async_control_heating(now=t_drop)
        assert t._window_open is True
        assert t._decision_key == DECISION_WINDOW_OPEN

        # At t_drop + 30 min, _async_control_heating expires window_timeout WITHOUT prior sensor event:
        # recovery must arm immediately in the same tick, preventing emergency_deficit!
        t_expire = t_drop + timedelta(minutes=30)
        t._cur_temp_ts = t_expire
        with patch("homeassistant.util.dt.utcnow", return_value=t_expire):
            await t._async_control_heating(now=t_expire)
        assert t._window_open is False
        assert t._window_recovery_until == t_expire + timedelta(minutes=60)
        assert t._decision_key == DECISION_IDLE
        assert t._simulated_heater_state is False

        # Early exit: room rebounds to 18.8°C (within 0.2°C of pre-airing 19.0°C) at +15 min
        t_rebound = t_expire + timedelta(minutes=15)
        t._cur_temp = 18.8
        t._cur_temp_ts = t_rebound
        with patch("homeassistant.util.dt.utcnow", return_value=t_rebound):
            t._update_trajectory_projection(t_rebound)
        assert t._window_recovery_until is None
        assert t._filtered_temp == 18.8

    asyncio.run(_test())
