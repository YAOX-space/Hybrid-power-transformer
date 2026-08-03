# Experiment Manifest Archive

This directory contains compact CSV/JSON manifests from previous experiment
stages. They are retained to connect reports, actor hashes, and generated
`lab/results/` artifacts. They are not an executable campaign registry and must
not be treated as the current accepted-controller manifest.

## Current Family Evidence

The maintained campaign is:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_family_specialist_matrix --help
```

The current frozen topology2 A-phase LVRT candidate is:

```text
data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip
SHA-256 44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5
```

Current evidence locations:

- Targeted family result and promotion status:
  `lab/results/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803/`
- Fresh unchanged-actor 10 x 6 switch-level recheck:
  `lab/results/hpt_family_specialist_t2_a_lvrt_r6_square60_currentwindow_20260803_r1/`
- Result: r6 46/60 voltage-survival versus strong dq 48/60, with three local
  dq-fail/r6-pass cells. This supports a local boundary-expansion claim only.

## Interpretation Rules

1. Manifests dated before the current evaluator/interface must be labeled
   historical or stale when cited.
2. A family matrix must use one unchanged checkpoint for every matrix cell.
3. Proxy-only results cannot promote an actor.
4. Voltage survival requires timestep envelope, recovery envelope, DC-link,
   and action-bound gates in the switch-level evaluator.
5. Full FRT additionally requires valid grid-current and reactive-current
   checks. No archived `accepted_specialists_*.csv` file overrides this rule.

## Why Files Remain Here

Failed, superseded, and interrupted manifests are negative evidence used by the
paper and debugging record. Deleting them would break provenance. New campaign
outputs belong in `lab/results/<run_id>/`; add a compact manifest here only when
it is needed by a maintained paper or promotion workflow.
