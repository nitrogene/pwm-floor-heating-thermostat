"""Unit tests for thermodynamic modeling, alpha-beta state observer, and e_model evaluation."""

import math
from datetime import datetime, timedelta

import pytest


def update_alpha_beta_observer(
    filtered_temp: float | None,
    temp_derivative: float,
    last_update: datetime | None,
    now: datetime,
    cur_temp: float,
    dead_time_hours: float,
    window_open: bool = False,
    window_recovery_until: datetime | None = None,
) -> tuple[float, float, float]:
    """Emulate the continuous-discrete 1D Kalman (Kalata alpha-beta) state observer from climate.py."""
    if filtered_temp is None or last_update is None:
        return cur_temp, 0.0, cur_temp

    dt = (now - last_update).total_seconds() / 3600.0
    if dt <= 0:
        eff_deriv = 0.0 if window_open else temp_derivative
        return filtered_temp, temp_derivative, filtered_temp + (dead_time_hours * eff_deriv)

    if dt > 2.0:
        return cur_temp, 0.0, cur_temp

    # Prediction step
    t_pred = filtered_temp + (dt * temp_derivative)
    v_pred = temp_derivative

    # Innovation
    innov = cur_temp - t_pred

    # Kalata gains
    var_r = 0.0008333
    q_proc = 1.0
    lambda_k = (q_proc * (dt**2)) / math.sqrt(var_r)
    r_k = (4.0 + lambda_k - math.sqrt(max(0.0, 8.0 * lambda_k + (lambda_k**2)))) / 4.0
    alpha = max(0.01, min(0.9, 1.0 - (r_k**2)))
    beta = max(0.0001, min(0.8, 2.0 * (2.0 - alpha) - 4.0 * math.sqrt(max(0.0, 1.0 - alpha))))

    # Correction step
    new_filt = t_pred + (alpha * innov)
    new_deriv = v_pred + ((beta / dt) * innov)
    new_deriv = max(-2.5, min(2.5, new_deriv))

    in_recovery = window_recovery_until is not None and now < window_recovery_until
    if window_open:
        effective_deriv = 0.0
    elif in_recovery:
        effective_deriv = min(0.05, max(-0.5, new_deriv))
    else:
        effective_deriv = new_deriv

    projected = new_filt + (dead_time_hours * effective_deriv)
    return new_filt, new_deriv, projected


def test_observer_initialization_zero_spike():
    """Verify clean startup: first reading initializes projection to ambient without jumping to 19°C."""
    now = datetime(2026, 11, 8, 18, 40, 0)
    t_filt, deriv, projected = update_alpha_beta_observer(
        filtered_temp=None,
        temp_derivative=0.0,
        last_update=None,
        now=now,
        cur_temp=22.2,
        dead_time_hours=2.25,
    )
    assert t_filt == 22.2
    assert deriv == 0.0
    assert projected == 22.2


def test_observer_constant_temp():
    """Verify that constant temperature maintains zero slope and stable projection."""
    now = datetime(2026, 11, 8, 19, 0, 0)
    t_filt = 21.0
    deriv = 0.0
    last_update = now

    for m in range(1, 30):
        t_now = now + timedelta(minutes=m)
        t_filt, deriv, projected = update_alpha_beta_observer(
            filtered_temp=t_filt,
            temp_derivative=deriv,
            last_update=last_update,
            now=t_now,
            cur_temp=21.0,
            dead_time_hours=2.0,
        )
        last_update = t_now

    assert pytest.approx(t_filt, abs=1e-2) == 21.0
    assert pytest.approx(deriv, abs=1e-3) == 0.0
    assert pytest.approx(projected, abs=1e-2) == 21.0


def test_observer_cooling_tracking():
    """Verify that the observer smoothly tracks cooling without quantization-induced oscillations."""
    now = datetime(2026, 11, 8, 20, 0, 0)
    t_filt = 21.0
    deriv = 0.0
    last_update = now

    # Continuous cooling of 0.3°C in 60 minutes
    for m in range(1, 61):
        t_now = now + timedelta(minutes=m)
        # Quantized sensor measurement to tenths of a degree
        raw_temp = round(21.0 - (0.3 * (m / 60.0)), 1)
        t_filt, deriv, projected = update_alpha_beta_observer(
            filtered_temp=t_filt,
            temp_derivative=deriv,
            last_update=last_update,
            now=t_now,
            cur_temp=raw_temp,
            dead_time_hours=2.0,
        )
        last_update = t_now

    # Negative derivative matches cooling trend (~ -0.3 °C/h)
    assert -0.45 <= deriv <= -0.15
    # Anticipation leads ahead of current filtered temperature
    assert projected < t_filt


def test_observer_window_opening_freeze():
    """Verify that active ventilation freezes projection derivative to 0 (no false plunge to 14°C)."""
    now = datetime(2026, 11, 9, 9, 0, 0)
    t_filt = 20.5
    deriv = -0.05
    last_update = now

    # Rapid air drop during aeration: 19.0°C with window_open=True
    t_now = now + timedelta(minutes=5)
    t_filt, deriv, projected = update_alpha_beta_observer(
        filtered_temp=t_filt,
        temp_derivative=deriv,
        last_update=last_update,
        now=t_now,
        cur_temp=19.0,
        dead_time_hours=2.0,
        window_open=True,
    )

    # During window open, effective_deriv = 0 -> projected = t_filt (~20°C, never plunges to 14°C)
    assert projected == t_filt
    assert projected > 18.0


def test_observer_window_recovery_damping():
    """Verify that post-ventilation air rewarming does not cause false overshoot projection to 23°C."""
    now = datetime(2026, 11, 9, 9, 30, 0)
    recovery_until = now + timedelta(minutes=30)
    t_filt = 19.5
    deriv = 1.5  # Fast localized air rebound
    last_update = now

    t_now = now + timedelta(minutes=5)
    t_filt, deriv, projected = update_alpha_beta_observer(
        filtered_temp=t_filt,
        temp_derivative=deriv,
        last_update=last_update,
        now=t_now,
        cur_temp=20.2,
        dead_time_hours=2.0,
        window_open=False,
        window_recovery_until=recovery_until,
    )

    # Projection is bounded against air draft rebound overshoot (max effective slope clamped to 0.05°C/h)
    assert projected <= t_filt + (2.0 * 0.05) + 0.1
    assert projected < 20.5


def test_observer_derivative_bounds():
    """Verify that estimated derivative is strictly clamped within physical bounds [-2.5, +2.5] °C/h."""
    now = datetime(2026, 11, 8, 20, 0, 0)
    t_filt, deriv, _ = update_alpha_beta_observer(
        filtered_temp=20.0,
        temp_derivative=0.0,
        last_update=now,
        now=now + timedelta(minutes=1),
        cur_temp=30.0,  # Extreme jump of +10°C in 1 min
        dead_time_hours=2.0,
    )
    assert deriv == 2.5


def test_model_error_calculation():
    """Verify evaluation of thermodynamic model error: e_model(t) = T_measured(t) - T_projected(t - dead_time)."""
    now = datetime(2026, 11, 3, 20, 0, 0)
    dead_time_hours = 2.0

    # Past projections framing t - 2h = 18:00
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

    # If current measured temperature is 19.58°C, model_error = 19.58 - 19.50 = +0.08°C
    cur_temp = 19.58
    model_error = round(cur_temp - past_proj, 2)
    assert model_error == 0.08
