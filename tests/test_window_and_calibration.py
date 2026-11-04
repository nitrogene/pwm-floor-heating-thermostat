"""Tests unitaires pour la détection de fenêtre ouverte et l'auto-calibration passive (Mode A)."""

from datetime import UTC, datetime, timedelta


def evaluate_window_and_calibration_decision(
    cur_temp: float,
    target_temp: float,
    temp_projected: float,
    temp_derivative: float,
    outdoor_temp: float,
    window_open: bool,
    fsm_state: str,
    time_since_stop_hours: float,
    dead_time_hours: float,
    heat_loss_wk: float,
    slab_tau_hours: float,
    current_measured_ua: float | None = None,
) -> tuple[bool, str, float | None]:
    """Simule la logique combinée de fenêtre ouverte et de calibration U*A."""
    error = target_temp - cur_temp
    projected_error = target_temp - temp_projected
    should_heat = False
    reason = "Idle"

    # Décision normale de chauffe
    if projected_error > 0.15 or error > 0.2:
        should_heat = True
        reason = f"Anticipated drop: {temp_projected}°C"

    # Règle E : Fenêtre ouverte
    if window_open:
        should_heat = False
        reason = "Open window / ventilation detected. Heating suspended."

    # Calibration Mode A
    measured_ua = current_measured_ua
    if (
        fsm_state in ["idle", "waiting_min_off"]
        and not window_open
        and cur_temp is not None
        and outdoor_temp is not None
    ):
        required_rest = 2.0 * dead_time_hours
        delta_t = cur_temp - outdoor_temp

        if time_since_stop_hours >= required_rest and delta_t >= 3.0 and temp_derivative < -0.05:
            c_eff = slab_tau_hours * heat_loss_wk
            p_loss = -c_eff * temp_derivative
            sample_ua = p_loss / delta_t

            if 0.3 * heat_loss_wk <= sample_ua <= 3.0 * heat_loss_wk:
                if measured_ua is None:
                    measured_ua = round(sample_ua, 1)
                else:
                    measured_ua = round(0.98 * measured_ua + 0.02 * sample_ua, 1)

    return should_heat, reason, measured_ua


def test_window_open_blocks_heating():
    """Vérifie qu'une fenêtre ouverte suspend immédiatement l'allumage."""
    should_heat, reason, _ = evaluate_window_and_calibration_decision(
        cur_temp=18.5,
        target_temp=19.0,
        temp_projected=18.2,
        temp_derivative=-0.5,
        outdoor_temp=5.0,
        window_open=True,
        fsm_state="idle",
        time_since_stop_hours=1.0,
        dead_time_hours=2.25,
        heat_loss_wk=60.0,
        slab_tau_hours=15.0,
    )
    assert not should_heat
    assert "Open window" in reason


def test_window_closed_resumes_heating():
    """Vérifie que la refermeture de la fenêtre rétablit la demande de chauffe."""
    should_heat, reason, _ = evaluate_window_and_calibration_decision(
        cur_temp=18.5,
        target_temp=19.0,
        temp_projected=18.2,
        temp_derivative=-0.5,
        outdoor_temp=5.0,
        window_open=False,
        fsm_state="idle",
        time_since_stop_hours=1.0,
        dead_time_hours=2.25,
        heat_loss_wk=60.0,
        slab_tau_hours=15.0,
    )
    assert should_heat
    assert "Anticipated drop" in reason


def test_window_auto_detection_slope():
    """Vérifie la détection par rupture brutale de pente sur historique 15 min."""
    now = datetime.now(UTC)
    history = [
        (now - timedelta(minutes=14), 20.2),
        (now - timedelta(minutes=10), 19.9),
        (now - timedelta(minutes=5), 19.6),
        (now, 19.3),  # Chute de 0.9°C en 14 min
    ]
    cur_temp = 19.3
    cutoff_15m = now - timedelta(minutes=15)
    recent = [v for t, v in history if t >= cutoff_15m]
    drop = max(recent) - cur_temp
    assert drop >= 0.4  # Doit déclencher window_open


def test_passive_heat_loss_calibration_mode_a():
    """Vérifie le calcul et le filtrage de la déperdition mesurée U*A en repos nocturne."""
    # Salle à 20.0°C, extérieur 5.0°C (Delta T = 15°C)
    # H = 60 W/K, Tau = 15h -> C_eff = 900 Wh/K
    # Si la pente naturelle est -1.0 °C/h : P_loss = 900 W -> UA = 900 / 15 = 60.0 W/K
    should_heat, _, measured_ua = evaluate_window_and_calibration_decision(
        cur_temp=20.0,
        target_temp=19.0,
        temp_projected=19.8,
        temp_derivative=-1.0,
        outdoor_temp=5.0,
        window_open=False,
        fsm_state="idle",
        time_since_stop_hours=5.0,  # >= 2 * 2.25h (4.5h)
        dead_time_hours=2.25,
        heat_loss_wk=60.0,
        slab_tau_hours=15.0,
        current_measured_ua=None,
    )
    assert measured_ua == 60.0


def test_passive_heat_loss_calibration_ignored_if_recently_heated():
    """Vérifie que la calibration est ignorée tant que la dalle n'a pas dissipé son onde (> 2 * theta)."""
    _, _, measured_ua = evaluate_window_and_calibration_decision(
        cur_temp=20.0,
        target_temp=19.0,
        temp_projected=19.8,
        temp_derivative=-1.0,
        outdoor_temp=5.0,
        window_open=False,
        fsm_state="idle",
        time_since_stop_hours=2.0,  # Trop court (< 4.5h)
        dead_time_hours=2.25,
        heat_loss_wk=60.0,
        slab_tau_hours=15.0,
        current_measured_ua=None,
    )
    assert measured_ua is None
