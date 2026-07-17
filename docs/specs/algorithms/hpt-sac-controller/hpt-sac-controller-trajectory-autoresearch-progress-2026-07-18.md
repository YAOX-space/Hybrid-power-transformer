# HPT Direct SAC Trajectory Autoresearch Progress - 2026-07-18

## Objective

Move from fixed-state/fixed-action validation to trajectory-level direct HPT
control:

- Simulink switch-level model receives a time-varying 4-D action trajectory.
- SAC actor action contract remains `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`.
- The first target case is `topology2 / LVRT / 0.95 pu / 80 ms`.
- The first promotion gate is voltage-survival and score improvement over
  `conventional_dq`; full GBT-style FRT remains the final gate.

## Implemented

- Added `trajectory_action` mode in `HPTSACController`.
  - `hpt_sac_policy_mode = -2`.
  - Reads `hpt_sac_trajectory.mat` containing `hpt_traj_t` and
    `hpt_traj_action`.
- Added `sac_actor_always_raw` evaluation mode.
  - Actor is active from simulation start.
  - This is the correct mode for direct SAC control experiments.
  - It avoids the old hidden assumption that the dynamic actor is enabled
    only after fault detection.
- Added trajectory tools:
  - `version_2/sac/build_hpt_action_trajectory.py`
  - `version_2/sac/validate_hpt_trajectory_switchlevel.py`
  - `version_2/simulink/collect_hpt_v2_trajectory_trace.m`
- Updated SAC interface regression to cover `policy_mode = -2`.

## Switch-Level Results

Case: `topology2 / LVRT / 0.95 pu / 80 ms`.

| Run | Mode | Voltage Survival | Score | LV Mean | LV Recovery | Vdc Min | Vdc Max | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conventional baseline | `conventional_dq` | pass | 239.88 | 199.32 | 214.54 | 683.00 | 998.54 | Full FRT fails reactive/current/envelope checks. |
| constant trajectory | `trajectory_action` | pass | 127.58 | 194.95 | 220.89 | 728.73 | 995.45 | Exact match to fixed action. |
| all-window BC actor | `sac_actor_always_raw` | fail | 129.17 | 194.94 | 220.67 | 765.18 | 1008.20 | Better than baseline, but DC-link upper bound fails. |
| DAgger1 actor | `sac_actor_always_raw` | fail | 128.23 | 195.10 | 221.91 | 665.17 | 1005.74 | Better score, still DC-link upper bound; lower Vdc margin. |
| DAgger2 actor | `sac_actor_always_raw` | fail | 128.68 | 194.98 | 220.77 | 736.75 | 1005.68 | Balanced but still DC-link upper bound. |
| DAgger3 noisy actor | `sac_actor_always_raw` | fail | 127.40 | 194.89 | 221.91 | 646.09 | 1000.97 | Nearly best score, but DC-link lower/upper margins fail. |
| DAgger4 Vdc-feedback actor | `sac_actor_always_raw` | pass | 127.85 | 194.99 | 220.86 | 716.15 | 999.56 | First direct actor to pass voltage-survival and beat conventional. |
| fault-window trajectory | `trajectory_action` | fail | 115.44 | 202.63 | 207.51 | 783.66 | 1006.65 | Best score so far, but DC-link upper bound fails. |

## What This Proves

- The new trajectory interface works: constant trajectory is exactly
  equivalent to fixed-action mode at switch level.
- Direct always-on actor control is now testable in the same switch-level
  comparison framework.
- Switch-level trajectory samples can train a 24-D/4-D actor:
  - BC error reached `~1e-8` to `~1e-7` action MSE.
  - The actor reproduces the successful control region well enough to reduce
    score from `239.88` to about `128-129`.
- DAgger-style closed-loop state collection is necessary.
  - Training only on open-loop trajectory states causes closed-loop action
    peaks and DC-link overshoot.
- Adding local observation-neighborhood BC augmentation plus a Vdc-feedback
  energy label produced the first direct actor that passes the staged
  voltage-survival gate.

## What Is Not Done

- No actor has passed full GBT-style FRT yet.
- Full GBT-style FRT is not passed.
  - Existing failures include voltage envelope, recovery, current limit, and
    reactive-current sign/support.
- The current successful actor is a topology/scenario specialist:
  `topology2 / LVRT / 0.95 pu / 80 ms`.
- This is still BC/DAgger warm-start, not final SAC reinforcement fine-tuning.

## Interpretation

The fixed/trajectory command has a real successful switch-level operating
point.  A neural actor can reproduce it only after closed-loop DAgger data are
added.  The decisive fix was to label energy action as a function of measured
Vdc, not as a fixed scalar.  This lets the actor keep Vdc inside the staged
survival window while still using the regulating bridge to recover LV voltage.

## Next Autoresearch Plan

1. Preserve DAgger4 as the current promoted voltage-survival specialist:
   `hpt_sac_actor_weights_topology2_lvrt095_dagger4.mat`.
2. Generate a small family of shaped trajectories around the successful region:
   - pre-fault target vs zero pre-fault,
   - ramp-in duration `5/10/20 ms`,
   - recovery ramp-out,
   - reg_d around `0.160-0.176`,
   - energy_d around `0.000-0.030`.
3. Run switch-level validation for those shaped trajectories and select only
   trajectories that pass voltage survival.
4. Collect switch-level traces from the passing trajectories.
5. Train actor with mixed DAgger data:
   - successful open-loop trajectory states,
   - actor-visited states,
   - explicit DC-link over/under states with corrected labels.
6. Add a behavior-regularized SAC stage only after the BC actor passes the
   voltage-survival gate.
7. Re-run switch-level comparison:
   - `conventional_dq`
   - `trajectory_action`
   - `sac_actor_always_raw`
8. Promote only if the actor passes voltage survival and beats conventional
   on score.  Full GBT reactive-current/current-limit checks remain the next
   certification phase.
