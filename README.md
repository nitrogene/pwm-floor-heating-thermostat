# PWM Floor Heating Thermostat for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/nitrogene/pwm-floor-heating-thermostat?include_prereleases)](https://github.com/nitrogene/pwm-floor-heating-thermostat/releases)

A predictive, thermodynamic underfloor heating thermostat for Home Assistant, engineered specifically for high thermal inertia heavy slabs (*chape liquide / dalle béton*) and on/off (TOR / *Tout-Ou-Rien*) heating devices: geothermal heat pumps, electrothermal wax actuators, and pellet boilers.

---

## Targeted Heating Systems & Architectures

This integration is purpose-built to solve the acute regulation challenges of **heavy inertia floor heating** powered by **fixed-speed on/off (TOR) actuators**:

### 1. Direct-Expansion & Hydronic Geothermal Systems (Enalsa, Sofath, France Géothermie...)
* **Compressors**: Danfoss (Maneurop M26DX, MT series), Copeland Scroll, Tecumseh.
* **Mechanical & Refrigerant Constraints**:
  * **Mandatory Oil Return ($\ge 30\text{ min}$ ON)**: Unlike inverter heat pumps, fixed-speed scroll or hermetic reciprocating compressors eject lubrication oil into the refrigeration circuits during operation. In direct-expansion floor loops (hundreds of meters of copper tubing embedded in concrete), it takes **at least 20 to 30 minutes of continuous flow** for the oil to migrate back to the compressor crankcase. Stopping prematurely causes progressive oil starvation and catastrophic mechanical seizure.
  * **Pressure Equalization ($\ge 15\text{ min}$ OFF)**: After compressor shutdown, High Pressure (HP) and Low Pressure (BP) sides must fully balance before restarting. Starting against a residual differential pressure causes severe motor stall, capacitor degradation, or thermal breaker trips.
  * **Cycle Budget ($\le 6\text{ cycles/day}$)**: Eliminating mechanical fatigue by substituting erratic micro-starts with long, consolidated heat charges.

### 2. Heavy Screed Dalles & High Thermal Inertia
* Designed for 5 to 8 cm screeds (*chape fluide anhydrite, chape ciment, dalle béton armé*).
* Characterized by a **pure dead time of 2 to 3 hours** ($\theta$) before heat reaches the room surface, and a **thermal dissipation time constant of 12 to 20 hours** ($\tau$).

### 3. Hydronic Underfloor Manifolds (Electrothermal Wax Actuators)
* 230V or 24V Normally Closed (NC) / Normally Open (NO) thermal actuators on distribution manifolds.
* These actuators feature a slow wax-expansion response (3 to 5 minutes to fully open/close), which naturally pairs with this thermostat's slow-cycle PWM modulation (1 to 3 hours PWM periods).

### 4. Pellet Boilers & Thermal Buffer Tanks (*Ballons Tampons*)
* Heating systems where short cycling creates incomplete combustion, soot accumulation, and excessive ignition resistance wear.

---

## Why standard PID thermostats fail on heavy slabs

Standard PID thermostats (such as `smart_thermostat`) are ill-adapted for heavy underfloor heating:
1. **Dead Time ($\theta \approx 2\text{h}$ to $3\text{h}$)**: Heat takes hours to diffuse through the slab. During this time, the error persists, the integral term saturates (*integral windup*), forcing the heater to run too long and causing massive overshoots (+1.5°C to +2.5°C).
2. **Destructive Compressor Short-Cycling**: PID algorithms frequently oscillate around the setpoint, turning on/off compressors within minutes—severely damaging Danfoss compressors without guaranteed oil return and pressure equalization.
3. **No Tariff Optimization**: Conventional thermostats heat reactively whenever ambient temperature drops, missing the opportunity to store cheap calories in the slab during Off-Peak hours (*Heures Creuses*).

**`pwm_floor_heating_thermostat` solves all three issues by combining physical building modeling, slow PWM duty-cycle allocation, and a hardware-grade Finite State Machine (FSM).**

---

## Key Features

- 🏗️ **Thermodynamic Slab Model**: Predicts the daily heat deficit based on outdoor temperature (current and forecast) and house heat loss ($H$ in W/K).
- ⏱️ **Predictive Dead-Time Anticipation**: Projects the slab's internal thermal wave to prevent cold morning drops without overshooting.
- 🛡️ **Danfoss Compressor Safety Guard**: Built-in, non-bypassable FSM:
  - Minimum ON cycle: 30 minutes (ensures complete oil return).
  - Minimum OFF cycle: 15 minutes (ensures refrigerant pressure equalization).
  - Daily cycle budget limit (e.g. maximum 6 cycles/day).
- ⚡ **Dynamic Off-Peak (*Heures Creuses*) Scheduling**: Prioritizes running long charging cycles when electricity is cheapest (Linky TIC / sensor integration).
- 👻 **Shadow Mode / Digital Twin (Dry-Run)**: Run in parallel with an existing legacy thermostat without actuating physical relays to compare theoretical decisions against real curves before live switchover.
- 🔍 **AI Auto-Tuning & Telemetry**: Exposes model error $e_{\text{model}}$, trajectory projections, energy quota, passive cooling rates, and FSM diagnostics for automated calibration via AI agents or analytics.
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

## Configuration Examples

### Production Mode (Direct Physical Control)

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
    power_watts: 6500.0         # Useful heat output (W) - e.g. 2x Danfoss M26DX
    slab_tau_hours: 15.0        # Slab thermal time constant (hours)
    dead_time_hours: 2.25       # Dead time for heat wave diffusion (hours)
    
    # Mechanical compressor protections (Danfoss specifications)
    min_cycle_duration: "00:30:00"      # Minimum ON time (30 min for oil return)
    min_off_cycle_duration: "00:15:00"  # Minimum OFF time (15 min for pressure balance)
    max_cycles_per_day: 6
    
    # Setpoints
    target_temp: 19.0
    min_temp: 16.0
    max_temp: 26.0
```

### Shadow / Simulation Mode (Dry-Run in parallel with existing PID)

Run safely alongside an existing PID or manual thermostat. The model will calculate everything, record state, and report why and when it would have started heating—**without triggering the physical switch**:

```yaml
climate:
  - platform: pwm_floor_heating_thermostat
    name: "Salon Simulation Shadow"
    target_sensor: sensor.temperature_salon
    outdoor_sensor: sensor.temperature_exterieure_meteo
    heures_creuses_sensor: binary_sensor.heures_creuses_nuit
    
    # Shadow mode configuration
    dry_run: true                                  # No physical relay switching!
    heater: input_boolean.simulation_relais_salon  # Optional virtual helper to visualize simulated state
    observed_heater: switch.relais_compresseurs_salon # Observe what the current PID is actually doing
    
    heat_loss_wk: 60.0
    power_watts: 6500.0
    slab_tau_hours: 15.0
    dead_time_hours: 2.25
```

---

## License

MIT License - Copyright (c) 2026 Nitrogene.
