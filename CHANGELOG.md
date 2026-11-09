# Changelog

All notable changes to the **PWM Floor Heating Thermostat** integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.4] - 2026-11-09

### Fixed
- **FSM Deferred Shutdown on HVAC OFF**:
  - Resolved critical issue where requesting `HVACMode.OFF` while compressor was in `FSM_RUNNING_MIN_LOCK` caused premature loop exit, leaving the physical compressor running indefinitely.
  - Periodic control loop now maintains safe shutdown tracking until the 30-minute minimum runtime elapses, properly turning off the actuator and entering `FSM_WAITING_MIN_OFF`.
- **Enforce Daily Compressor Cycle Budget (`max_cycles_per_day`)**:
  - Applied Danfoss mechanical anti-fatigue constraint in `_async_start_heating_safe` (denies startup once `_cycles_today >= _max_cycles`), with safety override for floor frost protection.
- **Diagnostics Dump Field Alignment (`diagnostics.py`)**:
  - Re-aligned internal entity attribute names in diagnostics export (`_temp_derivative`, `_temp_projected`, `_energy_needed_kwh`, `_hours_needed_24h`, `_hours_run_today`, `_quota_blocked`, `_window_open`, `_cycles_today`), eliminating null values in "Download diagnostics".
- **Resilient Reboot FSM State & Counters Restoration**:
  - On Home Assistant restart during an active run cycle, safely transitions to `WAITING_MIN_OFF` to enforce mandatory refrigerant pressure equalization before allowing any restart.
  - Added datation stamp (`counters_date`) to daily cycle and run hour counters to prevent carrying over stale counters from previous days after overnight downtime.
- **Midnight Counters Reset in OFF Mode**:
  - Evaluated daily midnight counter reset prior to HVAC mode evaluation, ensuring cycles and operating hours reset cleanly even if the thermostat is turned OFF for days.

### Added
- **Modern Home Assistant Compliance**:
  - Added `ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF` in `supported_features` for full Home Assistant 2024.2+ compatibility.
  - Declared `_attr_min_temp = 16.0` and `_attr_max_temp = 26.0` properties restricting UI setpoint slider to floor heating operational ranges.
  - Migrated `iot_class` from `local_polling` to `local_push` in `manifest.json`.
  - Added `heater_required_unless_dry_run` validation check in Config Flow.
- **Defensive Error Handling & CI Concurrency**:
  - Wrapped physical switch service calls (`turn_on` / `turn_off`) in `try...except Exception` blocks to prevent unhandled service exceptions.
  - Added GitHub Actions concurrency controls and least-privilege read permissions in `validate.yaml`.

---

## [0.2.3] - 2026-11-09

### Added
- **Continuous-Discrete $\alpha$-$\beta$ State Observer (Kalata Optimal Kalman 1D)**:
  - Replaced rolling linear regression with a state observer ($T$, $\dot{T}$) modeling Zigbee sensor quantization noise ($R = \Delta^2 / 12$) and building slab acceleration limits ($q$).
  - Dynamically computes optimal $\alpha$ and $\beta$ gains using the Kalata formulation across variable event-driven update intervals $\Delta t$.
  - Completely eliminates high-frequency derivative noise and sawtooth oscillations in projected slab temperature ($T_{\text{projected}}$).
- **Ventilation & Post-Airing Thermal Damping**:
  - Automatically freezes slab projection derivative to $0.0\text{ °C/h}$ during active window opening / rapid room aeration, preventing false projection plunges.
  - Implements a 30-minute post-airing recovery window with bounded positive derivative to prevent false overshoot spikes when cold air rewarms against warm building envelope surfaces.

### Fixed
- **Startup Projection Spike Fix**:
  - Resolved startup artifact where `temp_projected_ahead` was initialized to hardcoded `19.0 °C` before first sensor reading, causing a vertical drop on Lovelace graphs.
  - Initialized to `None` with direct alignment to measured room ambient temperature on the first received sample.

### Changed
- **Codebase Internationalization & English Standardization**:
  - Standardized all Python module code, docstrings, internal comments, and unit test documentation across the entire integration repository to 100% English.

---

## [0.2.2] - 2026-11-08

### Added
- **Native Diagnostic Sensor Platform (`sensor.py`)**:
  - Automatically instantiates 7 companion diagnostic entities attached directly to the thermostat device card (`temp_projected_ahead`, `temp_derivative_hourly`, `model_error`, `energy_quota_24h_kwh`, `heating_hours_remaining_24h`, `heat_loss_measured_wk`, `fsm_state`).
  - Enables out-of-the-box long-term statistics and Lovelace graphing without requiring custom YAML template sensors.
  - Reactive state propagation with the master climate entity using Home Assistant core dispatcher (`async_dispatcher_send` / `async_dispatcher_connect`).
  - Full English and French entity localization in `strings.json` and `translations/`.
- **Thermodynamic Model Error Metric ($e_{\text{model}}$)**:
  - Continuously evaluates prediction accuracy: $e_{\text{model}}(t) = T_{\text{measured}}(t) - T_{\text{projected}}(t - \theta)$.
  - Uses linear interpolation across rolling projection history window.
  - Exposes `model_error` in `extra_state_attributes` and native diagnostics export with `RestoreEntity` state restoration.
  - Dedicated unit test suite (`tests/test_math.py`).

### Changed
- **Power Input Step Resolution**:
  - Relaxed heating power input step from 100 W to 10 W in Config Flow and Options Flow, allowing fine-grained entries like 3250 W.
- **Documentation & Localization**:
  - Full translation of the development roadmap (`TODO.md`) into technical English for HACS default repository compliance.
  - Reorganized and clarified off-peak tariff optimization vs future spot-market schedulers.

---

## [0.2.1] - 2026-11-08

### Fixed
- **Options Flow 500 Error Fix**:
  - Resolved `AttributeError: property 'config_entry' of 'OptionsFlowHandler' object has no setter` on Home Assistant 2024.4+ when accessing integration options via the gear icon ⚙️.
  - Implemented safe internal `_config_entry` encapsulation with fallback property accessor.

### Added
- **Native Diagnostics Platform (`diagnostics.py`)**:
  - Full support for Home Assistant's native "Download diagnostics" button (*Settings -> Devices & Services -> PWM Floor Heating Thermostat -> Download diagnostics*).
  - Generates a sanitized JSON export of entry data, options, live climate entity state, thermodynamic model attributes, Danfoss FSM state, and telemetry with sensitive tokens automatically redacted.
  - Dedicated unit tests (`tests/test_diagnostics.py`).
- **Standardized GitHub Issue Templates**:
  - Added structured `.github/ISSUE_TEMPLATE/bug_report.yml` prompting for HA version, integration version, heating architecture, diagnostics file attachment, and debug logs.
  - Added `.github/ISSUE_TEMPLATE/feature_request.yml`.
- **Documentation & Visual Setup Guide**:
  - Added step-by-step UI installation and configuration screenshots to `README.md`.
  - Added detailed Troubleshooting, Debug Logging (`logger:`), and Diagnostics export section.

---

## [0.2.0] - 2026-11-05

### Added
- **Native Home Assistant Config Flow (`config_flow.py`)**:
  - Full UI setup support: Add thermostats directly via *Settings -> Devices & Services -> Add Integration*.
  - Guided form validating required temperature sensors (`target_sensor`, `outdoor_sensor`), physical/virtual actuators (`heater`), off-peak tariff sensor, floor slab sensor, and core thermodynamic parameters ($H$, $P$, $\tau$, $\theta$).
  - Automatic predictable `unique_id` assignment preventing duplicate thermostat instances.
- **Dynamic Options Flow**:
  - Realtime parameter tuning without restarting Home Assistant (*Settings -> Devices & Services -> Configure*).
  - Instant toggle between *Shadow Mode (Simulation)* and *Active Physical Control* (`dry_run`).
  - Runtime calibration of building heat loss ($H$ in W/K), slab dead time ($\theta$), slab time constant ($\tau$), daily quota enforcement, open window detection, and floor temperature DTU limits.
  - Automatic entity reload with seamless state restoration via `RestoreEntity`.
- **Integration Device Registry**:
  - Exposes dedicated Home Assistant Device cards bound to `pwm_floor_heating_thermostat` (`Nitrogene` - `PWM Thermodynamic Underfloor Thermostat`).
- **Translations & Hassfest Compliance**:
  - Full localization in French (`translations/fr.json`) and English (`strings.json`, `translations/en.json`).
  - Comprehensive unit test suite (`tests/test_config_flow.py`) validating user flow, duplicate aborts, options updates, and platform delegation (35 automated unit tests passing).

---

## [0.1.6] - 2026-11-04

### Added
- **Native Home Assistant Presets (`comfort`, `eco`, `away`)**:
  - Integrated standard `ClimateEntityFeature.PRESET_MODE` with `comfort`, `eco`, and `away` modes.
  - Dedicated configurable setpoints: `eco_temp` (default: 17.0°C), `away_temp` (default: 15.0°C), and `comfort_temp` (default: target_temp).
  - One-click preset switching directly from Lovelace without losing the nominal comfort setpoint.
  - State restoration across Home Assistant reboots via `RestoreEntity`.
  - Extra state attributes: `comfort_temp`, `eco_temp`, `away_temp`.
- **Multi-Zone Coordination & Anti-Inrush Peak Staggering (`stagger_delay`)**:
  - Added `stagger_delay` (time period, default: 0s) to sequence compressor startups across multiple zones (e.g. 0s Salon, 5 min Chambre, 10 min Bureau).
  - Prevents massive electrical grid inrush current spikes and 13 kW simultaneous power surges when switching into cheap Off-Peak hours.
  - Exposes `stagger_delay_sec` in attributes with realtime countdown in `decision_reason`.

### Added
- **Open Window / Rapid Ventilation Detection**:
  - Added `window_detection` (boolean, default: true) and `window_detection_sensor` (`input_boolean` entity) for full UI toggle override from Lovelace.
  - Added `window_sensor` (`binary_sensor`) option for direct physical magnetic contact sensors.
  - Automatic drop detection: detects rapid temperature drops ($\ge 0.4^\circ\text{C}$ in $\le 15$ minutes or $dT/dt \le -1.5^\circ\text{C/h}$).
  - Heating suspension: immediately inhibits compressor start or safely winds down running cycle via Danfoss FSM without violating oil lubrication guards.
  - Auto-recovery: resumes regulation when temperature starts rising ($> +0.2^\circ\text{C/h}$) or after `window_timeout` (default: 30 minutes).
  - New telemetry attributes: `window_detection_active`, `window_open_detected`.
- **Passive Building Heat Loss Auto-Calibration (Mode A - Advisory Telemetry)**:
  - Continuously identifies the actual physical heat loss coefficient $U \cdot A$ ($W/K$) during relaxed passive night decay periods ($t_{\text{off}} \ge 2 \cdot \theta$, $\Delta T \ge 3^\circ\text{C}$, $dT/dt < -0.05^\circ\text{C/h}$, window closed).
  - Employs a robust outlier rejection filter and a slow 98/2 IIR exponential smoothing filter.
  - Persists learned value across Home Assistant reboots via `RestoreEntity`.
  - New telemetry attributes: `heat_loss_measured_wk` and `heat_loss_samples_count`.

### Added
- **Dynamic Daily Quota Enforcement (Anti-Peak Tariff Protection)**:
  - Added `enforce_daily_quota` (boolean, default: true) and `enforce_daily_quota_sensor` (`input_boolean` entity) configuration options.
  - Automatically inhibits unnecessary compressor cycles in Peak hours (Heures Pleines) once the 24-hour heat quota has been fulfilled during cheap Off-Peak hours.
  - Full UI override: toggle the switch directly from Lovelace dashboards (`maison.yaml`) without restarting Home Assistant.
  - Absolute comfort fallback: safety override triggers heating if ambient temperature unexpectedly drops more than 0.8°C below setpoint.
  - New telemetry attributes: `daily_quota_enforced`, `daily_quota_blocked`, `heating_hours_remaining_24h`.
  - Real-time continuous tracking of active running cycles in `heating_hours_done_today`.

---

## [0.1.3] - 2026-11-04

### Added
- **Automated GitHub Releases**: Fully automated GitHub Actions workflow (`.github/workflows/release.yaml`) automatically triggering, compiling and publishing official GitHub Releases upon any new `v*` tag.
- **Enhanced Documentation Badges**: Official vector logos for Open Source Initiative (MIT License), Home Assistant (HACS), and GitHub Actions status.

### Changed
- Converted all raw LaTeX mathematical formulas in `README.md` to universal standard Markdown and UTF-8 typography for clean rendering in the HACS in-app browser.

---

## [0.1.2] - 2026-11-04

### Added
- **Native `unique_id` Support**: Added official `unique_id` option to `PLATFORM_SCHEMA` and `PwmFloorHeatingThermostat` entity, allowing users to rename, configure and assign areas directly from the Home Assistant UI.

---

## [0.1.1] - 2026-11-04

### Added
- **Complete Brand Assets Pack**:
  - Light mode: `icon.png` (256x256) and `icon@2x.png` (512x512).
  - Dark mode: `dark_icon.png` (256x256) and `dark_icon@2x.png` (512x512).
  - Banners & Logos: `logo.png`, `logo@2x.png`, `dark_logo.png`, and `dark_logo@2x.png`.
- Full compliance with modern Home Assistant local branding specifications (`custom_components/<domain>/brand/`).

---

## [0.1.0] - 2026-11-03

### Initial Release
- **Predictive Thermodynamic Slab Engine**:
  - Pure dead-time ($\theta$) trajectory projection via linear regression on rolling ambient temperature.
  - Heat deficit calculation over 24-hour horizon based on building heat loss ($H$ in W/K) and outdoor forecast ($H_0 \rightarrow H+4$).
- **Inviolable Danfoss Compressor FSM**:
  - Guaranteed minimum ON duration (30 minutes) ensuring complete oil return to the crankcase.
  - Guaranteed minimum OFF duration (15 minutes) ensuring complete refrigerant pressure balance.
  - Daily cycle budget enforcement (max 6 cycles/day) protecting mechanical equipment from fatigue.
- **Shadow Mode (Digital Twin)**:
  - Zero-risk simulation (`dry_run: true`) running in parallel with existing PID thermostats.
  - Live comparison with physical switches via `observed_heater`.
  - Comprehensive telemetry attributes (`decision_reason`, `fsm_state`, `temp_projected_ahead`, `energy_quota_24h_kwh`).
- **Hydronic Floor & Water Loop Sensor Support**:
  - Optional `floor_temp_sensor` monitoring return water.
  - Anti-overshoot safety enforcing European standard DTU 65.14 (28°C max floor temperature).
  - Slab freeze protection (14°C min floor temperature).
- **Restart Resilience**:
  - Full state, timer, and cycle restoration via `RestoreEntity`.
