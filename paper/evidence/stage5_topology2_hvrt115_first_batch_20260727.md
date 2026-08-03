# Stage-5 Topology2 HVRT 1.15 pu First Batch

Date: 2026-07-27

## Scope

This file records the first protected SAC promotion run for topology2 HVRT
`1.15 pu`, `80/120 ms`.  The claim remains switch-level voltage-survival only.

## Command

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage5_topology2_hvrt115_targets_20260727.csv --run-id hpt_stage5_t2_hvrt115_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 90 --behavior-anchor-epochs 18 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,26,26 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt115_80_120_20260727`

## Promotion Results

| Case | Status | Conventional voltage-survival | Best SAC voltage-survival | Best model | Best SAC score | Prior actor score | Notes |
|---|---|---:|---:|---|---:|---:|---|
| topology2 balanced HVRT 1.15 pu / 80 ms | not trained | fail | not evaluated | previous balanced actor | 121.051 | 121.051 | invalid curriculum label |
| topology2 balanced HVRT 1.15 pu / 120 ms | not trained | fail | not evaluated | previous balanced actor | 122.353 | 122.353 | invalid curriculum label |
| topology2 A HVRT 1.15 pu / 80 ms | improved | fail | pass | `data/models/hpt_stage5_t2_hvrt115_80_120_20260727_03_topology2_a_hvrt1p150_80ms_stage5_chunk01.zip` | 130.477 | 137.698 | exact recheck required |
| topology2 A HVRT 1.15 pu / 120 ms | improved | fail | pass | `data/models/hpt_stage5_t2_hvrt115_80_120_20260727_04_topology2_a_hvrt1p150_120ms_stage5_chunk01.zip` | 129.813 | 134.565 | exact recheck required |
| topology2 AB HVRT 1.15 pu / 80 ms | not improved | fail | fail | prior AB 1.10 actor | 136.754 | 136.754 | all chunks failed recovery envelope |
| topology2 AB HVRT 1.15 pu / 120 ms | improved | fail | pass | `data/models/hpt_stage5_t2_hvrt115_80_120_20260727_06_topology2_ab_hvrt1p150_120ms_stage5_chunk01.zip` | 129.858 | 134.163 | exact recheck required |

## Failure Notes

The balanced rows used `topology2_hvrt110_60ms_balanced`, but the current
training entry point accepts `topology2_hvrt110_60ms`.  These two rows require
a corrected retry before any conclusion can be drawn.

The AB 1.15 pu / 80 ms row did train, but all four chunks failed the recovery
envelope with about `0.010 pu` recovery violation.  This is a real control
failure in the current protected-SAC setup and should be retuned with stronger
recovery damping or a trajectory teacher that explicitly suppresses recovery
overvoltage.

## Next Action

Run exact current-SAC recheck for the three improved rows:

- `version_2/sac/experiments/stage5_t2_hvrt115_success_recheck_20260727.csv`

Then create a corrected balanced retry manifest and a separate AB 80 ms
recovery-focused retry.

## Exact Recheck

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt115_success_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt115_success_recheck_20260727 --controller-mode current-sac --timeout-s 1800
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt115_success_recheck_20260727`

Summary:

- cases: `3`
- conventional voltage-survival pass: `0/3`
- SAC voltage-survival pass: `3/3`
- SAC beats conventional: `3/3`
- traditional fail / SAC pass: `3/3`
- traditional pass / SAC fail: `0/3`

| Case | Conventional score | SAC score | SAC envelope violation max pu | SAC recovery violation max pu |
|---|---:|---:|---:|---:|
| topology2 A HVRT 1.15 pu / 80 ms | 232.108 | 130.477 | 0.000 | 0.000 |
| topology2 A HVRT 1.15 pu / 120 ms | 231.675 | 129.813 | 0.000 | 0.000 |
| topology2 AB HVRT 1.15 pu / 120 ms | 232.143 | 129.858 | 0.000 | 0.000 |

The exact recheck confirms three new topology2 HVRT 1.15 pu voltage-survival
actors.  The unresolved rows are balanced 1.15 pu 80/120 ms, which need a
corrected curriculum retry, and AB 1.15 pu / 80 ms, which needs recovery-focused
control refinement.

## Retry Results

Retry command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage5_topology2_hvrt115_retry_targets_20260727.csv --run-id hpt_stage5_t2_hvrt115_retry_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 4e-6 --teacher-prior-weight 110 --behavior-anchor-epochs 24 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 12,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt115_retry_20260727`

Retry outcome:

| Case | Retry outcome | Main failure mode |
|---|---|---|
| topology2 balanced HVRT 1.15 pu / 80 ms | no promoted actor | `dc_link_bounds`, `Vdc_max ~= 1103 V` |
| topology2 balanced HVRT 1.15 pu / 120 ms | no promoted actor | `dc_link_bounds`, `Vdc_max ~= 1103 V` |
| topology2 AB HVRT 1.15 pu / 80 ms | no promoted actor | `timestep_recovery_envelope`, best retry recovery violation about `0.01109 pu` |

Interpretation:

- Balanced 1.15 pu is not blocked by LV voltage regulation.  The observed LV
  envelope and recovery violations are zero, but DC-link overvoltage violates
  the current voltage-survival gate.
- AB 1.15 pu / 80 ms is not blocked by DC-link survival.  Its unresolved issue
  is recovery overvoltage after fault clearance.
- The next retry should not simply increase SAC steps.  It needs a targeted
  mechanism: stronger DC-link/chopper/energy-head shaping for balanced HVRT and
  explicit recovery damping for AB 80 ms.
