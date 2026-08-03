# Stage-5 Topology2 HVRT 1.20 pu Expansion

Date: 2026-07-27

## Scope

This evidence note records the topology2 HVRT `1.20 pu` voltage-survival
expansion.  The claim is limited to switch-level voltage-survival and
beat-conventional evidence.  Full FRT certification is not claimed.

## Training Manifest

Manifest:
`version_2/sac/experiments/stage5_topology2_hvrt120_targets_20260727.csv`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage5_topology2_hvrt120_targets_20260727.csv --run-id hpt_stage5_t2_hvrt120_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 4e-6 --teacher-prior-weight 120 --behavior-anchor-epochs 24 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 12,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt120_80_120_20260727`

The manifest used exact-rechecked `1.15 pu` specialists as warm starts.

## Candidate Outcome Before Exact Recheck

| Case | Best voltage-survival candidate | Best passing chunk | Best passing score | Notes |
|---|---:|---:|---:|---|
| balanced HVRT 1.20 pu / 80 ms | yes | 4 | `138.748` | All chunks passed voltage-survival. |
| balanced HVRT 1.20 pu / 120 ms | no | - | - | All chunks failed `timestep_fault_lv_band` with max violation about `0.00926 pu`. |
| A HVRT 1.20 pu / 80 ms | yes | 1 | `132.233` | Later chunks failed recovery, so chunk 1 was retained. |
| A HVRT 1.20 pu / 120 ms | yes | 1 | `131.574` | Chunks 1-3 passed; chunk 1 had the best score. |
| AB HVRT 1.20 pu / 80 ms | yes | 1 | `132.167` | Later chunks failed recovery, so chunk 1 was retained. |
| AB HVRT 1.20 pu / 120 ms | yes | 2 | `132.060` | Chunk 2 passed and had the best score. |

The failed balanced `120 ms` row is useful boundary evidence: the same control
structure survives `80 ms`, but the longer `120 ms` fault pushes the fault
window above the current LV band.

The A/AB rows show a recurring training behavior: additional protected SAC
chunks can improve scalar score or change operating point while violating the
sampled recovery envelope.  Candidate selection therefore must remain
gate-first: retain the best passing chunk, not the lowest raw score.

## Exact Recheck

Exact recheck manifest:
`version_2/sac/experiments/stage5_t2_hvrt120_success_recheck_20260727.csv`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt120_success_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt120_success_recheck_20260727 --controller-mode current-sac --timeout-s 2400
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt120_success_recheck_20260727`

Summary:

- cases: `5`
- conventional voltage-survival pass: `0/5`
- SAC voltage-survival pass: `5/5`
- SAC beats conventional: `5/5`
- traditional fail / SAC pass: `5/5`
- traditional pass / SAC fail: `0/5`

| Case | Conventional score | SAC score | SAC minus conventional | Conventional reason | SAC reason | SAC envelope violation max pu | SAC recovery violation max pu | SAC Vdc min/max |
|---|---:|---:|---:|---|---|---:|---:|---:|
| balanced HVRT 1.20 pu / 80 ms | `271.541` | `138.748` | `-132.793` | `timestep_fault_lv_band;timestep_recovery_envelope` | none | `0.000` | `0.000` | `736.68 / 800.77 V` |
| A HVRT 1.20 pu / 80 ms | `235.233` | `132.233` | `-103.000` | `timestep_recovery_envelope` | none | `0.000` | `0.00016` | `761.25 / 833.11 V` |
| A HVRT 1.20 pu / 120 ms | `234.086` | `131.574` | `-102.512` | `timestep_recovery_envelope` | none | `0.000` | `0.000` | `761.25 / 833.11 V` |
| AB HVRT 1.20 pu / 80 ms | `238.115` | `132.167` | `-105.948` | `timestep_recovery_envelope` | none | `0.000` | `0.000` | `764.75 / 858.64 V` |
| AB HVRT 1.20 pu / 120 ms | `236.796` | `132.060` | `-104.736` | `timestep_recovery_envelope` | none | `0.000` | `0.000` | `765.81 / 863.12 V` |

The promoted manifest was updated:
`version_2/sac/experiments/stage4_promoted_specialists_20260727.csv`.

## Balanced 120 ms Repair

The initial balanced `1.20 pu / 120 ms` candidate failed the sampled
fault-window LV band by about `0.009 pu`.  A targeted switch-level smoke test
showed that reducing the regulating d-axis command from the previous
approximately `0.60` operating point to `0.55` removed the fault-band
over-boost while preserving recovery:

```powershell
py -3 -m version_2.sac.validate_hpt_trajectory_switchlevel --run-id hpt_stage5_t2_bal_hvrt120_120ms_reg055_smoke_20260727 --topology topology2 --fault-pu 1.20 --duration-s 0.12 --fault-start 0.035 --fault-stop-margin 0.125 --fault-settle-s 0.020 --chopper-threshold 760 --rchop-scale 0.55 --preset constant --action 0.55 0 0 0 --timeout-s 1200
```

The constant trajectory passed voltage-survival and beat the conventional
baseline:

- trajectory score: `137.641` vs conventional `272.305`
- LV fault/recovery means: `224.410 / 203.022 V`
- DC link min/max: `739.08 / 802.29 V`
- envelope and recovery violations: `0`

The trajectory was then converted into an actor with BC plus one DAgger
iteration.  Both actors passed the internal switch-level evaluation; the BC0
actor had the lower score and was selected:

| Actor | Voltage-survival pass | Score | Beats conventional | LV fault min/max | LV recovery mean | Vdc min/max | Full-FRT reason |
|---|---:|---:|---:|---:|---:|---:|---|
| BC0 | yes | `137.770` | yes | `215.77 / 237.63 V` | `204.38 V` | `737.13 / 800.37 V` | `grid_current_limit` |
| DAgger1 | yes | `138.208` | yes | `215.15 / 237.82 V` | `204.32 V` | `738.59 / 800.31 V` | `grid_current_limit` |

Independent exact recheck manifest:
`version_2/sac/experiments/stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727.csv`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727.csv --run-id hpt_stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727 --controller-mode current-sac --timeout-s 1800
```

Exact recheck result:

- conventional voltage-survival pass: `0/1`
- SAC voltage-survival pass: `1/1`
- SAC beats conventional: `1/1`
- SAC score: `137.770` vs conventional `272.305`
- SAC envelope and recovery violations: `0`
- SAC Vdc min/max: `737.13 / 800.37 V`

## Interpretation

This run extends topology2 HVRT voltage-survival coverage beyond the previous
`1.15 pu` limit.  Six new `1.20 pu` cases are exact-rechecked and beat the
traditional dq baseline after the balanced `120 ms` repair.  The repaired
balanced row is useful evidence that Stage-5 promotion should remain
case-specific: a slightly lower regulating command solved the over-boost that
appeared at the longer balanced HVRT duration.

The result strengthens the voltage-survival claim but also reinforces a
limitation: the actors still fail full-FRT current-related requirements.  The
full-FRT failures should be handled in a later phase after the voltage-survival
boundary is fully mapped.

## Next Actions

1. Rerun a compact Stage-5 boundary matrix including all new `1.15 pu` and
   `1.20 pu` promotions.
2. Continue topology1 unbalanced score optimization, where the challenge is
   not survival but beating the conventional dq baseline.
