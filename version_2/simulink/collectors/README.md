# Collectors

- `collect_hpt_v2_frt_calibration_matrix.m`: collect fixed and grouped
  switch-level calibration rows for proxy fitting.
- `collect_hpt_v2_trajectory_trace.m`: export per-control-step observations,
  commands, measured responses, and FRT metrics for a trajectory.

Run from `version_2/simulink` with
`run(fullfile(pwd,'collectors','<script>.m'))`. Older guard/energy/step teacher
collectors were removed; the trajectory collector owns the maintained trace
schema.
