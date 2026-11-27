# Development Roadmap & Technical Specifications (TODO.md)

This document tracks all **pending tasks, bug fixes, algorithmic improvements, and technical milestones** for the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration.
All items are strictly ordered from **most critical to least critical**.

---

## v0.4.3 — Non-Circular Heat-Loss Calibration, Unified `C_eff`, `E_transit` Projection & Dead-Time Rest Guard

- [x] **[CORE - M-08] Non-Circular 24h Rolling Energy-Balance Calibration for `H` (`climate.py`, `Store`, `tests/`) :**
  - Replace circular passive-cooling Mode A with rolling 24h energy balance using persisted `_cumulative_injected_kwh` and `_energy_balance_history`.
  - Unify `C_eff` across all calculations via `_effective_thermal_capacity_kwh_k()`.
  - Enrich `temp_projected_ahead` with bounded net `slab_energy_in_transit_kwh / C_eff` (`<= +0.5°C`) when `dT/dt <= 0.05°C/h`.
  - Require relaxed slab rest (`>= 2 * dead_time`) and zero solar credit before accepting `dead_time_measured_hours` inflection samples.
  - Remove dead `_async_quota_sensor_changed` callback.

## Next — Peak-Hour Cycle Latch & Unified °C Entry Gate (Eliminate `energy_balance_satisfied` vs `anticipated_drop` Micro-Cycling)

- [x] **[CORE - M-07] Peak-Hour Cycle Latch & Equivalent-°C Entry Gate (`climate.py`, `tests/`) :**
  - Latch active Peak-hour `anticipated_drop` cycles via `_cycle_start_decision_key` (persisted in `Store`) so rising `E_transit` during the run never aborts the cycle at `t + 1 min` (forcing 30-min micro-cycles instead of completing up to `peak_max_run_duration`).
  - Keep HC-to-HP handoff clean: cycles started by `off_peak_precharge` are not latched into Peak hours when off-peak ends and balance is already met.
  - Gate Peak-hour entry in °C (`delta_t_equiv = net_energy_needed_kwh / c_eff >= rule_b_threshold`, unless `comfort_override`) so negligible residual kWh noise never triggers spurious compressor startups.
  - Added regression tests in `tests/test_v040_predictive_engine.py`.
