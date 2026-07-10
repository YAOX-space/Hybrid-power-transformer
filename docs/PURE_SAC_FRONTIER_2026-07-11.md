# Pure SAC Frontier Update - 2026-07-11

## Current Best Simulink Result

Artifact:

- `lab/results/selected_expanded_switching_pure_sac_recent_hvrt_hvrtsym_multilabel_selected_20260711_mi12.csv`

Strict selected-31 result:

- PASS: 25
- FAIL: 1
- NOT_EVALUATED: 5

The only strict FAIL is scenario `1441`:

- `HVRT / swell_3ph / SCR=2 / target=1.10`
- current pure SAC result: connect PASS, reactive NOT_EVALUATED, limit PASS, recover FAIL, survive PASS
- final voltage deviation: about `-0.1383` in the deployed SAC trace

The five NOT_EVALUATED cases are shallow/weak HVRT cases where reactive support is not evaluated by the
strict frt-v2 metric because there is no sustained reactive demand after the response delay.

## Recent-HVRT Gate Fix

The deployed pure-SAC routing now keeps HVRT-visible state during post-clear recovery by latching recent
HVRT for a short hold window. This fixed the earlier routing problem where post-clear HVRT recovery was
sent to the normal/LVRT expert after `V2p` dropped below the instantaneous HVRT threshold.

Effect:

- LVRT hard24 remains `24/24` PASS.
- Selected HVRT recovery failures improved from multiple recover FAIL cases to only scenario `1441`.
- Scenarios `1481` and `1500` moved from recover FAIL to recover PASS.

## 1441 Pure-Authority Search

Pure SAC action bounds:

- `iq in [-0.27, 0.27]`
- `mse_d, mse_q in [-0.20, 0.20]`

Diagnostic sweep:

- `lab/results/control_sweep_selected_twostage_1441_timing_frontier_20260711.csv`
- 420 two-stage candidates across fault action, post-clear action, and switching delay
- best recover metric: `0.079064909`
- required metric: `<= 0.07`
- remaining gap: about `0.00906`

Best pure-bound candidate:

- fault action: `[iq, mse_d, mse_q] = [0.10, 0.10, 0.20]`
- post action: `[iq, mse_d, mse_q] = [0.27, 0.20, 0.20]`
- post delay: `0.25 s`
- `Vdc_min = 0.81744325`

Conclusion: within the current pure SAC bounds, the timing search did not find a feasible 1441 pass.

## 1441 Authority Frontier

Diagnostic-only sweeps, not valid as final pure SAC deployment:

- `lab/results/control_sweep_selected_1441_authority_frontier_20260711.csv`
- `lab/results/control_sweep_selected_1441_high_authority_probe_20260711.csv`

Findings:

- raising post-clear `iq` from `0.27` to about `0.30` and series action beyond `0.20` moves 1441 close
  to the recovery boundary.
- examples with `iq_post=0.30`, `mse_d_post=0.30`, `mse_q_post=0.30~0.35` can make recover PASS
  (`recover_worst` around `0.068~0.070`).
- these actions exceed the current pure SAC series bound (`0.20`), and strict FRT can still be blocked by
  reactive `FAIL` or `NOT_EVALUATED`.

Conclusion: 1441 is best treated as an action-authority/spec frontier, not as a normal SAC tuning failure.

## Next Research Decisions

1. Keep final controller pure SAC with the current bounds:
   - report best strict result as `25 PASS / 1 FAIL / 5 NOT_EVALUATED`;
   - explain 1441 as an infeasible or near-infeasible weak-grid HVRT frontier under current action limits.

2. If the goal is literally all selected scenarios strict PASS:
   - the project must change one of: action bounds, HPT hardware authority, scenario/evaluation design, or the
     reactive NOT_EVALUATED handling;
   - pure SAC training alone is unlikely to solve 1441 under the current bounds.

3. The next useful SAC-only training work is not more blind tuning for 1441, but robustness:
   - retrain HVRT experts with recent-HVRT observations;
   - keep 1441 as a frontier/holdout;
   - verify full 2040 selected/expanded set for regression after the recent-HVRT gate.
