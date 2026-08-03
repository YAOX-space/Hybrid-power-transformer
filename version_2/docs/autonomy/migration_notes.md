# Interface Migration Notes

## 2026-07-21 - FRT Matrix Fault-Band Envelope Fields

- Old interface:
  - `collect_hpt_v2_frt_calibration_matrix.m` emitted sampled GBT envelope
    and recovery-envelope metrics, but did not emit the explicit fault-window
    LV band metrics used by the 20260721 voltage-survival gate.
- New additive fields:
  - `fault_lv_min`
  - `fault_lv_max`
  - `fault_lv_band_violation_max_pu`
  - `fault_lv_band_violation_mean_pu`
  - `fault_lv_band_violation_duration_s`
  - `fault_lv_band_pass`
  - `trace_fault_lv_band_violation_pu` in stripped trace payloads.
- Function signature change:
  - Internal `run_fixed_case(...)` calls now pass `faultSettleS` explicitly
    instead of relying on a script-scope variable that is invisible inside
    MATLAB subfunctions.
- Compatibility:
  - Existing matrix readers still accept older CSVs for diagnostic purposes,
    but final proxy calibration and SAC training should use matrices that
    include `fault_lv_band_violation_max_pu`,
    `envelope_violation_max_pu`, and `recovery_violation_max_pu`.
- Validation:
  - `py -3 -m py_compile version_2\sac\calibration\calibrate_hpt_frt_proxy_from_matrix.py version_2\sac\hpt_voltage_sac_env.py version_2\sac\frt_envelope.py`
    passed.
  - `py -3 -m version_2.sac.smoke_matlab_engine --dry-run` passed.
  - Pilot matrix `frt_calibration_matrix_pilot_all_20260721_034530.csv`
    contains the three voltage-survival calibration fields and aligns with
    `hpt_proxy_calibration.json` on pilot support points.

## 2026-07-21 - Conventional DQ Baseline Tuning Knobs

- Old interface:
  - `hpt_conventional_reg_scale`
  - `hpt_conventional_energy_scale`
- New additive workspace variables:
  - `hpt_conventional_reg_scale_sag`
  - `hpt_conventional_reg_scale_swell`
  - `hpt_conventional_energy_scale_sag`
  - `hpt_conventional_energy_scale_swell`
  - `hpt_conventional_recovery_reg_gain`
  - `hpt_conventional_recovery_reg_max`
  - `hpt_conventional_recovery_hold_s`
- Compatibility:
  - Defaults are `1.0` for sag/swell scale multipliers and `0.0` for recovery
    damping/hold, so the generated Simulink models preserve previous
    conventional-dq behavior unless a sweep explicitly overrides the new
    parameters.
- Validation:
  - `py -3 -m version_2.sac.smoke_matlab_engine --runner batch --test interface
    --timeout-s 900` passed after the interface migration.
- Follow-up:
  - Keep all conventional-boundary reports tied to their run labels because
    Stage-2 claims depend on the exact baseline parameter profile.

## 2026-07-21 - Unbalanced Fault Source And Grid Negative-Sequence Observation

- Old interface:
  - Fault descriptors in `eval_hpt_v2_control_comparison.m` and the main FRT
    collector represented only balanced source amplitude changes:
    `{case_name, fault_pu}` or `{case_name, fault_pu, duration_s}`.
  - The Simulink `HPTSACController` observation vector reserved `obs_03` for
    grid negative-sequence voltage, but the grid-side implementation set
    `g_vneg = 0`.
- New additive fault descriptor:
  - `{case_name, fault_pu, duration_s, [puA puB puC]}`.
  - If the phase vector is omitted, the old balanced programmable-source path
    is preserved.
  - If the phase vector is present, the grid source is replaced by three
    controlled phase voltage sources driven by a common waveform block.
- New/additive result fields:
  - `fault_a_pu`, `fault_b_pu`, `fault_c_pu`
  - `grid_va_fault_pu`, `grid_vb_fault_pu`, `grid_vc_fault_pu`
  - `grid_vabc_unbalance_fault_pu`
  - `grid_vpos_seq_fault_pu`, `grid_vneg_seq_fault_pu`
  - trace fields `grid_vneg_seq_pu_inst` and
    `grid_vabc_unbalance_pu_inst` in the FRT calibration collector.
- Controller observation fix:
  - `add_hpt_sac_controller.m` now estimates grid positive/negative sequence
    using the same quarter-cycle delay method used for LV sequence estimation.
  - A topology1 A-phase LVRT trace smoke confirmed fault-window `obs_03`
    is nonzero and tracks the measured grid negative-sequence order of
    magnitude.
- Compatibility:
  - Existing balanced evaluator/collector calls remain valid.
  - New trajectory wrappers accept `--fault-phase-pu A B C`; old calls without
    that option keep the balanced source.

## 2026-07-21 - Reproducible Fault/Recovery Action Trajectory Preset

- Old workflow:
  - Some topology2 recovery-shaping teachers were generated as one-off MAT/CSV
    files, making it hard to reproduce the exact fault-support and recovery
    transition profile from a command.
- New additive preset:
  - `version_2.sac.build_hpt_action_trajectory --preset fault_recovery`
  - Interpretation:
    - `base-action`: pre-event command;
    - `start-action`: high fault-window command;
    - `action`: lower recovery command;
    - `ramp-start` to `step-time`: ramp from base to fault command;
    - `ramp-end` to `down-start`: ramp from fault command to recovery command.
- Compatibility:
  - Existing trajectory presets are unchanged.
  - Existing MAT trajectory files remain valid.
- Experiment caution:
  - Do not run multiple MATLAB evaluator/validator jobs in parallel when they
    write the same `lab/results/hpt_v2_control_comparison` filename pattern and
    the caller selects the newest file.  Use sequential validation or unique
    result-discovery logic before treating results as evidence.

## 2026-07-21 - Grid Sequence Observation Startup Normalization

- Old behavior:
  - `HPTSACController` normalized grid positive/negative sequence voltage using
    the ideal configured grid phase RMS.
  - In topology2 unbalanced controlled-source cases, the measured primary-side
    sequence seen by the controller could sit around `0.6-0.8 pu` even before
    or after the commanded event, so the internal fault state could become
    active before the actual fault and remain active during the evaluator
    recovery window.
- New behavior:
  - During startup, the controller estimates a local measured grid positive
    sequence baseline and normalizes `g_vpos/g_vneg` by that baseline.
  - Fault detection is blanked for the first `30 ms` to avoid sequence-buffer
    initialization artifacts.
  - Internal controller thresholds now use the startup-normalized grid
    sequence observation.
- Compatibility:
  - Observation dimension remains 24 and action dimension remains 4.
  - Actor weight file structure is unchanged, but old actors and unbalanced
    accepted-specialist rows are not semantically equivalent after this change.
  - Rerun unbalanced specialist validation before citing any prior unbalanced
    pass count.
- Stale evidence marker:
  - `version_2/sac/experiments/stale_specialists_after_gridnorm_20260721.csv`

## 2026-07-21 - Unbalanced Source/Observation Smoke Gate Rebuild

- Old behavior:
  - `smoke_hpt_v2_unbalanced_source.m` checked only fault-window phase ordering
    and negative-sequence presence at the grid measurement point.
  - In topology2, that measurement is affected by HPT/DC-link dynamics, so it
    could not cleanly distinguish source-command correctness from plant
    response.
  - The evaluator also used one final observation average, so pre-fault,
    fault-window, and recovery-window observation-state problems were hidden.
- New additive evaluator fields:
  - `source_va_*_pu`, `source_vb_*_pu`, `source_vc_*_pu`,
    `source_vpos_seq_*_pu`, `source_vneg_seq_*_pu`,
    `source_vabc_unbalance_*_pu` for `pre`, `fault`, and `recovery` windows.
  - Matching `grid_*` pre/fault/recovery fields remain available for plant-side
    and controller-observation diagnostics.
  - Observation aggregates are now split into `obs_*_pre_mean`,
    `obs_*_fault_mean`, and `obs_*_recovery_mean`.
- Controller startup migration:
  - Added `hpt_sac_gridnorm_startup_s` to control how long the local grid
    sequence baseline is updated and fault/recovery state is blanked.
  - The evaluator sets this to a value before the configured fault start, while
    the model default remains `30 ms`.
- Smoke evidence:
  - Topology2 source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`.
  - Topology1 source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`.
- Compatibility:
  - Balanced scalar fault descriptors remain valid.
  - The 24-D observation / 4-D action actor contract remains valid.
  - Unbalanced specialist results generated before this gate should remain
    marked stale until rerun.

## 2026-07-21 - Conventional-DQ LV-Error Fallback

- Old behavior:
  - `conventional_dq` policy mode `0` responded mainly to the internal
    grid-side `fault_active` / `recovery_active` state.
  - Mild unbalanced source faults could leave `fault_active` low while LV
    voltage was already outside the voltage-survival band, so the conventional
    rule path produced zero regulating command.
- New behavior:
  - Policy mode `0` now also has an LV-voltage-error fallback:
    if `vpu < 0.98` or `vpu > 1.02`, it generates a bounded `reg_d` command
    from `hpt_conventional_recovery_reg_gain * (1 - vpu)`.
  - The tuned-v1 conventional profile sets nonzero recovery/LV-error gain and
    max command limits for both topologies.
- Compatibility:
  - Observation/action dimensions and actor weight formats are unchanged.
  - This changes the traditional baseline behavior, so old conventional
    boundary matrices must not be mixed with post-fallback matrices.
- Current status:
  - The fallback improves topology1 unbalanced recovery voltage, but gain-only
    pilots still do not produce a mixed pass/fail boundary.
  - Further tuning must sweep injection phase/polarity and recovery law.

## 2026-07-21 - Diagnostic Phase-Override Observation Contract

- Old behavior:
  - The 24-D SAC observation used measured/internal fault and recovery flags
    derived from startup-normalized grid sequence voltage.
  - In topology2 LVRT trajectory actor traces, the actor could still see
    ambiguous fault/recovery phase indicators in closed loop and therefore did
    not reliably reproduce the teacher transition.
- New additive interface:
  - Added default-off model-workspace variables:
    `hpt_sac_phase_override_enable`,
    `hpt_sac_phase_fault_start_s`,
    `hpt_sac_phase_fault_clear_s`, and
    `hpt_sac_phase_recovery_end_s`.
  - When enabled, only the observation phase fields are replaced by scheduled
    fault/recovery features.  The 24-D observation size, 4-D action size, actor
    MAT format, and default behavior are unchanged.
  - Python trajectory validator/campaign runners expose this as
    `--phase-override`.
- Purpose:
  - This is a diagnostic/training contract to test whether topology2 actor
    failures are due to phase-identification ambiguity.
  - It is not a final deployable FRT mechanism unless later replaced by a
    measured, robust phase detector.
- Smoke evidence:
  - Teacher validation with phase override passed for topology2 LVRT
    0.90 pu / 60 ms:
    `lab/results/hpt_t2_lvrt090_phase_override_validation_20260721/summary.json`.
  - BC actor smoke improved action imitation but did not promote:
    `lab/results/hpt_t2_lvrt090_phase_override_actor_smoke_20260721/summary.json`.

## 2026-07-29 - Runtime Depth-Selector SAC Mode

- Old behavior:
  - `sac_actor_always_raw` loaded one exported dynamic SAC actor and used it for
    the whole fault case.
  - The first topology1 balanced LVRT family improvement was only demonstrated
    by a manifest-level actor choice: deep cases used a support-dataset SAC
    checkpoint and all other cases used the seed actor.
- New additive interface:
  - Added evaluator mode `sac_actor_depth_selector_raw`.
  - Added controller `actor_select_mode = 4.0`.
  - In this mode, the Simulink HPTSACController loads the base actor from
    `hpt_sac_actor_weights.mat` and the dynamic actor from
    `hpt_sac_actor_weights_dynamic.mat`, then switches online to the dynamic
    actor for topology1 deep LVRT when `g_vpos` or remembered `v_fault_min` is
    below `0.885` during fault/recovery.
  - `validate_hpt_accepted_specialists.py` now supports optional manifest
    columns `comparison_mode`, `base_model_path`, and `dynamic_model_path`.
- Compatibility:
  - Existing manifest rows without these optional columns keep the old
    `sac_actor_always_raw` behavior.
  - The 24-D observation, 4-D action, and actor MAT weight format are unchanged.
- Evidence:
  - Runtime selector smoke:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_smoke_20260729/summary.json`.
  - Runtime selector full 19-case family gate:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_full_20260729/summary.json`.
  - Full-family result: `14 / 19` voltage-survival pass and `14 / 19` beat
    conventional, matching the earlier case-level selector and improving over
    the seed actor's `13 / 19`.

## 2026-08-03 - Family-SAC Workspace Cleanup

- Canonical interface:
  - Family orchestration is now exclusively
    `version_2.sac.campaigns.run_hpt_family_specialist_matrix`.
  - Switch-level promotion is exclusively based on
    `evaluators/eval_hpt_v2_control_comparison.m`.
  - The 24-D observation and 4-D action contracts are unchanged.
- Moved capability:
  - `version_2.sac.build_hpt_action_trajectory` moved to
    `version_2.sac.datasets.build_hpt_action_trajectory`.
  - All maintained imports were migrated; no compatibility wrapper remains.
- Removed executable paths:
  - fixed-action/per-case campaigns, overnight runners, CEM search, generic
    offline baselines, learned reward correction, safety-classifier training,
    old calibration sweep adapters, and old raw switch smoke tools;
  - source-tree actor archives and redundant teacher collectors.
- Evidence policy:
  - Historical manifests and generated result directories remain for
    provenance but are not supported launch commands.
  - Earlier accepted-manifest claims do not override the current evaluator.
  - The current r6 topology2 A-phase LVRT result is local voltage-survival
    boundary evidence and is not full-FRT certification.
