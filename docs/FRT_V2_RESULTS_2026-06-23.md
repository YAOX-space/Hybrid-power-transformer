# frt-v2 Full-320 Switching Results — 2026-06-23

First **faithful switching-layer** frt-v2 result. Unlike the ODE proxy (which leaves `limit`/`survive`
NOT_EVALUATED), this evaluates all five criteria at the switching level, so it is a **certified
frt-v2 result, not a proxy**. It is **not** to be called a "国标认证通过率"; use *strict pass rate* and
*no-fail / effective pass rate* (defined below).

## Method (scenario calibration)

The CSV `trans_resistance` does **not** reproduce the intended sag in the switching model (e.g. sym
`target_V_pu=0.2` → switching V+≈0.017). So each scenario's fault was **re-calibrated**: the
open-loop terminal positive-sequence voltage V+ is matched to the ODE's imposed
`Vg_p = fault_sequence(fault_type, target_V_pu)` (single source: `src/hpt_frt/device/frt_env.py`).

- 32 unique `(fault_type, SCR)` operating points → open-loop sweeps (`lab/simulink/frt_v2_calibrate.m`,
  HLC mode 10 / zero command) → curves `lab/results/calib_{LVRT,HVRT}_scr{3,10}.mat`.
- Per-scenario fault resistance / swell amplitude interpolated → `lab/results/p3_scenario_faultparams.json`
  (20 sub-threshold `swell_1ph@scr10` extrapolated — immaterial, V+ barely > 1.1).
- Runner: `lab/simulink/frt_v2_full320_switching.m` (resumable; one build per grid-mode×SCR; reuses the
  validated 4-fix measurement pipeline + the authoritative `frt_v2_evaluate.m`).

## Metric definitions (three, keep distinct)

| Metric | Definition |
|---|---|
| **strict_pass** (*frt-v2 switching strict pass rate*) | all 5 frt-v2 criteria **evaluated AND PASS** |
| **NOT_EVALUATED (NE)** | no FAIL, but ≥1 criterion is N/A / has no assessment window |
| **no-fail / effective_pass** | no criterion FAILED (PASS + NE). **NOT** a strict grid-code pass rate |

**The 116/320 NE for SAC are not "fault-free".** They are scenarios where the `reactive` criterion finds
**no sustained reactive demand after the response delay** (`"no sustained reactive demand after response
delay"`) — shallow sags / single-phase swells whose positive-sequence deviation never sustains a droop
command. They rode through; the reactive criterion simply did not apply.

> ⚠️ **Effective-diversity caveat (read with the headline %).** Under the Δ-Yg topology the deepest
> reachable asymmetric residual is V+≈0.78, so the three `1ph_g` depth levels (target_V_pu 0.2/0.5/0.75
> → V+ 0.73/0.83/0.92) are essentially the **same mild operating point ×3** — exactly the 40 `1ph_g` NE.
> The nominal 320 therefore contains equivalent-repeat easy cases; **effective diversity ≪ 320** and the
> headline percentages over-weight benign repeats. See AUDIT_2026-06-22.md M3, README §诚实局限 #1,
> PROJECT_OVERVIEW §7.3. (frt-v2 numbers below are unchanged; this only governs their interpretation.)

## Result

| Controller | True | False | NE | strict_pass | no-fail/effective | fail | pass\|determinable |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Residual SAC mi=14 (deployed)** | 170/320 | 34/320 | 116/320 | **53.1%** | **89.4%** | **10.6%** | 83.3% |
| dq fixed-law mi=7 (fair peak-base baseline) | 127/320 | 102/320 | 91/320 | 39.7% | 68.1% | 31.9% | 55.5% |

`pass|determinable = True / (True+False)` — excludes NE.

### By category

| | SAC True/False/NE | SAC pass\|det | dq True/False/NE | dq pass\|det |
|---|:---:|:---:|:---:|:---:|
| LVRT (240) | 160/14/66 | **92.0%** | 107/92/41 | 53.8% |
| HVRT (80)  | 10/20/50  | 33.3% | 20/10/50 | **66.7%** |

### By fault type (True / False / NE)

| fault_type | SAC | dq |
|---|:---:|:---:|
| sym3ph (60) | 60 / 0 / 0 | 50 / 10 / 0 |
| 1ph_g (60) | 20 / 0 / 40 | 10 / 30 / 20 |
| 2ph (60) | 40 / 12 / 8 | 17 / 33 / 10 |
| 2ph_g (60) | 40 / 2 / 18 | 30 / 19 / 11 |
| swell_3ph (40) | 10 / 10 / 20 | 20 / 10 / 10 |
| swell_1ph (40) | 0 / 10 / 30 | 0 / 0 / 40 |

## Reading

- **SAC dominates LVRT** (pass|det 92.0% vs dq 53.8%): `1ph_g` zero fails (dq 30), `sym3ph` 60/0/0
  perfect (dq 50/10). dq's LVRT failures are mostly slow `recover` at the strong grid (scr10) plus
  deep-sym/`2ph` survive.
- **dq beats SAC on HVRT** (66.7% vs 33.3%). SAC's HVRT failures are the **weak-grid (scr3) deep
  swells**: `swell_3ph` Vg_p=1.30 → `survive=FAIL` (DC-bus undershoot), `swell_1ph` Vg_p=1.10 →
  `reactive=FAIL`. The switching layer **exposes a DC-survival weakness the ODE proxy (HVRT 100%)
  cannot see**, because the ODE leaves limit/survive NOT_EVALUATED — exactly why the switching layer
  matters.
- **Net**: SAC fails 3× fewer (34 vs 102); the edge is entirely LVRT.

## Active vs legacy entry points

- **frt-v2 active**: `lab/simulink/frt_v2_full320_switching.m`, `frt_v2_spotcheck.m`, `frt_v2_evaluate.m`.
- **legacy guard (NOT a frt-v2 entry)**: `lab/simulink/validate_mode_full.m`, `run_spotcheck.m` —
  fail-fast guarded, retained for history only.

## Remaining research (NOT this round — no more large runs / no Simulink full-320)

**Error analysis of the SAC 34/320 FAIL** — the next investigation, to be done on the *already-saved*
per-scenario MATs (`p3_full320_sw_mi14.mat`, with `crit` + `prov`), **without re-running any sim**:

1. **Decompose the failing criterion** — split the 34 FAIL into `reactive=FAIL` vs `survive=FAIL` (vs
   any `connect`/`recover`/`limit`), since the fix differs per criterion (reactive ⇒ command/prior;
   survive ⇒ DC-bus/chopper).
2. **Classify each failure by**: (a) fault_type, (b) SCR (3 weak / 10 strong), (c) residual depth
   (LVRT Vg_p) / swell level (HVRT Vg_p), (d) LVRT vs HVRT. From the run, the clusters are
   HVRT weak-grid deep swell (`swell_3ph` Vg_p=1.30@scr3 → survive/DC undershoot; `swell_1ph`
   Vg_p=1.10@scr3 → reactive) + a `2ph` Vg_p=0.88 reactive-boundary cluster — to be confirmed by the
   decomposition.
3. **Then, and only then, choose a remedy** — among: targeted sampling (over-weight the failing
   regions in training), reward shaping (penalise deep-swell DC undershoot / under-absorption), or a
   deployment-side safety projection (clip/coordinate the command at the failing boundary). Decide
   *after* the breakdown, not before.
4. **No large experiments this round** — the breakdown is pure post-processing of saved data; any
   retrain / re-sim is a separate, later decision.

Context: the deployed residual is **LVRT-strong / HVRT-weak**; a HVRT-specialised prior or expert is the
natural improvement direction (note the `hvrt_asym` expert is broken — flat +0.018, never absorbs).

Data: `lab/results/p3_full320_switching_summary.json`, `p3_full320_sw_mi{14,7}.mat`,
`p3_scenario_faultparams.json`, `calib_*.mat`.
