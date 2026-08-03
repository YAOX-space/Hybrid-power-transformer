# Overnight Constrained Projection Results - 2026-07-09

## Objective

Run non-promoting constrained SAC/fallback experiments on the aligned ODE failure cases, maximize pass
counts, and keep only candidates that do not regress the broad ODE proxy sets.

## Current Best Candidate

Result directory:

- `lab/results/overnight_constrained_projection_20260709_100552`

Winner:

- `lvrt_fallback_proj_0`

Full ODE evaluation:

| Set | Result |
| --- | --- |
| hard24 | 24 / 24 |
| hard92 | 89 / 92 |
| switching_fail_ode | 16 / 17 |
| original320 partial proxy | 86.2 |
| expanded2040 partial proxy | 84.0 |
| expanded2040 Vdc-survive proxy | 92.5 |

The candidate is non-regressing against the current promoted residual SAC baseline. After the
2026-07-09 ODE realignment below, the remaining ODE-visible switching-failure case is scenario 1441
(`HVRT`, `swell_3ph`, `SCR=2`, `target=1.10`), failing `recover`.

## What Changed

`src/hpt_frt/device/overnight_constrained_projection.py` now includes:

- LVRT hard24 projection from the aligned ODE fine sweep.
- A narrow high-Vdc recovery lift (`lvrt_recover_proj_*`) for weak HVRT recover-low cases.
- A high-authority fallback gate (`lvrt_fallback_proj_*`) for the weak-HVRT recovery frontier.
- Two-stage evaluation: quick scan first, full 320/2040 checks only for the top ranked candidates.
- No automatic model promotion or SAC weight overwrite.

## Fallback Gate

`lvrt_fallback_proj_0` uses a deliberately narrow near-normal recovery gate:

- `0.90 <= V+ < 0.97`
- `V2n <= 0.025`
- `0.75 <= Vdc <= 1.0`
- total fallback command `[iq, mse_d, mse_q] = [0.27, 0.12, 0.0]`

This is intentionally not represented as a SAC residual action. It returns an unclipped residual and
lets the plant/controller total-command clamps apply. Treat it as a fallback controller experiment
that needs Simulink implementation and validation before any deployment claim.

## Scenario 1441 Evidence

Aligned ODE-vs-Simulink evidence:

- `lab/results/selected_preserve_strong_ode_vs_sim_after_xr_align_v2.json`
- Simulink: `sim_frt=False`, `sim_final_signed=-0.142189`, `sim_vdc_min=0.835735`
- ODE: `ode_pass=false`, `ode_fails=recover`, `ode_final_signed=-0.124446`, `ode_vdc_min=0.887525`

Control-authority probes before the final ODE realignment:

- Even using residual upper bounds in the low-voltage recovery region (`iq_res=+0.10`,
  `md_res=+0.06`), the best observed `recover.worst` stayed near 0.101.
- This is still outside the frt-v2 recovery band of 0.07.
- Vdc dropped near 0.785 under the strongest probe, so further boost spends the remaining DC margin.
- A high-authority total-command counterfactual initially appeared to pass 1441 in the ODE:
  `iq_total=0.27`, `mse_d_total=0.12`, `recover.worst ~= 0.0689`, `Vdc_min ~= 0.7504`.
- Simulink did not confirm this. The ODE was still too optimistic for weak-SCR shallow three-phase
  HVRT post-clear voltage recovery.

## Interpretation

Scenario 1441 is not currently an ODE-blind case. Simulink and the re-aligned ODE both fail in the
same direction: weak-grid HVRT post-clear under-recovery. The current SAC residual action bounds are
not sufficient, and the earlier high-authority ODE pass was a surrogate-model false positive.

## Recommended Next Step

Do not claim final success until the fallback is implemented in the switching/Simulink controller and
spotchecked. The next experiment should be:

1. Implement an equivalent weak-HVRT recovery fallback in the Simulink HLC path.
2. Run Simulink spotcheck on hard24, hard92 selected cases, and especially scenario 1441.
3. If Simulink confirms the ODE result, then consider exporting/documenting this as a fallback
   controller rather than as a pure SAC weight update.

## Simulink Follow-Up - 2026-07-09

Implemented guarded experimental Simulink modes `mi20..mi70` in `lab/simulink/build_hpt_frt_full.m`.
These modes keep the guarded residual path (`mi19`-style `guard_en=2`) and add HVRT-labeled recovery
fallback sweeps. The selected/full320 switching scripts now set `/fclass` from the scenario metadata
and load residual weights for these experiment modes.

Key spotcheck artifacts:

- `lab/results/selected_expanded_switching_fallback_best_mi63_hard24_hvrt4_mi63.json`
- `lab/results/selected_expanded_switching_fallback_1441_mq_mi63_mi63.json`
- `lab/results/selected_expanded_switching_fallback_direction_sweep_mi23_mi23.json`

Main result:

- `mi63` is the best observed 1441 Simulink recovery candidate so far.
- Scenario 1441 improves from about `recover.worst=0.143` to `0.0962`, with `Vdc_min=0.7909`, but
  still fails the frt-v2 recovery band (`0.07`).
- `mi23` can make scenarios 1456, 1873, and 1875 recover-pass in the small HVRT spotcheck, but it does
  not fix 1441.
- Full selected mi63 spotcheck on hard24 + 1441/1456/1873/1875 gives 12/28 strict `frt=True`; hard24
  behavior is essentially guarded-mi19-level, but the remaining LVRT recovery-high and HVRT recovery-low
  cases still fail.

Interpretation update:

- The ODE high-authority fallback result does not transfer directly to the switching model.
- Scenario 1441 is Simulink-visible but not closed by the current actuator/fallback search. Even
  high-authority `iq/mse_d/mse_q` sweeps stayed outside the 0.07 recovery band.
- The next credible path is no longer just SAC residual tuning. It needs either:
  1. a better Simulink-aligned ODE model for the weak-SCR HVRT post-clear voltage floor,
  2. a higher-level voltage restoration module beyond the current residual interface, or
  3. revisiting whether SCR=2, target=1.10 HVRT scenario 1441 is a feasible pass case under the current
     plant and frt-v2 recovery window.

## ODE Re-Alignment - 2026-07-09

After the Simulink sweep showed that `lvrt_fallback_proj_0` did not transfer, the ODE was tightened
for the weak-SCR shallow three-phase HVRT recovery case:

- Added `HVRT_SHALLOW_SCR2_EXTRA_UNDER = 0.040` in `src/hpt_frt/device/frt_env.py`.
- The term is narrow: `category=HVRT`, `fault_type=swell_3ph`, low SCR around 2, and target near
  `1.10`.
- Added regression coverage in `tests/test_env_envelope_unification.py` so the ODE keeps 1441-like
  recovery failure visible.

Validation:

- Python regression: `20 passed`.
- ODE probe for scenario 1441 with `[iq,mse_d,mse_q]=[0.27,0.12,0]` now gives
  `recover=FAIL`, `recover.worst=0.1089`, `Vdc_min=0.7504`.
- Re-run constrained projection:
  `lab/results/overnight_constrained_projection_20260709_100552`.
- Latest best candidate: `lvrt_fallback_proj_0`, with hard24 `24/24`, hard92 `89/92`,
  switching_fail_ode `16/17`; remaining failure is scenario 1441 (`recover`).

## Simulink Frontier Sweep - 2026-07-09 Night

Added guarded experimental HLC sweep modes through `mi208` in `lab/simulink/build_hpt_frt_full.m`.
These are not promoted modes; they are Simulink alignment probes for scenario 1441.

Best single-scenario 1441 frontier found:

- Mode: `mi181`
- Scenario: `1441` (`HVRT`, `swell_3ph`, `SCR=2`, `target=1.10`)
- Artifact: `lab/results/selected_expanded_switching_postclear_steady_frontier_1441_mi181_mi181.json`
- Criteria: connect `PASS`, reactive `NOT_EVALUATED`, limit `PASS`, survive `PASS`, recover `FAIL`
- `recover.worst = 0.072628`
- `V1_final_min = 0.927372`, `V1_final_mean = 0.931928`
- `Vdc_min = 0.771892`

This is the best non-survive-regressing single-case result so far, but it still misses the frt-v2
recovery band by about `0.00263 pu`. The recovery worst occurs at the final sample, so the remaining
problem is a terminal positive-sequence voltage floor/ripple issue, not an early post-clear transient.

Important non-promotion evidence:

- Spotcheck artifact:
  `lab/results/selected_expanded_switching_frontier_mi181_hard24_hvrt4_mi181.json`
- Spotcheck set: hard24 (`217:240`) plus `1441`, `1456`, `1873`, `1875`.
- `mi181` improves 1441 but regresses hard24:
  - `225:228`: `recover=FAIL`, `survive=FAIL`
  - `233:240`: `recover=FAIL`
  - `1441`: still `recover=FAIL`
  - `1456`, `1873`, `1875`: recover-pass with reactive `NOT_EVALUATED`, so `frt=None` rather than
    strict `True`.

Conclusion:

- Do not promote `mi181` or any `mi20..mi208` HLC sweep mode.
- The global fallback gate is too broad for hard24. The next Simulink-side attempt must use a much
  narrower weak-HVRT shallow-swell gate, or move the recovery action into a controller that is aware of
  the 1441-like condition without touching LVRT hard24 recovery cases.

## Narrow HVRT-Only Simulink Probe - 2026-07-09

Added experimental modes `mi209..mi240`. These modes deliberately map back to the plain mode-14
residual controller and add only narrow HVRT post-clear fallback actions:

- `fc_label == 5` (`swell_3ph`): strong shallow-HVRT recovery action, best single-case mode `mi214`.
- `fc_label == 6` (`swell_1ph`): gentler recovery action with a higher Vdc gate, best combined mode
  `mi233`.
- LVRT hard24 behavior is unchanged relative to `mi14` because these modes do not use the broad
  `mi20..mi208` guarded fallback path.

Key artifacts:

- `lab/results/selected_expanded_switching_narrow_hvrt_1441_mi214_mi214.json`
- `lab/results/selected_expanded_switching_narrow_combo_mi233_hard24_hvrt4_mi233.json`
- Baseline comparator:
  `lab/results/selected_expanded_switching_baseline_mi14_hard24_hvrt4_for_mi214_compare_mi14.json`

Best 1441 result:

- `mi214`: `recover.worst = 0.072465`, `V1_final_min = 0.927535`, `Vdc_min = 0.781111`.
- This is the best Simulink 1441 recovery frontier so far, but it still misses the `0.07` frt-v2
  recovery band by about `0.00247 pu`.

Best combined selected-HVRT result:

- `mi233` leaves hard24 unchanged versus `mi14`.
- Strict pass count on the 28-case selected set stays `8/28`, but no-fail count improves from `8/28`
  to `11/28`.
- Improvements relative to `mi14`:
  - `1456`: `recover` fail -> no FAIL (`recover.worst 0.095976 -> 0.022443`)
  - `1873`: `recover` fail -> no FAIL (`recover.worst 0.095932 -> 0.061830`)
  - `1875`: `recover` fail -> no FAIL (`recover.worst 0.095998 -> 0.061909`)
- Remaining selected HVRT failure:
  - `1441`: still `recover` fail (`recover.worst = 0.072465` under the best narrow three-phase gate)

Interpretation:

- The narrow HVRT gate is a useful non-regressing improvement for selected HVRT cases, but not a final
  all-pass solution.
- Scenario 1441 now appears to be a very tight terminal voltage-floor/ripple limit in Simulink: the
  best final minimum is still about `0.9275`, while the criterion requires `>= 0.93`.

## Narrow HVRT Fine Scan and Overnight Driver - 2026-07-09

Fine scan `mi241..mi260` around the narrow three-phase HVRT gate found only marginal improvement:

- Best mode: `mi247`
- Artifact: `lab/results/selected_expanded_switching_narrow_hvrt_1441_fine_mi247_mi247.json`
- `recover.worst = 0.072245`
- `V1_final_min = 0.927755`, `V1_final_mean = 0.931982`
- `Vdc_min = 0.782733`, `Vdc_max = 1.175919`

This is still a recover failure by about `0.002245 pu`. The plateau is consistent with the series
converter low-level controller saturating: `ctrl_series_code()` maps `mse` to modulation with `K=5`
and clips each phase to `[-1, 1]`. Therefore, simply increasing HLC action is unlikely to solve 1441.

New overnight automation:

- Added narrow HVRT probes `mi261..mi292` in `lab/simulink/build_hpt_frt_full.m`.
- Updated residual-weight routing in:
  - `lab/simulink/frt_v2_selected_expanded_switching.m`
  - `lab/simulink/frt_v2_full320_switching.m`
- Added `lab/simulink/frt_v2_overnight_auto_1441.m`.

The driver does three things automatically:

- Sweeps `mi261..mi292` on scenario `1441`.
- Spotchecks any no-fail or recover-pass candidate on hard24 plus selected HVRT cases
  `[217:240 1441 1456 1873 1875]`.
- Runs a mode-10 fixed-control angle sweep to determine whether a purely fixed control shape can pass
  the physical switching model.

Active background jobs:

- ODE/SAC constrained projection:
  `lab/results/overnight_constrained_projection_20260709_115516`
- Simulink overnight driver:
  `lab/results/background_runs/simulink_overnight_auto_1441_20260709_131043.log`

## Continuation Status - 2026-07-09 13:25

ODE constrained projection quick phase found a better non-regressing family:

- Best quick candidates so far: `lvrt_fallback_proj_0` and `lvrt_fallback_proj_1`
- Artifact directory: `lab/results/overnight_constrained_projection_20260709_115516`
- hard24: `24/24`
- hard92: `89/92`
- switching-fail ODE set: `16/17`
- sampled expanded2040 proxy: about `83.3%`

Remaining ODE hard92 failures under `lvrt_fallback_proj_0`:

- `1441`: `HVRT`, `swell_3ph`, `SCR=2`, `target=1.10`, recover fail
- `1443`: `HVRT`, `swell_3ph`, `SCR=2`, `target=1.10`, recover fail
- `1444`: `HVRT`, `swell_3ph`, `SCR=2`, `target=1.10`, recover fail

The same family leaves only `1441` failing in the switching-fail ODE set. This confirms the residual
problem is concentrated in the weak-grid shallow three-phase HVRT recovery floor, not spread across all
hard24/LVRT cases.

Simulink `mi261..mi292` narrow sweep:

- No `mi261..mi292` candidate passed 1441 recover.
- Best values returned to the previous frontier, e.g. `mi285..mi290` at
  `recover.worst = 0.072245`, `V1_final_min = 0.927755`.
- `mi276` triggered an automatic spotcheck, but it is not promotable:
  - hard24 regressions: `225:228` survive fail, `233:240` recover+survive fail.
  - selected HVRT still has `1441` recover fail, and `1873/1875` survive fail in that spotcheck.

Added focused ODE search:

- New script: `src/hpt_frt/device/focused_projection_search.py`
- Purpose: sweep only the weak-HVRT fallback gate around the remaining `1441/1443/1444` failures.
- A `--hard-only` mode was added for broad overnight exploration before expensive sampled 320/2040
  proxy verification.
- Active hard-only run:
  - command: `python -m hpt_frt.device.focused_projection_search --limit 180 --hours 8 --hard-only --quick-eval 80`
  - log prefix: `lab/results/background_runs/focused_projection_search_hardonly_20260709_132248.*.log`
  - result directory: `lab/results/focused_projection_search_20260709_132252`

Validation after adding the focused runner:

- `python -m py_compile src/hpt_frt/device/focused_projection_search.py`
- `pytest tests/test_env_envelope_unification.py tests/test_device_pipeline.py tests/test_error_analysis_visibility.py -q`
- Result: `20 passed`

## Target-First Search Update - 2026-07-09 13:30

The first focused hard-only implementation was still slow because it built sampled 320/2040 baseline
metrics before entering the hard-only loop. This was corrected:

- `src/hpt_frt/device/focused_projection_search.py` now skips sampled 320/2040 baseline work when
  `--hard-only` is used.
- The stale slow hard-only process was stopped and restarted.
- Active corrected focused hard-only run:
  - result directory: `lab/results/focused_projection_search_20260709_132514`
  - logs: `lab/results/background_runs/focused_projection_search_hardonly_20260709_132510.*.log`

Added a faster prefilter:

- New script: `src/hpt_frt/device/target_projection_search.py`
- It evaluates only `1441/1443/1444` first, then evaluates hard24 and switching-fail ODE only if a
  target candidate improves.
- Initial d-axis-only target-first run found no pass in the first 40 candidates.
- The search was expanded to include `fallback_iq` as well as `fallback_md`; the old d-only process was
  stopped and the iq/md run was started.
- Active iq/md target-first run:
  - command: `python -m hpt_frt.device.target_projection_search --limit 768 --hours 8`
  - result directory: `lab/results/target_projection_search_20260709_132955`
  - logs: `lab/results/background_runs/target_projection_search_iqmd_20260709_132951.*.log`

Simulink fixed-control feasibility sweep status:

- The sweep is still running, but through command 247 no fixed command has passed 1441 recover.
- Observed recover values remain around `0.0728` or worse, and most commands fail reactive; this is
  consistent with the previous saturation/frontier diagnosis.

## Simulink Overnight Driver Complete - 2026-07-09 13:31

The Simulink overnight driver completed and wrote:

- `lab/results/simulink_overnight_auto_1441_20260709_131043.json`
- `lab/results/control_sweep_1441_overnight_auto_angle_20260709_131043.{mat,json,csv}`

Best single-mode 1441 result:

- `mi276`
- `recover.worst = 0.072129596`
- `V1_final_min = 0.927870404`
- `V1_final_mean = 0.932047564`
- `Vdc_min = 0.782732587`
- FRT result: `False`

This is a small improvement over `mi247`/`mi271`, but still fails the `recover.worst <= 0.07` band.
It is also not promotable because its automatic spotcheck regressed hard24:

- `225:228`: survive fail
- `233:240`: recover + survive fail
- `1441`: still recover fail
- `1873/1875`: survive fail in that spotcheck

Mode-10 fixed-control feasibility sweep:

- Evaluated `265` fixed commands.
- No command passed 1441.
- Best fixed command family:
  - approximately `iq=0.40..0.66`, `md=0.373`, `mq=0.708`
  - `recover.worst = 0.072832`
  - failures: `reactive,recover`

Interpretation:

- HLC/fixed-command tuning alone is plateauing above the recovery threshold.
- The remaining 1441 Simulink failure is likely structural: terminal voltage floor/ripple under the
  switching plant, low-level modulation saturation, or criterion/model mismatch around final recovery,
  not a simple SAC action-selection issue.

## ODE iq30 and Simulink T_sim Alignment - 2026-07-09 14:32

ODE update:

- Added a narrow symmetric-HVRT post-clear cap in `HPTFRTResidualEnvV2`: `iq` can reach the physical
  `0.30 pu` cap only for `swell_3ph` HVRT post-clear recovery (`V2n<=0.025`, `0.90<=V2p<0.97`).
- Added/updated target-first search around `fallback_iq=0.30`, `fallback_md~=0.118`.
- Regression validation:
  - `py_compile` passed for the modified search/env modules.
  - `pytest tests/test_env_envelope_unification.py tests/test_device_pipeline.py tests/test_error_analysis_visibility.py -q`
  - Result: `21 passed`.
- ODE target-first result directory: `lab/results/target_projection_search_20260709_135543`
  - `1441/1443/1444`: `3/3`
  - hard24: `24/24`
  - switching-fail ODE set: `17/17`

Simulink validation update:

- Found a validation-window mismatch: selected Simulink runner used `StopTime=tf+dur+0.35`, while the
  expanded scenarios carry `T_sim` near 2 s for these recovery cases.
- Updated:
  - `lab/simulink/frt_v2_selected_expanded_switching.m`
  - `lab/simulink/frt_v2_full320_switching.m`
- The runners now preserve the scenario post-clear horizon:
  `post_window = max(0.35, T_sim - (scenario_t_fault + effective_dur))`.

Simulink findings after T_sim alignment:

- ODE iq30 candidate as `mi321` is too weak in Simulink:
  - `1441`: recover still fails, final mean about `0.862`.
- Previous Simulink frontier modes improve with the aligned horizon:
  - `mi276` on `1441`: `recover=PASS`, `survive=PASS`, `limit=PASS`, `connect=PASS`,
    `V1_final_worst_signed=-0.068424`, `Vdc_min=0.782733`.
  - `mi271`, `mi275`, and `mi280` pass all three weak-HVRT target cases
    `1441/1443/1444` under the aligned horizon.

Combined Simulink mode:

- Added `mi322` in `build_hpt_frt_full.m`:
  - LVRT side: stronger guard3 projection for hard24 (`fc_label<5` only).
  - HVRT side: weak-HVRT probe using `mi271` behavior.
- Representative `mi322` probe after restricting projection/guard to LVRT:
  - LVRT probes `221,225,233,237`: all FRT `True`.
  - weak-HVRT targets `1441/1443/1444`: no FAIL criteria (`frt=None` only because reactive is
    `NOT_EVALUATED` for shallow HVRT).
  - Remaining known selected Simulink issues: `1500` recover fail, `1873`/likely `1875` survive fail.

Active background work:

- Full selected Simulink spotcheck for `mi322` is running:
  - scenarios: `217:240, 1441,1443,1444,1456,1500,1873,1875`
  - log: `lab/results/background_runs/simulink_mi322_fullspot_20260709_143201.out.log`
  - expected artifact prefix: `lab/results/selected_expanded_switching_mi322_tsim_fullspot_20260709_143201_mi322`
- ODE background searches are still running/finishing:
  - `overnight_constrained_projection_20260709_135543`
  - `focused_projection_search_20260709_135543`

## Simulink mi324 Selected Spotcheck - 2026-07-09 14:58

`mi322` reduced the selected Simulink failures to three cases:

- `1500`: recover high by a small margin.
- `1873` and `1875`: Vdc survive failures under single-phase HVRT.

Added `mi323`/`mi324` as switching-plant alignment variants:

- Preserve the `mi322` LVRT guard/projection only for `fc_label<5`.
- Add a weak-HVRT Vdc gate for single-phase HVRT.
- Add a post-clear high-voltage clamp for strong HVRT; `mi324` uses the stronger clamp.

Selected `mi324` fullspot command:

```matlab
frt_v2_selected_expanded_switching(unique([217:240 1441 1443 1444 1456 1500 1873 1875], 'stable'), 324, 'mi324_fullspot_20260709')
```

Artifacts:

- `lab/results/selected_expanded_switching_mi324_fullspot_20260709_mi324.mat`
- `lab/results/selected_expanded_switching_mi324_fullspot_20260709_mi324.json`
- `lab/results/selected_expanded_switching_mi324_fullspot_20260709_mi324.csv`

Summary:

- `n=31`
- fail rows: none
- FRT true: `24/31` (the LVRT hard24 block)
- FRT false: `0/31`
- FRT none: `7/31`; these are shallow HVRT rows where `reactive=NOT_EVALUATED`, while connect,
  limit, recover, and survive are all `PASS`.

Representative repaired HVRT rows:

- `1441/1443/1444`: connect/limit/recover/survive all `PASS`.
- `1500`: recover margin now passes (`V1_final_worst_signed=0.0654304`).
- `1873/1875`: Vdc survive now passes (`Vdc_min=0.795340` and `0.791534`).

Active full320 validation:

- Launcher script: `lab/simulink/run_mi324_full320_20260709.m`
- Running artifact: `lab/results/p3_full320_sw_mi324.mat`
- Diary/log prefix: `lab/results/background_runs/simulink_mi324_full320_*.log`
- First logged cases `11:13` were all `PASS`; full320 is still running and must complete before
  claiming full scenario coverage.

## Simulink mi343 Full320 Closure - 2026-07-09

`mi324` full320 completed with 20 true failures, all in weak-grid HVRT:

- `271:280`: `swell_3ph`, `scr3`, `Vg_p=1.30`, `survive=FAIL` due to `Vdc<0.75`.
- `311:320`: `swell_1ph`, `scr3`, `Vg_p=1.10`, `reactive=FAIL` due to wrong reactive direction.

Fix exploration:

- `mi326` fixed the single-phase HVRT reactive-direction failures by adding a sign projection for
  `fc_label==6`, but left `271:280` failing.
- Stronger post-clear clamp variants barely changed the Vdc margin.
- The successful direction was an in-fault-only strong-HVRT takeover:
  - for three-phase HVRT with `V2n<=0.025`, `V2p>1.14`, and `t<=tf+fdur+0.005`,
    set `a1=-0.20`, `a2=0`, `a3=0`;
  - after clearing, return to the `mi324` post-clear high-voltage clamp.
- This became `mi343`.

Validation artifacts:

- `lab/results/p3_full320_sw_mi343.mat`
- `lab/results/selected_expanded_switching_mi343_fullspot_20260709_mi343.{mat,json,csv}`

Machine summary:

- full320 `mi343`: `n=320`, fail rows `0`, FRT `True=160`, FRT `None=160`, FRT `False=0`.
- selected expanded fullspot `mi343`: `n=31`, fail rows `0`, FRT `True=24`, FRT `None=7`,
  FRT `False=0`.
- Python regression:
  `pytest tests/test_env_envelope_unification.py tests/test_device_pipeline.py tests/test_error_analysis_visibility.py -q`
  returned `21 passed`.

Remaining scope:

- The original full320 switching benchmark is closed for `mi343`.
- The expanded2040 switching benchmark still needs an overnight all-scenario run; selected expanded
  hard probes are clean, but that is not yet a full expanded2040 certificate.

## Expanded2040 First Blocker - 2026-07-09

Started a chunked expanded2040 runner:

- `lab/simulink/run_mi343_expanded2040_20260709.m`
- diary prefix: `lab/results/background_runs/simulink_mi343_expanded2040_*.log`

The first chunk immediately exposed a new class outside the original full320 closure:

- `sid 1:4`
- LVRT `sym3ph`, `scr2`, `target_V_pu=0.10`
- fault parameter source: `nearest_calib_scr3`
- failures under `mi343`: recover/survive, and late connect on `sid 3:4`

Focused probes:

- `mi343`: reactive passes, but Vdc survive fails by about `0.071 pu`; recover error is about `0.136`.
- Deep-LVRT iq sweep:
  - `iq=0.20` (`mi349`) fixes reactive and Vdc survive.
  - remaining failures are recover, plus late connect on `sid 3:4`.
- Post-clear recovery boost:
  - `mi353/354/356/357` fix connect and survive while keeping reactive pass.
  - best recover error is still about `0.100`, above the `0.07` band.
- Zero-action baseline on the same four rows has recover error about `0.183`, so the controller does
  help, but the remaining recovery is saturated under the current plant/actuator envelope.

Current interpretation:

- `mi343` closes original full320 and the selected hard expanded spotcheck.
- Full expanded2040 is not closed. The first blocker is `scr2,target=0.10` deep LVRT recovery.
- This looks like an expanded scenario/plant feasibility boundary rather than an ODE-blind SAC tuning
  issue: the controller can trade reactive/Vdc/recovery, but cannot reach the `recover<=0.07` band for
  these rows with the currently exposed action channels.
