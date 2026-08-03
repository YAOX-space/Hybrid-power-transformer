# Stage-5 Topology2 HVRT 1.15/1.20 Compact Recheck

Date: 2026-07-27

## Purpose

This compact recheck verifies all Stage-5 topology2 HVRT specialists at
`1.15 pu` and `1.20 pu` under the same switch-level voltage-survival validator.
The goal is to avoid relying on separate campaign-level results when making the
paper-level claim that the promoted actors beat the conventional dq baseline.

## Manifest

Manifest:
`version_2/sac/experiments/stage5_t2_hvrt115_120_compact_recheck_20260727.csv`

The manifest was generated from the promoted specialist matrix by selecting:

- topology: `topology2`
- fault family: `HVRT`
- fault magnitude: `1.150` or `1.200 pu`

Total cases: `12`.

## Command

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt115_120_compact_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt115_120_compact_recheck_20260727 --controller-mode current-sac --timeout-s 3600
```

Run directory:
`lab/results/hpt_stage5_t2_hvrt115_120_compact_recheck_20260727`

## Summary

- cases: `12`
- conventional voltage-survival pass: `0/12`
- SAC voltage-survival pass: `12/12`
- SAC beats conventional: `12/12`
- traditional fail / SAC pass: `12/12`
- traditional pass / SAC fail: `0/12`
- maximum SAC envelope violation: `0.0 pu`
- maximum SAC recovery violation: `0.000160 pu`

## Per-Case Results

| Case | Conventional score | SAC score | SAC minus conventional | Phase | Envelope max pu | Recovery max pu |
|---|---:|---:|---:|---|---:|---:|
| A HVRT 1.15 pu / 80 ms | `232.108` | `130.477` | `-101.631` | A | `0.000000` | `0.000000` |
| A HVRT 1.15 pu / 120 ms | `231.675` | `129.813` | `-101.862` | A | `0.000000` | `0.000000` |
| AB HVRT 1.15 pu / 80 ms | `232.840` | `129.976` | `-102.863` | AB | `0.000000` | `0.000000` |
| AB HVRT 1.15 pu / 120 ms | `232.143` | `129.858` | `-102.285` | AB | `0.000000` | `0.000000` |
| Balanced HVRT 1.15 pu / 80 ms | `269.359` | `131.686` | `-137.673` | balanced | `0.000000` | `0.000000` |
| Balanced HVRT 1.15 pu / 120 ms | `271.334` | `132.057` | `-139.277` | balanced | `0.000000` | `0.000000` |
| A HVRT 1.20 pu / 80 ms | `235.233` | `132.233` | `-103.000` | A | `0.000000` | `0.000160` |
| A HVRT 1.20 pu / 120 ms | `234.086` | `131.574` | `-102.512` | A | `0.000000` | `0.000000` |
| AB HVRT 1.20 pu / 80 ms | `238.115` | `132.167` | `-105.948` | AB | `0.000000` | `0.000000` |
| AB HVRT 1.20 pu / 120 ms | `236.796` | `132.060` | `-104.736` | AB | `0.000000` | `0.000000` |
| Balanced HVRT 1.20 pu / 80 ms | `271.541` | `138.748` | `-132.793` | balanced | `0.000000` | `0.000000` |
| Balanced HVRT 1.20 pu / 120 ms | `272.305` | `137.770` | `-134.534` | balanced | `0.000000` | `0.000000` |

## Interpretation

This recheck confirms that the Stage-5 topology2 HVRT promoted set is stable
under a single validator call.  The evidence supports the voltage-survival
claim for topology2 HVRT `1.15/1.20 pu`, `80/120 ms`, balanced, A-phase, and
AB-phase cases.

The result does not certify full FRT compliance.  The campaign-level actor
evaluations still report current-related full-FRT failures, especially
`grid_current_limit`; those criteria remain outside the current
voltage-survival claim.

## Next Research Step

The next voltage-survival improvement target is topology1 unbalanced score
optimization.  In that line, the actors often survive but do not yet
consistently beat the conventional dq baseline, so the objective changes from
feasibility repair to score improvement.
