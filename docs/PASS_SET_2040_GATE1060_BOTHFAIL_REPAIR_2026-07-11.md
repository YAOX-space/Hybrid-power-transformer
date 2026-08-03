# 2040 Pass-Set Repair: Gate 1.060 and Both-Fail Experiments

Date: 2026-07-11

## Selected Result

Final selected configuration:

- SAC weights: current pure-SAC combo from `pure_sac_recent_hvrt_hvrtsym_multilabel_20260711`
- Router change: HVRT expert route threshold `V2p >= 1.060`
- Runtime action path: pure SAC only
- No residual controller, MPC fallback, projection wrapper, BC teacher, or action override

Result files:

- `lab/results/pass_sets_2040_gate1060_current_models_20260711.json`
- `lab/results/pass_sets_2040_gate1060_current_models_20260711.csv`
- `lab/results/pass_sets_2040_gate1060_current_models_20260711_traditional_only_union.csv`

## Main Metrics

| configuration | SAC pass | SAC-only | traditional-only | both-pass | both-fail |
|---|---:|---:|---:|---:|---:|
| original current pure SAC | `1636 / 2040` | `232` | `72` | `1404` | `332` |
| gate 1.075, current weights | `1718 / 2040` | `242` | `0` | `1476` | `322` |
| gate 1.060, current weights | `1802 / 2040` | `326` | `0` | `1476` | `238` |

The gate 1.060 configuration preserves full traditional pass-set coverage (`traditional-only = 0`)
and reduces both-fail by `84` scenarios relative to gate 1.075.

## Rejected Weight-Retrain Attempts

Targeted HVRT recover retraining was tested but not selected:

- r3: `pure_sac_bothfail_hvrt_recover_20260711_r3`
  - full 2040 pass dropped to `1506`
  - traditional-only regressed to `156`
- r4: `pure_sac_hvrt_asym_repair_union_20260711_r4`
  - fast SAC-only screen gave `1723` pass
  - traditional-only regressed to `8`

These runs improved some direct target-set recover metrics but damaged reactive behavior on shallow
HVRT, so they are archived as rejected experiments. The best current solution is the original
weights with earlier HVRT routing.

## Remaining Both-Fail

After gate 1.060, `both-fail = 238`. Main remaining groups:

- HVRT `swell_3ph target=1.3`: 44
- LVRT `sym3ph target=0.1/0.2/0.35/0.5`: 88 total
- HVRT `swell_1ph target=1.1..1.3`: 80 total
- LVRT `2ph target=0.7`: 6

Main remaining SAC failure criteria:

- `recover`: 100
- `vdc_survive_proxy`: 70
- `connect+vdc_survive_proxy`: 31
- `connect+recover`: 20
- `reactive`: 6

Next repair should target these remaining failures with preservation constraints against the
gate-1.060 pass-set, not against the older gate-1.075 target.
