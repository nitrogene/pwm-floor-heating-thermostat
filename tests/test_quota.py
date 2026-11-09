"""Unit tests for dynamic daily thermal budget quota enforcement."""


def evaluate_quota_decision(
    cur_temp: float,
    target_temp: float,
    temp_projected: float,
    outdoor_temp: float,
    off_peak_active: bool,
    hours_needed_24h: float,
    hours_run_today: float,
    quota_enforced: bool,
) -> tuple[bool, str, bool]:
    """Decision logic including peak-hour daily quota capping."""
    error = target_temp - cur_temp
    projected_error = target_temp - temp_projected
    should_heat = False
    reason = "Idle"
    quota_blocked = False

    if off_peak_active:
        if error >= -0.5 and outdoor_temp <= 12.0:
            should_heat = True
            reason = f"Off-peak thermal precharge (ext: {outdoor_temp}°C)"
    else:
        if projected_error > 0.15 or error > 0.2:
            should_heat = True
            reason = f"Anticipated thermal drop: projected {temp_projected}°C"

    # Overshoot cutoff safeguard
    if error < -0.6 or (projected_error < -0.8 and cur_temp >= target_temp):
        should_heat = False
        reason = f"Overshoot prevention cutoff: curr {cur_temp}°C"

    # Daily quota enforcement during peak hours
    quota_exceeded = (hours_needed_24h > 0.0) and (hours_run_today >= hours_needed_24h)
    if should_heat and not off_peak_active and quota_enforced and quota_exceeded:
        if error < 0.8:
            should_heat = False
            quota_blocked = True
            reason = f"Daily quota fulfilled ({hours_run_today}h / {hours_needed_24h}h). Peak-hour cycle inhibited."

    return should_heat, reason, quota_blocked


def test_quota_blocks_peak_heating_when_enforced():
    """Verify peak-hour heating is inhibited when 24h quota is reached and enforcement is ON."""
    should_heat, reason, quota_blocked = evaluate_quota_decision(
        cur_temp=18.7,
        target_temp=19.0,
        temp_projected=18.6,
        outdoor_temp=5.0,
        off_peak_active=False,      # Peak hours
        hours_needed_24h=2.5,
        hours_run_today=2.6,        # Quota exceeded
        quota_enforced=True,        # Capping enabled
    )
    assert not should_heat
    assert quota_blocked
    assert "Daily quota fulfilled" in reason


def test_quota_allows_peak_heating_when_disabled_via_switch():
    """Verify peak-hour heating resumes if user disables quota enforcement switch."""
    should_heat, reason, quota_blocked = evaluate_quota_decision(
        cur_temp=18.7,
        target_temp=19.0,
        temp_projected=18.6,
        outdoor_temp=5.0,
        off_peak_active=False,      # Peak hours
        hours_needed_24h=2.5,
        hours_run_today=2.6,        # Quota exceeded
        quota_enforced=False,       # Overridden by user
    )
    assert should_heat
    assert not quota_blocked
    assert "Anticipated thermal drop" in reason


def test_quota_does_not_block_off_peak_precharge():
    """Verify off-peak precharge remains prioritized even if calculated quota is reached."""
    should_heat, reason, quota_blocked = evaluate_quota_decision(
        cur_temp=18.8,
        target_temp=19.0,
        temp_projected=18.7,
        outdoor_temp=3.0,
        off_peak_active=True,       # Off-peak hours
        hours_needed_24h=2.0,
        hours_run_today=2.2,
        quota_enforced=True,
    )
    assert should_heat
    assert not quota_blocked
    assert "Off-peak thermal precharge" in reason


def test_comfort_safety_overrides_quota_block_on_deep_drop():
    """Verify comfort fallback overrides quota block on severe drop (> 0.8°C below target)."""
    should_heat, reason, quota_blocked = evaluate_quota_decision(
        cur_temp=18.0,              # Severe drop: 1.0°C below target
        target_temp=19.0,
        temp_projected=17.8,
        outdoor_temp=0.0,
        off_peak_active=False,      # Peak hours
        hours_needed_24h=2.5,
        hours_run_today=2.8,
        quota_enforced=True,
    )
    # Comfort safeguard lifts quota block
    assert should_heat
    assert not quota_blocked
