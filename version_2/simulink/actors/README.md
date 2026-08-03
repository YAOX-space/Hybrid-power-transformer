# Actor Storage Policy

This directory contains deployment policy only; expert checkpoints are stored
with their fault-family workspace.

- Active MATLAB weights: `version_2/simulink/hpt_sac_actor_weights*.mat`
- Trained Python checkpoints: `version_2/experts/<expert_id>/models/`
- Per-run exported weights: `version_2/experts/<expert_id>/results/<run_id>/`

The former `actors/archive/` directory was removed on 2026-08-03. Git history
retains those diagnostic snapshots.
