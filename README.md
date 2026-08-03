# Hybrid Power Transformer FRT Research

This repository studies switch-level fault ride-through control for two hybrid
power transformer (HPT) topologies. The active research line is under
`version_2/` and uses one state-feedback SAC actor per fault family, a calibrated
averaged proxy for training, and Simulink switch-level evaluation as the final
promotion gate.

Previous-generation `frt-v2` reports use three distinct governance metrics:
`strict_pass`, `no-fail` (also called `effective_pass`), and `NOT_EVALUATED`
(`NE`). They are not interchangeable and none is a certification rate. Those
legacy result metrics are retained for reproducibility but are separate from
the current `version_2` family-SAC evidence below.

## Active Research Line

- Plant models: `version_2/simulink/topoloty1/` and
  `version_2/simulink/topology2/`
- Canonical switch evaluator:
  `version_2/simulink/evaluators/eval_hpt_v2_control_comparison.m`
- Canonical family campaign:
  `version_2/sac/campaigns/run_hpt_family_specialist_matrix.py`
- SAC environment and trainer:
  `version_2/sac/hpt_voltage_sac_env.py` and
  `version_2/sac/offline/train_hpt_voltage_sac.py`
- Generated experiment outputs: `lab/results/`
- Trained Python actors: `data/models/`
- Paper and reviewer evidence: `paper/`

The current strongest topology2 A-phase LVRT family actor is
`data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`. It is a
research candidate, not a full-FRT-certified controller. On the current 10 x 6
switch-level matrix it passes 46/60 voltage-survival cases versus 48/60 for the
strong-dq baseline, while recovering three local cases that strong dq misses.
This is local boundary-expansion evidence, not global dominance.

## Canonical Commands

Inspect the family campaign without running MATLAB:

```powershell
$env:PYTHONPATH = "src"
py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix --help
```

Run Python regression tests:

```powershell
$env:PYTHONPATH = "src"
py -3 -m pytest tests -q
```

Run the switch-level controller evaluator from MATLAB:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"
```

## Evidence Boundaries

- A proxy result is training evidence only.
- A switch-level row is voltage-survival evidence only when the timestep
  voltage envelope, recovery envelope, DC-link bounds, and action bounds pass.
- Full FRT additionally requires grid-current limit and reactive-current
  support checks. The current family actor must not be described as full-FRT
  certified.
- Historical manifests under `version_2/sac/experiments/` and old outputs under
  `lab/results/` remain for provenance. They are not active entry points.

## Previous-Generation Code

`src/hpt_frt/`, `lab/simulink/`, and older reports document the earlier HPT/FRT
research generation. They are retained for reproducibility and comparison but
must not be mixed with the `version_2` evaluator, calibration, or promotion
claims. New work belongs in `version_2/`.

See `version_2/sac/README.md`, `version_2/simulink/README.md`, and
`version_2/docs/autonomy/` for the maintained workflow and migration policy.
