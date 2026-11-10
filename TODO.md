# Development Roadmap & Technical Specifications (TODO.md)

This document tracks all **pending tasks, algorithmic improvements, and technical milestones** remaining to be implemented for the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration.
All items are ordered from **most critical to least critical**.

---

## 1. Critical Stability & Kalata Filter De-noising (Release v0.2.7) [COMPLETED]

- [x] **Eradicate Sawtooth Oscillations on Projected Temperature ($T_{\text{projected}}$) (Completed in v0.2.7):**
  Real-world telemetry revealed persistent $\pm 0.8^\circ\text{C}$ to $1.2^\circ\text{C}$ sawtooth oscillations on $T_{\text{projected}}$ occurring on every $0.1^\circ\text{C}$ discrete step of Zigbee ambient sensors:
  - **Continuous-Discrete Kalata Formulation & Process Noise Tuning ($q_{\text{proc}}$):** Lowered process noise acceleration parameter $q_{\text{proc}}$ from `1.0` to `0.005` $(\text{°C/h})^2/\text{h}$ in [`climate.py`](custom_components/pwm_floor_heating_thermostat/climate.py) and applied continuous tracking gains $K_p = \sqrt{2}\omega_0, K_v = \omega_0^2$ with $\omega_0 = (q_{\text{proc}} / \sigma_v^2)^{0.25}$, completely eliminating gain explosion when $dt \to 0$.
  - **Deduplicate Projection Updates in Heating Loop:** Eliminated duplicate projection calculation in `_async_read_sensors` right before `_async_control_heating`, and added a sub-second deduplication guard (< 1 second) in `_update_trajectory_projection`.
  - **First-Order Low-Pass Filter on Derivative:** Applied a 1-hour first-order low-pass filter on the velocity derivative ($\tau_v = 1.0\,\text{h}$), feeding a smooth derivative into $T_{\text{projected}} = T_{\text{filtered}} + \theta \cdot (dT/dt)_{\text{smooth}}$, completely eliminating quantization ringing.

---

## 2. Sensor Reliability & Hardware Safety Guards (Code Review)

- [ ] **Stale Sensor Watchdog (Fail-Safe Heating Shutdown) :**
  Prevent blind continuous heating if a Zigbee sensor battery dies or the mesh link freezes without Home Assistant marking it `unavailable`:
  - Track update timestamps (`_cur_temp_ts`, `_outdoor_temp_ts`) on every incoming state change.
  - Enforce a configurable stale threshold between **90 and 120 minutes** (adapted to typical Zigbee heartbeat keep-alives to eliminate false positives in thermally stable rooms).
  - Transition FSM safely to `IDLE`, turn off active heating, expose `sensor_stale: true` attribute, and set an explicit reason in `decision_reason`.
- [ ] **Software DTU 65.14 Slab Guards for Probe-less Installations :**
  Provide software-level slab protection when no embedded loop water return probe (`floor_temp_sensor`) is present:
  - **Thermal Runaway Cutoff :** Trigger emergency shutdown if ambient $dT/dt > +1.5^\circ\text{C/h}$ sustained for $> 30\,\text{min}$ during active heating.
  - **Hard Ambient Overshoot Ceiling :** Immediate unconditional heating cutoff if $T_{\text{cur}} \ge T_{\text{target}} + 1.0^\circ\text{C}$.
  - **Global Maximum Continuous Run Cap (`max_continuous_run`) :** Extend the maximum continuous run cap (120 min) across all tariff periods (including Off-Peak hours) to ensure mandatory thermal diffusion intervals in the heavy slab.
  - **Emergency Comfort Deficit Bypass :** Unconditional emergency heating trigger if ambient temperature drops severely below target ($T_{\text{cur}} \le T_{\text{target}} - 1.5^\circ\text{C}$), overriding daily quota blocks.

---

## 3. Algorithmic Refinement & Quota Forecast Stabilization

- [x] **Adaptive Rule B Trigger Threshold & RMS Diagnostic Metric (Completed in v0.2.7):**
  - Replaced the rigid $0.15^\circ\text{C}$ fixed threshold with an adaptive threshold scaled by model uncertainty:
    $$\text{threshold} = \max(\text{rule\_b\_min\_threshold},\; 2.0 \cdot \text{RMS}(e_{\text{model}}))$$
    preventing spurious turn-ons triggered by background measurement noise.
  - Aggregated continuous 24h rolling $\text{RMS}(e_{\text{model}})$ and exposed it as an entity attribute (`model_error_rms`, `rule_b_threshold`, `rule_b_min_threshold`) and as a dedicated companion diagnostic entity in `sensor.py`.
  - Configurable `rule_b_min_threshold` baseline floor via `OptionsFlow`.
- [ ] **Rolling 24h Forecast Weather Average for Daily Thermal Quota :**
  - Stabilize daily energy quota calculation ($E_{\text{day}}$) by calculating outdoor delta against the rolling 24h average forecast from weather service rather than instantaneous temperature spikes or an inflexible fixed 04:00 AM snapshot.
  - **Weather Outage Fallback :** In case weather entity is `unavailable`, gracefully fall back to the previous day's quota $+5\%$ or last valid reading with a warning log.
  - **Unserved Quota Carry-Over :** Carry over unserved duty time to the next cycle/period when heating is temporarily suspended (e.g. by window opening or peak cap).
  - **Configurable Precharge Sealing Seuil :** Move hardcoded `OUTDOOR_PRECHARGE_MAX_TEMP` (12.0°C) into `OptionsFlow` settings.

---

## 4. Code Quality, Deprecation Fixes & Architecture Modernization

- [ ] **Expose Hardcoded Thermodynamic & Safety Parameters to UI (OptionsFlow):**
  Eliminate all hardcoded magic numbers by making advanced parameters runtime-configurable in `config_flow.py` (`OptionsFlow`) with sensible defaults matching recommended specifications:
  - [x] `CONF_KALATA_PROCESS_NOISE` ($q_{\text{proc}}$): default `0.005` $(\text{°C/h})^2/\text{h}$, bounds `[0.001, 0.100]`, step `0.001` (Implemented in v0.2.7).
  - [x] `CONF_OUTDOOR_PRECHARGE_MAX_TEMP`: default `12.0` °C, bounds `[5.0, 20.0]`, step `0.5` (Implemented in v0.2.7).
  - [x] `CONF_COMFORT_SAFETY_DEFICIT`: default `0.8` °C, bounds `[0.3, 2.5]`, step `0.1` (Implemented in v0.2.7).
  - [x] `CONF_RULE_B_MIN_THRESHOLD`: default `0.25` °C, bounds `[0.10, 1.00]`, step `0.05` (Implemented in v0.2.7).
  - [ ] `CONF_SENSOR_STALE_TIMEOUT_MINUTES`: default `90` min, bounds `[30, 360]`, step `15`.
  - [ ] `CONF_MAX_CONTINUOUS_RUN_MINUTES`: default `120` min (or 0 to disable), bounds `[30, 240]`, step `15`.
  - [ ] `CONF_THERMAL_RUNAWAY_DERIVATIVE`: default `1.5` °C/h, bounds `[0.5, 3.0]`, step `0.1`.
  - [ ] `CONF_HARD_OVERSHOOT_MARGIN`: default `1.0` °C, bounds `[0.3, 2.5]`, step `0.1`.
- [x] **Home Assistant Core 2024.x Modernization (Completed in v0.2.7):**
  - Replaced deprecated `EVENT_HOMEASSISTANT_START` with `EVENT_HOMEASSISTANT_STARTED`.
  - Resolved `sw_version` dynamically from `manifest.json` in `device_info` via `INTEGRATION_VERSION` rather than hardcoding static version strings in `climate.py` and `sensor.py`.
  - Removed dead variable `_heating_start_temp` in `climate.py`.
- [ ] **Architecture Evolution toward `DataUpdateCoordinator` :**
  - Refactor entity-to-sensor communication by replacing the overridden `async_write_ha_state()` dispatcher pattern with a native Home Assistant `DataUpdateCoordinator`.
  - Eliminate the retry busy loop (`asyncio.sleep(0.1)`) in `sensor.py`.
- [ ] **End-to-End Real Entity Unit Testing :**
  Migrate unit test suites from standalone mocks toward `pytest-homeassistant-custom-component` to execute FSM transitions, Rule G capping, and dead time calibration directly on the real `DanfossFloorHeatingThermostat` instance.

---

## 5. Long-term Research & Feature Backlog

- [ ] **Inter-Zone Convective Coupling :**
  Model passive heat transfer drafts between adjacent zones (e.g. warm air draft rising from high-ceiling Living Room to mezzanine/Office).
- [ ] **Dynamic Multi-Rate & Spot-Market Tariff Schedulers :**
  Native integration for dynamic hourly pricing (EPEX Spot, NordPool, EDF Tempo 6-color matrix).
