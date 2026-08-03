# Version 2 Archive

This directory is read-only storage for superseded Version 2 artifacts. Active
experiments must write family-specific data, proxy calibrations, checkpoints,
and results under `version_2/experts/<expert_id>/`.

`legacy_data/` contains the former `version_2/data/` tree. It is retained only
for historical reproduction and selective migration into an expert workspace.
Do not use it as an implicit input to a new experiment.
