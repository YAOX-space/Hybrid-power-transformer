# Curated Family Data

This directory contains only artifacts on the promoted r6 dependency chain.
See `../manifests/data_manifest.json` for source paths, SHA-256 hashes, file
roles, and format checks.

- `raw_switch_level/`: nine source trajectories used by the support anchor;
- `support_anchor/`: base and final behavior-support datasets;
- `train/`: the online-proxy SAC training protocol (no saved replay buffer);
- `validation/`: targeted and expanded switch-level evaluation tables;
- `holdout/`: currently documents the missing untouched holdout.
