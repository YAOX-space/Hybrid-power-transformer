# Version 2 HPT Research Workspace

`version_2` is the active switch-level HPT fault-family SAC workspace.

- `sac/`: family SAC environment, training, calibration, datasets, campaigns,
  and summaries.
- `experts/`: twelve canonical fault-family workspaces containing controller
  checkpoints, results, and promotion manifests.
- `simulink/`: two switch-level plants, collectors, evaluators, sweeps, and
  regression tests.
- `docs/autonomy/`: Git, experiment, debugging, migration, and paper policies.
- `archive/`: read-only historical artifacts excluded from the active pipeline.

Canonical commands:

```powershell
$env:PYTHONPATH = "src"
py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix --help
py -3 -m pytest tests -q
```

There are no compatibility wrappers for removed campaigns. Historical result
directories and manifests are evidence, not supported launch commands.
