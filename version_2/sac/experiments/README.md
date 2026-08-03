# HPT SAC Experiment Registry

This folder documents how version 2 SAC experiments should be launched and
interpreted.  The actual generated outputs stay in `lab/results/`; trained
actors stay in `data/models/`.

## Result Locations

- `lab/results/hpt_v2_frt_calibration_matrix/`
  - switch-level FRT calibration matrix and 2 ms traces.
- `lab/results/hpt_v2_frt_proxy_gap/`
  - proxy-vs-switch-level error summaries.
- `lab/results/hpt_v2_frt_teacher_traces/`
  - selected teacher actions and per-step FRT teacher traces.
- `lab/results/hpt_case_specialists_<timestamp>/`
  - per-case specialist training logs, exported actors, status JSON, and report.
- `data/models/hpt_case_specialists/`
  - trained specialist policy ZIP files.

## Campaign Naming

Use this naming pattern in reports and commits:

```text
<topology>_<scenario-type>_<case>_<purpose>
```

Examples:

- `topology1_fault_sag_0p75_teacher_bc`
- `topology2_fault_swell_1p20_joint_proxy_gap`
- `topology1_steady_grid_9000V_switch_promotion`

## Current Campaigns

### Voltage-Survival Boundary Matrix - 2026-07-25

Research plan:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-voltage-survival-boundary-plan-2026-07-25.md`

Manifest generator:

```powershell
py -3 -m version_2.sac.campaigns.generate_hpt_voltage_survival_boundary_manifest
```

Switch-level grouped runner:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --dry-run
```

The full matrix contains 630 voltage-survival scenarios:

- topology1 and topology2;
- LVRT 0.75/0.80/0.85/0.90/0.95 pu;
- HVRT 1.05/1.10/1.15/1.20 pu;
- durations 40/60/80/120/200 ms;
- balanced, A, B, C, AB, BC, CA phase modes.

The first SAC boundary scan uses nearest-neighbor actors from
`accepted_specialists_20260722_stage2_voltage_survival.csv`.  These rows are
boundary probes; only exact switch-level specialist rechecks can promote a new
final accepted actor.

### Current Stage-2 Voltage-Survival Evidence

Completion/evidence report:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage2-completion-report-2026-07-22.md`

Authoritative balanced accepted matrix:

- `version_2/sac/experiments/accepted_specialists_20260721_balanced.csv`
- latest reproducible recheck:
  `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/REPORT.md`
- four switch-level voltage-survival specialists:
  topology1 LVRT 0.90 pu / 60 ms, topology1 HVRT 1.10 pu / 60 ms,
  topology2 LVRT 0.90 pu / 60 ms, topology2 HVRT 1.10 pu / 60 ms
- all four pass the current switch-level voltage-survival gate and beat the
  corresponding conventional/rule baseline score
- all four remain `full_frt_pass = false`
- the topology2 LVRT row now points to the 20260722 no-noise/high-weight
  phase-grid actor, which is the strongest current topology2 LVRT
  voltage-survival evidence.
- the topology1 HVRT row now points to the 20260722 current-interface retrain
  from the passing constant trajectory `[0.249, 0, -0.005, 0]`.  The previous
  topology1 HVRT actor remains archived as stale in
  `version_2/sac/experiments/stale_specialists_after_phaseaware_recheck_20260722.csv`.

Authoritative Stage-2 combined voltage-survival matrix:

- `version_2/sac/experiments/accepted_specialists_20260722_stage2_voltage_survival.csv`
- unified latest reproducible recheck:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/REPORT.md`
- result: `8 / 8` switch-level voltage-survival pass, `6 / 8`
  beat-conventional, `0 / 8` full FRT pass
- includes the four balanced specialists above and the four accepted
  unbalanced A/AB LVRT specialists below; topology2 unbalanced A/AB now point
  to warm-start SAC fine-tuned actors.

Authoritative unbalanced accepted matrix:

- `version_2/sac/experiments/accepted_specialists_20260721_unbalanced.csv`
- latest phase-vector recheck:
  `lab/results/hpt_accepted_unbalanced_matrix_20260722_current4_phasefix_recheck/REPORT.md`
- four switch-level voltage-survival specialists:
  topology1 A-phase LVRT 0.90 pu / 60 ms, topology1 AB LVRT 0.90 pu / 60 ms,
  topology2 A-phase LVRT 0.90 pu / 60 ms, topology2 AB LVRT 0.90 pu / 60 ms
- all four pass the current switch-level voltage-survival gate; topology2 A/AB
  also beat the corresponding conventional baseline score, while topology1
  A/AB are survival-only rows under the current score definition.
- topology2 A/AB use the accepted warm-start SAC fine-tuned actors:
  `data/models/hpt_t2_a_lvrt090_warm_sac_reganchor_20260722.zip` and
  `data/models/hpt_t2_ab_lvrt090_warm_sac_reganchor_20260722.zip`.

Current mixed unbalanced voltage-survival boundary:

- `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_legacy_mixed_boundary_20260721_20260721_191851.csv`
- topology1: 12 / 16 voltage-survival pass, 0 / 16 full-FRT pass
- topology2: 0 / 16 voltage-survival pass, 0 / 16 full-FRT pass
- use this only as voltage-survival boundary evidence, not as full FRT evidence

Unbalanced source/observation smoke gate:

- topology1:
  `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`
- topology2:
  `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`
- both passed 14 / 14 source cases after `Vgrid_cmd_abc` and local
  grid-sequence normalization changes

Current unbalanced proxy pilot:

- matrix:
  `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_193807.csv`
- JSON:
  `version_2/sac/hpt_proxy_calibration_unbalanced_pilot.json`
- diagnostic only; do not use as final SAC training evidence until rollout
  alignment improves for topology1 HVRT weak groups and topology2 DC-link
  dynamics.

### FRT Proxy Calibration Matrix

Canonical command:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_calib_mode='full'; hpt_calib_topology='all'; run(fullfile(pwd,'collectors','collect_hpt_v2_frt_calibration_matrix.m'));"
```

Latest accepted source:

- `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_full_all_20260717_005608.csv`
- `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_traces_full_all_20260717_005608.csv`

This 20260717 source is useful for historical balanced proxy calibration.  For
post-grid-normalization unbalanced work, use the 20260721 pilot artifacts above
as diagnostics and regenerate a larger matrix before final training.

### FRT Trajectory Specialist Training

Current trajectory-specialist entry point:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign --help
```

Use this route for switch-level teacher validation, behavior cloning, DAgger,
actor export, and switch-level promotion.  Older case-specialist trainers under
`version_2.sac.offline` are retained for diagnostics but are not the current
accepted-matrix path.

Interrupted diagnostic run:

- `lab/results/hpt_case_specialists_20260717_011726`
- reached 11 fault specialist records before interruption
- no actor was promoted
- several LVRT candidates improved score and Vdc survival, but still failed
  full FRT criteria

## Promotion Standard

A model can be called a switch-level voltage-survival success only if all are
true:

1. The candidate is evaluated in the switch-level Simulink model, not only the
   averaged proxy.
2. The case evaluator returns `voltage_survival_pass = true`.
3. The report includes LV metrics, Vdc metrics, action bounds, and failure
   reasons.
4. New fault candidates must include timestep envelope fields from the
   switch-level evaluator.  A row missing `fault_lv_band_violation_max_pu`,
   `envelope_violation_max_pu`, or `recovery_violation_max_pu` is legacy
   evidence and is not promotable under the trajectory-specialist gate.
5. For fault cases, voltage survival means every sampled control step stays
   inside the active LVRT/HVRT envelope and the recovery band.  Fault-window
   and recovery-window averages are diagnostic values, not pass criteria by
   themselves.

A model can be called full FRT certified only if the voltage-survival gate
passes and the extra grid-code current criteria also pass:

1. The report includes grid-side `Igrid_abc` derived dq metrics,
   reactive-current support/response status, and grid-current limit status.
2. A case with missing or failed current metrics is not full-FRT promotable.
3. Proxy-only SAC results are not promotable unless the active proxy
   calibration JSON was generated from an FRT matrix containing those same
   grid-current fields.
4. Proxy training runs must pass rollout alignment with
   `verify_hpt_proxy_rollout_alignment.py`; this checks the actual SAC
   environment, not only the static lookup tables.

## Cleanup Policy

Interrupted runs should be stopped explicitly and documented in the next progress
report.  Do not delete partial diagnostic results unless they are known to be
corrupt or the user asks for cleanup.

The full-action boundary dataset builder now skips known stale/corrupt matrix
stems and rejects rows without timestep envelope metrics by default.  Use
`--allow-legacy-no-envelope` only for debugging old reports, not for new SAC
training.

### Protected SAC Promotion Round 1

Active plan:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stabilize-and-expand-plan-2026-07-26.md`

Main artifacts:

- promotion targets:
  `version_2/sac/experiments/trustregion_promotion_targets_20260726.csv`
- promoted manifest:
  `version_2/sac/experiments/protected_sac_promoted_specialists_20260726_round1.csv`
- recheck manifest:
  `version_2/sac/experiments/protected_sac_promoted_recheck_manifest_20260726.csv`
- promotion run:
  `lab/results/hpt_trustregion_promotion_20260726_round1/REPORT.md`
- switch-level recheck:
  `lab/results/hpt_promoted_recheck_20260726_round1/REPORT.md`

Recheck result:

- conventional dq voltage-survival pass: 2 / 11
- promoted SAC voltage-survival pass: 11 / 11
- SAC beats conventional: 9 / 11
- traditional fail / SAC pass: 9 / 11
- traditional pass / SAC fail: 0 / 11

The two survival-only rows are topology1 A-phase LVRT 0.90 pu / 60 ms and
topology1 AB LVRT 0.90 pu / 60 ms.  These are the highest-priority quality
improvement targets before expanding the boundary matrix.
