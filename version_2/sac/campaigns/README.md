# Campaigns

## Canonical Family Campaign

`run_hpt_family_specialist_matrix.py` trains one unchanged actor for an entire
fault family and evaluates it over a depth-duration matrix. It is the only
maintained high-level SAC campaign.

```powershell
$env:PYTHONPATH = "src"
py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix --help
```

All `family_seed_before_sac` rows must share one seed checkpoint and all
`family_sac_after_finetune` rows must share one SAC checkpoint. A matrix made
from one actor per cell is not family-specialist evidence.

## Supporting Modules

- `run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py`: maintained shared helpers
  for family datasets, training, and boundary evaluation. It is not a second
  canonical campaign.
- `tune_hpt_conventional_dq_profile.py`: reproducible strong-dq profile sweep.
- `summarize_hpt_boundary_run.py`: produces compact boundary summaries.

Older stage, fixed-action, trust-region, reviewer-only, and overnight runners
were removed on 2026-08-03. Their generated results remain under `lab/results/`.
