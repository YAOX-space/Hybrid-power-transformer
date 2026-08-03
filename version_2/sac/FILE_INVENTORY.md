# version_2/sac File Inventory

This folder contains the version-2 SAC research code for the HPT switch-level
Simulink models.  The current main line is trajectory/state-feedback specialist
control for voltage-survival, validated in switch-level Simulink.

After the 2026-07 cleanup, historical top-level scripts were moved into focused
subdirectories and the compatibility wrappers were removed.  Use the new module
paths directly, for example
`py -3 -m version_2.sac.offline.train_hpt_voltage_sac`.

## Current Main Line

- `hpt_voltage_sac_env.py`  
  Fast averaged HPT proxy environment.  Defines the 24-D observation, 4-D action
  `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`, FRT scenarios, reward, proxy
  calibration lookup, voltage-envelope tracking, grid-current/reactive-current
  estimates, and teacher/action projection helpers.

- `frt_envelope.py`  
  Shared GB/T-style LVRT/HVRT voltage envelope helper used by the proxy and
  analysis scripts.  Keeps timestep envelope definitions consistent.

- `pretrain_hpt_actor_bc.py`  
  Behavior-cloning/warm-start trainer for the exported SAC actor format.  It
  trains an SB3 SAC actor from switch-level trajectory traces or fixed-action
  teacher data while preserving the Simulink export contract.

- `search_hpt_frt_trajectory_cem.py`  
  Proxy-guided CEM trajectory search.  Samples piecewise-linear 4-D action
  trajectories, validates top candidates in switch-level Simulink, and finds
  teacher trajectories for specialist training.

- `run_hpt_trajectory_specialist_campaign.py`  
  Main current specialist workflow.  It validates a teacher trajectory, collects
  switch-level traces, behavior-clones a state-feedback actor, optionally runs
  DAgger, exports the actor, evaluates in switch-level Simulink, and promotes
  only voltage-survival actors that beat conventional control.

- `validate_hpt_trajectory_switchlevel.py`  
  Switch-level validator for a generated or existing trajectory MAT file.
  Compares `trajectory_action`, `fixed_action`, and `conventional_dq` on the
  same Simulink fault case.

- `validate_hpt_accepted_specialists.py`  
  Regression validator for accepted specialist checkpoints listed in a manifest
  CSV.  Exports each checkpoint to Simulink and re-runs switch-level comparison.

- `export_hpt_sac_actor.py`  
  Converts an SB3 SAC actor checkpoint to the MAT weight file consumed by the
  Simulink MATLAB Function block.

- `experiment_metadata.py`  
  Shared metadata helper.  Records run configuration, git/source state, dataset
  paths, and output artifacts for reproducibility.

## Current Manifests And Configuration

- `hpt_proxy_calibration.json`  
  Large generated calibration file for the averaged proxy.  Built from
  switch-level calibration matrices.  It is data, not executable code.

- `experiments/accepted_specialists_20260720.csv`  
  Current accepted voltage-survival specialist matrix:
  topology1 LVRT/HVRT and topology2 LVRT/HVRT.

- `experiments/accepted_specialists_20260719.csv`  
  Older accepted manifest containing the topology1 accepted specialists before
  the topology2 timefix additions.

- `experiments/stale_specialists_after_gridobs_20260720.csv`  
  Stale/diagnostic manifest retained to explain why older specialists should
  not be trusted after the grid-observation and timestep-envelope changes.

- `experiments/README.md`  
  Notes for accepted/stale specialist manifests.

## Subpackage Layout

- `calibration/`
- `datasets/`
- `offline/`
- `campaigns/`
- `summaries/`

Top-level wrapper files are intentionally not kept.  This keeps the directory
window small and makes stale commands fail loudly instead of silently running an
old path.

## `calibration/`: Proxy Calibration And Alignment Tools

- `calibrate_hpt_frt_proxy_from_matrix.py`  
  Builds/updates `hpt_proxy_calibration.json` from the switch-level FRT
  calibration matrix.  Current proxy calibration tool for FRT work.

- `verify_hpt_proxy_rollout_alignment.py`  
  Runs the proxy on fixed matrix actions and compares rollout metrics against
  Simulink matrix rows.  Used to check whether the proxy behaves like the
  switch-level model over a whole scenario.

- `measure_hpt_frt_proxy_gap.py`  
  Quantifies proxy prediction error against the FRT calibration matrix,
  including holdout/joint-action checks.

- `measure_hpt_reward_alignment.py`  
  Checks whether proxy reward ranks actions the same way as switch-level
  FRT metrics.  Useful before training on the proxy.

- `fit_hpt_energy_cmd_response.py`  
  Fits command-to-measured-response mappings for the energy branch.  Created
  because `m_energy_*` command and measured energy response can differ.

- `calibrate_hpt_proxy_from_sweep.py`  
  Older steady/fixed-action proxy calibration from action-response sweeps.
  Useful historically, but not the main FRT calibration path now.

- `calibrate_hpt_energy_proxy_from_sweep.py`  
  Older energy-converter sweep merger for proxy calibration.  Superseded by
  newer FRT matrix and energy command-response tools for the current work.

- `measure_hpt_proxy_gap.py`  
  Older proxy-gap checker for early fixed-action sweeps.  Superseded by the
  FRT-specific gap/alignment scripts for current FRT work.

- `train_hpt_learned_proxy.py`  
  Experimental learned/probabilistic proxy trainer.  Not part of the current
  accepted specialist path; kept for future model-based/offline RL research.

- `train_hpt_reward_correction.py`  
  Experimental learned reward-correction model for proxy-vs-Simulink mismatch.
  Currently not used because the active direction is direct specialist
  switch-level validation rather than residual correction.

- `train_hpt_safety_classifier.py`  
  Trains a support/safety classifier from switch data.  Useful for future
  offline or model-based RL with behavior constraints; not required for the
  current accepted voltage-survival matrix.

## `datasets/`: Dataset Builders

- `build_hpt_action_trajectory.py`  
  Builds simple 4-D action trajectory MAT/CSV files for Simulink trajectory
  validation.  This one remains a top-level current main-line implementation.

- `build_hpt_trajectory_teacher_dataset.py`  
  Indexes trajectory-search runs and writes a dataset/manifest of accepted and
  diagnostic trajectory teachers.

- `build_hpt_trace_aggregate.py`  
  Concatenates multiple switch-level trace CSVs into one aggregate trace dataset
  for DAgger-style BC.

- `build_hpt_frt_teacher_traces.py`  
  Older fixed-action teacher-trace builder from the FRT calibration matrix.
  Useful for historical fixed-action experiments, less central now that
  trajectory teachers are used.

- `build_hpt_boundary_full_action_dataset.py`  
  Builds a boundary-centered contextual full-action dataset for offline
  beat-conventional experiments.  Useful for offline baselines, not the current
  trajectory specialist main path.

- `build_hpt_switch_dataset.py`  
  Builds compact datasets from labeled switch-level sweeps.  Earlier data path;
  not the primary trajectory-specialist data builder.

- `build_hpt_local_action_sweep.py`  
  Generates local fixed-action sweep candidate CSVs for switch-level validation.
  Useful for focused plant/action debugging.

## `offline/`: Offline And Alternative Training Experiments

- `train_hpt_voltage_sac.py`  
  Trains SAC directly on the averaged proxy.  This was an early direct-SAC path;
  current accepted specialists rely on switch-level teacher trajectories plus
  BC/DAgger because proxy reward alone was not trustworthy enough.

- `train_hpt_case_specialists.py`  
  Earlier per-case specialist trainer and switch-level validator.  Mostly
  superseded by trajectory-specialist campaigns.

- `train_hpt_fault_specialists_vs_baseline.py`  
  Fault-specialist trainer comparing SAC against conventional DQ from boundary
  sweeps.  Research/experimental path; not the current promoted matrix path.

- `train_hpt_offline_full_action_baselines.py`  
  Offline full-action baselines such as TD3+BC/IQL-style contextual action
  training.  Useful for research comparison, not the current accepted
  trajectory-specialist path.

## Campaign Orchestration

- `run_hpt_sac_pipeline.py`  
  Canonical stage launcher/dry-run helper for version-2 SAC research stages.
  Intended to make long workflows more reproducible.

- `run_hpt_specialist_matrix_campaign.py`  
  Orchestrates multiple specialist campaigns and summarizes a matrix.  Useful
  for larger batch runs; individual trajectory campaigns are easier to debug.

- `campaigns/run_hpt_dynamic_trajectory_sweep.py`  
  Batch runner around `validate_hpt_trajectory_switchlevel.py` for dynamic
  two-stage trajectory sweeps.

- `campaigns/run_hpt_full_action_recalibration_campaign.py`  
  End-to-end recalibration campaign: matrix collection, proxy calibration,
  proxy gap/reward alignment, dataset building, offline training, and switch
  validation.  Heavy research workflow, not the small current accepted gate.

- `campaigns/run_hpt_topology2_lvrt_step1_5_campaign.py`  
  Historical focused topology2 LVRT campaign.  Useful forensic script for the
  topology2 energy/DC-link debugging path; largely superseded by the timefix
  trajectory-specialist workflow.

## Validation And `summaries/`

- `validate_hpt_offline_actions_switchlevel.py`  
  Validates offline full-action candidate actions in switch-level Simulink and
  promotes only rows that satisfy configured switch-level gates.

- `summaries/summarize_hpt_control_comparison.py`  
  Summarizes Simulink control-comparison CSVs across modes/cases.

- `summaries/summarize_hpt_conventional_boundary.py`  
  Summarizes conventional-DQ boundary sweep results.

## Package And Generated Folders

- `__init__.py`  
  Marks `version_2.sac` as a Python package.

- `__pycache__/`  
  Python bytecode cache.  Generated automatically and safe to delete.

- `legacy/`  
  Older scripts moved out of the active folder.  Keep for reference only unless
  deliberately reviving an old experiment.

## Cleanup Rule Going Forward

Keep only current main-line implementations and shared core utilities at the top
level.  New calibration, dataset, offline-training, campaign, and summary tools
should live in the matching subpackage from the start.  Do not add compatibility
wrappers unless we explicitly choose to support an old command name again.
