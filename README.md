# PWM Floor Heating Thermostat for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?logo=homeassistant&logoColor=white)](https://github.com/hacs/default)
[![License](https://img.shields.io/github/license/nitrogene/pwm-floor-heating-thermostat)](https://github.com/nitrogene/pwm-floor-heating-thermostat/blob/main/LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/nitrogene/pwm-floor-heating-thermostat?logo=github&logoColor=white)](https://github.com/nitrogene/pwm-floor-heating-thermostat/releases)

A predictive, thermodynamic underfloor heating thermostat for Home Assistant, engineered specifically for high thermal inertia heavy slabs (*chape liquide / dalle béton*) and on/off (TOR / *Tout-Ou-Rien*) heating devices: geothermal heat pumps, hydronic manifolds with water return sensors, electrothermal wax actuators, and pellet boilers.

---

## Targeted Heating Systems & Architectures

This integration is purpose-built to solve the acute regulation challenges of **heavy inertia floor heating** powered by **fixed-speed on/off (TOR) actuators**:

### 1. Direct-Expansion & Hydronic Geothermal Systems (Enalsa, Sofath, France Géothermie...)
* **Compressors**: Danfoss (Maneurop M26DX, MT series), Copeland Scroll, Tecumseh.
* **Mechanical & Refrigerant Constraints**:
  * **Mandatory Oil Return (>= 30 min ON)**: Unlike inverter heat pumps, fixed-speed scroll or hermetic reciprocating compressors eject lubrication oil into the refrigeration circuits during operation. In direct-expansion floor loops (hundreds of meters of copper tubing embedded in concrete), it takes **at least 20 to 30 minutes of continuous flow** for the oil to migrate back to the compressor crankcase. Stopping prematurely causes progressive oil starvation and catastrophic mechanical seizure.
  * **Pressure Equalization (>= 15 min OFF)**: After compressor shutdown, High Pressure (HP) and Low Pressure (BP) sides must fully balance before restarting. Starting against a residual differential pressure causes severe motor stall, capacitor degradation, or thermal breaker trips.
  * **Cycle Budget (<= 6 cycles/day)**: Eliminating mechanical fatigue by substituting erratic micro-starts with long, consolidated heat charges.

### 2. Heavy Screed Dalles & High Thermal Inertia
* Designed for 5 to 8 cm screeds (*chape fluide anhydrite, chape ciment, dalle béton armé*).
* Characterized by a **pure dead time of 2 to 3 hours** (theta) before heat reaches the room surface, and a **thermal dissipation time constant of 12 to 20 hours** (tau).

### 3. Hydronic Underfloor Systems with Water Return Sensors
* Loop return temperature sensor directly measures the core slab thermal state with near-zero dead time.
* Hard limit anti-overshoot protection enforcing European standard **DTU 65.14 barefoot comfort limit (28°C max)**.

### 4. Hydronic Manifolds with Electrothermal Wax Actuators
* 230V or 24V Normally Closed (NC) / Normally Open (NO) thermal actuators on distribution manifolds.
* These actuators feature a slow wax-expansion response (3 to 5 minutes to fully open/close), which naturally pairs with this thermostat's slow-cycle PWM modulation (1 to 3 hours PWM periods).

---

## Why standard PID thermostats fail on heavy slabs

Standard PID thermostats (such as `smart_thermostat`) are ill-adapted for heavy underfloor heating:
1. **Dead Time (θ ≈ 2h to 3h)**: Heat takes hours to diffuse through the slab. During this time, the error persists, the integral term saturates (*integral windup*), forcing the heater to run too long and causing massive overshoots (+1.5°C to +2.5°C).
2. **Destructive Compressor Short-Cycling**: PID algorithms frequently oscillate around the setpoint, turning on/off compressors within minutes—severely damaging Danfoss compressors without guaranteed oil return and pressure equalization.
3. **No Tariff Optimization**: Conventional thermostats heat reactively whenever ambient temperature drops, missing the opportunity to store cheap calories in the slab during Off-Peak hours (*Heures Creuses*).

---

## Beyond the Heating Curve (*Loi d'Eau*): Predictive Time-Modulated Quotas

Traditional hydronic heating systems rely on a **Heating Curve (*Loi d'eau*)**, which calculates the supply water temperature dynamically from instantaneous outdoor temperature:
> `T_water_supply = T_setpoint + Slope * (T_setpoint - T_outdoor)`

### Why the classical Heating Curve fails on fixed-speed & heavy slab systems:
1. **Compressors cannot modulate flow temperature**: Fixed-speed scroll or hermetic reciprocating compressors (Danfoss, Copeland) run at **100% capacity or 0%**. In direct-expansion systems, condensing refrigerant enters the slab at a constant thermodynamic condensing temperature (~35°C to 40°C). Flow temperature modulation is physically impossible.
2. **Phase Lag & The Morning Cold Dip**: When a winter night freeze occurs at 04:00 AM, a reactive heating curve responds at 04:00 AM. But with a theta = 2.25 h dead time, heat only emerges into the living space around 06:30 or 07:00 AM—resulting in the infamous morning temperature drop.
3. **Blindness to Tariff Opportunities**: A heating curve forces heating whenever outdoor temperature is cold, regardless of peak electricity pricing.

### The Solution: From Water Temperature Modulation to Time Modulation (PWM)
Instead of varying supply temperature, **`pwm_floor_heating_thermostat` modulates the compressor operating time over a 24-hour horizon**:
> `Daily Quota (kWh) = [ H * (T_setpoint - T_outdoor_avg) * 24h ] / 1000`
> `Compressor Hours Needed = (Daily Quota * 1000) / P_thermal_watts`

### Role of `outdoor_sensor` / `outdoor_temperature_forecast`
The slab acts as a physical low-pass thermal filter. The outdoor temperature that the slab "sees" as it delivers a heat pulse is not the instantaneous reading at minute t, but the thermal profile over the traversal window:
* **Option A: Forecast Sliding Window (H0 -> H+4) [Recommended]**: Providing an outdoor temperature sensor averaged over the next 4 hours (e.g. from Météo-France or a weather integration) mirrors the exact heat loss profile the building will undergo while the injected heat wave travels through the screed.
* **Option B: Real-Time Instantaneous Sensor**: If no forecast sensor is available, a standard outdoor probe works natively, with the model estimating the daily budget from continuous readings.

---

## Key Features

- 🏗️ **Thermodynamic Slab Model**: Predicts the daily heat deficit based on outdoor temperature (current and forecast) and house heat loss (H in W/K).
- ⏱️ **Predictive Dead-Time Anticipation**: Projects the slab's internal thermal wave to prevent cold morning drops without overshooting.
- 🛡️ **Danfoss Compressor Safety Guard**: Built-in, non-bypassable FSM:
  - Minimum ON cycle: 30 minutes (ensures complete oil return).
  - Minimum OFF cycle: 15 minutes (ensures refrigerant pressure equalization).
  - Daily cycle budget limit (e.g. maximum 6 cycles/day).
- 💧 **Hydronic Water Circuit Feedback**: Optional `floor_temp_sensor` monitoring the loop return water temperature for DTU 65.14 max floor temperature cutoffs (28°C) and freeze protection.
- ⚡ **Dynamic Off-Peak (*Heures Creuses*) Scheduling**: Prioritizes running long charging cycles when electricity is cheapest (Linky TIC / dynamic sensor integration).
- 👻 **Shadow Mode / Digital Twin (Dry-Run)**: Run in parallel with an existing legacy thermostat without actuating physical relays to compare theoretical decisions against real curves before live switchover.
- 🔍 **AI Auto-Tuning & Telemetry**: Exposes model error e_model, trajectory projections, energy quota, passive cooling rates, and FSM diagnostics for automated calibration via AI agents or analytics.
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

### 1. Geothermal Heat Pump (Direct Expansion / TOR Compressors)

```yaml
climate:
  - platform: pwm_floor_heating_thermostat
    name: "Living Room Geothermal"
    heater: switch.living_room_compressor_relay
    target_sensor: sensor.living_room_temperature
    outdoor_sensor: sensor.outdoor_temperature_forecast
    off_peak_sensor: binary_sensor.off_peak_electricity_tariff # Optional: French Linky TIC or energy tariff
    
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

### 2. Hydronic Floor Heating with Water Return Sensor

For hydronic systems with a temperature probe clamped to the floor loop return pipe:

```yaml
climate:
  - platform: pwm_floor_heating_thermostat
    name: "Kitchen Hydronic Floor"
    heater: switch.kitchen_underfloor_actuator
    target_sensor: sensor.kitchen_ambient_temperature
    outdoor_sensor: sensor.outdoor_temperature
    off_peak_sensor: binary_sensor.off_peak_electricity_tariff
    
    # Hydronic loop temperature monitoring
    floor_temp_sensor: sensor.kitchen_water_return_temperature # Loop return probe
    max_floor_temp: 27.5                                       # Hard cutoff (DTU 65.14 standard)
    min_floor_temp: 14.0                                       # Slab freeze protection
    
    # Shorter cycles adapted for manifold wax actuators
    min_cycle_duration: "00:15:00"
    min_off_cycle_duration: "00:10:00"
    heat_loss_wk: 45.0
    power_watts: 3200.0
    dead_time_hours: 1.5
```

### 3. Shadow / Simulation Mode (Dry-Run in parallel with existing PID)

Run safely alongside an existing PID or manual thermostat. The model will calculate everything, record state, and report why and when it would have started heating—**without triggering the physical switch**:

```yaml
climate:
  - platform: pwm_floor_heating_thermostat
    name: "Living Room Simulation Shadow"
    target_sensor: sensor.living_room_temperature
    outdoor_sensor: sensor.outdoor_temperature_forecast
    off_peak_sensor: binary_sensor.off_peak_electricity_tariff
    
    # Shadow mode configuration
    dry_run: true                                          # Disables physical relay switching!
    heater: input_boolean.living_room_simulated_relay      # Optional: virtual helper to visualize simulated state
    observed_heater: switch.living_room_compressor_relay   # Observe what the existing PID is currently doing
    
    heat_loss_wk: 60.0
    power_watts: 6500.0
    slab_tau_hours: 15.0
    dead_time_hours: 2.25
    
    # Anti-Peak Tariff Quota Enforcement
    enforce_daily_quota: true                              # Inhibit unnecessary Peak-Hour cycles once daily quota is fulfilled
    enforce_daily_quota_sensor: input_boolean.enforce_daily_quota_living_room # Optional: toggle switch directly in Lovelace UI
```

> [!NOTE]
> **French Linky TIC users:** For backward compatibility, `heures_creuses_sensor` can be used as a direct alias for `off_peak_sensor` (e.g. `heures_creuses_sensor: binary_sensor.heures_creuses_nuit`).

---

## License

MIT License - Copyright (c) 2026 Nitrogene.
