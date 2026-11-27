"""Comprehensive unit and E2E tests for v0.4.0 unified predictive HC/HP energy-balance engine."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import CONF_NAME

from custom_components.pwm_floor_heating_thermostat.climate import (
    PwmFloorHeatingThermostat,
)
from custom_components.pwm_floor_heating_thermostat.config_flow import (
    PwmFloorHeatingConfigFlow,
)
from custom_components.pwm_floor_heating_thermostat.const import (
    CONF_DEAD_TIME,
    CONF_DRY_RUN,
    CONF_HEAT_LOSS,
    CONF_HEATER,
    CONF_OFF_PEAK_COMFORT_MARGIN,
    CONF_OFF_PEAK_DURATION_HOURS,
    CONF_OFF_PEAK_END_ENTITY,
    CONF_OFF_PEAK_SENSOR,
    CONF_OFF_PEAK_START_ENTITY,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_WATTS,
    CONF_SLAB_TIME_CONSTANT,
    CONF_TARGET_SENSOR,
    CONF_WEATHER_ENTITY,
    DECISION_ANTICIPATED_DROP,
    DECISION_ENERGY_BALANCE_SATISFIED,
    DECISION_IDLE,
    DECISION_OFF_PEAK_DEFERRED,
    DECISION_OFF_PEAK_PRECHARGE,
    DECISION_OVERSHOOT_CUTOFF,
    DEMAND_CURVE_TIER_KALATA_DERIVATIVE,
    DEMAND_CURVE_TIER_OUTDOOR_PERSISTENCE,
    DEMAND_CURVE_TIER_WEATHER_API,
    FSM_IDLE,
    FSM_RUNNING_MIN_LOCK,
    FSM_RUNNING_NORMAL,
)


@pytest.fixture
def base_config():
    """Create a realistic v0.4.0 zone configuration (Chambre-like)."""
    return {
        CONF_NAME: "Thermostat Chambre PWM",
        CONF_TARGET_SENSOR: "sensor.temperature_chambre",
        CONF_OUTDOOR_SENSOR: "sensor.temperature_exterieure_anticipee",
        CONF_WEATHER_ENTITY: "weather.meteo_france",
        CONF_OFF_PEAK_SENSOR: "binary_sensor.heures_creuses_nuit",
        CONF_OFF_PEAK_START_ENTITY: "input_datetime.hc_debut",
        CONF_OFF_PEAK_END_ENTITY: "input_datetime.hc_fin",
        CONF_OFF_PEAK_DURATION_HOURS: 8.0,
        CONF_OFF_PEAK_COMFORT_MARGIN: 0.3,
        CONF_HEATER: "switch.compresseur_chambre",
        CONF_HEAT_LOSS: 8.5,
        CONF_POWER_WATTS: 3250.0,
        CONF_SLAB_TIME_CONSTANT: 15.0,
        CONF_DEAD_TIME: 2.0,
        CONF_DRY_RUN: True,
    }


def _mock_hass_states(state_map: dict[str, tuple[str, dict | None]]):
    """Build a mock hass with states.get backed by a dictionary."""
    hass = MagicMock()

    def _get(entity_id):
        if entity_id not in state_map:
            return None
        val, attrs = state_map[entity_id]
        st = MagicMock()
        st.state = val
        st.attributes = attrs or {}
        return st

    hass.states.get = MagicMock(side_effect=_get)
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock(return_value={})
    hass.data = {}
    return hass


def test_config_flow_requires_weather_entity():
    """Verify ConfigFlow rejects submission when weather_entity is missing."""

    async def _test():
        flow = PwmFloorHeatingConfigFlow()
        result = await flow.async_step_user(
            user_input={
                CONF_NAME: "Test Zone",
                CONF_TARGET_SENSOR: "sensor.room",
                CONF_OUTDOOR_SENSOR: "sensor.ext",
                CONF_DRY_RUN: True,
            }
        )
        assert result["type"] == "form"
        assert result["errors"][CONF_WEATHER_ENTITY] == "missing_weather_entity"

    asyncio.run(_test())


def test_three_tier_demand_curve_fallback(base_config):
    """Verify strict 3-tier fallback: weather_api -> outdoor_persistence -> kalata_derivative."""

    async def _test():
        t0 = datetime(2026, 11, 25, 10, 0, 0, tzinfo=UTC)

        # Tier 1: Weather API hourly forecast
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 6.0}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._cur_temp = 19.0
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 8.0

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        assert thermostat._demand_curve_tier == DEMAND_CURVE_TIER_WEATHER_API
        assert thermostat._weather_outage_fallback_active is False
        assert thermostat._forecast_outdoor_temp_24h == 6.0
        # 8.5 * (19.0 - 6.0) * 24 / 1000 = 2.652 kWh
        assert thermostat._forecast_energy_need_24h_kwh == 2.65

        # Tier 2: Weather API unavailable & cache empty -> outdoor_sensor persistence
        thermostat._weather_forecast_curve = []
        thermostat._weather_forecast_cache_ts = None
        hass_t2 = _mock_hass_states(
            {
                "weather.meteo_france": ("unavailable", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {}),
            }
        )
        thermostat.hass = hass_t2
        thermostat._outdoor_temp = 9.0
        thermostat._outdoor_history_24h = [
            (t0 - timedelta(hours=3), 9.0),
            (t0 - timedelta(hours=2), 9.0),
            (t0 - timedelta(hours=1), 9.0),
        ]

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        assert thermostat._demand_curve_tier == DEMAND_CURVE_TIER_OUTDOOR_PERSISTENCE
        assert thermostat._weather_outage_fallback_active is True
        assert thermostat._forecast_outdoor_temp_24h == 9.0
        # 8.5 * (19.0 - 9.0) * 24 / 1000 = 2.04 kWh
        assert thermostat._forecast_energy_need_24h_kwh == 2.04

        # Tier 3: Outdoor sensor also missing -> Kalata passive cooling derivative
        thermostat._outdoor_temp = None
        thermostat._derivative_smooth = -0.15
        thermostat._observer_last_update = t0

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        assert thermostat._demand_curve_tier == DEMAND_CURVE_TIER_KALATA_DERIVATIVE
        assert thermostat._forecast_outdoor_temp_24h is None
        # c_eff = max(0.5, 8.5*15/1000) = 0.5 kWh/K -> 0.5 * 0.15 * 24 = 1.8 kWh
        assert thermostat._forecast_energy_need_24h_kwh == 1.8

    asyncio.run(_test())


def test_end_of_off_peak_scheduling_and_comfort_ceiling(base_config):
    """Verify HC defers charge to end of window, starts on time, and respects +0.3°C ceiling."""

    async def _test():
        # HC window: 21:00 UTC -> 05:00 UTC (8h). Current time: 22:00 UTC (7h before HC end)
        t_early = datetime(2026, 11, 24, 22, 0, 0, tzinfo=UTC)
        t_hc_end = datetime(2026, 11, 25, 5, 0, 0, tzinfo=UTC)

        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": (
                    "on",
                    {"next_end": t_hc_end.isoformat()},
                ),
            }
        )
        forecasts = [
            {"datetime": (t_early + timedelta(hours=i)).isoformat(), "temperature": 6.7}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 7.0

        # Case 1: Room is at 19.3°C (>= target + 0.3°C HC comfort margin) -> must NOT heat!
        thermostat._cur_temp = 19.3
        with patch("homeassistant.util.dt.utcnow", return_value=t_early):
            await thermostat._async_control_heating(now=t_early)
        assert thermostat._decision_key == DECISION_OVERSHOOT_CUTOFF
        assert thermostat._fsm_state == FSM_IDLE

        # Case 2: Room is at 19.0°C at 22:00 UTC, only ~0.77h needed -> deferred to end of HC!
        thermostat._cur_temp = 19.0
        thermostat._filtered_temp = 19.0
        thermostat._temp_projected = 19.0
        with patch("homeassistant.util.dt.utcnow", return_value=t_early):
            await thermostat._async_control_heating(now=t_early)
        assert thermostat._decision_key == DECISION_OFF_PEAK_DEFERRED
        assert thermostat._fsm_state == FSM_IDLE
        assert thermostat._scheduled_off_peak_start_time is not None
        assert thermostat._scheduled_off_peak_start_time > t_early

        # Case 3: Advance to 04:20 UTC (40 min before HC end) -> starts charging!
        t_late = datetime(2026, 11, 25, 4, 20, 0, tzinfo=UTC)
        with patch("homeassistant.util.dt.utcnow", return_value=t_late):
            await thermostat._async_control_heating(now=t_late)
        assert thermostat._decision_key == DECISION_OFF_PEAK_PRECHARGE
        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK

    asyncio.run(_test())


def test_slab_in_transit_energy_prevents_back_to_back_overheating(base_config):
    """Verify slab energy in transit stops HC charging once horizon energy is injected."""

    async def _test():
        t0 = datetime(2026, 11, 25, 4, 0, 0, tzinfo=UTC)
        t_hc_end = datetime(2026, 11, 25, 5, 0, 0, tzinfo=UTC)

        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("on", {"next_end": t_hc_end.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 6.7}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 19.0
        thermostat._outdoor_temp = 6.7

        # Simulate compressor already ran 48 minutes (~2.6 kWh injected into slab)
        thermostat._fsm_state = FSM_RUNNING_NORMAL
        thermostat._cycle_start_time = t0 - timedelta(minutes=48)
        thermostat._last_state_change = t0 - timedelta(minutes=48)
        thermostat._last_energy_tick_ts = t0
        thermostat._slab_energy_pulses = [(t0 - timedelta(minutes=5), 2.8)]

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        # Energy in transit (~2.72 kWh) exceeds 24h need (~2.51 kWh) -> stops cleanly!
        assert thermostat._slab_energy_in_transit_kwh > 2.5
        assert thermostat._planned_heating_hours == 0.0
        assert thermostat._decision_key == DECISION_ENERGY_BALANCE_SATISFIED
        assert thermostat._fsm_state != FSM_RUNNING_NORMAL

    asyncio.run(_test())


def test_peak_hour_strict_top_up_skips_when_hc_imminent_or_energy_in_transit(base_config):
    """Verify Peak-hour top-up is skipped if energy is in transit or HC starts soon, and fires otherwise."""

    async def _test():
        t0 = datetime(2026, 11, 25, 14, 0, 0, tzinfo=UTC)
        t_hc_soon = t0 + timedelta(minutes=45)
        t_hc_far = t0 + timedelta(hours=8)

        # 1. HC starts in 45 min (< 0.5 * dead_time = 1h) -> skip peak top-up
        hass_soon = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_hc_soon.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 5.0}
            for i in range(24)
        ]
        hass_soon.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass_soon, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.6
        thermostat._temp_projected = 18.4
        thermostat._outdoor_temp = 5.0

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ENERGY_BALANCE_SATISFIED
        assert thermostat._fsm_state == FSM_IDLE

        # 2. HC is 8h away, no energy in transit -> fires strict Peak top-up
        hass_far = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_hc_far.isoformat()}),
            }
        )
        hass_far.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )
        thermostat.hass = hass_far

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ANTICIPATED_DROP
        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK

    asyncio.run(_test())


def test_zero_impact_restart_persistence_store_roundtrip(base_config):
    """Verify Store roundtrip preserves E_transit, outdoor history, weather curve, and post-airing recovery."""

    async def _test():
        t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("unavailable", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {}),
            }
        )

        t1 = PwmFloorHeatingThermostat(hass, base_config)
        t1._slab_energy_pulses = [(t0 - timedelta(minutes=30), 2.0)]
        t1._last_energy_tick_ts = t0 - timedelta(minutes=30)
        t1._outdoor_history_24h = [
            (t0 - timedelta(hours=2), 7.0),
            (t0 - timedelta(hours=1), 7.5),
            (t0, 8.0),
        ]
        t1._weather_forecast_curve = [
            (t0 + timedelta(hours=i), 6.5) for i in range(12)
        ]
        t1._weather_forecast_cache_ts = t0
        t1._window_open = False
        t1._was_window_open = False
        t1._window_recovery_until = t0 + timedelta(minutes=35)
        t1._filtered_temp = 19.2
        t1._temp_history = [(t0 - timedelta(minutes=5), 17.5), (t0, 17.8)]

        persisted = t1._build_persisted_state()

        # Simulate HA restart 10 minutes later during a brief weather API outage
        t_reboot = t0 + timedelta(minutes=10)
        t2 = PwmFloorHeatingThermostat(hass, base_config)
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=persisted)
        t2._state_store = mock_store

        with patch("homeassistant.util.dt.utcnow", return_value=t_reboot):
            await t2._async_restore_persisted_store()

            # 1. Slab in-transit energy restored with 10 min downtime accurately subtracted (40 min age / 180 min)
            assert len(t2._slab_energy_pulses) == 1
            assert 1.5 <= t2._slab_energy_in_transit_kwh <= 1.6

            # 2. Outdoor history & weather forecast curve restored
            assert len(t2._outdoor_history_24h) == 3
            assert len(t2._weather_forecast_curve) == 12

            # 3. Post-airing recovery preserved -> room at 17.4°C must NOT trigger emergency_deficit
            assert t2._window_recovery_until == t0 + timedelta(minutes=35)
            t2._cur_temp = 17.4
            t2._target_temp = 19.0
            t2._outdoor_temp = 8.0
            await t2._async_control_heating(now=t_reboot)
            assert t2._demand_curve_tier == DEMAND_CURVE_TIER_WEATHER_API
            assert "Emergency comfort deficit" not in t2._decision_reason

    asyncio.run(_test())


def test_decision_key_resets_to_idle_when_room_stabilizes(base_config):
    """Verify decision_key returns to idle on next tick instead of sticking to energy_balance_satisfied."""

    async def _test():
        t0 = datetime(2026, 11, 25, 11, 0, 0, tzinfo=UTC)
        t_next_hc = datetime(2026, 11, 25, 21, 6, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_next_hc.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 6.5}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._outdoor_temp = 7.5
        thermostat._slab_energy_pulses = [(t0, 2.2)]

        # Tick 1: room slightly cold (18.6°C), but covered by E_transit -> energy_balance_satisfied
        thermostat._cur_temp = 18.6
        thermostat._temp_projected = 18.5
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ENERGY_BALANCE_SATISFIED

        # Tick 2: room warms up to 19.2°C (stable) -> must transition cleanly back to idle!
        t1 = t0 + timedelta(minutes=15)
        thermostat._cur_temp = 19.2
        thermostat._filtered_temp = 19.2
        thermostat._temp_projected = 19.3
        with patch("homeassistant.util.dt.utcnow", return_value=t1):
            await thermostat._async_control_heating(now=t1)
        assert thermostat._decision_key == DECISION_IDLE
        assert "Idle (stable trajectory" in thermostat._decision_reason

    asyncio.run(_test())


def test_peak_cycle_latch_prevents_energy_balance_abort_and_runs_to_peak_cap(base_config):
    """[M-07] An active Peak-hour anticipated_drop cycle must not be aborted at t+1 min by rising E_transit."""

    async def _test():
        from custom_components.pwm_floor_heating_thermostat.const import (
            DECISION_PEAK_CYCLE_CAP,
            FSM_WAITING_MIN_OFF,
        )

        t0 = datetime(2026, 11, 26, 6, 58, 0, tzinfo=UTC)
        t_next_hc = datetime(2026, 11, 26, 21, 6, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_next_hc.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 4.0}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.5
        thermostat._temp_projected = 18.3
        thermostat._outdoor_temp = 4.0
        thermostat._peak_max_run_duration = timedelta(minutes=45)

        # Tick 1 (t0): meaningful deficit -> starts anticipated_drop and latches cycle start key
        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ANTICIPATED_DROP
        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK
        assert thermostat._cycle_start_decision_key == DECISION_ANTICIPATED_DROP

        # Tick 2 (t0 + 1 min): inject large E_transit so net_energy_needed_kwh == 0.0
        # Latch must keep anticipated_drop active instead of flipping to energy_balance_satisfied
        t1 = t0 + timedelta(minutes=1)
        thermostat._slab_energy_pulses = [(t1, 6.0)]
        with patch("homeassistant.util.dt.utcnow", return_value=t1):
            await thermostat._async_control_heating(now=t1)
        assert thermostat._planned_heating_hours == 0.0
        assert thermostat._decision_key == DECISION_ANTICIPATED_DROP
        assert thermostat._fsm_state == FSM_RUNNING_MIN_LOCK

        # Tick 3 (t0 + 32 min): past Danfoss 30-min lock, still latched -> continues running toward 45-min cap
        t32 = t0 + timedelta(minutes=32)
        thermostat._slab_energy_pulses = [(t32, 6.0)]
        with patch("homeassistant.util.dt.utcnow", return_value=t32):
            await thermostat._async_control_heating(now=t32)
        assert thermostat._decision_key == DECISION_ANTICIPATED_DROP
        assert thermostat._fsm_state == FSM_RUNNING_NORMAL

        # Tick 4 (t0 + 46 min): peak_max_run_duration (45 min) reached -> stops cleanly and clears latch
        t46 = t0 + timedelta(minutes=46)
        with patch("homeassistant.util.dt.utcnow", return_value=t46):
            await thermostat._async_control_heating(now=t46)
        assert thermostat._decision_key == DECISION_PEAK_CYCLE_CAP
        assert thermostat._fsm_state == FSM_WAITING_MIN_OFF
        assert thermostat._cycle_start_decision_key is None

    asyncio.run(_test())


def test_peak_hour_ignores_negligible_energy_deficit_below_rule_b_threshold(base_config):
    """[M-07] Peak-hour entry requires delta_t_equiv >= rule_b_threshold (no startup on tiny kWh noise)."""

    async def _test():
        t0 = datetime(2026, 11, 26, 14, 0, 0, tzinfo=UTC)
        t_next_hc = datetime(2026, 11, 26, 21, 6, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_next_hc.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 5.0}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.6
        thermostat._temp_projected = 18.3
        thermostat._outdoor_temp = 5.0
        thermostat._model_error_rms = 0.30  # rule_b_threshold = 0.60°C

        # Set E_transit just 0.02 kWh below horizon need -> net_energy_needed_kwh > 0 but delta_t_equiv << 0.60°C
        c_eff = thermostat._effective_thermal_capacity_kwh_k()
        hourly_loss_kw = thermostat._effective_heat_loss * (19.0 - 5.0) / 1000.0
        horizon_kwh = hourly_loss_kw * 7.1
        room_excess_kwh = c_eff * (18.6 - 19.0)
        e_transit_almost_full = max(0.0, horizon_kwh - room_excess_kwh - 0.02)
        thermostat._slab_energy_pulses = [(t0, e_transit_almost_full)]

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ENERGY_BALANCE_SATISFIED
        assert thermostat._fsm_state == FSM_IDLE

    asyncio.run(_test())


def test_off_peak_cycle_not_latched_into_peak_when_balance_met(base_config):
    """[M-07] A cycle started by off_peak_precharge must not stay latched into Peak hours once balance is met."""

    async def _test():
        from custom_components.pwm_floor_heating_thermostat.const import (
            DECISION_OFF_PEAK_PRECHARGE,
            FSM_WAITING_MIN_OFF,
        )

        t0 = datetime(2026, 11, 26, 5, 6, 0, tzinfo=UTC)
        t_next_hc = datetime(2026, 11, 26, 21, 6, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {"next_start": t_next_hc.isoformat()}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 5.0}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.6
        thermostat._temp_projected = 18.5
        thermostat._outdoor_temp = 5.0
        # Simulate HC precharge cycle already past 30-min lock with full slab energy in transit
        thermostat._fsm_state = FSM_RUNNING_NORMAL
        thermostat._cycle_start_time = t0 - timedelta(minutes=45)
        thermostat._last_state_change = t0 - timedelta(minutes=45)
        thermostat._cycle_start_decision_key = DECISION_OFF_PEAK_PRECHARGE
        thermostat._slab_energy_pulses = [(t0, 6.0)]

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._decision_key == DECISION_ENERGY_BALANCE_SATISFIED
        assert thermostat._fsm_state == FSM_WAITING_MIN_OFF
        assert thermostat._cycle_start_decision_key is None

    asyncio.run(_test())


def test_non_circular_24h_energy_balance_heat_loss_calibration(base_config):
    """[v0.4.3] Rolling 24h energy-balance calibration measures true H (W/K) independent of initial H."""

    async def _test():
        t0 = datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("off", {}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 4.7}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        cfg = dict(base_config)
        cfg["heat_loss_wk"] = 13.1  # Intentionally underestimated initial H
        cfg["power_watts"] = 6500.0
        cfg["auto_calibrate_heat_loss"] = False

        thermostat = PwmFloorHeatingThermostat(hass, cfg)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.8
        thermostat._outdoor_temp = 4.7

        # Populate 23 hourly snapshots over 23h with 40.82 kWh injected (~6.28h at 6.5 kW) at ΔT = 14.1 K
        thermostat._energy_balance_history = [
            (t0 - timedelta(hours=24 - i), (40.82 * i) / 24.0, 18.8, 4.7)
            for i in range(24)
        ]
        thermostat._cumulative_injected_kwh = 40.82

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)

        # True H = 40820 Wh / (24h * 14.1 K) = 120.6 W/K (completely independent of configured 13.1 W/K!)
        assert thermostat._heat_loss_measured_wk is not None
        assert 115.0 <= thermostat._heat_loss_measured_wk <= 126.0
        assert thermostat._heat_loss_samples_count == 1
        # Because auto_calibrate_heat_loss is False, effective H stays strictly at configured baseline
        assert thermostat._effective_heat_loss == 13.1

    asyncio.run(_test())


def test_temp_projected_includes_slab_energy_in_transit_when_cooling(base_config):
    """[v0.4.3] T_projected reflects net slab energy in transit when heat wave has not yet accelerated dT/dt."""
    t0 = datetime(2026, 11, 27, 8, 0, 0, tzinfo=UTC)
    hass = _mock_hass_states({})
    thermostat = PwmFloorHeatingThermostat(hass, base_config)
    thermostat._cur_temp = 18.8
    thermostat._filtered_temp = 18.8
    thermostat._outdoor_temp = 3.0
    thermostat._temp_derivative = -0.04
    thermostat._derivative_smooth = -0.04
    thermostat._observer_last_update = t0 - timedelta(minutes=5)

    # Without E_transit: pure linear extrapolation (~18.72°C)
    thermostat._slab_energy_in_transit_kwh = 0.0
    thermostat._update_trajectory_projection(t0)
    proj_without = thermostat._temp_projected

    # With 2.0 kWh in transit: net transit boost lifts T_projected (bounded <= +0.5°C)
    thermostat._slab_energy_in_transit_kwh = 2.0
    thermostat._observer_last_update = t0
    thermostat._update_trajectory_projection(t0 + timedelta(minutes=1))
    proj_with = thermostat._temp_projected

    assert proj_with > proj_without
    assert (proj_with - proj_without) <= 0.55


def test_dead_time_calibration_requires_relaxed_slab_rest(base_config):
    """[v0.4.3] Dead-time inflection samples are rejected after back-to-back cycles and accepted after rest."""

    async def _test():
        t0 = datetime(2026, 11, 27, 2, 0, 0, tzinfo=UTC)
        hass = _mock_hass_states(
            {
                "weather.meteo_france": ("cloudy", {}),
                "binary_sensor.heures_creuses_nuit": ("on", {}),
            }
        )
        forecasts = [
            {"datetime": (t0 + timedelta(hours=i)).isoformat(), "temperature": 3.0}
            for i in range(24)
        ]
        hass.services.async_call = AsyncMock(
            return_value={"weather.meteo_france": {"forecast": forecasts}}
        )

        thermostat = PwmFloorHeatingThermostat(hass, base_config)
        thermostat._hvac_mode = HVACMode.HEAT
        thermostat._target_temp = 19.0
        thermostat._cur_temp = 18.6
        thermostat._outdoor_temp = 3.0

        # 1. Back-to-back cycle (not started from rest) -> inflection ignored
        thermostat._fsm_state = FSM_RUNNING_NORMAL
        thermostat._cycle_start_time = t0 - timedelta(hours=1.2)
        thermostat._last_state_change = t0 - timedelta(hours=1.2)
        thermostat._cycle_started_from_rest = False
        thermostat._heating_start_derivative = -0.05
        thermostat._filtered_temp = 18.6
        thermostat._temp_derivative = 0.08
        thermostat._derivative_smooth = 0.08
        thermostat._observer_last_update = t0 - timedelta(seconds=30)

        with patch("homeassistant.util.dt.utcnow", return_value=t0):
            await thermostat._async_control_heating(now=t0)
        assert thermostat._dead_time_measured_hours is None
        assert thermostat._dead_time_samples_count == 0

        # 2. Cycle started after relaxed slab (>= 2 * theta rest) -> inflection accepted (~1.2h)
        thermostat._cycle_started_from_rest = True
        thermostat._heating_start_derivative = -0.05
        thermostat._temp_derivative = 0.08
        thermostat._derivative_smooth = 0.08
        thermostat._observer_last_update = t0

        t1 = t0 + timedelta(seconds=30)
        with patch("homeassistant.util.dt.utcnow", return_value=t1):
            await thermostat._async_control_heating(now=t1)
        assert thermostat._dead_time_measured_hours is not None
        assert 1.1 <= thermostat._dead_time_measured_hours <= 1.3
        assert thermostat._dead_time_samples_count == 1

    asyncio.run(_test())
