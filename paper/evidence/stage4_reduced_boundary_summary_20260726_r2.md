# Stage-4 Reduced Boundary Matrix Summary

Run: `lab/results/hpt_stage4_reduced_boundary_20260726_r2`

## Overall

- Cases: 144
- Conventional voltage-survival pass: 48/144
- SAC voltage-survival pass: 90/144
- SAC beats conventional: 49/144
- Traditional fail / SAC pass: 45/144
- Traditional pass / SAC fail: 3/144

## Group Summary

| topology | family | phase | cases | conv pass | SAC pass | SAC beat | conv fail / SAC pass | conv pass / SAC fail | SAC fail |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| topology1 | HVRT | a | 12 | 12 | 12 | 3 | 0 | 0 | 0 |
| topology1 | HVRT | ab | 12 | 12 | 12 | 1 | 0 | 0 | 0 |
| topology1 | HVRT | balanced | 12 | 0 | 12 | 12 | 12 | 0 | 0 |
| topology1 | LVRT | a | 12 | 12 | 9 | 0 | 0 | 3 | 3 |
| topology1 | LVRT | ab | 12 | 12 | 12 | 0 | 0 | 0 | 0 |
| topology1 | LVRT | balanced | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | a | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | ab | 12 | 0 | 2 | 2 | 2 | 0 | 10 |
| topology2 | HVRT | balanced | 12 | 0 | 4 | 4 | 4 | 0 | 8 |
| topology2 | LVRT | a | 12 | 0 | 8 | 8 | 8 | 0 | 4 |
| topology2 | LVRT | ab | 12 | 0 | 10 | 10 | 10 | 0 | 2 |
| topology2 | LVRT | balanced | 12 | 0 | 5 | 5 | 5 | 0 | 7 |

## Traditional Pass / SAC Fail Rows

| topology | case | reason | conv score | SAC score | max envelope pu | recovery pu |
|---|---|---|---:|---:|---:|---:|
| topology1 | a_lvrt_060ms_0p950pu | timestep_voltage_envelope | 102.004 | 105.523 | 0.0108 | 0.0000 |
| topology1 | a_lvrt_080ms_0p950pu | timestep_voltage_envelope | 142.592 | 148.828 | 0.0224 | 0.0000 |
| topology1 | a_lvrt_120ms_0p950pu | timestep_voltage_envelope | 142.853 | 150.038 | 0.0224 | 0.0000 |

## Interpretation

- The reduced matrix establishes a broad voltage-survival advantage: SAC passes many scenarios where the conventional baseline fails.
- The result is still not full FRT certification because reactive current support and grid current limit are not part of the promotion gate.
- The clearest remaining repair target is topology1 A-phase LVRT at 0.95 pu, where conventional passes but SAC violates the timestep voltage envelope.
- Topology2 HVRT remains difficult at wider depth/duration ranges; current actors pass only a subset and should be expanded with dedicated HVRT specialists.

## Follow-Up: Topology1 A-LVRT 0.95 Repair Attempt

Run: `lab/results/hpt_stage4_t1_a_lvrt095_repair_20260726`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest version_2/sac/experiments/stage4_t1_a_lvrt095_repair_targets_20260726.csv --run-id hpt_stage4_t1_a_lvrt095_repair_20260726 --max-chunks 4 --chunk-steps 60 --learning-rate 4e-6 --teacher-prior-weight 100 --behavior-anchor-epochs 18 --behavior-anchor-interval-steps 30 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 30,20,8,8 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail
```

Result:

- Completed: 3/3 repair targets.
- Improved: 0/3.
- The best model for each target remained the original topology1 A-LVRT 0.90
  actor.
- All generated chunks still failed `timestep_voltage_envelope`.

Interpretation:

- Simple protected SAC fine-tuning around the 0.90 pu A-phase LVRT actor does
  not repair shallow 0.95 pu A-phase LVRT.
- The likely issue is action semantics: the actor is tuned for a deeper sag and
  over-injects at shallow sag, so the next attempt should use a shallow-LVRT
  teacher or explicit regulating-action protection rather than more local SAC
  from the same actor.

## Follow-Up: Topology1 A-LVRT 0.95 Action Sweep

Evidence:
`paper/evidence/stage4_t1_a_lvrt095_action_sweep_20260727.md`

Result:

- A constant shallow-LVRT action region was found at approximately
  `m_reg_d = 0.33` to `0.36`, with `m_reg_q = m_energy_d = m_energy_q = 0`.
- This region makes all three topology1 A-LVRT 0.95 rows pass the switch-level
  voltage-survival validator.
- The pass points still do not beat the conventional dq baseline on score, so
  this is a teacher/action-region discovery rather than a final SAC actor
  improvement.

## Follow-Up: Topology1 A-LVRT 0.95 Actor Repair

Evidence:
`paper/evidence/stage4_t1_a_lvrt095_action_sweep_20260727.md`

Recheck run:
`lab/results/hpt_stage4_t1_a_lvrt095_actor_repair_recheck_20260727`

Result:

- The new topology1 A-LVRT 0.95 actor passes all three former
  traditional-pass / SAC-fail rows under the boundary-matrix runner.
- Rechecked rows: 60 ms, 80 ms, and 120 ms.
- SAC voltage-survival pass: `3/3`.
- SAC beats conventional: `0/3`.
- This closes the reduced-matrix SAC-fail hole as a voltage-survival repair,
  but it should not be counted as a beat-conventional result.
