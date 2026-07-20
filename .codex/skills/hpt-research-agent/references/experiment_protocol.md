# Experiment Protocol

Before running:

- State hypothesis, success metric, baseline, command, expected runtime, and
  output directory.
- Capture current Git metadata.
- Prefer dry-run/list commands before long runs.

During running:

- Save stdout/stderr to the run folder.
- Write a config snapshot and metadata.
- Preserve failed outputs.

After running:

- Summarize pass/fail, metrics, artifacts, and failure reason.
- Compare against conventional dq and previous best where applicable.
- Decide one next action: promote, rerun, debug, ablate, or retire as
  diagnostic.

Minimum final-evidence metrics:

- voltage survival and full FRT pass;
- control score;
- LV/HV recovery mean;
- DC-link min/max;
- current limit metrics;
- envelope and recovery violation magnitude/duration.
