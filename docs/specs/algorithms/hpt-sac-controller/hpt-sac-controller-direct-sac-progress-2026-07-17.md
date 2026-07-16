# HPT Direct SAC Progress - 2026-07-17

## Interruption Handling

The full fault-specialist run was interrupted while evaluating
`topology2 / fault / sag_0p75`.

Interrupted run directory:

- `lab/results/hpt_case_specialists_20260717_011726`

The residual Python and MATLAB processes were stopped.  The run produced 11
diagnostic fault-specialist records before interruption.  It should not be
treated as a completed campaign.

## Engineering Cleanup

Added an explicit package map and workflow for `version_2/sac`:

- `version_2/sac/README.md`
- `version_2/sac/experiments/README.md`
- `version_2/sac/run_hpt_sac_pipeline.py`

The scripts were not moved yet because current tests, wrappers, and commands
import modules directly from `version_2.sac`.  Any future folder migration should
leave compatibility wrappers.

## Current Technical Status

Completed:

- Full switch-level FRT calibration matrix exists for topology1/topology2,
  LVRT depths `0.20/0.50/0.75/0.85/0.90 pu`, and HVRT depths
  `1.10/1.20/1.25/1.30 pu`.
- The FRT proxy is calibrated for independent d-axis regulation and independent
  energy-bridge sweeps.
- FRT teacher traces were generated for 18 topology/fault cases.
- Fault specialist training now uses FRT teacher traces instead of steady traces.

Partial result from the interrupted run:

- Topology1 LVRT specialists generally improved the switch-level score and Vdc
  survival but still failed full FRT criteria.
- Topology1 HVRT specialists did not consistently improve score.
- Topology2 sag `0.20/0.50 pu` improved some metrics but still failed.

Not completed:

- No fault specialist actor was promoted from the interrupted full run.
- Full GB/T pass/fail certification is still provisional because grid-side
  reactive-current logging is missing.
- Topology2 joint regulating+energy proxy behavior still has a large Vdc gap and
  needs a joint-interaction model before proxy-only training can be trusted.

## Proxy Calibration Update

The resumed full fault-specialist run was stopped at the user's request and the
work shifted back to proxy calibration.

Stopped run:

- `lab/results/hpt_case_specialists_20260717_011726`
- completed `13 / 18` fault specialist records before stop
- no specialist actor was promoted

Proxy changes:

- Added `fault_reg_response_table` from all FRT `reg_sweep` rows, including
  nonzero `reg_q` cases.
- Added `fault_joint_response_table` from FRT `joint_sweep` rows, representing
  the coupled `(reg_d, energy_d, energy_q)` response.
- Updated the proxy environment to use calibrated multi-axis lookup tables for
  fault LV/Vdc targets.
- Updated the FRT proxy-gap measurement so it evaluates the same joint lookup
  model that the environment uses.

Latest matrix-calibrated in-sample gap:

- topology2 `joint_sweep` Vdc MAE improved from about `0.40-0.45 pu` to `0`.
- topology2 `reg_q_sweep` Vdc MAE improved from about `0.26-0.33 pu` to `0`.
- topology1 `joint_sweep` and `reg_q_sweep` are also matched in-sample.

Important limitation:

This is a calibration-matrix in-sample match, not yet a generalization proof.
The next proxy step should create a small holdout or newly sampled topology2
joint-action matrix to verify interpolation between the calibrated points.

## Next Engineering Step

Use `run_hpt_sac_pipeline.py` for repeatable launches:

```powershell
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --list
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --stage fault-specialists-smoke
```

Before another full 8-hour campaign, the next code work should be:

1. Add grid-side current/reactive-current logging to the switch-level evaluator.
2. Validate the new joint lookup proxy on held-out or newly sampled topology2
   joint regulating/energy actions.
3. Resume specialist training only after a short smoke case proves the new
   scoring and proxy gap are consistent.
