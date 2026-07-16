# Version 2 HPT SAC Package

This package contains the controller-training workflow for the version 2
switch-level Hybrid Power Transformer models.  Keep this package import-stable:
existing commands such as `py -3.8 -m version_2.sac.train_hpt_case_specialists`
are treated as public entry points.

## Package Map

Core environment and metadata:

- `hpt_voltage_sac_env.py` - averaged HPT proxy environment used for SAC and
  behavior-cloning pretraining.
- `experiment_metadata.py` - reproducibility helpers for result manifests.

Switch-level data and calibration:

- `build_hpt_switch_dataset.py` - converts switch-level traces into ML datasets.
- `calibrate_hpt_proxy_from_sweep.py` - steady/regulating proxy calibration.
- `calibrate_hpt_energy_proxy_from_sweep.py` - energy-bridge proxy calibration.
- `calibrate_hpt_frt_proxy_from_matrix.py` - GB/T FRT matrix calibration.
- `build_hpt_frt_teacher_traces.py` - selects switch-level FRT teacher actions
  and builds per-SAC-step teacher traces.

Proxy validation:

- `measure_hpt_proxy_gap.py` - steady and step proxy-vs-Simulink gap report.
- `measure_hpt_frt_proxy_gap.py` - FRT proxy-vs-Simulink gap report.
- `measure_hpt_reward_alignment.py` - ranking test between calibrated proxy
  reward-like scores and switch-level FRT matrix scores.
- `train_hpt_reward_correction.py` - supervised correction from proxy reward to
  switch-level reward-like action ranking, with held-out action evaluation.

Training:

- `train_hpt_voltage_sac.py` - baseline SAC training on the proxy.
- `pretrain_hpt_actor_bc.py` - behavior-cloning and mixed teacher pretraining.
- `train_hpt_case_specialists.py` - topology/case specialist training and
  switch-level promotion gate.
- `train_hpt_learned_proxy.py` - learned proxy experiments.
- `train_hpt_safety_classifier.py` - safety classifier experiments.

Export and deployment:

- `export_hpt_sac_actor.py` - exports a Python actor to Simulink MAT weights.

Long-running experiments:

- `overnight_hpt_sac_simulink_optimize.py`
- `overnight_hpt_sac_steptrace_specialists.py`
- `overnight_hpt_case_specialists.py`

These are retained for reproducibility.  New long experiments should be launched
through `run_hpt_sac_pipeline.py` or documented in `experiments/README.md`.

## Current Engineering Rules

1. Do not move public entry-point scripts without leaving wrapper modules.
2. Keep generated data under `lab/results/`, trained models under
   `data/models/`, and Simulink actor MAT files under `version_2/simulink/`.
3. Every long run must write a report and a status JSON under a timestamped
   result directory.
4. Every run that can overwrite Simulink actor MAT files must back them up and
   restore them after case validation.
5. A switch-level actor is promoted only after the Simulink case evaluator marks
   the case as passed.  "Improved but failed" actors remain research artifacts,
   not final candidates.

## Canonical Workflow

Use the pipeline helper to print or run repeatable stages:

```powershell
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --list
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --stage frt-matrix --dry-run
```

The current full workflow is:

1. Collect switch-level FRT calibration matrix.
2. Calibrate the proxy from that matrix.
3. Measure proxy-vs-switch-level gap.
4. Build teacher traces.
5. Measure reward alignment.
6. Train/evaluate reward correction for weak proxy-ranking groups.
7. Train topology/case specialists.
8. Validate promoted actors on switch-level cases.

## Known Open Blockers

- Full GB/T pass/fail certification still needs grid-side reactive-current
  logging. Current fault results report `not_evaluated_no_grid_reactive_current`.
- Topology2 joint regulating+energy action still has a large Vdc proxy gap.
  Independent d-axis and energy sweeps are calibrated; joint interaction is not
  yet reliable enough for final direct-SAC claims.
- The interrupted full fault specialist run at
  `lab/results/hpt_case_specialists_20260717_011726` produced partial results
  only. It should be treated as diagnostic data, not a completed campaign.
