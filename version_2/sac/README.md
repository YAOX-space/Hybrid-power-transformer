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
- `build_hpt_boundary_full_action_dataset.py` - builds the boundary-centered
  full-action dataset used to train direct actors against the conventional DQ
  baseline.
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
- `summarize_hpt_control_comparison.py` - summarizes switch-level legacy
  conventional, strong conventional, and SAC comparison CSVs.
- `validate_hpt_offline_actions_switchlevel.py` - promotes proxy-beating
  offline full-action candidates into switch-level fixed-action validation
  against the traditional baseline.

Training:

- `train_hpt_voltage_sac.py` - baseline SAC training on the proxy.
- `pretrain_hpt_actor_bc.py` - behavior-cloning and mixed teacher pretraining.
- `train_hpt_offline_full_action_baselines.py` - TD3+BC-style and
  AWAC/IQL-style contextual offline baselines from the full-action boundary
  dataset.  This is the stronger behavior-constrained route used when ordinary
  proxy SAC drifts outside switch-level support.
- `train_hpt_case_specialists.py` - topology/case specialist training and
  switch-level promotion gate.
- `train_hpt_learned_proxy.py` - learned proxy experiments.
- `train_hpt_safety_classifier.py` - safety classifier experiments.

Export and deployment:

- `export_hpt_sac_actor.py` - exports a Python actor to Simulink MAT weights.

Long-running experiments:

- `legacy/overnight_hpt_sac_simulink_optimize.py`
- `legacy/overnight_hpt_sac_steptrace_specialists.py`
- `legacy/overnight_hpt_case_specialists.py`

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
6. Do not commit or depend on generated caches such as `__pycache__/`, `slprj/`,
   or `*.slxc`.
7. The only active Simulink actor MAT files expected in
   `version_2/simulink/` are `hpt_sac_actor_weights.mat` and
   `hpt_sac_actor_weights_dynamic.mat`.  Other candidate MAT snapshots should
   live in timestamped result directories, not beside the model scripts.
8. Full-action data must keep command and response semantics separate:
   `cmd_m_*` fields are controller/actor commands, while `meas_*` fields are
   reconstructed switch-level responses.  The legacy `reg_d_mean`,
   `reg_q_mean`, `energy_d_mean`, and `energy_q_mean` fields are treated as
   response-compatible fields; action labels must come from `raw_m_*` or
   `cmd_m_*`.

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
7. Run legacy-conventional/strong-conventional/SAC switch-level comparison.
8. Build the boundary-centered full-action dataset.
9. Run BC-only reproduction before any long SAC training.
10. Run offline full-action baselines (`offline-full-action-smoke`, then
    `offline-full-action-group-boundary`) to check whether behavior-constrained
    per-topology/per-fault policies can improve on conventional DQ without
    leaving the calibrated switch-level support.  The pooled
    `offline-full-action-boundary` stage is retained as a diagnostic, but it is
    weaker because topology2 DC-link behavior can poison topology1/HVRT gains.
11. Run `offline-full-action-switch-validate` for proxy-beating candidates.
    Proxy-gate success is not a final result until it survives this switch-level
    gate.
12. Train topology/case specialists only after the offline/proxy and
    switch-level fixed-action gates expose a viable candidate.
13. Validate promoted actors on switch-level cases.

## Known Open Blockers

- Grid-side current logging is now available in the switch-level models as
  `Igrid_abc`, and the FRT evaluators compute dq reactive-current support,
  response, and grid-current limit metrics.  Some shallow cases can still report
  `not_evaluated_no_sustained_reactive_demand_after_delay` when the measured
  post-delay droop demand is below the configured tolerance.
- The Python proxy now has the same reward-side hooks for these grid-current
  metrics.  Re-run the FRT calibration matrix and
  `calibrate_hpt_frt_proxy_from_matrix.py` before trusting SAC training that
  optimizes reactive-current support or grid-current limits.
- `verify_hpt_proxy_rollout_alignment.py` checks the actual
  `HPTVoltageSACEnv` rollout against switch-level matrix rows.  Use it after
  every calibration refresh; lookup/reward alignment alone is not enough to
  certify the SAC training environment.
- The strong `conventional_dq` baseline is topology-aware: topology1 uses the
  tuned physical `VoltageRegulator`/`EnergyController` path, while topology2 uses
  the calibrated rule/dq current-loop fallback because the physical topology2
  `EnergyController` DC-link outer-loop sign still collapses the DC link.
- Topology2 joint regulating+energy action still has a large Vdc proxy gap.
  Independent d-axis and energy sweeps are calibrated; joint interaction is not
  yet reliable enough for final direct-SAC claims.
- Offline full-action AWAC proxy-gate gains currently transfer only partially
  to switch-level Simulink.  In the latest topology1/HVRT gate, only
  `hvrt_200ms_1p120pu` beat conventional after fixed-action validation.  The
  main remaining mismatch is energy-branch action semantics and recovery-window
  voltage behavior.
- Energy-branch command and response can have different signs/magnitudes in
  switch-level validation.  For example, a fixed-action request near
  `cmd_m_energy_d=+0.07` in topology2/HVRT can produce a measured effective
  response near `meas_energy_d=-0.02`.  Do not train new SAC policies from a
  dataset that lacks both `cmd_m_energy_d_mean` and `meas_energy_d_mean`.
- The interrupted full fault specialist run at
  `lab/results/hpt_case_specialists_20260717_011726` produced partial results
  only. It should be treated as diagnostic data, not a completed campaign.

## Cleanup Notes

The version 2 tree was cleaned so that the top-level `sac/` package contains
current workflow modules, while old overnight runners are isolated under
`version_2/sac/legacy/`.

The following files are intentionally not part of the maintained source tree:

- Python bytecode caches: `__pycache__/`, `*.pyc`
- Simulink generated caches: `slprj/`, `*.slxc`
- one-off or broken MAT candidates beside the Simulink scripts

The following Simulink sweep scripts are still in `version_2/simulink/` because
they depend on that directory layout to find `topoloty1/` and `topology2/`.
Treat them as diagnostics/calibration helpers, not as the main experiment
entrypoint:

- `sweep_hpt_v2_sac_action_response.m`
- `sweep_hpt_v2_sac_energy_response.m`
- `sweep_hpt_v2_reg_energy_response.m`
- `sweep_hpt_v2_fault_fixed_reg_response.m`
- `sweep_hpt_v2_topology2_energy_signs.m`
- `sweep_hpt_v2_topology2_fault_fixed_reg.m`
