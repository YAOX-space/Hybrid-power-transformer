# Version 2 Simulink Workspace

This folder contains the switch-level HPT Simulink plants, MATLAB evaluators,
data collectors, calibration sweeps, and the active exported SAC actor weights.

## Top-Level Files

- `add_hpt_sac_controller.m` - shared helper used by both topology build
  scripts to add the SAC/controller subsystem.
- `hpt_sac_actor_weights.mat` - active steady/default exported actor.
- `hpt_sac_actor_weights_dynamic.mat` - active dynamic actor used by current
  switch-level validation.

Only these actor MAT files should live at the top level.  One-off actor
snapshots belong in `actors/archive/` or, preferably, the timestamped
`lab/results/<run_id>/` directory that produced them.

## Subdirectories

- `topoloty1/` - topology1 switch-level model and build script.  The misspelling
  is historical and intentionally preserved because many scripts reference it.
- `topology2/` - topology2 paper-style switch-level model and build script.
- `collectors/` - scripts that collect FRT matrices, trajectory traces, and
  teacher traces from switch-level simulations.
- `evaluators/` - scripts that evaluate controller modes and write pass/fail
  comparison CSVs.
- `calibration/` - focused calibration scripts, currently topology2 energy
  branch calibration.
- `sweeps/` - diagnostic and calibration sweeps; not the main training entry.
- `tests/` - MATLAB regression/smoke-test scripts.
- `actors/archive/` - old exported actor MAT snapshots kept only for forensics.

## Canonical Commands

Run from the Simulink root:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_calib_mode='full'; hpt_calib_topology='all'; run(fullfile(pwd,'collectors','collect_hpt_v2_frt_calibration_matrix.m'));"
```

For switch-level controller comparison:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_compare_topology='topology1'; hpt_compare_modes={'conventional_dq','sac_actor_raw_guard0'}; run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"
```

## Generated Files

Do not commit or depend on these generated files:

- `slprj/`
- `*.slxc`
- `hpt_sac_trajectory.mat`
- temporary actor snapshots beside model scripts
