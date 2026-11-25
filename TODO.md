# Development Roadmap & Technical Specifications (TODO.md)

This document tracks all **pending tasks, bug fixes, algorithmic improvements, and technical milestones** for the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration.
All items are strictly ordered from **most critical to least critical**.

---

## 0. v0.4.0 — Unified Predictive Energy-Balance Engine (HC/HP & Forecast Curve)

*Architectural overhaul replacing the legacy midnight-reset daily quota and greedy Rule A off-peak precharge with a unified, forecast-driven predictive energy-balance model (MPC).*

### Critical / Core Regulation Engine
- [x] **[CORE - M-01] Require Weather API & External Sensor with 3-Tier Forecast Curve Fallback (`config_flow.py`, `climate.py`) :**
  - Make `weather_entity` (hourly forecast API) and `outdoor_sensor` mandatory in `ConfigFlow` and `OptionsFlow`.
  - Build a unified hourly heat-loss demand curve $P_{\text{need}}(t) = H_{\text{eff}} \cdot f_{\text{wind}} \cdot \max(0, T_{\text{target}} - T_{\text{ext}}(t))$ over a rolling 24h horizon using a strict 3-tier fallback cascade:
    - **Tier 1 (Primary):** Hourly forecast from `weather_entity` (`weather.get_forecasts(type="hourly")`, 15-min cache).
    - **Tier 2 (Local fallback):** Rolling 24h persistence/average profile from `outdoor_sensor` when the weather API is unavailable.
    - **Tier 3 (Degraded fallback):** Observed passive cooling derivative $dT/dt$ from the Kalata observer ($P \approx -C \cdot dT/dt$) when `outdoor_sensor` is also unavailable.
- [x] **[CORE - M-02] Slab In-Transit Energy Tracker ($E_{\text{transit}}$) & Closed-Loop Recalibration (`climate.py`, `Store`) :**
  - Track active and recently injected thermal energy still propagating through the slab over the effective dead time $\theta_{\text{eff}}$ (`slab_energy_in_transit_kwh`), persisted across restarts in `Store`.
  - Combine $E_{\text{transit}}$ with the room's current thermal state $C_{\text{eff}} \cdot (T_{\text{cur}} - T_{\text{target}})$ (where $C_{\text{eff}} = H_{\text{eff}} \cdot \tau$) so that free heat gains (sun, appliances, adjacent rooms) continuously recalibrate the reservoir in closed loop and prevent back-to-back blind cycles.
- [x] **[CORE - M-03] Unified HC/HP Decision Engine with End-of-Off-Peak Scheduling (`climate.py`) :**
  - Remove legacy greedy Rule A (`off_peak_precharge` ignoring quota) and legacy midnight-reset daily quota / `unserved_quota_carryover_hours`.
  - **Off-Peak (HC) scheduling:** Compute total predicted heat losses until the next off-peak window, subtract current excess room energy and $E_{\text{transit}}$, and schedule the required heating pulse(s) ($\ge 30\text{ min}$ Danfoss minimum) toward the **end of the off-peak window** (accounting for inter-zone `stagger_delay` and `off_peak_end_entity` / configurable off-peak duration) to minimize overnight losses and deliver comfort at wake-up.
  - **Off-Peak comfort ceiling (`off_peak_comfort_margin`):** Add configurable upper margin (default `+0.3°C`, range `0.0°C` to `0.5°C`) in `ConfigFlow` / `OptionsFlow`; inhibit or stop off-peak charging whenever $T_{\text{cur}}$ or projected peak temperature exceeds $T_{\text{target}} + \text{off\_peak\_comfort\_margin}$.
  - **Peak (HP) strict top-up:** Only trigger heating during peak hours if the projected energy balance (including $E_{\text{transit}}$) predicts a drop below $T_{\text{target}} - \text{threshold}$ **before** the next off-peak window, keeping short cycles (`peak_max_run_duration`, default `45 min`) and preserving all safety overrides (Rule 0 `-1.5°C` emergency deficit, `-0.8°C` comfort safety deficit, Hard Overshoot Cutoff, Thermal Runaway, Open Window, Danfoss 30/15 locks).

- [x] **[CORE - M-04] Zero-Impact Home Assistant Restart Persistence (`climate.py`, `Store`) :**
  - Ensure a Home Assistant restart or integration reload has zero behavioral impact on ongoing thermal calculations by persisting all time-stamped model state in `Store` (flushed on `EVENT_HOMEASSISTANT_STOP`):
    - Timestamped slab energy-in-transit pulses (`[[ts_utc, kwh], ...]` over the last ~4h) so elapsed downtime is accurately subtracted on boot.
    - Rolling 24h hourly `outdoor_sensor` history (up to 24 hourly points) so Tier 2 local fallback is immediately ready after reboot.
    - Last valid hourly weather forecast curve (with timestamps) so Tier 1 survives a reboot during a brief weather API outage.
    - Open-window and post-airing recovery timestamps (`_window_open`, `_window_open_time`, `_window_recovery_until`, and recent `_temp_history`) so rebooting shortly after airing never triggers a spurious emergency heating cycle.

### Breaking Changes, Companion Sensors & Validation
- [x] **[BREAKING - M-05] Replace Legacy Quota Sensors & Config Options with Dedicated Predictive Energy Sensors (`sensor.py`, `config_flow.py`, `diagnostics.py`, `translations/`) :**
  - Remove legacy quota entities and options (`enforce_daily_quota`, `enforce_daily_quota_sensor`, `energy_quota_24h_kwh`, `heating_hours_remaining_24h`, `daily_quota_blocked`, `unserved_quota_carryover_hours`).
  - Expose new dedicated companion sensors with full EN/FR translations:
    - `forecast_energy_need_24h_kwh` (rolling 24h integral of the weather demand curve)
    - `slab_energy_in_transit_kwh` (energy currently propagating through the slab)
    - `planned_heating_hours` (remaining compressor hours required to cover the horizon)
    - Update `next_transition_time` lookahead to reflect end-of-off-peak scheduled start/stop times.
- [x] **[TESTS & RELEASE - M-06] Simulation, Full Test Suite, README Update & v0.4.0 Release (`tests/`, `CHANGELOG.md`, `README.md`, `manifest.json`) :**
  - Add unit and E2E tests covering the 3-tier fallback cascade, $E_{\text{transit}}$ propagation & persistence, end-of-HC placement, `+0.3°C` HC comfort margin, strict HP top-up, midnight-crossing stability, and zero-impact HA restart recovery (mid-cycle, post-airing, and during weather outage).
  - Update `README.md` thoroughly (unified HC/HP architecture, mandatory weather/outdoor inputs & 3-tier fallback, end-of-HC scheduling, zero-impact restart persistence, new companion sensors table, and v0.3.x $\to$ v0.4.0 migration guide).
  - Finalize `CHANGELOG.md` breaking-change notes and validate 100% CI (Pytest, Ruff, Hassfest, HACS) before tagging `v0.4.0`.
  - *(Downstream `MyHomeAutomation` follow-up)* Update `dashboards/maison.yaml`, `config/packages/geothermie.yaml`, and `pwm.md` for the new v0.4.0 companion sensors and removal of `input_boolean.plafonnement_quota_*`.
