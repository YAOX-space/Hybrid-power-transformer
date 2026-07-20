# Version 2 HPT Research Workspace

`version_2` is the active research workspace for the switch-level Hybrid Power
Transformer RL/FRT effort.

Canonical areas:

- `sac/` - Python proxy environment, SAC/offline training, trajectory
  specialists, validation runners, and experiment metadata helpers.
- `simulink/` - switch-level topology models, MATLAB collectors, evaluators,
  sweeps, tests, and active actor interface files.
- `data/` - generated or local model/data artifacts; do not rely on committing
  large payloads.
- `docs/autonomy/` - research charter, policies, roadmap, logs, and templates
  for long-running Codex work.

First smoke checks:

```powershell
py -3 -m version_2.sac.smoke_matlab_engine --dry-run
py -3 -m version_2.sac.smoke_matlab_engine --runner engine --test interface
```

Use `version_2.sac.run_hpt_sac_pipeline --list` to inspect repeatable research
stages before launching long experiments.
