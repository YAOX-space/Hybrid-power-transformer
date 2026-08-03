# Stage-6 Fault-Family Repair Runbook

Date: 2026-07-27

This runbook turns the Stage-6 research plan into executable batches.  The
current user-scoped goal is to repair the paper evidence around three hard
gates: 12 representative specialists rather than 8, SAC-vs-conventional
switch-level superiority, and fault-family rather than single-point claims.
Teacher replay / BC / DAgger provenance should still be recorded honestly, but
that ablation is no longer a required completion gate.

## Artifacts

- Planning document:
  `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-fault-family-repair-plan-2026-07-27.md`
- Target 12-case matrix:
  `version_2/sac/experiments/stage6_fault_family_experiment_matrix_20260727.csv`
- Current executable 10-case recheck manifest:
  `version_2/sac/experiments/stage6_recheck_manifest_current10_20260727.csv`

## Stage 6A: Freeze Current Evidence

Smoke check:

```powershell
py -3.8 -m version_2.sac.smoke_matlab_engine --dry-run
```

Recheck the current executable 10 cases:

```powershell
py -3.8 -m version_2.sac.validate_hpt_accepted_specialists `
  --manifest version_2/sac/experiments/stage6_recheck_manifest_current10_20260727.csv `
  --run-id hpt_stage6_recheck_current10_20260727 `
  --timeout-s 1200
```

Expected output goes under `lab/results/` with a CSV and Markdown report.  The
result is diagnostic until the two missing topology1 HVRT unbalanced cases are
trained or explicitly reported as gaps.

## Stage 6A Gap Training: Topology1 A/AB-HVRT

The first negative-command attempt was retired: it drove the A-HVRT recovery
voltage too low and was worse than conventional control.  The balanced
topology1 HVRT actor was then probed as a fallback and survived A/AB-HVRT, but
did not beat conventional.  The next repair must therefore be score-aware
positive-regulation search, not blind negative-d training.

Run a CEM trajectory search for topology1 A-HVRT first:

```powershell
py -3.8 -m version_2.sac.search_hpt_frt_trajectory_cem `
  --run-id hpt_stage6_t1_a_hvrt110_cem_20260727 `
  --topology topology1 `
  --fault-pu 1.10 `
  --fault-phase-pu 1.10 1.00 1.00 `
  --duration-s 0.060 `
  --fault-start 0.035 `
  --fault-settle-s 0.020 `
  --case-name topology1_a_hvrt110_60ms_stage6 `
  --iterations 3 `
  --population 48 `
  --switch-top-k 6 `
  --return-to-zero `
  --timeout-s 1200
```

Then run the same style for topology1 AB-HVRT:

```powershell
py -3.8 -m version_2.sac.search_hpt_frt_trajectory_cem `
  --run-id hpt_stage6_t1_ab_hvrt110_cem_20260727 `
  --topology topology1 `
  --fault-pu 1.10 `
  --fault-phase-pu 1.10 1.10 1.00 `
  --duration-s 0.060 `
  --fault-start 0.035 `
  --fault-settle-s 0.020 `
  --case-name topology1_ab_hvrt110_60ms_stage6 `
  --iterations 3 `
  --population 48 `
  --switch-top-k 6 `
  --return-to-zero `
  --timeout-s 1200
```

If CEM finds a switch-level trajectory that passes and beats conventional,
train a state-feedback actor from that accepted trajectory with
`run_hpt_trajectory_specialist_campaign`.  If CEM only finds voltage-survival
without beating conventional, keep the fallback rows and mark the result as a
score gap.

## Stage 6B: SAC-vs-Conventional Promotion Table

After the 12 center cases are complete, recheck each promoted SAC actor against
the same conventional dq baseline and record one of:

- `sac_beats_conventional`
- `sac_survives_only`
- `sac_fails_voltage_survival`

Promotion requires switch-level voltage survival and a lower switch-level score
than conventional.  Teacher replay / BC / DAgger ablations may be added later
as supporting analysis, but they are not required for this user-scoped result.

## Stage 6C: Fault-Family Pilot

Start with these families:

1. topology1 balanced LVRT;
2. topology1 A-HVRT;
3. topology2 A-HVRT;
4. topology2 AB-HVRT.

For LVRT, use train depth `0.85/0.90/0.95 pu` and duration
`40/60/80/120 ms`; holdout uses `0.875/0.925 pu` and `100/160 ms`.

For HVRT, use train depth `1.05/1.10/1.15 pu` and duration
`40/60/80/120 ms`; holdout uses `1.075/1.125 pu` and `100/160 ms`.

Family claims require holdout evidence.  Without holdout, describe the actor as
case-specialized.

## Logging Rule

After each batch, append the command, result directory, pass count, beat count,
failure reasons, and next action to:

`version_2/docs/autonomy/logs/research_log.md`
