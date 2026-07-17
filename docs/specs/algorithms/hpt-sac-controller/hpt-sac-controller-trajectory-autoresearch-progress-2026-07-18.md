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

## What Is Not Done

- No actor has passed the voltage-survival gate yet in `sac_actor_always_raw`.
  The current failure is narrow and DC-link related:
  - `Vdc max` is around `1005-1008 V`, while the current gate is `<=1000 V`.
- Full GBT-style FRT is not passed.
  - Existing failures include voltage envelope, recovery, current limit, and
    reactive-current sign/support.
- This is still BC/DAgger warm-start, not final SAC improvement over a strong
  traditional controller.

## Interpretation

The fixed/trajectory command has a real successful switch-level operating
point, but the neural actor introduces small closed-loop deviations in visited
states.  Those deviations are enough to push the DC link above the current
upper gate.  The next work should not blindly train longer SAC on the proxy.
It should improve the trajectory dataset and actor deployment loss around
DC-link dynamics.

## Next Autoresearch Plan

1. Generate a small family of shaped trajectories around the successful region:
   - pre-fault target vs zero pre-fault,
   - ramp-in duration `5/10/20 ms`,
   - recovery ramp-out,
   - reg_d around `0.160-0.176`,
   - energy_d around `0.000-0.030`.
2. Run switch-level validation for those shaped trajectories and select only
   trajectories that pass voltage survival.
3. Collect switch-level traces from the passing trajectories.
4. Train actor with mixed DAgger data:
   - successful open-loop trajectory states,
   - actor-visited states,
   - explicit DC-link over/under states with corrected labels.
5. Add a behavior-regularized SAC stage only after the BC actor passes the
   voltage-survival gate.
6. Re-run switch-level comparison:
   - `conventional_dq`
   - `trajectory_action`
   - `sac_actor_always_raw`
7. Promote only if the actor passes voltage survival and beats conventional
   on score.  Full GBT reactive-current/current-limit checks remain the next
   certification phase.
