SUPERSEDED models from the pre-checkpoint-fix sweeps (first in-distribution sweep + the second
held-out sweep that still had the best=0 / proxy>best pollution bug). PRESERVED, not deleted.
Specifically polluted (audit round-5 A): sac_sym_best (03:18 first sweep), sd_7_sym_best (05:04),
sd_123_sym_best (07:29) never re-saved because held-out sym proxy stayed 0 under `proxy>best`;
sd_2024_sym_best was never created. These do NOT correspond to the corrected re-run.
The corrected re-run (with CheckpointSelector: best=-inf, save-on-first, sidecars) regenerates a
clean, fully-traceable model set in data/models/.
