# Simulink Pass-Set Check: Current Pure SAC vs Traditional Baselines

Date: 2026-07-12

## Scope

This is a real switching-level Simulink check on the current selected-expanded scenario set:

- Scenarios: `unique([217:240 1441 1456 1481 1500 1873 1875 1884])`, 31 total.
- Metrics: `frt-v2`.
- SAC controller: current pure SAC, internal `mi=12`.
- Traditional baselines: fixed-law `mi=7` and explicit-MPC `mi=8`.

This is not a full 2040 Simulink certification. It answers the current selected real-Simulink pass-set question.

## Result Files

- `lab/results/selected_expanded_switching_gate1060_puresac_selected_20260711_mi12.csv`
- `lab/results/selected_expanded_switching_passset_trad_fixed_selected_20260712_mi7.csv`
- `lab/results/selected_expanded_switching_passset_trad_mpc_selected_20260712_mi8.csv`
- `lab/results/simulink_passset_selected_current_pure_sac_vs_traditional_20260712.csv`
- `lab/results/simulink_passset_selected_current_pure_sac_vs_traditional_20260712.json`

## Strict Pass-Set

Strict pass means `frt == True`. `None` / `NOT_EVALUATED` is not counted as pass.

| category | count |
|---|---:|
| SAC-only | 0 |
| traditional-only | 0 |
| both-pass | 25 |
| both-fail | 6 |

Conclusion: on this selected real-Simulink set, every scenario strictly passed by the traditional union
(`mi=7` or `mi=8`) is also strictly passed by current pure SAC.

## Proxy Pass-Set

Proxy pass means `frt == True or frt == None`, matching the earlier ODE-style handling of shallow-boundary
`NOT_EVALUATED` cases.

| category | count |
|---|---:|
| SAC-only | 4 |
| traditional-only | 0 |
| both-pass | 26 |
| both-fail | 1 |

The four SAC-only proxy cases are shallow HVRT:

| sid | fault | SCR | target | SAC | fixed | MPC |
|---:|---|---:|---:|---|---|---|
| 1456 | `swell_3ph` | 3 | 1.10 | None | False | False |
| 1500 | `swell_3ph` | 15 | 1.10 | None | False | False |
| 1873 | `swell_1ph` | 3 | 1.20 | None | False | False |
| 1875 | `swell_1ph` | 3 | 1.20 | None | False | False |

## Remaining Non-Strict-Pass Cases

The strict both-fail set is concentrated in shallow HVRT:

| sid | fault | SCR | target | SAC | fixed | MPC | SAC reactive | SAC recover |
|---:|---|---:|---:|---|---|---|---|---|
| 1441 | `swell_3ph` | 2 | 1.10 | False | False | False | NOT_EVALUATED | FAIL |
| 1456 | `swell_3ph` | 3 | 1.10 | None | False | False | NOT_EVALUATED | PASS |
| 1481 | `swell_3ph` | 10 | 1.10 | None | None | None | NOT_EVALUATED | PASS |
| 1500 | `swell_3ph` | 15 | 1.10 | None | False | False | NOT_EVALUATED | PASS |
| 1873 | `swell_1ph` | 3 | 1.20 | None | False | False | NOT_EVALUATED | PASS |
| 1875 | `swell_1ph` | 3 | 1.20 | None | False | False | NOT_EVALUATED | PASS |

## Interpretation

For the current selected real-Simulink evidence, the answer is yes: SAC covers the traditional strict pass-set.
The limitation is scope. A full claim for all 2040 expanded scenarios would require a much larger Simulink
batch using the same SAC/fixed/MPC union comparison.
