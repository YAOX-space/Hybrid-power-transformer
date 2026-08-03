# Actors

Active actor MAT files stay in the Simulink root because the MATLAB Function
controller loads:

- `hpt_sac_actor_weights.mat`
- `hpt_sac_actor_weights_dynamic.mat`

Old snapshots are kept under `archive/` for forensics only.  New experiment
snapshots should usually stay under their timestamped `lab/results/<run_id>/`
folder instead of being copied here.

