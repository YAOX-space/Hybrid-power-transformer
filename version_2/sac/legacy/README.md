# Legacy SAC Experiment Runners

These scripts are preserved for reproducibility only.  They were useful during
the early Simulink-in-the-loop search, but they are no longer the recommended
entry points for version 2 experiments.

Use the pipeline helper instead:

```powershell
py -3 -m version_2.sac.run_hpt_sac_pipeline --list
```

Legacy runners kept here:

- `overnight_hpt_case_specialists.py`
- `overnight_hpt_sac_simulink_optimize.py`
- `overnight_hpt_sac_steptrace_specialists.py`

They now locate the repository root dynamically, so they can still be run from
the archive location if an old experiment must be reproduced.
