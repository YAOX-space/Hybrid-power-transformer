# HPT Direct SAC Progress - 2026-07-17

## Interruption Handling

The full fault-specialist run was interrupted while evaluating
`topology2 / fault / sag_0p75`.

Interrupted run directory:

- `lab/results/hpt_case_specialists_20260717_011726`

The residual Python and MATLAB processes were stopped.  The run produced 11
diagnostic fault-specialist records before interruption.  It should not be
treated as a completed campaign.

## Engineering Cleanup

Added an explicit package map and workflow for `version_2/sac`:

- `version_2/sac/README.md`
- `version_2/sac/experiments/README.md`
- `version_2/sac/run_hpt_sac_pipeline.py`

The scripts were not moved yet because current tests, wrappers, and commands
import modules directly from `version_2.sac`.  Any future folder migration should
leave compatibility wrappers.

## Current Technical Status

Completed:

- Full switch-level FRT calibration matrix exists for topology1/topology2,
  LVRT depths `0.20/0.50/0.75/0.85/0.90 pu`, and HVRT depths
  `1.10/1.20/1.25/1.30 pu`.
- The FRT proxy is calibrated for independent d-axis regulation and independent
  energy-bridge sweeps.
- FRT teacher traces were generated for 18 topology/fault cases.
- Fault specialist training now uses FRT teacher traces instead of steady traces.

Partial result from the interrupted run:

- Topology1 LVRT specialists generally improved the switch-level score and Vdc
  survival but still failed full FRT criteria.
- Topology1 HVRT specialists did not consistently improve score.
- Topology2 sag `0.20/0.50 pu` improved some metrics but still failed.

Not completed:

- No fault specialist actor was promoted from the interrupted full run.
- Full GB/T pass/fail certification is still provisional because grid-side
  reactive-current logging is missing.
- Topology2 joint regulating+energy proxy behavior still has a large Vdc gap and
  needs a joint-interaction model before proxy-only training can be trusted.

## Proxy Calibration Update

The resumed full fault-specialist run was stopped at the user's request and the
work shifted back to proxy calibration.

Stopped run:

- `lab/results/hpt_case_specialists_20260717_011726`
- completed `13 / 18` fault specialist records before stop
- no specialist actor was promoted

Proxy changes:

- Added `fault_reg_response_table` from all FRT `reg_sweep` rows, including
  nonzero `reg_q` cases.
- Added `fault_joint_response_table` from FRT `joint_sweep` rows, representing
  the coupled `(reg_d, energy_d, energy_q)` response.
- Updated the proxy environment to use calibrated multi-axis lookup tables for
  fault LV/Vdc targets.
- Updated the FRT proxy-gap measurement so it evaluates the same joint lookup
  model that the environment uses.

Latest matrix-calibrated in-sample gap:

- topology2 `joint_sweep` Vdc MAE improved from about `0.40-0.45 pu` to `0`.
- topology2 `reg_q_sweep` Vdc MAE improved from about `0.26-0.33 pu` to `0`.
- topology1 `joint_sweep` and `reg_q_sweep` are also matched in-sample.

Important limitation:

This is a calibration-matrix in-sample match, not yet a generalization proof.
The next proxy step should create a small holdout or newly sampled topology2
joint-action matrix to verify interpolation between the calibrated points.

Quick leave-one-depth diagnostic:

- Held-out standard depths show that interpolation is still uneven.
- topology2 LVRT `0.50 pu` held out: joint-sweep Vdc MAE about `0.335 pu`.
- topology2 HVRT `1.10 pu` held out: joint-sweep Vdc MAE about `0.230 pu`.
- topology2 LVRT `0.85 pu` and HVRT `1.25 pu` interpolate much better.

Operational implication:

- For the next SAC runs, keep the FRT proxy curriculum on the calibrated
  discrete GB/T depths first.
- Do not claim continuous fault-depth generalization until additional topology2
  joint-action samples or a better learned uncertainty-aware proxy are added.

## Reward Alignment Check

Added:

- `version_2/sac/measure_hpt_reward_alignment.py`

Latest outputs:

- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_detail.csv`
- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_summary.csv`
- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_REPORT.md`

Result:

- `20` topology/category/mode groups were checked.
- `13 / 20` groups show useful monotonic alignment.
- `7 / 20` groups are weak under the current criteria.

Important weak groups:

- topology1 HVRT `energy_sweep`: Spearman about `0.169`; proxy reward ranking
  is not reliable here.
- topology1/topology2 `joint_sweep`: Spearman is often acceptable, but top-3
  overlap is `0`; the proxy gets the broad trend but not the best action.
- topology2 HVRT `joint_sweep`: Spearman about `0.716`, proxy top-1 is only
  rank `15 / 36` in switch-level score.

Interpretation:

- The proxy is useful for coarse filtering and directionally ranking many LVRT
  groups.
- It is not yet trustworthy as a standalone SAC training environment for final
  action selection.
- Next training should use proxy candidates only with switch-level promotion
  gates, or switch to offline/DAgger training from Simulink-labeled actions for
  the weak groups.

## Next Engineering Step

Use `run_hpt_sac_pipeline.py` for repeatable launches:

```powershell
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --list
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --stage fault-specialists-smoke
```

Before another full 8-hour campaign, the next code work should be:

1. Add grid-side current/reactive-current logging to the switch-level evaluator.
2. Validate the new joint lookup proxy on held-out or newly sampled topology2
   joint regulating/energy actions.
3. Resume specialist training only after a short smoke case proves the new
   scoring and proxy gap are consistent.

## Literature-Driven Method Update

Added:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-offline-rl-literature-and-method.md`
- `version_2/sac/train_hpt_reward_correction.py`

Reference conclusion:

- Offline RL papers in `references/week6` point to a conservative data-first
  route when rollouts are expensive and the proxy is biased.
- SAC robustness papers in `references/week5` are relevant, but they do not
  remove the need to align the reward source with switch-level Simulink.
- The current practical fix is therefore reward correction from switch-level
  labels before more proxy SAC.

Reward-correction run:

- Output directory:
  `lab/results/hpt_v2_reward_correction/reward_correction_20260717_025529`
- Selected model: `extra_trees`
- Training rows: `656`
- Held-out action rows: `172`
- Feature count: `35`

Held-out action evaluation:

| Metric | Baseline proxy | Corrected proxy |
| --- | ---: | ---: |
| Weak groups | `3 / 20` | `0 / 20` |
| Mean Spearman | `0.852` | `0.992` |
| Mean top-k overlap fraction | `0.833` | `0.967` |
| Mean proxy-top1 switch percentile | `0.088` | `0.021` |

Full matrix sanity check:

| Metric | Baseline proxy | Corrected proxy |
| --- | ---: | ---: |
| Weak groups | `7 / 20` | `1 / 20` |
| Mean Spearman | `0.782` | `0.975` |
| Mean top-k overlap fraction | `0.467` | `0.850` |
| Mean proxy-top1 switch percentile | `0.155` | `0.025` |

Interpretation:

- The correction model substantially repairs action ranking on the current
  switch-level FRT matrix.
- It should now be used for candidate/teacher ranking and specialist training
  inputs.
- It is not a final proof of controller success.  Any actor trained with this
  corrected signal still needs switch-level validation.

## Conventional-Control Baseline Start

Added:

- `version_2/simulink/eval_hpt_v2_control_comparison.m`
- `version_2/sac/summarize_hpt_control_comparison.py`

Purpose:

- Move toward the real research target: compare SAC against a traditional
  dq/voltage-loop style controller on the same switch-level HPT plants.
- Keep the plant, PWM, converter limits, topology, and fault definitions
  identical across no-control, conventional, and SAC modes.

Implemented control modes:

- `no_control`: `hpt_sac_enable = 0`, energy bridge disabled.
- `conventional_dq`: current HPTSACController `policy_mode = 0` conventional-like
  voltage/DC-link feedback branch. This is a runnable baseline v0, not yet the
  final paper-grade PLL+dq+PI controller.
- `sac_actor_raw_guard0`: SAC actor with execution guard disabled.

Important repair:

- `version_2/simulink/hpt_sac_actor_weights.mat` was found incomplete; it only
  contained five actor variables and missed `mu_*`, `act_*`, `n_obs`, and
  `n_act`.
- The broken file was backed up locally and the complete
  `hpt_sac_actor_weights_step4_pass_20260715.mat` file was restored as the
  steady actor weight file so MATLAB Function compilation can succeed.

Smoke result:

- Input:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_sag_0p90_20260717_033421.csv`
- Summary:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_sag_0p90_20260717_033421_REPORT.md`

| Mode | Score | Pass | LV recovery | Vdc min |
| --- | ---: | --- | ---: | ---: |
| no_control | `101.583` | false | `204.405 V` | `709.352 V` |
| conventional_dq | `109.791` | false | `191.047 V` | `722.911 V` |
| sac_actor_raw_guard0 | `164.422` | false | `201.956 V` | `121.095 V` |

Interpretation:

- Current SAC does not beat the conventional baseline in this smoke case.
- Current conventional baseline v0 also does not beat no-control, so it needs
  tuning or replacement by a stronger PLL+dq+PI baseline before the final paper
  comparison.
- The comparison infrastructure is now in place; the next work is controller
  baseline tuning and then SAC training against that baseline.
