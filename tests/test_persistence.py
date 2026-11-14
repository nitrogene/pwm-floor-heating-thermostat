"""Unit tests for self-contained Store persistence across restarts."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID

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
)


def _make_thermostat(hass: MagicMock, unique_id: str = "pwm_persist_test") -> PwmFloorHeatingThermostat:
    """Create a thermostat instance wired to a mock hass."""
    config = {
        CONF_NAME: "Salon Persistence Test",
        CONF_UNIQUE_ID: unique_id,
        CONF_TARGET_SENSOR: "sensor.salon_temp",
        CONF_OUTDOOR_SENSOR: "sensor.ext_temp",
        CONF_HEATER: "switch.salon_heater",
        CONF_HEAT_LOSS: 15.0,
        CONF_POWER_WATTS: 6500.0,
        CONF_DEAD_TIME: 2.25,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DRY_RUN: True,
    }
    thermostat = PwmFloorHeatingThermostat(hass, config)
    thermostat.hass = hass
    return thermostat


def _make_hass(now_utc: datetime) -> MagicMock:
    """Create a mock Home Assistant object with running=False to avoid background task spawning."""
    hass = MagicMock()
    hass.is_running = False
    hass.states.get.return_value = None
    hass.bus.async_listen_once.return_value = lambda: None
    return hass


def test_store_roundtrip_preserves_histories_and_observer_state() -> None:
    """Verify histories, observer state, and sample counts survive unload and reload."""
    now_utc = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    hass = _make_hass(now_utc)

    t1 = _make_thermostat(hass, unique_id="salon_roundtrip_1")
    t1._projection_history = [
        (now_utc - timedelta(hours=3), 19.2),
        (now_utc - timedelta(hours=1), 19.8),
        (now_utc - timedelta(hours=10), 17.5),  # expired (> 5.5h)
    ]
    t1._model_error_history = [
        (now_utc - timedelta(hours=2), 0.3),
        (now_utc - timedelta(hours=1), -0.4),
        (now_utc - timedelta(hours=30), 2.5),  # expired (> 24h)
    ]
    t1._filtered_temp = 19.45
    t1._temp_derivative = 0.18
    t1._derivative_smooth = 0.14
    t1._observer_last_update = now_utc - timedelta(minutes=2)
    t1._heat_loss_samples_count = 14
    t1._heat_loss_measured_wk = 13.1
    t1._dead_time_samples_count = 3
    t1._dead_time_measured_hours = 2.15

    with patch("custom_components.pwm_floor_heating_thermostat.climate.dt_util.utcnow", return_value=now_utc):
        asyncio.run(t1.async_will_remove_from_hass())

        t2 = _make_thermostat(hass, unique_id="salon_roundtrip_1")
        t2.async_get_last_state = AsyncMock(return_value=None)
        asyncio.run(t2.async_added_to_hass())

    assert len(t2._projection_history) == 2
    assert t2._projection_history[0][1] == 19.2
    assert t2._projection_history[1][1] == 19.8

    assert len(t2._model_error_history) == 2
    # RMS of [0.3, -0.4] = sqrt((0.09 + 0.16) / 2) = sqrt(0.125) ~= 0.35
    assert t2._model_error_rms == 0.35

    assert t2._filtered_temp == 19.45
    assert t2._temp_derivative == 0.18
    assert t2._derivative_smooth == 0.14
    assert t2._observer_last_update == now_utc - timedelta(minutes=2)
    assert t2._heat_loss_samples_count == 14
    assert t2._heat_loss_measured_wk == 13.1
    assert t2._dead_time_samples_count == 3
    assert t2._dead_time_measured_hours == 2.15


def test_restore_entity_fallback_samples_and_no_filtered_temp_pollution() -> None:
    """Verify RestoreEntity restores heat_loss_samples_count without polluting _filtered_temp."""
    now_utc = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    hass = _make_hass(now_utc)

    t = _make_thermostat(hass, unique_id="salon_fallback_2")
    last_state = SimpleNamespace(
        state="heat",
        attributes={
            "temperature": 19.0,
            "temp_projected_ahead": 21.6,
            "temp_derivative_hourly": 0.4,
            "heat_loss_measured_wk": 13.1,
            "heat_loss_samples_count": 12,
        },
    )
    t.async_get_last_state = AsyncMock(return_value=last_state)

    with patch("custom_components.pwm_floor_heating_thermostat.climate.dt_util.utcnow", return_value=now_utc):
        asyncio.run(t.async_added_to_hass())

    assert t._temp_projected == 21.6
    assert t._filtered_temp is None
    assert t._heat_loss_measured_wk == 13.1
    assert t._heat_loss_samples_count == 12
