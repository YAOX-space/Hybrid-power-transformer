# Campaign Runners

Long or historical orchestration scripts. The current single-case trajectory
campaign remains at the top level for direct use.

## Maintained Campaigns

- `run_hpt_family_specialist_matrix.py`
  - Purpose: train and validate one actor for a whole fault family.  This is the
    canonical campaign when a depth-duration matrix must be interpreted as
    family-specialist evidence rather than case-specific actor evidence.
  - It collects strong-dq switch-level traces for all training cases, merges
    them into one family anchor dataset, trains one family seed actor, optionally
    fine-tunes one SAC actor, and validates the unchanged actor over the
    evaluation matrix.
  - The output CSV records `actor_model` and `actor_archive`; all rows for
    `family_seed_before_sac` must share one seed model and all rows for
    `family_sac_after_finetune` must share one SAC model.

- `sweep_hpt_t2_lvrt_phase_grid.py`
  - Purpose: small switch-level teacher grid around the current topology2
    LVRT 0.90 pu / 60 ms phase-aware fault/recovery trajectory boundary.
  - It generates `fault_recovery` trajectory MAT files, validates each one via
    `version_2.sac.validate_hpt_trajectory_switchlevel`, and writes ranked
    CSV/JSON summaries under `lab/results/<campaign_id>/`.
  - It does not modify accepted matrices, train actors, or update Simulink
    models. Use it before spending time on another topology2 actor campaign.

Canonical smoke command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix `
  --run-id hpt_family_specialist_smoke_t2_a_lvrt_20260801_r1 `
  --topology topology2 --category LVRT --phase-key a `
  --train-depths 0.90 --train-durations-ms 60 `
  --eval-depths 0.90 --eval-durations-ms 60 `
  --bc-epochs 5 --sac-steps 1

py -3 -m version_2.sac.campaigns.sweep_hpt_t2_lvrt_phase_grid `
  --campaign-id hpt_t2_lvrt090_phase_grid_smoke_20260721 `
  --case-limit 6
```
