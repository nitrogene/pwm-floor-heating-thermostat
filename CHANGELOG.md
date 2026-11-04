# Changelog

All notable changes to the **PWM Floor Heating Thermostat** integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.5] - 2026-11-04

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
