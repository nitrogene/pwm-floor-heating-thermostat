"""Constantes pour l'intégration PWM Floor Heating Thermostat."""

from datetime import timedelta

DOMAIN = "pwm_floor_heating_thermostat"

# Configuration des entités
CONF_HEATER = "heater"
CONF_TARGET_SENSOR = "target_sensor"
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_HEURES_CREUSES_SENSOR = "heures_creuses_sensor"

# Paramètres physiques du modèle thermodynamique
CONF_HEAT_LOSS = "heat_loss_wk"          # Déperditions thermiques globales de la pièce (W/K)
CONF_POWER_WATTS = "power_watts"        # Puissance thermique utile du/des compresseurs (W)
CONF_SLAB_TIME_CONSTANT = "slab_tau_hours"  # Constante de temps d'inertie de la dalle (heures)
CONF_DEAD_TIME = "dead_time_hours"      # Temps mort pur de traversée de dalle (heures)

# Sécurités mécaniques compresseurs (Danfoss)
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_MIN_OFF_CYCLE_DURATION = "min_off_cycle_duration"
CONF_MAX_CYCLES_PER_DAY = "max_cycles_per_day"

# Valeurs par défaut
DEFAULT_NAME = "PWM Floor Heating Thermostat"
DEFAULT_TARGET_TEMP = 19.0
DEFAULT_MIN_TEMP = 16.0
DEFAULT_MAX_TEMP = 26.0

DEFAULT_HEAT_LOSS = 60.0               # ~60 W/K pour salon moyen
DEFAULT_POWER_WATTS = 6500.0           # 2 compresseurs Danfoss M26DX (~6.5 kW th)
DEFAULT_SLAB_TAU_HOURS = 15.0          # ~15 heures d'inertie chape
DEFAULT_DEAD_TIME_HOURS = 2.25         # ~2h15 de temps mort de dalle

DEFAULT_MIN_CYCLE = timedelta(minutes=30)
DEFAULT_MIN_OFF = timedelta(minutes=15)
DEFAULT_MAX_CYCLES = 6

# États de la machine à états finis (FSM)
FSM_IDLE = "idle"
FSM_RUNNING_MIN_LOCK = "running_min_lock"        # En chauffe, verrouillé pour respecter les 30 min mini
FSM_RUNNING_NORMAL = "running_normal"            # En chauffe, au-delà des 30 min
FSM_WAITING_MIN_OFF = "waiting_min_off"          # À l'arrêt, verrouillé pour égalisation des pressions (15 min)
FSM_ERROR_SAFETY = "error_safety"
