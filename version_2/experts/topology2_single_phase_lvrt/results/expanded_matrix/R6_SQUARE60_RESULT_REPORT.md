# Topology2 A-Phase Deep-LVRT r6: Fresh 10x6 Switch-Level Matrix

Date: 2026-08-03

## Scope

This experiment evaluates the unchanged current topology2 A-phase deep-LVRT
family SAC r6 actor over a fresh 10-depth by 6-duration matrix.  Every SAC cell
uses the same checkpoint.  There is no per-cell actor, runtime checkpoint
selector, or case-specific action profile.

The claim scope is switch-level voltage survival under the corrected
current-window evaluator.  This is not full FRT certification.

## Matrix and frozen artifacts

- Topology: `topology2`
- Fault family: A-phase LVRT
- Depths: `0.20 / 0.50 / 0.575 / 0.65 / 0.70 / 0.75 / 0.80 / 0.825 / 0.85 / 0.875 pu`
- Durations: `80 / 120 / 160 / 200 / 240 / 300 ms`
- Fault start: `0.080 s`
- Actor filter time constant: `0.001 s`
- Cells: `60`
- Fresh result rows: `60 strong dq + 60 r6 = 120`
- r6 checkpoint: `data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`
- r6 SHA-256: `44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5`
- topology2 model SHA-256: `5e5f4d176c439ef352191a0018ab59e8c48ed1c1fd4adcacf883766018545680`
- comparison CSV SHA-256: `b227804bbe3897b7964edb2914438188bf5d8cb1ab2aa9edd110b81669adb482`

## Aggregate result

| Metric | Strong dq | Current family SAC r6 |
| --- | ---: | ---: |
| Voltage-survival pass | `48/60` | `46/60` |
| Timestep envelope pass | `60/60` | `60/60` |
| Recovery-envelope pass | `52/60` | `60/60` |
| Active DC-link gate pass (`650-1000 V`) | `48/60` | `52/60` |
| Corrected current-window pass | `60/60` | `60/60` |
| Mean control score (lower is better) | `123.600` | `115.571` |
| Cells where r6 score is lower than dq | - | `45/60` |

The pairwise pass partition is:

- both pass: `43/60`;
- dq fails and r6 passes: `3/60`;
- dq passes and r6 fails: `5/60`;
- both fail: `9/60`.

## Local boundary expansion

r6 passes three cells where strong dq fails:

| Depth | Duration | dq failure | dq Vdc min | r6 Vdc min |
| ---: | ---: | --- | ---: | ---: |
| `0.500 pu` | `200 ms` | DC-link lower bound | `548.91 V` | `665.65 V` |
| `0.500 pu` | `240 ms` | DC-link lower bound | `526.87 V` | `659.23 V` |
| `0.575 pu` | `300 ms` | DC link and recovery | `434.91 V` | `661.49 V` |

These are valid local boundary-expansion cells, but the complete 60-cell pass
area of r6 is not larger than dq because r6 loses five cells that dq passes.
All five losses are caused by the active DC-link lower bound in the
`0.65-0.70 pu`, `160-240 ms` region.

## Failure audit

r6 has 14 failed cells:

- six `0.20 pu` cells fail the timestep fault-voltage band while retaining
  Vdc above the active floor;
- eight cells fail the active DC-link lower bound;
- no r6 cell fails the recovery envelope or corrected current-window gate.

The duration pattern is non-monotonic in several rows.  For example,
`0.575 pu / 300 ms` passes while `0.575 pu / 200-240 ms` fails.  This matrix
therefore describes closed-loop controller coverage, not a strictly monotonic
plant withstand curve.  The actor observes causal fault and recovery timing,
and its state-feedback trajectory can move the DC-link minimum differently as
the clearing instant changes.  These cells must not be interpolated into a
monotonic certified boundary.

## Interpretation

The fresh matrix supports three precise conclusions:

1. r6 substantially improves control quality: its mean score is lower and it
   beats dq by score in `45/60` cells.
2. r6 improves DC-link survival in aggregate (`52/60` versus `48/60`) and
   creates three dq-fail/r6-pass cells.
3. r6 does not yet expand the total 10x6 voltage-survival pass area, because
   its `46/60` total is below dq's `48/60`.

The previously accepted targeted 3x3 result (`8/9` r6 versus `4/9` dq) remains
valid for its own `0.500/0.600/0.625 pu x 160/200/240 ms` family matrix.  The
larger result shows that this advantage does not transfer uniformly to the
entire historical 10x6 grid.

## Evidence

- Raw paired rows: `family_specialist_comparison_rows.csv`
- Pairwise audit: `boundary_summary/t2_a_lvrt_r6_square60_pairwise_audit.csv`
- Pass matrix: `boundary_summary/t2_a_lvrt_r6_square60_currentwindow_pass_matrix.png`
- Shared-scale score matrix: `boundary_summary/t2_a_lvrt_r6_square60_currentwindow_score_matrix.png`
- Per-controller cell tables and summary: `boundary_summary/`

