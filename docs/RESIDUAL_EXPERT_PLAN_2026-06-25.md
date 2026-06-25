# 4-Expert + Residual SAC (pure-learning hybrid) — Plan & Diagnosis, 2026-06-25

A new canonical mode (HLC dispatch **mi==17**), candidate **MAIN METHOD**: a single global residual
SAC on the **online-gated frozen-expert prior** (Mode-5 experts), instead of on the analytic MPC prior
(Mode 6). Stays **pure learning** (no analytic MPC) while gaining the residual's cross-domain
correction. Decided with the user 2026-06-25.

```
total = clip( gated_expert(obs) + residual(obs) )     # experts FROZEN, only the residual learns
gate  = gate_to_expert(V2p,V2n)  ==  network/sac_wrapper.gate_raw   (train == deploy)
```

## Why (the gap this closes)
Certified frt-v2 covers only mi=14 (Mode 6, extension) vs mi=7 (Mode 1 fixed law). The MAIN METHOD
Mode 5 and Mode 2/3/4 have **no frt-v2 switching score**. Mode 5 is LVRT-strong / HVRT-weak; Mode 6
is strong but NON-pure (MPC). This hybrid aims to be pure-learning AND ≥ Mode 6.

## Two diagnoses that reshape the HVRT fix (read before retraining anything)

**HVRT 33% = two different diseases; "retrain the HVRT expert" alone fixes neither cleanly.**

1. **`hvrt_asym` (swell_1ph) is NOT broken.** `fault_sequence` averages the single-phase swell:
   `Vg_p=(2+targetV)/3` → for targetV=1.2/1.3 → **V+ = 1.067 / 1.10**, never `>1.1`, so `_iq_ref ≡ 0`
   — training NEVER asks it to absorb. Flat ~0 is the correct optimum. Its 10 reactive FAILs are a
   deployment wrong-sign issue → **fixed by the deployment clip (`safety_projection` Part-1), not a
   retrain** (user-chosen, 2026-06-25).
2. **`hvrt_sym` (swell_3ph) FAILs are `survive` (DC undershoot), not reactive.** It already absorbs
   −0.30; the bus undershoots at deep swell + weak grid. Absorbing MORE makes it worse.
   ⚠️ **The training ODE is structurally blind to this**: swell uses negative `V_se_d` (anti-boost) so
   `sag_se = 1.9·max(0,V_se_d) = 0`, and `sag_iq ≈ 0.08·0.3/1.3 ≈ 0.018` → ODE `Vdc ≈ 0.98` on swells
   (that is exactly why ODE HVRT=100% but switching=33%). **No swell_3ph survive signal exists in the
   ODE to retrain against.**

   → OPEN DECISION (swell_3ph): (a) **extend the calibration to HVRT** operating points so the ODE
   `Vdc_eq` map reproduces the swell DC undershoot (then the residual can learn the trade), or
   (b) **accept swell_3ph deep@weak as a documented single-port limit** (like the deep-sym LVRT
   limit). Default recommendation: (b) for this round; (a) is a separate calibration experiment.

## Build status (2026-06-25)
- [x] `src/hpt_frt/device/residual_expert_env.py` — env (residual on gated-expert prior; lazy expert
      load; gate mirrors `gate_raw`). Smoke-tested: contract 20/3, zero-residual = pure expert prior
      rollout runs.
- [x] `src/hpt_frt/device/train_residual_expert.py` — trainer (LR anneal + actor EMA; experts loaded
      once, shared across vec-envs). Wiring smoke OK (260/60 split).
- [x] registered family `'residual_expert'` in `train_common.ENV_FAMILIES`; 134 pytest pass.
- [x] **A1** wrong-sign clip — already in the HLC as **mi==16** (`build_hpt_frt_full.m:267`, projected
      mode-14) AND baked into the new mi==17 branch (always on). `frt_v2_full320_switching(16,1,320)`
      certifies the projected-residual variant with zero new code.
- [x] **C-code** MATLAB HLC `mi==17` branch (gate→expert prior + residual forward + caps + wrong-sign
      clip) added to `build_hpt_frt_full.m`; `gen_obs_vectors.py` adds the `resexpert` net;
      `export_resexpert.py` written; static analysis clean. (Inner generated code needs a Simulink
      build + `frt_v2_spotcheck` to verify at runtime.)
- [ ] **A2** (only if calibration extended) hvrt_sym DC-undershoot retrain — else skip per (b).
- [ ] **B** train the residual: `python -m hpt_frt.device.train_residual_expert --seed 42`
      (+ multi-seed for mean±std) → `sac_resexpert_best.zip`.
- [ ] **export** `python -m hpt_frt.device.export_resexpert` → `sac_resexpert_weights.mat`; ensure the
      4 expert .mat present (`export_experts.py`); copy to `lab/simulink/`.
- [ ] **consistency** `python -m tests.consistency.gen_obs_vectors` (after export) +
      `frt_v2_consistency_test.m`; then `frt_v2_spotcheck()`.
- [ ] **D** `frt_v2_full320_switching(17,1,320)` (the certified result) + mi=12/8/11/15/16 to complete
      the certified comparison table + ablations (expertization gain Mode5−Mode3, gating loss
      Mode4−Mode5, projection gain mi16−mi14).

## Caveats locked in
- Proxy from the ODE is NOT a certified pass rate (limit/survive NOT_EVALUATED + swell DC blind).
- mi=17 must be added to `controller_registry.py` / `CONTROL_MODES.md` once it has a frt-v2 score
  (keep `score=None` until then). mi=16 (projected mode-14) likewise has no frt-v2 score yet.
