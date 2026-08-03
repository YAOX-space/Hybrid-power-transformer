# Topology2 A-Phase Deep-LVRT Family SAC Boundary Expansion

## Claim under test

One state-feedback SAC actor must cover the full `3 x 3` depth-duration
matrix. No case-specific actor, runtime selector, or per-cell checkpoint is
used. Final evidence is produced by the switch-level Simulink model and the
same voltage-survival validator used for the strong dq baseline.

## Matrix

- Topology: `topology2`
- Fault family: A-phase LVRT
- Fault start: `0.080 s`
- Fault depths: `0.500 / 0.600 / 0.625 pu`
- Fault durations: `160 / 200 / 240 ms`
- Actor checkpoint:
  `data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`
- Actor SHA-256:
  `44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5`

## Switch-level result

| Fault pu | Duration | Strong dq | SAC r6 | Boundary change |
| ---: | ---: | ---: | ---: | --- |
| 0.500 | 160 ms | pass | pass | retained |
| 0.500 | 200 ms | fail | pass | expanded |
| 0.500 | 240 ms | fail | pass | expanded |
| 0.600 | 160 ms | pass | pass | retained |
| 0.600 | 200 ms | pass | pass | retained |
| 0.600 | 240 ms | pass | pass | retained |
| 0.625 | 160 ms | fail | pass | expanded |
| 0.625 | 200 ms | fail | pass | expanded |
| 0.625 | 240 ms | fail | fail | non-monotonic DC-link failure |

- Strong dq voltage-survival pass: `4 / 9`.
- SAC r6 voltage-survival pass: `8 / 9`.
- DQ-fail/SAC-pass cells: `4 / 9`.
- SAC score lower than strong dq: `9 / 9`.
- SAC envelope pass: `9 / 9`.
- SAC recovery pass: `9 / 9`.
- The looser diagnostic `gbt_vdc_survive_pass` is `9 / 9`; however, the active
  voltage-survival validator uses a `650 V` DC-link floor. Therefore the final
  cell is correctly reported as `dc_link_bounds` at `626.49 V`.
- SAC grid-current pass: `9 / 9`; maximum evaluated peak is `1.314 pu`.

The final failed cell, `0.625 pu / 240 ms`, is retained as a failure and is
not excluded from the pass count. Because the deeper `0.500 pu / 240 ms` case
passes, this cell must not be interpreted as a monotonic depth-duration outer
boundary. It is an isolated non-monotonic failure under the active DC-link
gate and motivates trajectory-level DC-link alignment work.

## Why the previous actor failed

The earlier r5 actor passed `4 / 9`, equal to strong dq, but its fault-window
`m_reg_d` remained near `0.045`. Switch-level joint-action sweeps showed a
feasible band near `m_reg_d = 0.06` and `m_energy_q = 0.60`. A separate
energy-d zero-neighborhood sweep passed `12 / 12`, showing that the lost
`0.600 pu` cells were dominated by insufficient regulation command rather
than the sign of a small energy-d command.

The SAC support loss also contained an action-space contract bug: physical
dataset actions were compared directly with the actor's normalized tanh
outputs. After scaling physical targets to `[-1, 1]`, r6 moved into the
switch-supported action region and recovered all three `0.600 pu` cells.

## Training and calibration evidence

- Reward trace:
  `lab/results/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803/sac_training_reward_trace.csv`
- Actor/critic/support diagnostics:
  `lab/results/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803/sac_training_diagnostics_trace.csv`
- Convergence figure:
  `lab/results/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803/sac_reward_and_switch_score_convergence.png`
- Joint-action switch sweep:
  `lab/results/hpt_t2_a_lvrt_joint_support_switch_20260803_r1/switch_validation_results.csv`
- Energy-d zero-neighborhood sweep:
  `lab/results/hpt_t2_a_lvrt_energyd_zero_neighborhood_switch_20260803_r1/switch_validation_results.csv`
- Family calibration:
  `lab/results/hpt_t2_a_lvrt_deep_family_proxy_matrix_20260803/hpt_proxy_calibration_t2_a_deep_lvrt_joint_support_r2.json`
- Calibration SHA-256:
  `94f225d8937f3795b2dcdd93ea02f63fdcd603597263d6e4217bf02bb858a8e3`
- Reward-alignment check: `rho=1.0`, `tau=1.0`, top-3 overlap `3/3` on the
  18-row measured joint-support sweep.

## Scope

This result proves a switch-level **voltage-survival boundary expansion** for
one topology2 A-phase deep-LVRT family. It does not claim full grid-code FRT
certification or transfer to the other eleven fault families.
