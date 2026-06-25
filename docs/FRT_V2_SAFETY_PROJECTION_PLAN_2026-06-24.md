# frt-v2 Deployment-side Safety Projection — Plan + Minimal Implementation (2026-06-24)

> **Scope.** Deployment-side **post-processing** of the SAC 3-D action `[iq, mse_d, mse_q]` — no
> retraining, no network change, no full-320 re-run, no mutation of any result file. The original
> certified full-320 result is **unchanged**:
> **residual SAC mi=14 strict_pass = 53.1%, no-fail/effective = 89.4%, fail = 10.6%** (170/34/116).
> NOT_EVALUATED is never counted as PASS; no-fail/effective is **not** a strict grid-code pass rate.
> This document does **not** claim the switching pass rate is improved.

## Why projection first, not retraining

The error analysis ([FRT_V2_ERROR_ANALYSIS_2026-06-24.md](FRT_V2_ERROR_ANALYSIS_2026-06-24.md)) showed
all 34 SAC FAILs are single-criterion, with **24 reactive = wrong-sign at near-boundary V+** and **10
survive = weak-grid deep-swell DC undershoot**. The 24 reactive failures are a *sign* defect at tiny
demand, not a capacity/learning deficit — a deterministic, auditable **deployment-side clip** removes
them without touching the policy, with **zero training cost and zero risk to the existing result**.
Retraining is heavier, slower, and risks regressing the LVRT strength the SAC already has; it is
deferred until the cheap projection is validated.

## What the projection fixes (Part 1 — implemented)

`src/hpt_frt/device/safety_projection.py :: project_action(action, V1_pu, category, iq_ref,
current_limit, params)`.

The frt-v2 `reactive_criterion` FAILs immediately on a **wrong sign** (`common/frt_v2.py`):

| region | condition | wrong sign |
|---|---|---|
| under-voltage | V+ < 0.9 | iq < −ε (absorbing while sagging) |
| over-voltage | V+ > 1.1 | iq > +ε (sourcing while swelling) |

(ε = `REACTIVE_SIGN_EPS` = 1e-3.) The projection forces iq onto the correct side of zero **in exactly
that region**:

```
required_iq_sign(V1):  +1 if V1<0.9   (iq must be ≥0)
                       -1 if V1>1.1   (iq must be ≤0)
                        0 otherwise   (neutral band — no constraint)

if required>0 and iq < -ε:  iq ← max(0, iq)   (→ 0, or the correct-direction iq_ref if given)
if required<0 and iq > +ε:  iq ← min(0, iq)   (→ 0, or the correct-direction iq_ref if given)
then clip |iq| ≤ current_limit (= IQ_CAP 0.27)   # never grows |iq|; mse_d/mse_q untouched
```

Properties (all unit-tested in `tests/test_safety_projection.py`, 10 tests):
- under-volt iq<0 → projected ≥0; over-volt iq>0 → projected ≤0;
- near-zero-demand wrong sign → zeroed (dead-band);
- **correct-direction iq is never modified**; neutral band passes through;
- output stays **3-D**, mse_d/mse_q preserved, |iq| within the current bound;
- metadata records `{triggered, reason, iq_in, iq_out, V1_pu, required_sign, region, cap}`.

The projection's trigger is the **contrapositive** of the criterion's wrong-sign predicate (same V+, same
threshold), so by construction every sample that would trip wrong-sign is corrected.

## Offline reactive check (24 wrong-sign FAILs)

`src/hpt_frt/device/project_offline_check.py` →
`lab/results/projection_offline_reactive_check.csv` + `projection_offline_reactive_summary.json`.

Per-step iq traces are not saved, so this is a **static predicate-equivalence check**, not a replay: for
each of the 24 reactive-FAIL scenarios it evaluates the projection at the scenario's fault region (and a
full iq sweep) and confirms no wrong-sign survives.

**Result: 24/24 would be intercepted** — undervolt 14 (`2ph` V+0.875 ×12, `2ph_g` V+0.833 ×2),
overvolt boundary-crossing 10 (`swell_1ph` V+1.10). This shows the projection would remove the exact
condition that caused those FAILs; it does **not** by itself certify a switching pass (re-sim needed).

## HVRT DC-bus survival (Part 2 — PLAN ONLY, not implemented)

The 10 `survive=FAIL` (scr3 + `swell_3ph` + Vg_p=1.30; Vdc undershoots to ≈0.72 at swell clearing) are
**not** addressed by the reactive projection. Candidate strategies, to be designed/validated later:
1. **Action rate limit** on the reactive ramp-down at swell clearing (avoid an abrupt absorb→release DC
   transient);
2. **HVRT clearing ramp-down** — phase out absorption over a few cycles instead of instantly;
3. **DC-bus clamp / chopper coordination** — engage the chopper / clamp the bus when Vdc approaches the
   0.75 floor during HVRT release;
4. **Reward penalty** on Vdc undershoot during/after swell (a training-side option, deferred).
These need a **switching spotcheck** to validate (they affect DC dynamics the static check cannot model).

## Validation path (in order; stop if a step fails)

1. **Unit tests** — `tests/test_safety_projection.py` (✅ 10 passed).
2. **Offline reactive check** — 24/24 wrong-sign intercepted (✅, static).
3. **Small switching spotcheck** — wrap the deployed HLC output with `project_action` and re-run a
   handful of the failing scenarios via `frt_v2_spotcheck` / a few `frt_v2_full320_switching` indices
   (NOT this round; needs MATLAB).
4. **Only if 3 succeeds** — an optional, clearly-labelled projected-vs-baseline full-320 comparison
   (separate result file, never overwriting `p3_full320_sw_mi14.mat`).

## Files

- `src/hpt_frt/device/safety_projection.py` (new) — `project_action`, `required_iq_sign`, `is_wrong_sign`.
- `src/hpt_frt/device/project_offline_check.py` (new) — offline static check.
- `tests/test_safety_projection.py` (new) — 10 unit tests.
- `lab/results/projection_offline_reactive_check.csv` / `projection_offline_reactive_summary.json` (new).

Certified result of record (unchanged): [FRT_V2_RESULTS_2026-06-23.md](FRT_V2_RESULTS_2026-06-23.md) +
`lab/results/p3_full320_switching_summary.json`.
