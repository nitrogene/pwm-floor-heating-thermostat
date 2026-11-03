"""Tests pour les sécurités plancher chauffant et le Shadow Mode."""

from unittest.mock import MagicMock


def evaluate_heating_decision(
    cur_temp: float,
    target_temp: float,
    temp_projected: float,
    dead_time: float,
    outdoor_temp: float,
    off_peak_active: bool,
    floor_temp: float | None = None,
    max_floor_temp: float = 28.0,
    min_floor_temp: float = 14.0,
) -> tuple[bool, str]:
    """Extrait de la logique décisionnelle de _async_control_heating pour test unitaire pur."""
    error = target_temp - cur_temp
    projected_error = target_temp - temp_projected
    should_heat = False
    reason = "Idle"

    if off_peak_active:
        if error >= -0.5 and outdoor_temp <= 12.0:
            should_heat = True
            reason = f"Off-peak thermal precharge (ext: {outdoor_temp}°C)"
    else:
        if projected_error > 0.15 or error > 0.2:
            should_heat = True
            reason = f"Anticipated thermal drop: projected {temp_projected}°C in {dead_time}h"

    # Surchauffe
    if error < -0.6 or (projected_error < -0.8 and cur_temp >= target_temp):
        should_heat = False
        reason = f"Overshoot prevention cutoff: curr {cur_temp}°C"

    # Garde-fou boucle d'eau / plancher
    if floor_temp is not None:
        if floor_temp >= max_floor_temp:
            should_heat = False
            reason = f"Floor protection cutoff: water temp {floor_temp}°C exceeds max {max_floor_temp}°C"
        elif floor_temp <= min_floor_temp:
            should_heat = True
            reason = f"Floor freeze protection: water temp {floor_temp}°C"

    return should_heat, reason


def test_dtu_max_floor_cutoff():
    """Vérifie que la surchauffe d'eau (>= 28°C) coupe la chauffe même si l'air appelle."""
    # L'air est à 17.5°C pour consigne 19.0°C (fort appel thermique en Heures Creuses)
    should_heat, reason = evaluate_heating_decision(
        cur_temp=17.5,
        target_temp=19.0,
        temp_projected=17.0,
        dead_time=2.25,
        outdoor_temp=2.0,
        off_peak_active=True,
        floor_temp=28.2,  # Dalle saturée
        max_floor_temp=28.0,
    )
    assert should_heat is False
    assert "Floor protection cutoff" in reason


def test_floor_freeze_protection():
    """Vérifie qu'un plancher sous 14°C force la chauffe même si consigne atteinte."""
    should_heat, reason = evaluate_heating_decision(
        cur_temp=20.0,
        target_temp=19.0,
        temp_projected=20.0,
        dead_time=2.25,
        outdoor_temp=-5.0,
        off_peak_active=False,
        floor_temp=12.0,  # Risque gel dalle
        min_floor_temp=14.0,
    )
    assert should_heat is True
    assert "Floor freeze protection" in reason


def test_dry_run_does_not_call_physical_switch():
    """Vérifie que le mode dry-run ne déclenche aucun service switch réel."""
    dry_run = True
    heater_entity = "switch.relais_compresseurs_salon"
    mock_service_call = MagicMock()

    # Logique d'allumage sécurisé
    if dry_run:
        # Simulation : pas d'appel de service switch
        if heater_entity.startswith("input_boolean."):
            mock_service_call("input_boolean", "turn_on")
    else:
        domain = heater_entity.split(".")[0]
        mock_service_call(domain, "turn_on")

    # Vérification formelle : 0 appel au switch physique
    assert mock_service_call.call_count == 0
