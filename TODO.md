# Development Roadmap & Technical Specifications (TODO.md)

This document tracks all **pending tasks, bug fixes, algorithmic improvements, and technical milestones** for the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration following the v0.3.2 code review.
All items are strictly ordered from **most critical to least critical**.

---

## 1. Critical / Blocking Fixes (Mechanical & Regulation Safety)

- [x] **[BLOCKING - F-01] Preserve Danfoss 30-Minute Minimum Runtime Lock Across Restarts & Reloads (`climate.py:624-634`, `climate.py:2127-2148`) :**
  - Persist `_fsm_state`, `_last_state_change`, and `_cycle_start_time` in the self-contained Home Assistant `Store`.
  - In `async_added_to_hass`, if the physical `heater` switch is currently `"on"` (or was in `FSM_RUNNING_MIN_LOCK` / `FSM_RUNNING_NORMAL`), restore the active running state and original `_cycle_start_time` / `_last_state_change` instead of forcing `FSM_WAITING_MIN_OFF`.
  - Ensure the active reconciliation guard in `_async_stop_heating_safe()` never cuts off a running compressor before `min_cycle_duration` (30 min) has elapsed since its actual start time.
- [x] **[BLOCKING - F-03] Fix Minutes-vs-Seconds Unit Mismatch on `peak_max_run_duration` (`config_flow.py:497-511`, `climate.py:268-285`, `climate.py:376-378`, `climate.py:1780`) :**
  - `OptionsFlow` stores `CONF_PEAK_MAX_RUN_DURATION` as a number in **minutes** (e.g. `45`), whereas `_parse_timedelta` interprets numeric `int`/`float` values as **seconds** (`45s`), resulting in `peak_max_run_duration_min: 0` and prematurely cutting off every Peak-Hour heating cycle at 30 minutes via Rule G.
  - Explicitly parse numeric `CONF_PEAK_MAX_RUN_DURATION` values as **minutes** (`timedelta(minutes=float(val))`), and guard Rule G with `if self._peak_max_run_duration.total_seconds() > 0:`.
- [x] **[BLOCKING - F-02] Verify Physical Actuator State Transitions (Closed-Loop FSM Confirmation) (`climate.py:2104-2121`, `climate.py:2172-2189`) :**
  - Without coupling the integration to any specific hardware controller (preserving the v0.3.2 decoupling architecture), prevent phantom FSM transitions when a hardware controller (e.g. ESPHome local safety guard or manual override) rejects a `turn_on` command.
  - Verify that `self._heater_entity` actually transitions to `"on"` (or reconcile back to `FSM_IDLE` without incrementing `_cycles_today` or accumulating `_hours_run_today` if the switch remains `"off"` after a short confirmation grace window).

---

## 2. Major Fixes (Thermodynamic Model, Safeties & Home Assistant Integration)

- [x] **[MAJOR - F-07] Fix Mode A / Mode B Heat Loss ($H$) Auto-Calibration Downward Drift (`climate.py:1525-1541`, `climate.py:1848-1873`) :**
  - `_heat_loss_samples_count` is currently incremented every minute during `_async_control_heating` whenever `_derivative_smooth < -0.05`, including daytime periods with solar or internal heat gains. This reaches `heat_loss_confidence_samples` (10) within 10 minutes and unlocks unconstrained downward drift to `0.5 W/K`.
  - Restrict Mode A sampling to genuine night-time cooling windows (e.g. 23:00–06:00 local time, zero solar irradiance), throttle sample counting to at most 1 sample per hour (or 1 consolidated sample per night), and enforce a realistic lower safety bound (e.g. `>= 0.5 * self._heat_loss`) even after `heat_loss_confidence_samples` is reached.
- [x] **[MAJOR - F-08] Prevent Rule B Anticipation Paralysis from Positive-Slope Projection Errors (`climate.py:1376`, `climate.py:1401-1415`, `climate.py:1675-1688`, `const.py:51`) :**
  - Linear tangent extrapolation over `dead_time` during solar gains or active heating inflates `model_error_rms`, pushing `rule_b_threshold = 2.0 * RMS` above `1.1°C–2.5°C` and completely disabling Peak-Hour dead-time anticipation.
  - Lower `DEFAULT_KALATA_PROCESS_NOISE` from `0.005` to `0.001`, restrict `_model_error_history` accumulation to passive cooling regimes (or cap `rule_b_threshold` at a sane ceiling such as `0.6°C`).
- [x] **[MAJOR - F-04] Decouple Safety Guards from Outdoor Sensor Availability (`climate.py:1653-1748`) :**
  - Move Rule 0 (Emergency comfort deficit bypass), Rule C / Hard Ambient Overshoot Ceiling cutoff, Stale Sensor Watchdog cutoff, and Rule E (Open window cutoff) outside the `if self._cur_temp is not None and self._outdoor_temp is not None:` block so they remain active even when `outdoor_sensor` is temporarily `unavailable`.
- [x] **[MAJOR - F-05] Harden Stale Sensor Watchdog Across Restarts & Cover Outdoor Sensor (`climate.py:491`, `climate.py:1426-1441`, `climate.py:1489-1503`) :**
  - Persist `_cur_temp_ts` and `_outdoor_temp_ts` in the `Store` (updating timestamps on genuine sensor updates rather than trusting HA boot-time `last_updated` resets).
  - Evaluate `_outdoor_temp_ts` in the watchdog or fall back cleanly when the outdoor sensor is stale.
- [x] **[MAJOR - F-09] Expose Smoothed Derivative `_derivative_smooth` in Companion Sensor & Diagnostics (`sensor.py:70`, `diagnostics.py:58`) :**
  - Replace `t._temp_derivative` (raw unsmoothed Kalata velocity) with `t._derivative_smooth` (`tau_v = 1.0 h` low-pass filtered derivative) in `sensor.py` and `diagnostics.py` to match `climate.py:956`.
- [x] **[MAJOR - F-10] Fix Execution Order and Derivative Source in `_check_window_open_state` (`climate.py:1048-1049`, `climate.py:1268`, `climate.py:1281`, `climate.py:1505-1521`) :**
  - Update `_temp_history` and the Kalata observer **before** calling `_check_window_open_state`, and use `_derivative_smooth` (or properly updated state) Consistently.
- [x] **[MAJOR - F-11] Expose Missing Configuration Keys in UI ConfigFlow & OptionsFlow (`config_flow.py:118-258`, `config_flow.py:299-664`) :**
  - Add `CONF_ENFORCE_DAILY_QUOTA_SENSOR`, `CONF_WINDOW_DETECTION_SENSOR`, `CONF_COMFORT_TEMP`, `CONF_MIN_CYCLE_DURATION`, `CONF_MIN_OFF_CYCLE_DURATION`, and `CONF_MAX_CYCLES_PER_DAY` to the UI flows so UI-configured entries have full feature parity with YAML.
- [x] **[MAJOR - F-13] Remove Blocking Synchronous `open()` Call at Module Import Time (`const.py:8-18`) :**
  - Replace the import-time `open("manifest.json")` call in `const.py` with a static `INTEGRATION_VERSION = "0.3.2"` constant verified against `manifest.json` via a unit test, eliminating Home Assistant 2024.6+ event-loop blocking I/O warnings.
- [x] **[MAJOR - F-14] Strengthen Unit Test Suite Against Mocking Blind Spots (`tests/test_fsm.py`, `tests/conftest.py`, `tests/test_config_flow.py`) :**
  - Replace the standalone `MockDanfossFSM` in `tests/test_fsm.py` with tests against `PwmFloorHeatingThermostat`.
  - Add an end-to-end `OptionsFlow` $\rightarrow$ `async_setup_entry` unit test verifying parameter units (`peak_max_run_duration`, `stagger_delay`), restart during `FSM_RUNNING_MIN_LOCK` with active reconciliation, and safety evaluation when `outdoor_sensor` is `None`.

---

## 3. Minor Improvements (Performance, Code Hygiene, CI & Packaging)

- [x] **[MINOR - F-15] Cache `weather.get_forecasts` Responses (`climate.py:1167-1227`, `climate.py:1575-1576`) :**
  - Throttle `weather.get_forecasts` service calls with a 15-minute TTL cache (`WEATHER_FORECAST_CACHE_TTL_SECONDS = 900`, invalidated on `weather_entity` state change) instead of calling the service every 60 seconds per zone.
- [x] **[MINOR - F-16] Clean Up Hardcoded Entity Names, Dead Code & Deprecated OptionsFlow Init (`climate.py`, `sensor.py`, `config_flow.py`) :**
  - Replaced hardcoded French `input_datetime.heures_creuses_*` entity IDs with optional configurable `CONF_OFF_PEAK_START_ENTITY` (`off_peak_start_entity`) and `off_peak_sensor` attribute lookup.
  - Removed dead `_handle_thermostat_update` in `sensor.py` and unused `async_dispatcher_send` in `climate.py`.
  - Modernized `PwmFloorHeatingConfigFlow.async_get_options_flow` for Home Assistant 2024.11+ while preserving unit test compatibility.
- [x] **[MINOR - F-17] Align Packaging Metadata & CI Workflows (`pyproject.toml:7`, `manifest.json:9`, `.github/workflows/release.yaml:10-12`, `.github/workflows/validate.yaml:56`) :**
  - Synced `pyproject.toml` version (`0.3.2`) with `manifest.json`.
  - Updated `iot_class` in `manifest.json` from `"local_push"` to `"calculated"`.
  - Translated French input description in `.github/workflows/release.yaml` to English and added `voluptuous` to `.github/workflows/validate.yaml`.
