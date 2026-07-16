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

## Next Engineering Step

Use `run_hpt_sac_pipeline.py` for repeatable launches:

```powershell
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --list
py -3.8 -m version_2.sac.run_hpt_sac_pipeline --stage fault-specialists-smoke
```

Before another full 8-hour campaign, the next code work should be:

1. Add grid-side current/reactive-current logging to the switch-level evaluator.
2. Replace the additive topology2 FRT proxy Vdc approximation with a joint
   lookup/regression model over regulating and energy actions.
3. Resume specialist training only after a short smoke case proves the new
   scoring and proxy gap are consistent.
