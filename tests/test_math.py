"""Tests unitaires pour la logique mathématique et la FSM de PWM Floor Heating Thermostat."""

from datetime import datetime, timedelta

import pytest


def calculate_slope_and_projection(temp_history: list[tuple[datetime, float]], dead_time_hours: float) -> tuple[float, float]:
    """Extrait algorithmique de _update_trajectory_projection pour test unitaire pur."""
    if not temp_history:
        return 0.0, 0.0

    cur_temp = temp_history[-1][1]
    if len(temp_history) < 2:
        return 0.0, cur_temp

    dt_span = (temp_history[-1][0] - temp_history[0][0]).total_seconds()
    if dt_span < 300:  # < 5 minutes
        return 0.0, cur_temp

    t0 = temp_history[0][0]
    t_hours = [(t - t0).total_seconds() / 3600.0 for t, _ in temp_history]
    temps = [v for _, v in temp_history]

    n = len(t_hours)
    mean_t = sum(t_hours) / n
    mean_temp = sum(temps) / n

    denom = sum((t - mean_t) ** 2 for t in t_hours)
    if denom > 1e-6:
        raw_slope = sum((t - mean_t) * (v - mean_temp) for t, v in zip(t_hours, temps, strict=True)) / denom
        slope = max(-3.0, min(3.0, raw_slope))
    else:
        slope = 0.0

    projected = cur_temp + (dead_time_hours * slope)
    return slope, projected


def test_linear_regression_slope_stable():
    """Vérifie que la pente d'une température constante est nulle."""
    now = datetime(2026, 11, 3, 20, 0, 0)
    history = [
        (now - timedelta(minutes=40), 19.0),
        (now - timedelta(minutes=20), 19.0),
        (now, 19.0),
    ]
    slope, projected = calculate_slope_and_projection(history, dead_time_hours=2.25)
    assert pytest.approx(slope, abs=1e-3) == 0.0
    assert pytest.approx(projected, abs=1e-2) == 19.0


def test_linear_regression_cooling_slope():
    """Vérifie qu'un refroidissement de 0.4°C en 1 heure donne bien slope = -0.4°C/h."""
    now = datetime(2026, 11, 3, 20, 0, 0)
    history = [
        (now - timedelta(minutes=60), 19.4),
        (now - timedelta(minutes=30), 19.2),
        (now, 19.0),
    ]
    slope, projected = calculate_slope_and_projection(history, dead_time_hours=2.25)
    assert pytest.approx(slope, abs=1e-3) == -0.4
    # À -0.4°C/h, dans 2h15 (2.25h), la baisse est de 2.25 * (-0.4) = -0.9°C -> 19.0 - 0.9 = 18.1°C
    assert pytest.approx(projected, abs=1e-2) == 18.1


def test_linear_regression_bounded():
    """Vérifie que les variations aberrantes de capteurs sont bornées à [-3.0, +3.0] °C/h."""
    now = datetime(2026, 11, 3, 20, 0, 0)
    history = [
        (now - timedelta(minutes=10), 15.0),
        (now, 22.0),  # Saut artificiel de +7°C en 10 min
    ]
    slope, _ = calculate_slope_and_projection(history, dead_time_hours=2.25)
    assert slope == 3.0  # Limité à la borne max physique


def test_model_error_calculation():
    """Vérifie le calcul de l'erreur de modèle e_model(t) = T_mesurée(t) - T_projetée(t - dead_time)."""
    now = datetime(2026, 11, 3, 20, 0, 0)
    dead_time_hours = 2.0

    # Projections faites il y a 2h05 et 1h55 (encadrant t - 2h = 18h00)
    t1 = now - timedelta(hours=2, minutes=5)
    t2 = now - timedelta(hours=1, minutes=55)
    proj1 = 19.4
    proj2 = 19.6

    projection_history = [(t1, proj1), (t2, proj2)]

    target_time = now - timedelta(hours=dead_time_hours)
    past_proj = None
    for i in range(len(projection_history) - 1):
        pt1, p1 = projection_history[i]
        pt2, p2 = projection_history[i + 1]
        if pt1 <= target_time <= pt2:
            dt_span = (pt2 - pt1).total_seconds()
            if dt_span > 0:
                fraction = (target_time - pt1).total_seconds() / dt_span
                past_proj = p1 + fraction * (p2 - p1)
            else:
                past_proj = p1
            break

    assert past_proj is not None
    assert pytest.approx(past_proj, abs=1e-2) == 19.5

    # Si la température mesurée actuelle est 19.58°C, model_error = 19.58 - 19.50 = +0.08°C
    cur_temp = 19.58
    model_error = round(cur_temp - past_proj, 2)
    assert model_error == 0.08

