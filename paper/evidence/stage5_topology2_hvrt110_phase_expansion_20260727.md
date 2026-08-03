# Stage-5 Topology2 HVRT 1.10 pu Phase Expansion

Date: 2026-07-27

## Scope

This evidence file records the first Stage-5 topology2 HVRT expansion batch.
The goal is switch-level voltage-survival, not full FRT certification.

Target cases:

- topology2 A-phase HVRT, 1.10 pu, 80 ms
- topology2 A-phase HVRT, 1.10 pu, 120 ms
- topology2 AB-phase HVRT, 1.10 pu, 80 ms
- topology2 AB-phase HVRT, 1.10 pu, 120 ms

## Commands

Initial A/AB batch:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage5_topology2_hvrt_expansion_targets_20260727.csv --run-id hpt_stage5_t2_hvrt110_phase_80_120_20260727 --case-id topology2_a_hvrt1p100_80ms_stage5 --case-id topology2_a_hvrt1p100_120ms_stage5 --case-id topology2_ab_hvrt1p100_80ms_stage5 --case-id topology2_ab_hvrt1p100_120ms_stage5 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 80 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,24,24 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

AB retry after fixing the curriculum label:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage5_topology2_ab_hvrt110_retry_targets_20260727.csv --run-id hpt_stage5_t2_ab_hvrt110_retry_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 80 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,24,24 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

## Results

| Case | Conventional voltage-survival | Best SAC voltage-survival | Best SAC model | Best SAC score | Prior actor score | Improvement |
|---|---:|---:|---|---:|---:|---:|
| topology2 A HVRT 1.10 pu / 80 ms | fail | pass | `data/models/hpt_stage5_t2_hvrt110_phase_80_120_20260727_01_topology2_a_hvrt1p100_80ms_stage5_chunk01.zip` | 127.659 | 139.179 | 11.520 |
| topology2 A HVRT 1.10 pu / 120 ms | fail | pass | `data/models/hpt_stage5_t2_hvrt110_phase_80_120_20260727_02_topology2_a_hvrt1p100_120ms_stage5_chunk01.zip` | 127.069 | 135.203 | 8.134 |
| topology2 AB HVRT 1.10 pu / 80 ms | fail | pass | `data/models/hpt_stage5_t2_ab_hvrt110_retry_80_120_20260727_01_topology2_ab_hvrt1p100_80ms_stage5_retry_chunk02.zip` | 127.803 | 133.821 | 6.017 |
| topology2 AB HVRT 1.10 pu / 120 ms | fail | pass | `data/models/hpt_stage5_t2_ab_hvrt110_retry_80_120_20260727_02_topology2_ab_hvrt1p100_120ms_stage5_retry_chunk01.zip` | 127.196 | 130.813 | 3.617 |

All four promoted actors are switch-level voltage-survival candidates.  The
Simulink comparison logs still report grid-current or reactive-current
violations for some rows; those belong to full FRT certification and are not
claimed here.

## Failure Notes

The first AB attempt did not train because the generated manifest used an
invalid curriculum label, `topology2_ab_hvrt110_60ms`.  The corrected retry
uses the existing `topology2_ab_hvrt105_60ms` curriculum and succeeds.

Within the AB 120 ms retry, chunks 1 and 2 pass voltage-survival.  Chunks 3 and
4 fail the recovery envelope and are not promoted.

## Next Action

Run a four-row current-SAC boundary recheck using the exact promoted actor for
each case:

- `version_2/sac/experiments/stage5_t2_hvrt110_phase_recheck_20260727.csv`

This recheck is needed before adding these actors to broader boundary matrices.

## Exact Recheck

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt110_phase_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt110_phase_recheck_20260727 --controller-mode current-sac --timeout-s 1800
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt110_phase_recheck_20260727`

Summary:

- cases: `4`
- conventional voltage-survival pass: `0/4`
- SAC voltage-survival pass: `4/4`
- SAC beats conventional: `4/4`
- traditional fail / SAC pass: `4/4`
- traditional pass / SAC fail: `0/4`

| Case | Conventional score | SAC score | SAC envelope violation max pu | SAC recovery violation max pu |
|---|---:|---:|---:|---:|
| topology2 A HVRT 1.10 pu / 80 ms | 229.409 | 127.659 | 0.000 | 0.000 |
| topology2 A HVRT 1.10 pu / 120 ms | 229.289 | 127.069 | 0.000 | 0.000 |
| topology2 AB HVRT 1.10 pu / 80 ms | 228.987 | 127.803 | 0.000 | 0.000 |
| topology2 AB HVRT 1.10 pu / 120 ms | 229.116 | 127.196 | 0.000 | 0.000 |

The exact recheck confirms that the four promoted actors are reproducible
under the current voltage-survival validator.
