# Actor Storage Policy

This directory contains policy only; actor snapshots are no longer archived in
the source tree.

- Active MATLAB weights: `version_2/simulink/hpt_sac_actor_weights*.mat`
- Trained Python checkpoints: `data/models/`
- Per-run exported weights: `lab/results/<run_id>/`

The former `actors/archive/` directory was removed on 2026-08-03. Git history
retains those diagnostic snapshots.
