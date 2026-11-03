# PWM Floor Heating Thermostat for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/nitrogene/pwm-floor-heating-thermostat?include_prereleases)](https://github.com/nitrogene/pwm-floor-heating-thermostat/releases)

A predictive, thermodynamic underfloor heating thermostat for Home Assistant, engineered specifically for high thermal inertia heavy slabs (chape liquide / dalle béton) and on/off (TOR) heating devices (geothermal or aerothermal heat pumps, thermal wax actuators, pellet boilers).

---

## Why this integration?

Standard PID thermostats (such as `smart_thermostat`) fail on heavy underfloor heating systems:
1. **Dead Time ($\theta \approx 2\text{h}$ to $3\text{h}$)**: Heat takes hours to diffuse through 7 cm of screed. During this time, the error persists, the integral term saturates (*integral windup*), forcing the heater to run too long and causing massive overshoots (+1.5°C to +2.5°C).
2. **Compressor Short-Cycling**: PID algorithms frequently oscillate around the setpoint, turning on/off compressors within minutes—severely damaging scroll/piston compressors (Danfoss, Copeland) without guaranteed oil return and pressure equalization.
3. **No Tariff Optimization**: Conventional thermostats heat reactively whenever temperature drops, missing the opportunity to store cheap calories in the slab during Off-Peak hours (Heures Creuses).

**`pwm_floor_heating_thermostat` solves all three issues by combining physical building modeling, slow PWM duty-cycle allocation, and a hardware-grade Finite State Machine (FSM).**

---

## Key Features

- 🏗️ **Thermodynamic Slab Model**: Predicts the daily heat deficit based on outdoor temperature (current and forecast) and house heat loss ($H$ in W/K).
- ⏱️ **Predictive Dead-Time Anticipation**: Projects the slab's internal thermal wave to prevent cold morning drops without overshooting.
- 🛡️ **Danfoss Compressor Safety Guard**: Built-in, non-bypassable FSM:
  - Minimum ON cycle: 30 minutes (ensures complete oil return).
  - Minimum OFF cycle: 15 minutes (ensures refrigerant pressure equalization).
  - Daily cycle budget limit (e.g. maximum 6 cycles/day).
- ⚡ **Dynamic Off-Peak (Heures Creuses) Scheduling**: Prioritizes running long charging cycles when electricity is cheapest (Linky TIC / sensor integration).
- 🔄 **Restart-Resilient**: Inherits `RestoreEntity`—restores running state, elapsed timers, and cycle counts after Home Assistant reboots.

---

## Installation

### Via HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add `https://github.com/nitrogene/pwm-floor-heating-thermostat` as an **Integration**.
4. Click **Download**, then restart Home Assistant.

### Manual Installation

Copy all files into `<home_assistant_config>/custom_components/pwm_floor_heating_thermostat/` and restart Home Assistant.

---

## Configuration Example

In your `configuration.yaml`:

```yaml
climate:
  - platform: pwm_floor_heating_thermostat
    name: "Salon Geothermie"
    heater: switch.relais_compresseurs_salon
    target_sensor: sensor.temperature_salon
    outdoor_sensor: sensor.temperature_exterieure_meteo
    heures_creuses_sensor: binary_sensor.heures_creuses_nuit
    
    # Building thermal characteristics
    heat_loss_wk: 60.0          # Thermal loss rate (W/K)
    power_watts: 6500.0         # Useful heat output (W)
    slab_tau_hours: 15.0        # Slab thermal time constant (hours)
    dead_time_hours: 2.25       # Dead time for heat wave diffusion (hours)
    
    # Mechanical compressor protections
    min_cycle_duration: "00:30:00"      # Minimum ON time (30 min)
    min_off_cycle_duration: "00:15:00"  # Minimum OFF time (15 min)
    max_cycles_per_day: 6
    
    # Setpoints
    target_temp: 19.0
    min_temp: 16.0
    max_temp: 26.0
```

---

## License

MIT License - Copyright (c) 2026 Nitrogene.
