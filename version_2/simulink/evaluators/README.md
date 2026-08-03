# Evaluators

- `eval_hpt_v2_control_comparison.m`: canonical strong-dq, trajectory, and SAC
  switch-level comparison with voltage-survival and full-FRT diagnostic fields.
- `eval_hpt_v2_sac_single_case.m`: single-case trace export used by paper plots.

Promotion decisions must come from these switch-level evaluators. Proxy scores
and the removed raw-smoke evaluator are not promotion evidence.
