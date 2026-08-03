# Legacy Version 2 Data

This directory is the archived copy of the former `version_2/data/` tree,
moved on 2026-08-03. Its internal files are ignored by Git because they contain
approximately 120 MB of generated datasets and model checkpoints.

Contents include early switch-level rollout datasets, learned-proxy and safety
classifier experiments, full-action boundary datasets, and superseded model
checkpoints. They are not part of the current 12-expert training pipeline.

Use `inventory.csv` to identify and verify an artifact before selectively
migrating it into `version_2/experts/<expert_id>/`. New experiments must not
write here.
