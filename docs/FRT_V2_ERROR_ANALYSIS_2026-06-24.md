# frt-v2 full-320 — Error Analysis of the Residual SAC (mi=14) FAILs — 2026-06-24

> **Post-processing only.** This analysis reads existing results
> (`lab/results/p3_full320_sw_mi14.mat`, `p3_full320_sw_mi7.mat`,
> `p3_full320_switching_summary.json`, `p3_scenario_faultparams.json`). **No re-training, no Simulink,
> no full-320 re-run, no mutation of result values. NOT_EVALUATED is never counted as PASS;
> no-fail/effective is NOT a strict grid-code pass rate.**

## Certified full-320 context (use this for any conclusion)

| Controller | strict_pass | no-fail / effective | fail | True/False/NE |
|---|:---:|:---:|:---:|:---:|
| residual SAC mi=14 | **53.1%** | **89.4%** | **10.6%** | 170 / 34 / 116 |
| dq fixed-law mi=7 | 39.7% | 68.1% | 31.9% | 127 / 102 / 91 |

This document dissects the **34 SAC FAILs**.

## Headline: two failure modes, every FAIL is a single criterion

- **0** scenarios fail >1 criterion (no compound failures).
- **0** FAIL scenarios also carry a NOT_EVALUATED criterion (no FAIL+NE mix).
- **0** `connect` / `recover` / `limit` failures.
- The 34 FAILs are exactly: **`reactive`=24** and **`survive`=10**.

## The 5 failure clusters (all single-criterion)

| # | n | criterion | fault_type | SCR | Vg_p (V+) | reason | dq same sid |
|---|---|---|---|---|---|---|---|
| 1 | 6 | reactive | 2ph | 10 (strong) | 0.875 | wrong sign (absorbing during under-volt) | **also FAIL** |
| 2 | 6 | reactive | 2ph | 3 (weak) | 0.875 | wrong sign | SAC-only |
| 3 | 2 | reactive | 2ph_g | 10 (strong) | 0.833 | wrong sign | **also FAIL** |
| 4 | 10 | reactive | swell_1ph | 3 (weak) | 1.100 | wrong sign (sourcing during over-volt) | SAC-only |
| 5 | 10 | survive | swell_3ph | 3 (weak) | 1.300 | Vdc < 0.75 (DC-bus undershoot) | SAC-only |

- **reactive (24)** — **ALL "wrong sign"**, not under-support. They occur at **mild / boundary**
  deviations where the demanded reactive is tiny: 2ph V+≈0.875 (droop demand ≈0.04), 2ph_g V+≈0.833
  (≈0.10), swell_1ph V+≈1.10 (≈0, exactly the HVRT threshold). The residual policy's small reactive
  output crosses to the wrong side of zero in the post-delay assessment window, tripping the sign check.
- **survive (10)** — **all swell_3ph V+=1.30 at the weak grid (scr3)**: at swell clearing (~t≈0.60 s)
  the DC bus undershoots to ≈0.72 pu (worst margin ≈0.03 below the 0.75 floor) → `survive=FAIL`. This is
  the **weak-grid deep-swell DC-bus transient** the ODE proxy (HVRT 100%) cannot see.

## Breakdown by dimension

| Dimension | Split |
|---|---|
| by criterion | reactive 24 · survive 10 |
| by fault_type | 2ph 12 · 2ph_g 2 · swell_3ph 10 · swell_1ph 10 |
| by SCR | **scr3 (weak) 26** · scr10 (strong) 8 |
| by ride-through | LVRT 14 · HVRT 20 |
| by Vg_p | 0.833→2 · 0.875→12 · 1.10→10 · 1.30→10 |
| dq also fails same sid | **8** (all scr10 reactive-boundary) |
| SAC-only fails | **26** (all weak-grid scr3) |

**SAC-only vs dq:** the 8 shared failures are the strong-grid 2ph/2ph_g V+≈0.85 reactive boundary —
dq also fails them (on recover). The **26 SAC-only** failures are entirely **weak-grid (scr3)**:
2ph V+0.875 (6), swell_1ph V+1.10 (10), swell_3ph V+1.30 (10). At these weak-grid cases dq passes /
NEs where SAC fails — this is SAC's specific weakness. (Globally SAC still wins by a wide margin: 34
fails vs dq 102; dq's failures concentrate in LVRT `recover` at the strong grid.)

## SAC strengths vs weaknesses (from the full table)

- **Strength — LVRT** (pass|determinable 92.0% vs dq 53.8%): `sym3ph` 60/0/0, `1ph_g` 0 fails (dq 30),
  `2ph_g` mostly pass. SAC clearly dominates LVRT.
- **Weakness — HVRT + boundaries**: weak-grid deep swell (DC survival), and the mild 2ph/2ph_g/swell_1ph
  **reactive sign boundary**.

## Improvement suggestions (decide AFTER this breakdown; no blind large training)

1. **Targeted sampling** of the failing clusters in any future training — over-weight weak-grid (scr3)
   swell_3ph V+1.30, swell_1ph V+1.10, and 2ph/2ph_g V+≈0.85.
2. **HVRT deep-swell**: add a reward penalty on Vdc undershoot during/after swell clearing, or a
   deployment-side **safety projection** (coordinate reactive ramp-down + DC chopper at swell clear) for
   the `survive` cluster — no retrain required to test the projection.
3. **Reactive command prior / clipping**: the 24 reactive fails are **wrong-sign at near-zero demand**.
   A small **sign-consistent dead-band** on the reactive command near V+∈[0.875, 1.10] (forbid wrong-sign
   iq when |droop demand| is tiny) is a cheap deployment-side fix — candidate before any retrain.
4. **Do not blindly scale training.** All of the above are either deployment-side projections or
   targeted, to be validated on the existing harness first.

## Outputs

- `lab/results/error_analysis_mi14_failures.csv` — per-FAIL row (sid, fault_type, scr, category,
  target_V_pu, Vg_p, failed_criteria, per-criterion status, reason, worst, t_worst, has_not_evaluated,
  dq_frt, dq_also_fail).
- `lab/results/error_analysis_mi14_summary.json` — aggregate counts + cluster cross-tabs.
- `lab/results/figures/error_fail_by_{criterion,fault_type,scr,lvrt_hvrt}.png`.

Regenerate: `python -m hpt_frt.device.error_analysis_mi14`.
Certified result of record: [FRT_V2_RESULTS_2026-06-23.md](FRT_V2_RESULTS_2026-06-23.md) +
`lab/results/p3_full320_switching_summary.json`.
