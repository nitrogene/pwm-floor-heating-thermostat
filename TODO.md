# Development Roadmap & Technical Specifications (TODO.md)

This document tracks all **pending tasks, bug fixes, algorithmic improvements, and technical milestones** for the **PWM Floor Heating Thermostat** (`pwm_floor_heating_thermostat`) integration.
All items are strictly ordered from **most critical to least critical**.

---

## Next — Peak-Hour Cycle Latch & Unified °C Entry Gate (Eliminate `energy_balance_satisfied` vs `anticipated_drop` Micro-Cycling)

- [x] **[CORE - M-07] Peak-Hour Cycle Latch & Equivalent-°C Entry Gate (`climate.py`, `tests/`) :**
  - Latch active Peak-hour `anticipated_drop` cycles via `_cycle_start_decision_key` (persisted in `Store`) so rising `E_transit` during the run never aborts the cycle at `t + 1 min` (forcing 30-min micro-cycles instead of completing up to `peak_max_run_duration`).
  - Keep HC-to-HP handoff clean: cycles started by `off_peak_precharge` are not latched into Peak hours when off-peak ends and balance is already met.
  - Gate Peak-hour entry in °C (`delta_t_equiv = net_energy_needed_kwh / c_eff >= rule_b_threshold`, unless `comfort_override`) so negligible residual kWh noise never triggers spurious compressor startups.
  - Added regression tests in `tests/test_v040_predictive_engine.py`.
