# Stage-4 Reduced Boundary Matrix Summary, r3

Run: `lab/results/hpt_stage4_reduced_boundary_20260727_r3`

Manifest:
`version_2/sac/experiments/stage4_reduced_boundary_manifest_20260727_r3.csv`

Compared with r2, this manifest replaces topology1 A-phase LVRT 0.95 pu rows
with the shallow-LVRT repair actor trained on 2026-07-27.

## Overall

| metric | r2 | r3 |
|---|---:|---:|
| cases | 144 | 144 |
| conventional voltage-survival pass | 48 | 48 |
| SAC voltage-survival pass | 90 | 93 |
| SAC beats conventional | 49 | 49 |
| traditional fail / SAC pass | 45 | 45 |
| traditional pass / SAC fail | 3 | 0 |

## Group Summary

| topology | family | phase | cases | conv pass | SAC pass | SAC beat | conv fail / SAC pass | conv pass / SAC fail | SAC fail |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| topology1 | HVRT | a | 12 | 12 | 12 | 3 | 0 | 0 | 0 |
| topology1 | HVRT | ab | 12 | 12 | 12 | 0 | 0 | 0 | 0 |
| topology1 | HVRT | balanced | 12 | 0 | 12 | 12 | 12 | 0 | 0 |
| topology1 | LVRT | a | 12 | 12 | 12 | 0 | 0 | 0 | 0 |
| topology1 | LVRT | ab | 12 | 12 | 12 | 0 | 0 | 0 | 0 |
| topology1 | LVRT | balanced | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | a | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | ab | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | balanced | 12 | 0 | 4 | 4 | 4 | 0 | 8 |
| topology2 | LVRT | a | 12 | 0 | 8 | 8 | 8 | 0 | 4 |
| topology2 | LVRT | ab | 12 | 0 | 10 | 10 | 10 | 0 | 2 |
| topology2 | LVRT | balanced | 12 | 0 | 5 | 5 | 5 | 0 | 7 |

## Evidence Files

- Group summary CSV:
  `paper/evidence/stage4_reduced_boundary_summary_20260727_r3.csv`
- Breakthrough rows:
  `paper/evidence/stage4_reduced_boundary_breakthrough_rows_20260727_r3.csv`
- Remaining SAC failures:
  `paper/evidence/stage4_reduced_boundary_sac_failures_20260727_r3.csv`
- Raw boundary rows:
  `lab/results/hpt_stage4_reduced_boundary_20260727_r3/boundary_raw_rows.csv`
- Paired case summary:
  `lab/results/hpt_stage4_reduced_boundary_20260727_r3/boundary_case_summary.csv`

## Interpretation

- The r3 repair closes the only reduced-matrix region where conventional dq
  passed but SAC failed.
- The added actor increases SAC voltage-survival pass count from `90/144` to
  `93/144`.
- The beat-conventional count remains `49/144`, so the repaired topology1
  A-phase shallow LVRT rows should be described as survival repairs, not
  performance improvements.
- The remaining hard regions are unchanged:
  topology1 balanced LVRT, topology2 HVRT, and wider topology2 LVRT rows.

## Current Claim Supported by r3

The Stage-4 switch-level evidence supports the following limited claim:

> Specialist SAC controllers expand the voltage-survival boundary relative to
> the tuned conventional dq baseline on a reduced 144-case matrix, while the
> remaining conventional-pass/SAC-fail holes have been eliminated in r3.

It still does not support a full FRT-certified claim, because grid current
limit and reactive current support are not part of the current promotion gate.
