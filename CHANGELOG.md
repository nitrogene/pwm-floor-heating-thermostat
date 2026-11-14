# Changelog

All notable changes to the **PWM Floor Heating Thermostat** integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.5] - 2026-11-14

### Added
- **UI Exposure for `off_peak_start_entity`**:
  - Added `off_peak_start_entity` (`input_datetime` / `sensor`) to both `ConfigFlow` and `OptionsFlow` with English and French translations so users can configure their scheduled off-peak start time entity directly in the UI for `sensor.<zone>_next_transition_time`.

---

## [0.3.4] - 2026-11-14

### Added
- **Full UI ConfigFlow & OptionsFlow Feature Parity (`F-11`)**:
  - Exposed `comfort_temp`, `enforce_daily_quota_sensor`, `window_detection_sensor`, `min_cycle_duration`, `min_off_cycle_duration`, and `max_cycles_per_day` in both `ConfigFlow` and `OptionsFlow` with full English and French translations.
- **Persistent Sensor Watchdog Timestamps & Outdoor Sensor Coverage (`F-05`)**:
  - Persists `cur_temp_ts`, `outdoor_temp_ts`, and `last_heat_loss_sample_ts` in the Home Assistant `Store` so stale sensor detection survives restarts and config reloads without being masked by boot-time `last_updated` resets.
  - Evaluates outdoor sensor staleness and falls back cleanly to the rolling 24h weather forecast when the outdoor sensor is stale.
- **Real-Entity FSM & Safety Unit Tests (`F-14`)**:
  - Replaced standalone `MockDanfossFSM` in `tests/test_fsm.py` with tests exercising `PwmFloorHeatingThermostat` directly, plus dedicated tests for `F-04`, `F-07`, and `F-13` (90 unit tests passing).

### Changed
- **Kalata Process Noise Default & Import-Time I/O Removal (`F-08`, `F-13`)**:
  - Lowered `DEFAULT_KALATA_PROCESS_NOISE` from `0.005` to `0.001` `(°C/h)²/h`.
  - Replaced synchronous `open("manifest.json")` at module import time in `const.py` with a static `INTEGRATION_VERSION = "0.3.4"` verified against `manifest.json` by unit test, eliminating Home Assistant 2024.6+ event-loop blocking I/O warnings.
- Bumped integration version to `0.3.4` in `manifest.json` and `pyproject.toml`.

### Fixed
- **Mode A / Mode B Heat Loss ($H$) Downward Drift Prevention (`F-07`)**:
  - Restricted passive Mode A heat loss sampling to genuine night-time cooling windows (`23:00–06:00` local time with zero solar credit), throttled sample counting to at most 1 sample per hour, and enforced a minimum safety floor of `50%` of configured baseline $H$ (`MIN_HEAT_LOSS_RATIO = 0.50`) in Mode B even after `heat_loss_confidence_samples` is reached.
- **Rule B Anticipation Threshold Cap & Passive-Regime RMS Accumulation (`F-08`)**:
  - Restricted `_model_error_history` accumulation to passive cooling/resting regimes (`FSM_IDLE` / `FSM_WAITING_MIN_OFF` and `derivative_smooth <= 0.05`) and capped `rule_b_threshold` at `0.60°C` (`MAX_RULE_B_THRESHOLD`), preventing positive-slope heating or solar ramps from paralyzing Peak-Hour dead-time anticipation.
- **Decoupled Safety Guards from Outdoor Sensor Availability (`F-04`)**:
  - Moved Rule 0 (Emergency comfort deficit bypass), Rule C (Overshoot prevention), Hard Ambient Overshoot Ceiling, Stale Sensor Watchdog, and Rule E (Open window cutoff) outside the `outdoor_temp is not None` requirement so they remain unconditionally active even if the outdoor sensor becomes `unavailable`.
- **Smoothed Derivative Consistency & Window Detection Execution Order (`F-09`, `F-10`)**:
  - Exposed `_derivative_smooth` in `sensor.<zone>_temp_derivative_hourly` and `diagnostics.py` to match `climate.py`.
  - Updated `_temp_history` and the Kalata state observer before evaluating `_check_window_open_state()`, using `_derivative_smooth` consistently for ventilation detection and recovery.

---

## [0.3.3] - 2026-11-14

### Added
- **Persistent FSM State & Daily Counters Across Restarts/Reloads (`F-01`)**:
  - Persists `fsm_state`, `last_state_change`, `cycle_start_time`, `cycles_today`, `hours_run_today`, and `counters_date` inside the Home Assistant JSON `Store`.
  - Implemented `_reconcile_restored_fsm()`: when Home Assistant restarts or the config entry reloads while a compressor is actively running (`FSM_RUNNING_MIN_LOCK` or `FSM_RUNNING_NORMAL`), the integration restores the active running state and original start timestamp instead of forcing `FSM_WAITING_MIN_OFF`, protecting the mandatory 30-minute Danfoss oil-return minimum runtime lock.
- **Closed-Loop Physical Actuator Verification (`F-02`)**:
  - Implemented hardware-agnostic `_reconcile_rejected_or_stopped_heater()` to verify that `self._heater_entity` genuinely transitions to `"on"` after a `turn_on` call.
  - If a local hardware safety guard or manual override rejects the `turn_on` command (switch remains `"off"` past the 60-second confirmation window), the FSM cleanly reverts to `FSM_IDLE`, rolls back `_cycles_today`, and accumulates zero phantom runtime hours.
  - If an active heater is turned off externally after running for at least 5 minutes, actual elapsed runtime is recorded and the FSM transitions to `FSM_WAITING_MIN_OFF` to enforce the 15-minute pressure equalization rest.
- **Weather Forecast Service Response Caching (`F-17`)**:
  - Added a 15-minute TTL cache (`_weather_forecast_cache` / `_weather_forecast_cache_ts`) in `_async_update_weather_forecast()` so `weather.get_forecasts` is called at most once every 15 minutes instead of every 60 seconds during the control loop.
- **Unit Test Suite**:
  - Added 4 reconciliation and safety tests in `tests/test_v032_reconciliation.py` (`F-01`, `F-02`, `F-03`) and `test_weather_forecast_cache_ttl` in `tests/test_v028_features.py` (88 unit tests passing).

### Changed
- **Code Hygiene & Dead Code Removal (`F-16`)**:
  - Removed unused legacy constants from `const.py`, unused `_handle_thermostat_update` method from `sensor.py`, and unused imports from `config_flow.py`.
- Bumped integration version to `0.3.3` in `manifest.json`.

### Fixed
- **Peak-Hour Max Run Duration Unit Mismatch (`F-03`)**:
  - Fixed `_parse_timedelta()` where numeric `CONF_PEAK_MAX_RUN_DURATION` values saved by `OptionsFlow` (in minutes, e.g. `45`) were parsed as seconds (`45s` -> `0 min`), causing Rule G to cut off Peak-Hour heating cycles prematurely at 30 minutes. Numeric values for `CONF_PEAK_MAX_RUN_DURATION` are now explicitly parsed in minutes (`numeric_unit="minutes"`), and Rule G is guarded by `self._peak_max_run_duration.total_seconds() > 0`.
- **Danfoss 30-Minute Minimum Runtime Protection in `_async_stop_heating_safe()` (`F-01`)**:
  - Added a strict `min_cycle_duration` guard inside `_async_stop_heating_safe()` reconciliation so a running compressor within its 30-minute oil-return window can never be cut off prematurely.
- **Midnight Daily Counter Reset & Solar Forecast Alignment in User Local Timezone (`F-15`)**:
  - Replaced `datetime.now().date()` with `dt_util.now().date()` for midnight counter resets and aligned solar forecast timestamps with `dt_util.now()`.

---

## [0.3.2] - 2026-11-13

### Added
- **Active Reconciliation & Anti-Hijack Relay Guard**:
  - Implemented real-time event listener on `_heater_entity` (`async_track_state_change_event`). If the physical relay is turned ON unexpectedly by an external source (legacy thermostat, third-party automation, manual toggle) while FSM is resting (`FSM_IDLE` or `FSM_WAITING_MIN_OFF`), the thermostat immediately intercepts the event and schedules an active reconciliation cutoff (`turn_off`).
  - Hardened `_async_stop_heating_safe()`: when FSM is in `FSM_IDLE` or `FSM_WAITING_MIN_OFF`, actively queries the physical heater entity state in Home Assistant; if `state == "on"`, immediately issues a `turn_off` service call.
  - Startup reconciliation synchronization: verifies physical switch state upon `EVENT_HOMEASSISTANT_STARTED` during `_async_startup` to guarantee no residual boot-time heater excitation persists.
- **Unit Test Suite**:
  - Added `tests/test_v032_reconciliation.py` (5 unit tests) verifying reconciliation cutoff in `IDLE`, cutoff in `WAITING_MIN_OFF`, no-op when already `OFF`, immediate reaction to physical state change event, and clean bypass during authorized `RUNNING_MIN_LOCK`.

### Changed
- Bumped integration version to `0.3.2` in `manifest.json`.

---

## [0.3.1] - 2026-11-13

### Added
- **Native Next Transition Diagnostic Companion Sensor (`sensor.<zone>_next_transition`)**:
  - Automatically provisions a dedicated 9th diagnostic entity (`SensorDeviceClass.TIMESTAMP`) for each thermostat zone.
  - Predicts and surfaces the exact future wall-clock timestamp of the next FSM state transition (`turn_on` or `turn_off`).
  - Native Lovelace formatting displays relative time ("dans 1 heure", "in 45 minutes") or absolute timestamp according to user preferences.
  - Companion entity exposes rich diagnostic attributes:
    - `transition_type`: Direction of the upcoming transition (`turn_on` or `turn_off`).
    - `transition_reason`: Detailed physical or FSM rationale (e.g. Danfoss 15 min rest, scheduled off-peak precharge with stagger, Rule B cooling drop, quota completion, peak run cap).
    - `earliest_transition_time`: Earliest hardware-legal timestamp strictly respecting Danfoss compressor anti-short-cycle locks (30 min minimum runtime and 15 min pressure equalization rest).
- **Thermodynamic FSM Lookahead Engine**:
  - Implemented `_find_scheduled_off_peak_start(now)` dynamically detecting the next off-peak slot from linked sensors, schedule attributes, or `input_datetime` helpers.
  - Implemented `_update_next_transition_estimate(now)` predicting turn-off during active heating (Danfoss minimum runtime lock, peak-hour top-up run cap, daily thermal quota completion, or max continuous run diffusion pause) and turn-on during resting states (Danfoss rest lock, staggered off-peak precharge, or slab cooling trajectory intersection with Rule B).
- **Unit Test Suite**:
  - Added `tests/test_v031_transition_sensor.py` (6 unit tests) validating turn-off predictions (peak cap, quota completion, max continuous run), turn-on predictions (Danfoss rest, staggered off-peak, cooling drop), and companion sensor attribute surfacing.

### Changed
- Bumped integration version to `0.3.1` in `manifest.json`.
- Updated English and French translations with `next_transition_time` ("Next transition" / "Prochaine bascule").

---

## [0.3.0] - 2026-11-13

### Added
- **Stale Sensor Watchdog (Fail-Safe Heating Shutdown)**:
  - Tracks individual sensor update timestamps (`_cur_temp_ts`, `_outdoor_temp_ts`) on every incoming state change event.
  - Configurable stale timeout via `CONF_SENSOR_STALE_TIMEOUT_MINUTES` (default: 90 min, range: 30 to 360 min, step: 15 min).
  - Safely stops active heating, transitions FSM to `IDLE`, sets `sensor_stale: true` in `extra_state_attributes`, and records explicit diagnostic rationale in `decision_reason`.
  - Automatically clears `sensor_stale` and resumes normal control as soon as a fresh reading is received.
- **Software DTU 65.14 Slab Safeguards for Probe-less Installations**:
  - **Thermal Runaway Cutoff**: Triggers emergency heating cutoff if room heating derivative $dT/dt > +1.5^\circ\text{C/h}$ sustained for $> 30\text{ min}$ during active heating (`CONF_THERMAL_RUNAWAY_DERIVATIVE`, default: 1.5°C/h, range: 0.5 to 3.0°C/h, step: 0.1°C/h).
  - **Hard Ambient Overshoot Ceiling**: Unconditional immediate heating shutoff if room temperature exceeds target plus safety margin ($T_{\text{cur}} \ge T_{\text{target}} + \text{margin}$, `CONF_HARD_OVERSHOOT_MARGIN`, default: 1.0°C, range: 0.3 to 2.5°C, step: 0.1°C).
  - **Global Maximum Continuous Run Cap (`max_continuous_run`)**: Enforces maximum continuous run cap (`CONF_MAX_CONTINUOUS_RUN_MINUTES`, default: 120 min, range: 30 to 240 min, step: 15 min) across all tariff periods (including Off-Peak hours) to guarantee mandatory thermal diffusion rest intervals in the heavy slab.
  - **Emergency Comfort Deficit Bypass**: Rule 0 unconditional heating trigger if room falls severely below target ($T_{\text{cur}} \le T_{\text{target}} - 1.5^\circ\text{C}$), overriding daily thermal quota exhaustion blocks.
- **Runtime UI Configuration (Config Flow & Options Flow)**:
  - Exposed all four new safety parameters with UI number selectors (bounds, step, units) in both initial setup and runtime Options Flow.
  - Complete English (`en.json`) and French (`fr.json`) localization of all new parameters and descriptions.
- **Comprehensive Hardware Safety Test Suite**:
  - Added `tests/test_v030_safeties.py` (6 unit tests) asserting fail-safe watchdog shutdown, recovery, hard overshoot ceiling, global continuous run cap, thermal runaway derivative cutoff, emergency comfort deficit bypass, and config/options flow validation.

### Changed
- Bumped integration version to `0.3.0` in `manifest.json`.

---

## [0.2.9] - 2026-11-11

### Added
- **Two-Stage Mode B Self-Adaptation with Configurable Confidence Threshold**:
  - Introduced configurable `heat_loss_confidence_samples` (default: 10 samples) in both Config Flow and Options Flow.
  - Automatically transitions Mode B adaptation between two thermodynamic stages:
    1. **Stage 1 (Initial ramp-up, 3 <= N < threshold)**: Clamps effective heat loss within +/- 20% of baseline to protect against erratic early measurements.
    2. **Stage 2 (Full statistical confidence, N >= threshold)**: Releases the baseline safety clamp, applying 100% of the measured heat loss ($H_{\text{eff}} = H_{\text{measured}}$) directly with an absolute physical lower bound guard ($H \ge 0.5\text{ W/K}$).
  - Exposed `heat_loss_confidence_samples` attribute in `extra_state_attributes` and diagnostics export.
- **End-to-End Real Entity Unit Testing Suite**:
  - Implemented comprehensive end-to-end unit test suite in `tests/test_real_entity_e2e.py` operating directly on the live `PwmFloorHeatingThermostat` entity rather than isolated standalone simulator functions.
  - Validates Danfoss FSM transitions under time warping (mandatory 30 min oil return runtime lock and 15 min pressure equalization off-cycle lock).
  - Validates Rule G peak-hour run duration capping, DTU 65.14 slab water loop safeguards (max 28.0°C cutoff, freeze protection), and Mode B unconstrained adaptation on the real entity.

### Changed
- **Config Flow & Options Flow Heat Loss Lower Bound and Precision**:
  - Lowered minimum allowable heat loss coefficient `min` from 5.0 W/K to **1.0 W/K** in both Config Flow and Options Flow schemas, resolving validation errors on small, well-insulated, or passive rooms (e.g. offices, small bedrooms).
  - Refined selector step from 0.5 W/K to **0.1 W/K** for granular thermodynamic tuning.
- **Form Terminology Disambiguation**:
  - Renamed ambiguous "Heat Loss Coefficient H" to **"Baseline / Initial Heat Loss Coefficient H (W/K)"** (in French: **"Déperditions de référence (valeur initiale) H (W/K)"**), clearly establishing the distinction between baseline reference, measured passive loss (Mode A), and effective applied coefficient.

### Fixed
- Fixed `Value X is too small` validation error in Home Assistant UI when entering heat loss values below 5.0 W/K (e.g. 3.0 W/K).

---

## [0.2.8] - 2026-11-11

### Added
- **Rolling 24h Forecast Weather Average for Daily Thermal Quota**:
  - Added optional `weather_entity` selector and `use_weather_forecast_average` toggle in both Config Flow and Options Flow.
  - Resolves rolling 24-hour hourly forecast average from the weather service (calling `weather.get_forecasts` with fallback to state attributes) to stabilize the daily thermal energy quota ($E_{\text{day}}$) against instantaneous temperature fluctuations.
  - Exposed `forecast_outdoor_temp_24h` and `use_weather_forecast_average` telemetry attributes on the climate entity and diagnostics dump.
- **Weather Outage Graceful Fallback**:
  - Automatic and resilient fallback when the configured weather entity is unavailable or fails: automatically falls back to the previous day's calculated quota +5% (with explicit warning log) or to the instantaneous outdoor temperature sensor.
  - Exposed `weather_outage_fallback_active` telemetry attribute.
- **Unserved Quota Carry-Over**:
  - Automatic carry-over of unserved duty time at midnight (up to 2.0 hours maximum) into `unserved_quota_carryover_hours` to ensure slab thermal deficit is not discarded when heating was suspended (e.g., prolonged window opening or peak cap).
  - Exposed `unserved_quota_carryover_hours` telemetry attribute on the climate entity and diagnostics.
- **Native `PwmThermostatCoordinator` Architecture (`DataUpdateCoordinator`)**:
  - Introduced `PwmThermostatCoordinator` in `coordinator.py` orchestrating state synchronization between the master climate entity and companion diagnostic sensors.
  - Completely eradicated the startup busy-wait retry loop (`asyncio.sleep(0.1)`) and dispatcher signals in `sensor.py`.
  - Migrated `PwmDiagnosticSensor` to native `CoordinatorEntity[PwmThermostatCoordinator]` conforming strictly to Home Assistant Core architectural guidelines.

### Changed
- Replaced dispatcher event listeners on companion sensors with native coordinator push notifications.
- Diagnostics dump (`async_get_config_entry_diagnostics`) updated to support the coordinator pattern and export all new forecast and carry-over attributes.

---

## [0.2.7] - 2026-11-10

### Added
- **Continuous-Discrete Kalata Filter with Velocity Low-Pass Smoothing**:
  - Implemented continuous Kalata tracking formulation (`Kp = sqrt(2) * omega_0`, `Kv = omega_0^2` where `omega_0 = (q_proc / sigma_v^2)^0.25`) that scales smoothly across arbitrary time steps dt, strictly eliminating mathematical gain singularities when dt -> 0.
  - Added a first-order low-pass filter on temperature velocity (`tau_v = 1.0 h`) that completely eradicates the high-frequency +/- 0.8°C to +/- 1.2°C sawtooth ripple caused by discrete Zigbee 0.1°C stair-step quantization, yielding a smooth, continuous projected trajectory curve (`temp_projected_ahead`).
  - Added sub-second deduplication guard in `_update_trajectory_projection` (< 1 second) to cleanly ignore redundant sensor trigger cascades.
- **Dynamic Integration Version Resolution**:
  - Replaced hardcoded version strings across `device_info` and diagnostics with `get_integration_version()`, reading dynamically from `manifest.json`.
- **Configurable Regulation Parameters via Options Flow**:
  - `kalata_process_noise`: Filter process noise parameter q_proc (default: 0.005 (°C/h)²/h, adjustable from 0.001 to 0.100).
  - `outdoor_precharge_max_temp`: Outdoor temperature ceiling for Off-Peak precharge in Rule A (default: 12.0°C, adjustable from 5.0 to 20.0).
  - `comfort_safety_deficit`: Room deficit emergency override threshold in Rules D and G (default: 0.8°C, adjustable from 0.3 to 2.5).
  - `rule_b_min_threshold`: Baseline minimum anticipation threshold for Peak-hour heating in Rule B (default: 0.25°C, adjustable from 0.10 to 1.00).
  - Complete English (`en.json`) and French (`fr.json`) localization for all new configuration parameters.
- **Adaptive Rule B Trigger Threshold & RMS Diagnostic Metric**:
  - Replaced rigid static 0.15°C trigger in Rule B with an adaptive threshold scaled by statistical model uncertainty:
    `threshold = max(rule_b_min_threshold, 2.0 * RMS(model_error))`
    preventing spurious Peak-hour turn-ons triggered by background model/sensor noise.
  - Added continuous 24h rolling RMS calculation of model error (`model_error_rms`).
  - Exposed `model_error_rms`, `rule_b_threshold`, and `rule_b_min_threshold` attributes on the thermostat entity.
  - Added companion diagnostic sensor `model_error_rms` (`sensor.salon_model_error_rms`) to monitor digital twin fidelity on dashboards.

### Changed
- **Mode A Heat Loss & Dead Time Identification Noise Immunity**:
  - Switched passive calibration checks to consume the smoothed derivative `_derivative_smooth` instead of the raw quantized rate, protecting slab parameter estimation against measurement jitter.

### Fixed
- **Startup Redundant Projection Call**:
  - Removed duplicate `_update_trajectory_projection` execution in `_async_read_sensors` right before `_async_control_heating`.
- **Cleaned Dead Assignment**:
  - Removed write-only `self._heating_start_temp = self._cur_temp` assignment in `_async_start_heating_safe`.

---

## [0.2.6] - 2026-11-09

### Added
- **Adaptive PWM Period Modulation & Peak-Hour Run Cap (Rule G)**:
  - Asymmetric duration scheduling between tariff windows: promotes deep, continuous multi-hour accumulation cycles during cheap Off-Peak hours while enforcing a bounded run cap during expensive Peak hours.
  - Configurable `peak_max_run_duration` (default: 45 minutes, selectable 30-180 min in Options Flow) automatically terminating top-up cycles once the cap is reached to allow injected heat pulses to diffuse through the slab.
  - Fully compliant with Danfoss minimum 30-minute runtime requirement.
  - Automatic comfort emergency bypass (if room deficit >= 0.8°C) and floor frost protection bypass (<= 14°C).
  - Exposed via `peak_max_run_duration_min` telemetry attribute and companion diagnostics.
- **Wind Convective Heat Loss Amplification (`wind_sensor`)**:
  - Optional `wind_sensor` input integrating ambient wind speed into the 24h thermal energy quota.
  - Above calm conditions (15 km/h), applies +0.5%/km/h convective loss boost up to a strict +25% maximum ceiling.
  - Disabled by default (sensor unset, multiplier 1.0).
  - Exposed via `wind_factor` and `wind_speed` telemetry attributes.
- **Dynamic Calibration & Soft Adaptation of Slab Dead Time Theta (`auto_calibrate_dead_time`)**:
  - Automatically identifies experimental transport dead time by detecting the temperature slope reversal point upon heating cycles.
  - Computes rolling average `dead_time_measured_hours` via 90/10 exponential filter with sample counter.
  - Optional `auto_calibrate_dead_time: bool` (disabled by default) adjusting trajectory projection within a safe +/- 25% clamp of baseline configured theta.
  - Exposed via `effective_dead_time_hours`, `dead_time_measured_hours`, and `dead_time_samples_count`.

---

## [0.2.5] - 2026-11-09

### Added
- **Slow Drift Ambient Supervisor (Anti-Integral Windup)**:
  - Gentle, proportional trim (K_ambient = 0.15 / °C) applied directly to the 24h daily energy quota based on room setpoint error.
  - Strictly clamped between [0.80, 1.25] (-20% to +25%), eliminating persistent steady-state room offsets without integral accumulation, windup, or cycling.
  - Exposed via `ambient_trim_ratio` telemetry attribute and companion diagnostics.
- **Solar Irradiance Integration with Inviolable Morning Comfort Floor Guard**:
  - Optional `solar_sensor` configuration taking into account daytime solar irradiance (W/m² or illuminance).
  - **Inviolable Morning Wake-Up Comfort Guard**: Before 09:00 AM local time or during nighttime Off-Peak recharge, solar credit is strictly locked to 0.0 kWh, ensuring 100% full wake-up comfort and preventing under-heated morning floors based on afternoon solar forecasts.
  - Solar credit is immediately suspended if room ambient temperature drops below target setpoint (-0.3°C).
  - Strictly bounded to maximum 25% quota deduction (`solar_credit_kwh`), preventing midday overshoots from south-facing windows while preserving base heating needs.
- **Mode B Soft Self-Adaptation of Building Heat Loss (H = U * A)**:
  - Configurable `auto_calibrate_heat_loss: bool` option in UI Config Flow and Options Flow enabling automatic slow tuning of effective heat loss coefficient.
  - Activates only after at least 3 validated unheated night decay samples, strictly clamped within +/- 20% of baseline configured H.
  - Exposed via `effective_heat_loss_wk` and `auto_calibrate_heat_loss` attributes.

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
