# Simulink Pure-SAC Repair Notes - 2026-07-11

## Baseline

Current accepted pure-SAC deployment remains the gate1060 four-expert combo:

- sym: `lab/results/pure_sac_simtrace_bc_20260711_012231/sac_sym_best.zip`
- asym: `lab/results/pure_sac_simtrace_bc_20260710_134037/sac_asym_best.zip`
- hvrt_sym: `lab/results/pure_sac_simtrace_bc_20260711_020617/sac_hvrt_sym_best.zip`
- hvrt_asym: `lab/results/pure_sac_simtrace_bc_20260710_135918/sac_hvrt_asym_best.zip`

Simulink selected-expanded result after deployment gate alignment:

- `25 / 31` selected cases pass.
- LVRT selected hard cases `217-240`: `24 / 24` pass.
- Remaining selected failures are shallow HVRT:
  - `1441`: `swell_3ph target=1.10 SCR=2`, recover fail.
  - `1456`, `1481`, `1500`, `1873`, `1875`: reactive `NOT_EVALUATED`; most physical criteria pass.

Spotcheck result:

- `10 / 12` pass.
- `S1_deep_sym` and `S4_deep_sym_scr10` fail on reactive wrong-sign and Vdc survive.

## Alignment Fixes Kept

- Simulink online HVRT detector/router aligned to `V2p >= 1.060`.
- ODE `HPTFRTEnvV2` online detector aligned to `GATE_HV = 1.060`.
- Network wrapper `GATE_HV_THR` aligned to `1.060`.
- Pure-SAC combo export now writes a deployment `run_id` while keeping all expert MAT structs codegen-compatible.
- Selected-expanded Simulink writer now keeps full trace in MAT and writes JSON/CSV summaries.

## Rejected Screen Experiment

Run:

`pure_sac_hard_curriculum_20260711_235057_pure_sac_simfail_repair_screen_20260711`

Screen setup:

- Warm-started from current accepted four-expert combo.
- Trained `sym`, `hvrt_sym`, `hvrt_asym` for `20k` steps.
- Added aggressive Simulink-failure reward shaping for deep-sym LVRT and shallow-HVRT recovery.

Rejected results:

- Trained `sym + hvrt_sym + hvrt_asym` combo: expanded2040 proxy `61.7%`, hard24 `0 / 24`.
- Old `sym/asym` plus trained HVRT experts: expanded2040 proxy `69.1%`, hard92 `8 / 92`.

Conclusion:

- The aggressive reward shaping is too strong and destabilizes specialists.
- These weights must not be promoted or exported.
- The reward shaping is now guarded behind `HPT_SIMFAIL_REWARD_SCALE`; default is `0.0`.
- `deep_sym_weight` default was reduced to `4`.

## Rejected HVRT-Sym Micro Experiments

All experiments below kept the accepted `sym`, `asym`, and `hvrt_asym` checkpoints fixed and replaced
only `hvrt_sym` for ODE combo evaluation. None were promoted.

| run | change | expanded2040 proxy | hard92 pass | verdict |
|---|---|---:|---:|---|
| `pure_sac_hvrt_sym_smallrepair_20260712` | `HPT_SIMFAIL_REWARD_SCALE=0.05`, `20k`, shallow weight `16` | `69.1%` | `8 / 92` | reject |
| `pure_sac_hvrt_sym_samplingonly_20260712` | reward scale `0.0`, `20k`, shallow weight `16` | `79.9%` | `44 / 92` | reject |
| `pure_sac_hvrt_sym_micro_lr_20260712` | reward scale `0.0`, `lr=1e-5`, `10k`, shallow weight `12` | `69.1%` | `8 / 92` | reject |

Baseline for comparison:

- accepted gate-aligned combo after ODE detector alignment: expanded2040 proxy `85.4%`, hard92 `57 / 92`.

Conclusion:

- Re-training `hvrt_sym` by oversampling shallow HVRT is not a safe local repair.
- The expert drifts away from broad HVRT coverage before it fixes the selected Simulink edge cases.
- Do not increase steps for this route; it worsens the same failure.

## Checkpoint Selector Fix

The rejected runs exposed a selection bug in the repair workflow:

- old score: `target_proxy * 10 + broad_val_proxy`
- effect: a small shallow-HVRT target subset could overwrite the checkpoint even when broad HVRT
  validation collapsed.

Fix:

- save the warm-start checkpoint as the initial candidate at `step=0`;
- use broad validation proxy as the primary score;
- apply only a small target bonus after broad validation is above a floor.

New defaults:

- `--target-bonus-weight 0.25`
- `--min-val-proxy-for-target-bonus 80.0`

Verification run:

`pure_sac_hvrt_sym_selectorfix_20260712`

- `best_step = 0`, so the damaged trained checkpoint did not replace the accepted warm start.
- expanded2040 proxy returned to the gate-aligned accepted baseline: `85.4%`.
- hard92 returned to `57 / 92`.

## HVRT-Sym Candidate Search

Run:

`pure_sac_hvrt_sym_selector_search_20260712`

Setup:

- `hvrt_sym` only.
- `60k` steps, `lr=5e-5`, shallow weight `12`, reward scale `0.0`.
- selector fix enabled.

Result:

- `best_step = 0` for all evaluations through `60k`.
- final trained checkpoint fell to broad validation proxy `16.7%`.
- accepted warm-start remained selected, so no bad model was promoted.

Existing checkpoint scan:

| hvrt_sym candidate | expanded2040 proxy | hard92 pass | verdict |
|---|---:|---:|---|
| accepted current `pure_sac_recent_hvrt_hvrtsym_multilabel_20260711` | `85.4%` | `57 / 92` | keep |
| `pure_sac_shallow_hvrt_repair_20260711_r2` | `84.2%` | `56 / 92` | reject |
| `data/models/sac_hvrt_sym_best.zip` | `84.6%` | `57 / 92` | reject |
| historical `pure_sac_1783607069_2b64d078` | `85.1%` | `55 / 92` | reject |

Conclusion:

- No tested `hvrt_sym` candidate beats the current accepted checkpoint.
- The next improvement probably needs a different target formulation, not more `hvrt_sym` fine-tuning.

## BC / Distillation Attempt

Rationale:

- RL fine-tuning caused `hvrt_sym` drift.
- BC/distillation should preserve the accepted actor and only alter shallow-HVRT recovery windows.

Candidate 1:

`pure_sac_simtrace_bc_20260712_025653`

- source: accepted `hvrt_sym`.
- trace: `selected_expanded_switching_gate1060_puresac_selected_20260711_mi12.mat`.
- target sids: `1441,1456,1481,1500`.
- teacher mode: post-recover `iq`, gain `0.7`, teacher weight `20`.
- ODE combo: expanded2040 proxy `85.5%` (slightly above accepted `85.4%`), hard92 unchanged `57 / 92`.
- Simulink selected: still `25 / 31`; `1481` regressed from `frt=None/recover PASS` to `frt=False/recover FAIL`.
- verdict: reject.

Candidate 2:

`pure_sac_simtrace_bc_20260712_030731`

- target sids: `1441,1456` only, to avoid high-recovery cases `1481/1500`.
- teacher mode: post-recover `iq`, gain `0.45`, teacher weight `12`.
- ODE combo: expanded2040 proxy `85.4%`, hard92 unchanged `57 / 92`.
- Simulink selected/HVRT-only runs did not complete within normal time and produced no result file.
- verdict: reject as Simulink runtime regression.

After rejection, Simulink MAT weights were restored to the accepted gate1060 combo.

## Next Experiment

Use a safer two-stage repair:

1. Keep current accepted weights fixed.
2. Stop local `hvrt_sym` retraining until the checkpoint selection metric is changed.
3. Add a dedicated acceptance/selection metric that evaluates broad HVRT coverage, not only the
   oversampled shallow-HVRT target.
4. Try candidate selection from existing checkpoints or train a separate candidate and only select it
   if expanded2040 proxy stays above the accepted baseline.

Acceptance gate for any new model:

- No promotion unless expanded2040 proxy is at least the current accepted baseline.
- No promotion unless `traditional_only = 0` remains true in formal pass-set.
- Simulink selected-expanded must improve beyond `25 / 31` without breaking `217-240`.
