# Stage-4 Boundary Smoke Evidence

Run: `lab/results/hpt_stage4_boundary_smoke_20260726`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage4_boundary_smoke_manifest_20260726.csv --run-id hpt_stage4_boundary_smoke_20260726 --controller-mode current-sac --timeout-s 2400
```

## Summary

- Cases: 12
- Conventional voltage-survival pass: 4/12
- SAC voltage-survival pass: 11/12
- SAC beats conventional: 7/12
- Traditional fail / SAC pass: 7/12
- Traditional pass / SAC fail: 0/12

## Interpretation

The promoted Stage-4 actor manifest is executable and mostly consistent with
the Stage-3 evidence.  The smoke run also exposes the next high-priority gap:
`topology2/ab_hvrt_060ms_1p100pu` fails voltage-survival with
`timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope`.

The topology1 unbalanced rows remain survival-only quality gaps: SAC survives,
but the conventional baseline has a lower score for A/AB LVRT and A/AB HVRT at
60 ms.  These rows should not be claimed as beat-conventional.

## Weak Or Failed Rows

| topology | case | conventional pass | SAC pass | SAC score delta | reason |
|---|---|---:|---:|---:|---|
| topology1 | A-HVRT 1.10 / 60 ms | yes | yes | +1.118 | survival-only; conventional lower score |
| topology1 | A-LVRT 0.90 / 60 ms | yes | yes | +2.661 | survival-only; conventional lower score |
| topology1 | AB-HVRT 1.10 / 60 ms | yes | yes | +1.055 | survival-only; conventional lower score |
| topology1 | AB-LVRT 0.90 / 60 ms | yes | yes | +3.127 | survival-only; conventional lower score |
| topology2 | AB-HVRT 1.10 / 60 ms | no | no | -10.779 | SAC lowers score but fails fault LV, DC-link, and recovery gates |

## Next Action

Do not launch the full 144-case reduced boundary until the topology2 AB-HVRT
1.10 failure is either fixed or explicitly marked as a diagnostic gap.  The next
experiment should target topology2 AB-HVRT 1.10 with stronger energy-branch
anchoring and recovery-aware protected SAC.

## Follow-Up Repair

Run: `lab/results/hpt_stage4_t2_ab_hvrt110_repair_20260726`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage4_t2_ab_hvrt110_target_20260726.csv --run-id hpt_stage4_t2_ab_hvrt110_repair_20260726 --max-chunks 3 --chunk-steps 60 --learning-rate 5e-6 --teacher-prior-weight 90 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 30 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.002 --behavior-anchor-lr 5e-6 --behavior-anchor-action-weights 8,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

Result:

- Initial model: `data/models/hpt_trustregion_promotion_20260726_round1_11_topology2_ab_hvrt105_60ms_new_chunk01.zip`
- Best repaired model: `data/models/hpt_stage4_t2_ab_hvrt110_repair_20260726_01_topology2_ab_hvrt110_60ms_stage4_chunk03.zip`
- Conventional pass: no
- Repaired SAC pass: yes
- Best SAC score: `128.060512246615`
- Smoke fallback SAC score: `135.190765145462`
- Conventional score: `145.970008470231`
- Timestep voltage envelope violation: `0.0`
- Timestep recovery violation: `0.0`
- Fault LV band violation: `0.0`
- DC link range: `762.52 V` to `827.94 V`

This repaired actor was added to
`version_2/sac/experiments/stage4_promoted_specialists_20260726.csv`, and the
Stage-4 boundary manifests were regenerated as `_r2` files.

## R2 Smoke Recheck

Run: `lab/results/hpt_stage4_boundary_smoke_20260726_r2`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage4_boundary_smoke_manifest_20260726_r2.csv --run-id hpt_stage4_boundary_smoke_20260726_r2 --controller-mode current-sac --timeout-s 2400
```

Summary:

- Cases: 12
- Conventional voltage-survival pass: 4/12
- SAC voltage-survival pass: 12/12
- SAC beats conventional: 8/12
- Traditional fail / SAC pass: 8/12
- Traditional pass / SAC fail: 0/12

Remaining non-beat rows:

| topology | case | conventional score | SAC score | delta |
|---|---|---:|---:|---:|
| topology1 | A-HVRT 1.10 / 60 ms | 105.229 | 106.347 | +1.118 |
| topology1 | A-LVRT 0.90 / 60 ms | 102.465 | 105.127 | +2.661 |
| topology1 | AB-HVRT 1.10 / 60 ms | 104.983 | 106.038 | +1.055 |
| topology1 | AB-LVRT 0.90 / 60 ms | 102.888 | 106.015 | +3.127 |

Decision:

- The r2 promoted set is valid for launching the reduced 144-case boundary scan.
- The only smoke-level quality gap is topology1 unbalanced A/AB LVRT/HVRT.
