# Stage-4 Topology1 A-LVRT 0.95 Action Sweep

Run directory:
`lab/results/hpt_stage4_t1_a_lvrt095_action_sweep_20260727`

Raw summary:
`lab/results/hpt_stage4_t1_a_lvrt095_action_sweep_20260727/action_sweep_summary.csv`

## Purpose

The Stage-4 reduced boundary matrix found three traditional-pass / SAC-fail
rows:

- topology1 A-phase LVRT 0.95 pu / 60 ms
- topology1 A-phase LVRT 0.95 pu / 80 ms
- topology1 A-phase LVRT 0.95 pu / 120 ms

The prior protected SAC repair did not fix these rows because the existing
0.90 pu A-LVRT actor remained too aggressive for the shallow 0.95 pu sag. This
follow-up sweep tested whether a shallow-LVRT regulating-action region exists
before attempting another actor-training run.

## Setup

- Plant: switch-level topology1 model.
- Fault: A-phase LVRT, 0.95 pu.
- Controller mode: trajectory/fixed-action injection through the same
  switch-level comparison validator used by Stage-4.
- Action vector: `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`.
- Sweep variable: `m_reg_d`.
- Fixed values: `m_reg_q = 0`, `m_energy_d = 0`, `m_energy_q = 0`.

## Results

### 60 ms

| m_reg_d | pass | score | conventional score | envelope violation pu | recovery violation pu | fail reason |
|---:|---|---:|---:|---:|---:|---|
| 0.00 | no | 157.568 | 102.004 | 0.2024 | 0.1416 | fault LV band; voltage envelope; recovery envelope |
| 0.08 | no | 141.018 | 102.004 | 0.1513 | 0.0859 | fault LV band; voltage envelope; recovery envelope |
| 0.16 | no | 128.604 | 102.004 | 0.1046 | 0.0464 | fault LV band; voltage envelope; recovery envelope |
| 0.24 | no | 111.258 | 102.004 | 0.0516 | 0.0000 | voltage envelope |
| 0.32 | no | 102.946 | 102.004 | 0.0017 | 0.0000 | voltage envelope |
| 0.33 | yes | 103.034 | 102.004 | 0.0000 | 0.0000 | none |
| 0.34 | yes | 103.162 | 102.004 | 0.0000 | 0.0000 | none |
| 0.36 | yes | 103.063 | 102.004 | 0.0000 | 0.0000 | none |
| 0.38 | yes | 104.419 | 102.004 | 0.0000 | 0.0000 | none |

### 80 ms

| m_reg_d | pass | score | conventional score | envelope violation pu | recovery violation pu | fail reason |
|---:|---|---:|---:|---:|---:|---|
| 0.32 | no | 143.554 | 142.592 | 0.0017 | 0.0000 | voltage envelope |
| 0.33 | yes | 143.379 | 142.592 | 0.0000 | 0.0000 | none |
| 0.34 | yes | 143.335 | 142.592 | 0.0000 | 0.0000 | none |
| 0.36 | yes | 142.938 | 142.592 | 0.0000 | 0.0000 | none |

### 120 ms

| m_reg_d | pass | score | conventional score | envelope violation pu | recovery violation pu | fail reason |
|---:|---|---:|---:|---:|---:|---|
| 0.32 | no | 144.567 | 142.853 | 0.0017 | 0.0000 | voltage envelope |
| 0.33 | yes | 144.714 | 142.853 | 0.0000 | 0.0000 | none |
| 0.34 | yes | 144.504 | 142.853 | 0.0000 | 0.0000 | none |
| 0.36 | yes | 144.395 | 142.853 | 0.0000 | 0.0000 | none |

## Interpretation

- The shallow A-phase LVRT rows are physically controllable at switch level.
- A constant shallow-LVRT regulating action around `m_reg_d = 0.33` to `0.36`
  removes the timestep voltage-envelope violation for all three durations.
- This is not yet a SAC actor result. It is a teacher/action-region discovery.
- The pass points still do not beat the tuned conventional baseline on score.
  They close the survival failure but do not yet provide a quality improvement.

## Next Step

Train a topology1 A-LVRT 0.95 trajectory/state-feedback specialist from this
shallow action region, then recheck the three repaired rows and the reduced
boundary matrix under the same validator. The next actor should treat
`m_reg_d = 0.33` to `0.36` as a shallow-sag support region rather than
continuing local fine-tuning from the deeper 0.90 pu actor alone.

## Follow-Up Actor Training

Run:
`lab/results/hpt_stage4_t1_a_lvrt095_80ms_traj_actor_20260727`

Command summary:

- Topology: `topology1`
- Fault: A-phase LVRT `0.95 pu`
- Training duration: `80 ms`
- Teacher trajectory: constant `[0.36, 0, 0, 0]`
- Training: BC followed by two DAgger iterations
- Best selected actor:
  `data/models/hpt_stage4_t1_a_lvrt095_80ms_traj_actor_20260727_bc0.zip`

### Actor Result at 80 ms

| stage | voltage pass | score | conventional score | envelope pu | recovery pu | full FRT |
|---|---|---:|---:|---:|---:|---|
| BC0 | yes | 143.052 | 142.592 | 0.0000 | 0.0000 | no |
| DAgger1 | yes | 143.279 | 142.592 | 0.0000 | 0.0000 | no |
| DAgger2 | yes | 143.177 | 142.592 | 0.0000 | 0.0000 | no |

The BC0 actor was selected because it had the lowest score among the three
voltage-survival actors.

### Cross-Check at 60 ms and 120 ms

CSV:
`lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_all_hpt_stage4_t1_a_lvrt095_80ms_actor_crosscheck_60_120_20260727_20260727_022613.csv`

| case | controller | voltage pass | score | LV mean V | recovery mean V | envelope pu | recovery pu | full FRT reason |
|---|---|---|---:|---:|---:|---:|---:|---|
| A-LVRT 0.95 / 60 ms | conventional | yes | 102.004 | 201.924 | 204.083 | 0.0000 | 0.0000 | grid current limit; no sustained reactive demand |
| A-LVRT 0.95 / 60 ms | new actor | yes | 102.951 | 200.935 | 210.934 | 0.0000 | 0.0000 | grid current limit; no sustained reactive demand |
| A-LVRT 0.95 / 120 ms | conventional | yes | 142.853 | 202.747 | 203.932 | 0.0000 | 0.0000 | grid current limit; reactive wrong sign |
| A-LVRT 0.95 / 120 ms | new actor | yes | 144.279 | 202.434 | 213.813 | 0.0000 | 0.0000 | grid current limit; reactive wrong sign |

### Updated Interpretation

- The new actor removes the three Stage-4 reduced-boundary SAC failure holes
  for topology1 A-phase LVRT 0.95 pu at 60, 80, and 120 ms.
- The improvement is feasibility/survival, not score dominance. Conventional dq
  still has a lower score on these shallow A-LVRT rows.
- This actor should be promoted only as a voltage-survival repair specialist,
  not as evidence that SAC beats conventional on shallow topology1 A-LVRT.

## Reduced-Matrix Parameter Recheck

Manifest:
`version_2/sac/experiments/stage4_t1_a_lvrt095_actor_repair_recheck_20260727.csv`

Run:
`lab/results/hpt_stage4_t1_a_lvrt095_actor_repair_recheck_20260727`

This run uses the boundary-matrix runner and the reduced-matrix style fault
settings, including `fault_settle_s = 0.020`.

| case | conventional pass | actor pass | actor beats conventional | conventional score | actor score | envelope pu | recovery pu |
|---|---|---|---|---:|---:|---:|---:|
| A-LVRT 0.95 / 60 ms | yes | yes | no | 102.004 | 103.048 | 0.0000 | 0.0000 |
| A-LVRT 0.95 / 80 ms | yes | yes | no | 142.592 | 143.184 | 0.0000 | 0.0000 |
| A-LVRT 0.95 / 120 ms | yes | yes | no | 142.853 | 144.161 | 0.0000 | 0.0000 |

The recheck confirms that the original traditional-pass / SAC-fail rows are
closed under the same boundary-matrix validator path. The repair remains
survival-only because conventional dq still obtains a lower control score.
