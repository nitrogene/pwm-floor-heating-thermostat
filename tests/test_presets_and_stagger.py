"""Tests unitaires pour les modes Presets (Comfort, Eco, Away) et le déphasage Anti-Pic Multi-Zones."""

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
    """Simule la sélection de consigne selon le preset et le filtre de déphasage."""
    # 1. Consigne active
    if active_preset == "eco":
        target = eco_temp
    elif active_preset == "away":
        target = away_temp
    else:
        target = comfort_temp

    # 2. Demande de chauffe
    error = target - cur_temp
    projected_error = target - temp_projected
    should_heat = False
    reason = "Idle"

    if projected_error > 0.15 or error > 0.2:
        should_heat = True
        reason = f"Heating needed for {target}°C"

    # 3. Règle F : Déphasage anti-pic
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
    """Vérifie que les modes presets appliquent les consignes respectives sans écraser la base."""
    now = datetime.now(UTC)

    # 1. Mode Comfort (base 19.0°C)
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

    # 2. Bascule en Mode Eco (17.0°C) -> Avec 18.0°C réels, la chauffe n'est plus nécessaire
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

    # 3. Bascule en Mode Away (15.0°C)
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
    """Vérifie que le compresseur temporise son démarrage pendant la durée configurée."""
    t0 = datetime.now(UTC)

    # À t=0, la demande apparaît, mais le déphasage est de 300s (5 min)
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

    # À t=150s (2 min 30), toujours en temporisation
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

    # À t=301s (> 5 min), le déphasage est écoulé, le compresseur est autorisé à démarrer
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
