# Cleanup Inventory — 2026-06-25 (conservative, move-only, nothing deleted)

> Conservative closeout: **no file deleted, no result value changed, no retrain, no full-320 re-run.**
> Uncertain / stale items were **moved** (not deleted) to dated `archive_2026-06-25/` dirs. Tests stay
> green (`pytest tests -p no:cacheprovider -q` = 134 passed). Certified result of record is unchanged:
> residual SAC mi=14 **strict 53.1% / no-fail 89.4% / fail 10.6%** (170/34/116); dq mi=7 39.7/68.1/31.9.

## Legend
`KEEP_CURRENT` active main line · `KEEP_REFERENCE` historical/legacy kept in place · `ARCHIVE_LOG` training/intermediate log (moved) · `ARCHIVE_OLD_RESULT` superseded result (moved) · `ARCHIVE_OBSOLETE_SCRIPT` dead diagnostic (moved) · `REVIEW_MANUAL` uncertain, kept in place, flagged.

## What was MOVED this round (move-only; recover with a `git mv` back or filesystem move)

### → `lab/results/archive_2026-06-25/`  (ARCHIVE_LOG)
- Standalone logs: `p3_resweep5_20260622_122823.log`, `p3_sweep_20260622_031554.log`, `p3fix_20260622_220413.log`
- Orchestrator logs (6): `p3par_20260623_{010704,011150,011635,013726,014536,015450}_orchestrator.log`
- Resume logs (2): `p3par_20260623_015450_resume.log`, `_resume2.log`
- Early-interrupted run job dirs (4): `p3par_20260623_{011150,011635,013726,014536}_jobs/`
  - **KEPT in place**: `p3par_20260623_015450_jobs/` — the FINAL run; source of the convergence figure (`plot_p3_convergence.py` reads it).

### → `lab/simulink/archive_2026-06-25/`  (ARCHIVE_OBSOLETE_SCRIPT — 0 references in tests / active docs / active code)
- `diag_deepsag.m`, `w23_emt_crosscheck.m`, `w8_faithful_recovery.m`, `frt_v2_hlc_selftest.m`,
  `gen_fault_waveforms.m`, `make_subset.m`

## Classification of the rest (kept in place)

### Authoritative results — `lab/results/` (KEEP_CURRENT)
`p3_full320_sw_mi14.mat`, `p3_full320_sw_mi7.mat`, `p3_full320_switching_summary.json`,
`p3_scenario_faultparams.json`, `p3_resweep5_summary_v2.json`, `p3_full320_ode_proxy.json`,
`p3_sac_ode_proxy_convergence.csv`, `error_analysis_mi14_{failures.csv,summary.json}`,
`projection_offline_reactive_{check.csv,summary.json}`,
`projection_spotcheck_reactive.{mat,csv,json,_summary.json}`, `projection_spotcheck_diag.mat`,
`calib_{LVRT,HVRT}_scr{3,10}.mat`, `p3_calib_targets.json`, `figures/` (5 PNGs + PDF),
`frt_v2_spotcheck/` (12 gate MATs), `p3par_20260623_015450_jobs/` (convergence source).
All `.mat` carry `metrics_version='frt-v2'` (governance test passes).

### Already-isolated legacy — `lab/results/` (KEEP_REFERENCE, untouched)
`legacy_pre_audit/`, `legacy_pre_resweep/` — prior cleanups; remain as-is.

### Active source — `src/hpt_frt/` (KEEP_CURRENT)
- `common/`: `frt_v2.py`, `pu.py`, `sequence.py`
- `device/` evaluation+deploy: `frt_env.py`, `frt_env_v2.py`, `frt_metrics.py`, `residual_env.py`,
  `model_io.py`, `controller_registry.py`, `safety_projection.py`, `error_analysis_mi14.py`,
  `plot_p3_convergence.py`, `project_offline_check.py`, `eval_full320_ode.py`, `eval_resweep5.py`,
  `export_sac_actor.py`
- `device/` training pipeline (reproducibility): `train_common.py`, `train_experts.py`, `train_seeds.py`,
  `train_residual.py`, `train_single.py`, `run_sweep_parallel.py`, `export_experts.py`,
  `export_residual.py`, `gen_frt_scenarios.py`

### Active MATLAB — `lab/simulink/` (KEEP_CURRENT)
`frt_v2_evaluate.m`, `frt_v2_full320_switching.m`, `frt_v2_spotcheck.m`, `frt_v2_calibrate.m`,
`frt_v2_projected_spotcheck.m`, `frt_v2_golden_test.m`, `frt_v2_consistency_test.m`, `frt_v2_guard.m`,
`frt_v2_hlc.m`, `build_hpt_frt_full.m`, `pu_params.m`, `assert_metrics_version.m`, `controller_modes.m`

### Legacy guard — `lab/simulink/` (KEEP_REFERENCE, NOT a frt-v2 entry, not moved)
`validate_mode_full.m`, `run_spotcheck.m` — guarded (fail-fast); retained for history only.

### Phase-2 / B-stage (KEEP_REFERENCE)
`src/hpt_frt/network/*` (network test-bed + `report.md`); `lab/simulink/{build,run}_dual_*.m`,
`hpt_dual_*.slx`.

### Docs (KEEP_CURRENT)
`README.md`, `docs/FILE_GUIDE.md`, `docs/PROJECT_OVERVIEW.md`, `docs/FRT_SPEC.md`,
`docs/CONTROL_MODES.md`, `docs/FRT_V2_RESULTS_2026-06-23.md`, `docs/FRT_V2_ERROR_ANALYSIS_2026-06-24.md`,
`docs/FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md`, `docs/FRT_V2_PROJECTION_SPOTCHECK_2026-06-24.md`,
`docs/P3_SAC_CONVERGENCE_NOTE_2026-06-24.md`, `HPT_weekly_group_meeting_20260625.tex`, `tests/`.

### Docs (KEEP_REFERENCE — historical audit, kept in place because linked from 5 active files)
`docs/AUDIT_2026-06-22.md`, `docs/CHANGE_REPORT_2026-06-22.md`, `docs/MIGRATION_INVENTORY_2026-06-22.md`
— superseded by the FRT_V2_* docs for current conclusions, but linked from README / CONTROL_MODES /
PROJECT_OVERVIEW / network report as the audit-of-record; **not moved** to avoid breaking those links.
Treat as history, not current conclusions.

## REVIEW_MANUAL (uncertain — kept in place, flagged for a human call)
- `lab/results/{experts_train.json, residual_train.json, seeds_train.json}` — per-trainer metadata,
  superseded by `p3_resweep5_summary_v2.json`; 0–1 references; archivable later but kept (small,
  training provenance).
- `lab/results/p3_calib_targets.json` — intermediate calibration target (0 refs), part of the
  calibration chain to `p3_scenario_faultparams.json`; kept for reproducibility.
- `src/hpt_frt/device/{env_compare.py, train_ab.py, train_frt_sac.py, gen_p1_figs.py}` — older
  diagnostics/variants still referenced (3–7 refs); not moved.
- `lab/simulink/{sim_compare.m, pu_selfcheck.m, gen_allctrl_figs.m}` — referenced (1–4 refs); not moved.

## Reproduce the current figures/analysis (all from existing files; no Simulink / no retrain)
```
$env:KMP_DUPLICATE_LIB_OK="TRUE"; $env:MKL_THREADING_LAYER="SEQUENTIAL"; $PY=".venv\Scripts\python.exe"
& $PY -m hpt_frt.device.plot_p3_convergence     # convergence fig + csv  (reads p3par_20260623_015450_jobs/)
& $PY -m hpt_frt.device.error_analysis_mi14      # 34-FAIL breakdown + 4 figs
& $PY -m hpt_frt.device.project_offline_check     # offline reactive intercept check
```
The certified switching full-320 (`frt_v2_full320_switching.m`) and the projected spotcheck
(`frt_v2_projected_spotcheck.m`) require MATLAB and are NOT part of this cleanup round.

Archive dirs (`*/archive_2026-06-25/`, `legacy_pre_audit/`, `legacy_pre_resweep/`) are **not** sources of
any current frt-v2 conclusion.
