"""Unit tests for presets (Comfort, Eco, Away) and multi-zone staggered startup delay."""

from datetime import UTC, datetime, timedelta


def evaluate_preset_and_stagger(
    cur_temp: float,
    comfort_temp: float,
    eco_temp: float,
    away_temp: float,
    active_preset: str,
    temp_projected: float,
    fsm_state: str,
    stagger_delay_sec: int,
    demand_start_time: datetime | None,
    now: datetime,
) -> tuple[float, bool, str, datetime | None]:
    """Simulate target temperature selection based on active preset and stagger delay filter."""
    # 1. Active target temperature
    if active_preset == "eco":
        target = eco_temp
    elif active_preset == "away":
        target = away_temp
    else:
        target = comfort_temp

    # 2. Heating demand
    error = target - cur_temp
    projected_error = target - temp_projected
    should_heat = False
    reason = "Idle"

    if projected_error > 0.15 or error > 0.2:
        should_heat = True
        reason = f"Heating needed for {target}°C"

    # 3. Rule F: Staggered anti-inrush peak startup delay
    new_demand_start = demand_start_time
    if should_heat and fsm_state == "idle" and stagger_delay_sec > 0:
        if new_demand_start is None:
            new_demand_start = now
        elapsed = (now - new_demand_start).total_seconds()
        if elapsed < stagger_delay_sec:
            rem = int(stagger_delay_sec - elapsed)
            should_heat = False
            reason = f"Staggered startup delay ({rem}s remaining, anti inrush peak protection)"
    elif not should_heat:
        new_demand_start = None

    return target, should_heat, reason, new_demand_start


def test_preset_mode_consigne():
    """Verify preset modes apply their respective target temperatures without overwriting base setting."""
    now = datetime.now(UTC)

    # 1. Comfort mode (base 19.0°C)
    target, should_heat, _, _ = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="comfort",
        temp_projected=18.0,
        fsm_state="idle",
        stagger_delay_sec=0,
        demand_start_time=None,
        now=now,
    )
    assert target == 19.0
    assert should_heat

    # 2. Switch to Eco mode (17.0°C) -> With current 18.0°C, heating is no longer needed
    target_eco, should_heat_eco, _, _ = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="eco",
        temp_projected=18.0,
        fsm_state="idle",
        stagger_delay_sec=0,
        demand_start_time=None,
        now=now,
    )
    assert target_eco == 17.0
    assert not should_heat_eco

    # 3. Switch to Away mode (15.0°C)
    target_away, should_heat_away, _, _ = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="away",
        temp_projected=18.0,
        fsm_state="idle",
        stagger_delay_sec=0,
        demand_start_time=None,
        now=now,
    )
    assert target_away == 15.0
    assert not should_heat_away


def test_stagger_delay_delays_startup():
    """Verify compressor delays activation for the configured stagger duration."""
    t0 = datetime.now(UTC)

    # At t=0, demand appears, but stagger delay is 300s (5 min)
    target, should_heat, reason, demand_start = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="comfort",
        temp_projected=17.5,
        fsm_state="idle",
        stagger_delay_sec=300,
        demand_start_time=None,
        now=t0,
    )
    assert not should_heat
    assert "Staggered startup delay" in reason
    assert demand_start == t0

    # At t=150s (2 min 30s), still waiting in delay window
    t1 = t0 + timedelta(seconds=150)
    _, should_heat_t1, reason_t1, _ = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="comfort",
        temp_projected=17.5,
        fsm_state="idle",
        stagger_delay_sec=300,
        demand_start_time=demand_start,
        now=t1,
    )
    assert not should_heat_t1
    assert "150s remaining" in reason_t1

    # At t=301s (> 5 min), stagger delay has elapsed; compressor is allowed to turn on
    t2 = t0 + timedelta(seconds=301)
    _, should_heat_t2, reason_t2, _ = evaluate_preset_and_stagger(
        cur_temp=18.0,
        comfort_temp=19.0,
        eco_temp=17.0,
        away_temp=15.0,
        active_preset="comfort",
        temp_projected=17.5,
        fsm_state="idle",
        stagger_delay_sec=300,
        demand_start_time=demand_start,
        now=t2,
    )
    assert should_heat_t2
    assert "Heating needed" in reason_t2
