"""Tests pour la machine à états finis (FSM) et les sécurités compresseurs Danfoss."""

from datetime import datetime, timedelta

try:
    from const import (
        FSM_IDLE,
        FSM_RUNNING_MIN_LOCK,
        FSM_RUNNING_NORMAL,
        FSM_WAITING_MIN_OFF,
    )
except ImportError:
    from custom_components.pwm_floor_heating_thermostat.const import (
        FSM_IDLE,
        FSM_RUNNING_MIN_LOCK,
        FSM_RUNNING_NORMAL,
        FSM_WAITING_MIN_OFF,
    )


class MockDanfossFSM:
    """Simulateur pur de la machine à états finis de climate.py pour test unitaire."""

    def __init__(self, min_cycle_min: int = 30, min_off_min: int = 15):
        self.min_cycle_duration = timedelta(minutes=min_cycle_min)
        self.min_off_duration = timedelta(minutes=min_off_min)
        self.state = FSM_IDLE
        self.last_change = datetime(2026, 11, 3, 20, 0, 0)
        self.physical_heater_on = False

    def request_start(self, now: datetime) -> bool:
        """Tentative de démarrage compresseur."""
        if self.state in [FSM_RUNNING_MIN_LOCK, FSM_RUNNING_NORMAL]:
            return True  # Déjà allumé

        if self.state == FSM_WAITING_MIN_OFF:
            elapsed = (now - self.last_change).total_seconds()
            if elapsed < self.min_off_duration.total_seconds():
                return False  # Verrouillé : repos obligatoire

        self.state = FSM_RUNNING_MIN_LOCK
        self.last_change = now
        self.physical_heater_on = True
        return True

    def request_stop(self, now: datetime) -> bool:
        """Tentative d'arrêt compresseur."""
        if self.state in [FSM_IDLE, FSM_WAITING_MIN_OFF]:
            return True  # Déjà arrêté

        if self.state == FSM_RUNNING_MIN_LOCK:
            elapsed = (now - self.last_change).total_seconds()
            if elapsed < self.min_cycle_duration.total_seconds():
                return False  # Verrouillé : marche minimale obligatoire (retour huile)

        self.state = FSM_WAITING_MIN_OFF
        self.last_change = now
        self.physical_heater_on = False
        return True

    def update_time(self, now: datetime):
        """Mise à jour périodique des transitions d'états temporelles."""
        elapsed = (now - self.last_change).total_seconds()
        if self.state == FSM_RUNNING_MIN_LOCK and elapsed >= self.min_cycle_duration.total_seconds():
            self.state = FSM_RUNNING_NORMAL
        elif self.state == FSM_WAITING_MIN_OFF and elapsed >= self.min_off_duration.total_seconds():
            self.state = FSM_IDLE


def test_fsm_danfoss_min_run_lock():
    """Vérifie que l'arrêt est strictement interdit avant 30 minutes de marche."""
    t0 = datetime(2026, 11, 3, 22, 0, 0)
    fsm = MockDanfossFSM(min_cycle_min=30, min_off_min=15)

    # 1. Démarrage à 22h00
    assert fsm.request_start(t0) is True
    assert fsm.state == FSM_RUNNING_MIN_LOCK
    assert fsm.physical_heater_on is True

    # 2. Tentative d'arrêt à 22h10 (après 10 min) -> DOIT ÊTRE REFUSÉE
    t_10m = t0 + timedelta(minutes=10)
    assert fsm.request_stop(t_10m) is False
    assert fsm.state == FSM_RUNNING_MIN_LOCK
    assert fsm.physical_heater_on is True

    # 3. À 22h31 (après 31 min) -> Transition vers RUNNING_NORMAL
    t_31m = t0 + timedelta(minutes=31)
    fsm.update_time(t_31m)
    assert fsm.state == FSM_RUNNING_NORMAL

    # 4. Arrêt autorisé maintenant
    assert fsm.request_stop(t_31m) is True
    assert fsm.state == FSM_WAITING_MIN_OFF
    assert fsm.physical_heater_on is False


def test_fsm_danfoss_min_off_lock():
    """Vérifie que le redémarrage est strictement interdit pendant les 15 minutes d'égalisation."""
    t0 = datetime(2026, 11, 3, 22, 0, 0)
    fsm = MockDanfossFSM(min_cycle_min=30, min_off_min=15)

    # Démarrage puis arrêt après 35 min
    fsm.request_start(t0)
    t_stop = t0 + timedelta(minutes=35)
    fsm.update_time(t_stop)
    fsm.request_stop(t_stop)
    assert fsm.state == FSM_WAITING_MIN_OFF

    # Tentative de redémarrage après 5 minutes de repos -> REFUSÉE
    t_5m_off = t_stop + timedelta(minutes=5)
    assert fsm.request_start(t_5m_off) is False
    assert fsm.state == FSM_WAITING_MIN_OFF
    assert fsm.physical_heater_on is False

    # Après 16 minutes de repos -> Transition vers IDLE et redémarrage autorisé
    t_16m_off = t_stop + timedelta(minutes=16)
    fsm.update_time(t_16m_off)
    assert fsm.state == FSM_IDLE
    assert fsm.request_start(t_16m_off) is True
    assert fsm.state == FSM_RUNNING_MIN_LOCK
