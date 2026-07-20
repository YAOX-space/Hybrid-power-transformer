# 30-Day Roadmap

Week 1: reproducible platform.

- Audit Git state and active entry points.
- Freeze a smoke-test baseline for Python and MATLAB Engine.
- Document current topology, controller interface, data contracts, and known
  blockers.
- Confirm conventional dq and current SAC validation commands.

Week 2: core experiments.

- Re-run baseline PI/conventional dq versus RL for topology1/topology2.
- Refresh FRT matrix, proxy calibration, reward alignment, and rollout
  alignment if interface changes touched observations, actions, or envelope
  metrics.
- Promote only switch-level-passing candidates.

Week 3: robustness and explanation.

- Run selected LVRT/HVRT depth-duration generalization.
- Add parameter/grid uncertainty only after Week 2 gates are stable.
- Analyze transfer failures and ablations.

Week 4: paper first draft.

- Produce IEEE-style introduction, method, experiment, discussion, limitations,
  and figure/table stubs.
- Link every quantitative claim to a committed run manifest or result report.
