# Development Roadmap & Technical Specifications (TODO.md)

This document tracks the technical roadmap, algorithmic specifications, and development milestones of the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration.

---

## 1. Thermodynamic Engine & Physical Modeling

- [x] **Predictive Trajectory Projection with Dead Time ($\theta$):**
  - [x] Filtered temperature derivative $dT/dt$ (°C/h) via robust moving linear regression window (60 min).
  - [x] Projected ahead temperature calculation: $T_{\text{proj}}(t + \theta) = T_{\text{amb}}(t) + \theta \cdot \frac{dT_{\text{amb}}}{dt}$.
  - [x] Inflection point detection (morning cold dip) $\theta$ hours ahead to trigger heating before ambient drops below target setpoint.
  - [x] Telemetry attributes exposure: `temp_derivative_hourly` and `temp_projected_ahead`.
- [x] **Dynamic Heat Gains & Environmental Losses:**
  - [x] **Wind Convective Loss Amplification (`wind_sensor`):** Optional wind speed integration scaling building heat loss above 15 km/h (+0.5%/km/h, clamped to max +25%).
  - [x] **Solar Irradiance Integration with Morning Comfort Guard (`solar_sensor`):** Daytime solar gain deduction bounded by max 25% quota reduction, with inviolable 0h-9h morning comfort guard preventing under-heated morning wake-up.
- [ ] **Inter-Zone Convective Coupling:**
  - [ ] Model passive thermal heat transfers between adjacent open spaces (e.g. warm air convective draft from Living Room to Mezzanine/Office).
  - [x] **Multi-Zone Electrical Coordinator (`stagger_delay`):** Smooths grid power draws by staggering startup sequences across zones (preventing simultaneous 13 kW inrush).
- [x] **Self-Calibration & Continuous Learning:**
  - [x] Periodic heat loss estimation $H = U \cdot A$ (W/K) via passive unheated night decay periods.
  - [x] **Mode A (Advisory Passive Telemetry):** Telemetry attribute `heat_loss_measured_wk` showing real-world measured building heat loss without altering active control.
  - [x] **Mode B (Soft Auto-Adaptation `auto_calibrate_heat_loss: true`):**
    - [x] Strict validation conditions (minimum 3 validated night decay samples).
    - [x] Slow exponential smoothing IIR filter preventing sudden jumps.
    - [x] Hard bounds clamped to $\pm 20\%$ of baseline configured $H$.
  - [x] **Dynamic Calibration of Slab Dead Time $\theta$ (`auto_calibrate_dead_time`):** Experimental inflection point identification on active heating cycles with exponential filtering and optional $\pm 25\%$ soft adaptation.

---

## 2. Energy Scheduling, Danfoss FSM & Operation Modes

- [x] **Danfoss Finite State Machine (Mechanical Compressor Guard):**
  - [x] Minimum ON cycle: 30 minutes (mandatory oil return to compressor crankcase).
  - [x] Minimum OFF cycle: 15 minutes (full refrigerant pressure equalization between BP and HP).
  - [x] Maximum daily cycle budget (mechanical anti-fatigue, max 6 cycles/day).
- [x] **Shadow Mode & Digital Twin (Passive Dry-Run):**
  - [x] `dry_run: true` setting ensuring zero physical relay switching.
  - [x] Virtual helper support (`input_boolean.*`) to visualize simulated switching in the UI.
  - [x] `observed_heater` parameter to listen to and benchmark against existing legacy thermostat in real time.
  - [x] Explainability attributes: `simulated_heater_state`, `decision_reason`, and `dry_run`.
- [x] **Hydronic Underfloor Systems & Loop Water Return Probes:**
  - [x] Optional `floor_temp_sensor` parameter (direct water loop return probe monitoring).
  - [x] Emergency slab anti-overshoot cutoff `max_floor_temp` (default 28.0°C compliant with DTU 65.14 standard).
  - [x] Slab anti-freeze protection `min_floor_temp` (default 14.0°C).
  - [x] Telemetry attributes `floor_temperature`, `max_floor_temperature`, `min_floor_temperature`.
- [x] **Daily Energy Quota Enforcement & Anti-Peak Tariff Protection:**
  - [x] `enforce_daily_quota` and `enforce_daily_quota_sensor` options for instant UI Lovelace toggle.
  - [x] Automatic inhibition of Peak-Hour cycles once the 24h thermal budget has been satisfied during cheap Off-Peak hours.
  - [x] Comfort safety fallback (forced startup if setpoint deficit $\ge 0.8$°C).
  - [x] Realtime telemetry (`daily_quota_enforced`, `daily_quota_blocked`, `heating_hours_remaining_24h`).
- [x] **Open Window / Rapid Ventilation Detection (`window_detection`):**
  - [x] Automatic detection via rapid temperature drop rate ($dT/dt \le -1.5^\circ\text{C/h}$ or drop $> 0.4^\circ\text{C}$ in 15 min).
  - [x] Support for physical magnetic contact sensors (`window_sensor: binary_sensor.*`) and Lovelace UI toggle (`window_detection_sensor: input_boolean.*`).
  - [x] Instant heating suspension with `window_open` state and auto-recovery timer.
- [x] **Multi-Zone Coordination & Startup Inrush Staggering (`stagger_delay`):**
  - [x] Eliminates simultaneous multi-compressor startup spikes on Off-Peak switchover (e.g. 13 kW cumulative surge).
  - [x] Configurable delay (e.g. `stagger_delay: "00:05:00"`) with live countdown attribute (`stagger_delay_sec`).
- [x] **Native Home Assistant Presets (`Comfort`, `Eco`, `Away`):**
  - [x] Registered native presets `preset_modes: ["comfort", "eco", "away"]`.
  - [x] Dedicated setpoints `eco_temp` (default: 17.0°C) and `away_temp` (default: 15.0°C).
  - [x] 1-click preset switching in Lovelace without losing nominal comfort setpoint.
- [x] **Core Off-Peak Tariff Optimization & Anti-Peak Protection (Linky TIC):**
  - [x] Realtime Linky TIC integration via `off_peak_sensor` (`binary_sensor.heures_creuses_nuit`).
  - [x] Daily energy quota enforcement: blocks unnecessary Peak-Hour cycles once the daily thermal requirement is fulfilled.
  - [x] Startup inrush staggering (`stagger_delay`) preventing 13 kW simultaneous power surges.
  - [x] Absolute comfort fallback override (forces startup if setpoint deficit $\ge 0.8$°C).
- [ ] **Advanced Dynamic Tariffs & Multi-Rate Schedulers (Future Roadmap):**
  - [ ] Dynamic hourly spot-market tariff integration (EPEX Spot, NordPool, French EDF Tempo 6-color matrix).
  - [x] **Adaptive PWM Period Modulation (`peak_max_run_duration`):** Deep multi-hour accumulation cycles in Off-Peak vs 45 min capped top-up cycles in Peak hours with thermal diffusion pauses.
- [x] **Slow Drift Ambient Supervisor (Anti-Integral Windup):**
  - [x] Gentle and bounded proportional trim on the 24h daily energy quota ($K_{\text{ambient}} = 0.15\text{ /}^\circ\text{C}$, clamped $[0.80, 1.25]$).
  - [x] Permanent elimination of continuous divergent integrator windup and steady-state offsets.

---

## 3. Advanced Telemetry & Debug Data for AI Calibration (Auto-Tuning)

- [x] **Internal Physical Model Variables Telemetry (Exposed in `extra_state_attributes`):**
  - [x] `temp_projected_ahead`: Anticipated temperature at $t + \theta$ (°C).
  - [x] `temp_derivative_hourly`: Filtered derivative $dT/dt$ (°C/h).
  - [x] `daily_energy_quota_kwh`: Required 24h thermal quota calculated from weather forecast (`energy_quota_24h_kwh`).
  - [x] `heating_hours_needed_24h`, `heating_hours_done_today`, `heating_hours_remaining_24h`: Realtime compressor hour budget accounting.
  - [x] `duty_cycle_continuous`: Continuous theoretical requested duty ratio.
  - [x] `heat_loss_factor_wk`: Active building heat loss coefficient.
- [x] **FSM Instrumentation & Diagnostics (Exposed in `extra_state_attributes`):**
  - [x] `fsm_state` (`idle`, `running_min_lock`, `running_normal`, `waiting_min_off`).
  - [x] `cycles_count_today` and `max_cycles_budget` (`compressor_cycles_today`).
  - [x] `time_to_next_allowed_start` (`min_off_lock_remaining_sec` pressure equalization countdown).
  - [x] `min_cycle_lock_remaining_sec`: Mandatory oil return countdown.
- [x] **Passive Identification & Self-Learning Telemetry:**
  - [x] `heat_loss_measured_wk`: Passive unheated decay rate identification (Mode A).
  - [x] `heat_loss_samples_count`: Validated night decay measurement count.
- [x] **Model Error Metric ($e_{\text{model}}$):**
  - [x] Realtime evaluation: $e_{\text{model}}(t) = T_{\text{measured}}(t) - T_{\text{projected}}(t - \theta)$ exposed in `model_error` attribute.
  - [x] Linear interpolation across rolling projection history window.
  - [x] State restoration across Home Assistant reboots via `RestoreEntity`.
  - [x] Unit tested calculation (`tests/test_math.py`).
- [x] **Automated Companion Diagnostic Sensors (`sensor` Platform):**
  - [x] Dedicated `sensor.py` platform registering 7 companion diagnostic entities attached to the Device card.
  - [x] Native Home Assistant SQLite / InfluxDB recording and graphing without external YAML template sensors.
  - [x] Instant reactive dispatcher synchronization upon thermostat state updates (`async_dispatcher_connect`).
  - [x] English and French localized translation keys.

---

## 4. Software Quality, Testing & HACS Ecosystem

- [x] **HACS Compatibility:**
  - [x] `hacs.json` configured with `"content_in_root": true`.
  - [x] Standalone repository layout, MIT License, and comprehensive `README.md`.
- [x] **CI/CD Validation Workflows (GitHub Actions):**
  - [x] Manifest validator workflow (`hassfest`).
  - [x] HACS compliance workflow (`hacs` action).
  - [x] Code style and typing workflow (`ruff check`).
  - [x] Automated unit test suite (`pytest`) validating Danfoss FSM transitions, linear regression math, and DTU 65.14 safeties.
- [x] **Translations & Entity Metadata:**
  - [x] Root metadata `strings.json`.
  - [x] Full localization in English (`translations/en.json`) and French (`translations/fr.json`).
- [x] **Config Flow & Options Flow (Native Home Assistant UI) [Priority 1]:**
  - [x] Implemented `config_flow.py` allowing thermostat creation directly via UI (*Settings -> Devices & Services -> Add Integration*).
  - [x] Implemented dynamic `OptionsFlow` for runtime tuning (Shadow Mode toggle, heat loss $H$, dead time $\theta$, presets, anti-peak delay) without restarting Home Assistant.
  - [x] Resolved 500 error on Options Flow for Home Assistant 2024.4+ (safe `_config_entry` encapsulation).
  - [x] Implemented native diagnostics platform `diagnostics.py` ("Download diagnostics" button with automatic token redaction).
  - [x] Added standardized GitHub issue templates (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`).
  - [x] Declared `"config_flow": true` in `manifest.json`.
  - [x] Synchronized `strings.json` and translations (`translations/fr.json`, `translations/en.json`).
  - [x] Connected entry setup and unload handlers (`async_setup_entry`, `async_unload_entry`) in `__init__.py` and `climate.py`.
  - [x] Dedicated unit test suite (`tests/test_config_flow.py`, `tests/test_diagnostics.py`).
- [x] **Official HACS Default Submission (PR on hacs/default) [Priority 2]:**
  - [x] **Field Soak Test & Real-World Telemetry:** Validated on 24h real-world cycle across 3 zones (aeration freeze, Kalata quantization filtering, overshoot prevention, off-peak precharge).
  - [x] **UI Journey Screenshots:** HACS installation, Config Flow step-by-step, device card, and integration hub for documentation (`README.md`).
  - [x] **Final HACS Submission Gate:** 100% green CI (Hassfest, HACS, Ruff, Pytest), brand assets (icon, logo).
  - [x] **Submit Pull Request:** Open PR on official community repository `hacs/default` ([PR #13790](https://github.com/hacs/default/pull/13790)).
  - [x] **Public Directory Listing:** Approved and merged into official community repository `hacs/default` by @frenck! 1-click installation available worldwide in Home Assistant.
