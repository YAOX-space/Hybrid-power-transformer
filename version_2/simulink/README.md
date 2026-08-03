# Version 2 Simulink Workspace

This directory is the switch-level source of truth for the two HPT plants and
controller evaluation.

## Plant Models

- `topoloty1/build_hpt_v2_1to1_switchlevel.m`
- `topology2/build_hpt_v2_topology2_paper.m`

The historical spelling `topoloty1` is retained because it is part of the
current path contract.

## Controller Interface

- `add_hpt_sac_controller.m`: shared 24-observation, four-action controller
  subsystem.
- `hpt_sac_actor_weights.mat`: default/base exported actor.
- `hpt_sac_actor_weights_dynamic.mat`: current candidate actor used by the
  evaluator.

Experiment-specific actor snapshots must stay in
`version_2/experts/<expert_id>/models/`, and their run evidence in the matching
`results/` directory, not in this source directory.

## Maintained Data And Evaluation

- `collectors/collect_hpt_v2_frt_calibration_matrix.m`: calibration matrix.
- `collectors/collect_hpt_v2_trajectory_trace.m`: trajectory trace collector.
- `evaluators/eval_hpt_v2_control_comparison.m`: canonical matrix evaluator.
- `evaluators/eval_hpt_v2_sac_single_case.m`: paper/single-case trace export.
- `calibration/calibrate_hpt_v2_topology2_energy_branch.m`: focused energy
  branch calibration.
- `sweeps/`: strong-dq boundary and focused plant diagnostics.
- `tests/`: MATLAB switch-model and controller-interface regression tests.

## Commands

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_calib_mode='full'; hpt_calib_topology='all'; run(fullfile(pwd,'collectors','collect_hpt_v2_frt_calibration_matrix.m'));"
```

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"
```

Generated `slprj/`, `*.slxc`, trajectory MAT files, and temporary actor copies
are disposable and must not be committed.
