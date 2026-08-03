# Stage-3 Switch-Level Voltage-Survival Summary

Source CSV: `E:\research_space\Hybrid-power-transformer\lab\results\hpt_promoted_recheck_20260726_round1\boundary_case_summary.csv`

## Counts

- Cases: 11
- Conventional voltage-survival pass: 2/11
- SAC voltage-survival pass: 11/11
- SAC beats conventional by score: 9/11
- Traditional fail / SAC pass: 9/11

## Per-Case Table

| case | fault | phase | conv pass | SAC pass | SAC beats | conv score | SAC score | label |
|---|---|---|---|---|---|---|---|---|
| topology1:a_lvrt090_60ms | LVRT 0.9 pu/0.06s | a | True | True | False | 102.465 | 105.127 | survival_only_not_quality_win |
| topology1:ab_lvrt090_60ms | LVRT 0.9 pu/0.06s | ab | True | True | False | 102.888 | 106.015 | survival_only_not_quality_win |
| topology1:balanced_hvrt110_60ms | HVRT 1.1 pu/0.06s | balanced | False | True | True | 116.834 | 105.383 | traditional_fail_sac_pass |
| topology1:balanced_lvrt090_60ms | LVRT 0.9 pu/0.06s | balanced | False | True | True | 122.356 | 104.012 | traditional_fail_sac_pass |
| topology2:a_hvrt105_60ms | HVRT 1.05 pu/0.06s | a | False | True | True | 145.478 | 125.808 | traditional_fail_sac_pass |
| topology2:a_hvrt110_60ms | HVRT 1.1 pu/0.06s | a | False | True | True | 146.037 | 127.412 | traditional_fail_sac_pass |
| topology2:a_lvrt090_60ms | LVRT 0.9 pu/0.06s | a | False | True | True | 159.385 | 126.262 | traditional_fail_sac_pass |
| topology2:ab_hvrt105_60ms | HVRT 1.05 pu/0.06s | ab | False | True | True | 144.793 | 125.283 | traditional_fail_sac_pass |
| topology2:ab_lvrt090_60ms | LVRT 0.9 pu/0.06s | ab | False | True | True | 163.332 | 132.148 | traditional_fail_sac_pass |
| topology2:balanced_hvrt110_60ms | HVRT 1.1 pu/0.06s | balanced | False | True | True | 188.705 | 114.067 | traditional_fail_sac_pass |
| topology2:balanced_lvrt090_60ms | LVRT 0.9 pu/0.06s | balanced | False | True | True | 264.260 | 113.665 | traditional_fail_sac_pass |

## Current Limitations

- These rows are switch-level voltage-survival evidence, not full FRT certification.
- Grid current limit, reactive current support, and full GBT recovery gates are intentionally deferred.
- Weak rows that survive but do not beat conventional: topology1:a_lvrt090_60ms, topology1:ab_lvrt090_60ms
