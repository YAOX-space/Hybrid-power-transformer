# Systematic Pure-SAC Repair Plan

Date: 2026-07-12

## Current Evidence

Real switching-level Simulink full320, current pure SAC `mi12`:

| verdict | count |
|---|---:|
| True | 70 |
| False | 184 |
| None | 66 |

Strict pass is `70 / 320 = 21.9%`; no-fail is `(70 + 66) / 320 = 42.5%`.

Traditional union on full320 currently gives:

| bucket | count |
|---|---:|
| SAC-only | 0 |
| traditional-only | 75 |
| both-pass | 70 |
| both-fail | 175 |

## ODE-vs-Simulink Diagnosis

Diagnostic output:

- `lab/results/ode_vs_simulink_full320_current_puresac_vs_traditional_20260712.csv`
- `lab/results/ode_vs_simulink_full320_current_puresac_vs_traditional_20260712.json`
- `lab/results/ode_vs_simulink_full320_current_pure_sac_danger_blind.csv`

For pure SAC:

| item | count |
|---|---:|
| Simulink False | 184 |
| Simulink False but ODE proxy pass | 137 |
| ODE-visible Simulink failures | 1 |
| ODE blind/mismatch Simulink failures | 183 |

Blind/mismatch failed criteria among pure-SAC Simulink failures:

| criterion | count |
|---|---:|
| reactive | 103 |
| recover | 121 |
| survive | 70 |
| connect | 1 |
| limit | 0 |

Interpretation: the present ODE proxy is too optimistic for current pure SAC. It does not reliably expose
the recover/reactive/survive failures seen by switching Simulink, so SAC tuning against ODE proxy alone is
not trustworthy.

## Immediate Fix Implemented

Added diagnostic and target-generation scripts:

- `src/hpt_frt/device/compare_ode_simulink_passset.py`
- `src/hpt_frt/device/make_sac_repair_targets.py`

Generated repair targets:

- `lab/results/repair_targets_full320_sim_repair_20260712.csv`
- `lab/results/repair_targets_full320_sim_repair_20260712_sym.csv`
- `lab/results/repair_targets_full320_sim_repair_20260712_asym.csv`
- `lab/results/repair_targets_full320_sim_repair_20260712_hvrt_sym.csv`
- `lab/results/repair_targets_full320_sim_repair_20260712_hvrt_asym.csv`

Target distribution:

| expert | targets |
|---|---:|
| sym | 29 |
| asym | 141 |
| hvrt_sym | 40 |
| hvrt_asym | 40 |

Updated `pure_sac_hard_curriculum.py` so repair-target CSV rows can carry Simulink failure labels:

- `sim_failed_criteria`
- `ode_blind_failed_criteria`
- `target_group`

These labels affect only training reward shaping. They do not change the actor input dimension, deployment
router, or Simulink runtime controller. The deployed controller remains pure SAC.

## Active Experiment

Started a non-promoting candidate training run:

- script: `scripts/run_pure_sac_full320_simrepair.ps1`
- run id: `pure_sac_full320_simlabel_repair_20260712`
- scenario file: `lab/frt_scenarios.csv`
- repair target: `lab/results/repair_targets_full320_sim_repair_20260712.csv`
- steps: `40000`
- no `--promote`
- no `--export`

Important: full320 target IDs must be trained with `lab/frt_scenarios.csv`. They must not be directly
applied to `frt_scenarios_expanded.csv`, because the two files use different scenario-id spaces.

## Expert-Splitting Option

Do not add experts blindly before verifying the label-aware four-expert repair. If four experts still fail,
the next candidate architecture should split along the actual failure clusters:

| proposed expert | motivation |
|---|---|
| `lvrt_sym_deep` | strong-grid symmetric LVRT recover/survive tail |
| `lvrt_sym_shallow` | shallow symmetric LVRT recover/NE boundary |
| `lvrt_1ph` | single-phase reactive/recover mismatch |
| `lvrt_2ph` | two-phase reactive/recover mismatch |
| `lvrt_2ph_g` | two-phase-ground reactive/recover mismatch |
| `hvrt_3ph` | three-phase HVRT, currently 0 strict pass |
| `hvrt_1ph` | single-phase HVRT, reactive boundary/NE |

Adding experts requires coordinated changes in:

- Python router/evaluator
- training export
- Simulink HLC weight loading and routing
- pass-set comparison scripts

So it should be Stage B, after the current Stage A label-aware four-expert candidate is tested.

## Acceptance Gate

A candidate is not accepted unless all of the following improve:

1. full320 strict pass increases over `70/320`.
2. full320 traditional-only decreases below `75`.
3. HVRT `swell_3ph` is no longer `0/40` strict pass.
4. ODE-vs-Simulink dangerous blind count decreases from `137`.
5. selected-expanded 31-scene result does not regress.
