"""Canonical launcher for version 2 HPT SAC research stages.

This module does not replace the individual scripts.  It gives the project one
stable place to list, dry-run, and launch the repeatable stages so long-running
experiments are easier to audit.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIMULINK = ROOT / "version_2" / "simulink"
RESULTS = ROOT / "lab" / "results"
FRT_MATRIX_DIR = RESULTS / "hpt_v2_frt_calibration_matrix"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"


@dataclass(frozen=True)
class Stage:
    name: str
    description: str
    command: tuple[str, ...]


def _latest(pattern: str) -> Path:
    matches = sorted(FRT_MATRIX_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not matches:
        raise FileNotFoundError(f"No files match {FRT_MATRIX_DIR / pattern}")
    return matches[-1]


def _latest_control(pattern: str) -> Path:
    matches = sorted(
        (p for p in CONTROL_DIR.glob(pattern) if "_summary" not in p.stem),
        key=lambda p: p.stat().st_mtime,
    )
    if not matches:
        raise FileNotFoundError(f"No files match {CONTROL_DIR / pattern}")
    return matches[-1]


def _matlab_batch(statement: str) -> tuple[str, ...]:
    return ("matlab", "-batch", statement)


def build_stages(matrix_csv: str | None, trace_csv: str | None) -> dict[str, Stage]:
    matrix = Path(matrix_csv) if matrix_csv else _latest("frt_calibration_matrix_full_all_*.csv")
    trace = Path(trace_csv) if trace_csv else _latest("frt_calibration_traces_full_all_*.csv")
    expanded_matrix = _latest("frt_calibration_matrix_expanded_full_holdout_*.csv")
    conventional_boundary = _latest_control("control_comparison_*conventional_boundary*.csv")

    frt_matrix_cmd = _matlab_batch(
        "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); "
        "hpt_calib_mode='full'; hpt_calib_topology='all'; "
        "run(fullfile(pwd,'collectors','collect_hpt_v2_frt_calibration_matrix.m'));"
    )

    return {
        "frt-matrix": Stage(
            name="frt-matrix",
            description="Collect full switch-level FRT calibration matrix.",
            command=frt_matrix_cmd,
        ),
        "frt-proxy-calibrate": Stage(
            name="frt-proxy-calibrate",
            description="Merge the FRT calibration matrix into hpt_proxy_calibration.json.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.calibration.calibrate_hpt_frt_proxy_from_matrix",
                "--matrix-csv",
                str(matrix),
            ),
        ),
        "frt-proxy-gap": Stage(
            name="frt-proxy-gap",
            description="Measure proxy-vs-switch-level FRT gap.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.calibration.measure_hpt_frt_proxy_gap",
                "--matrix-csv",
                str(matrix),
            ),
        ),
        "frt-proxy-rollout-alignment": Stage(
            name="frt-proxy-rollout-alignment",
            description="Verify actual HPTVoltageSACEnv rollouts against switch-level matrix rows, including timestep envelope metrics.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.calibration.verify_hpt_proxy_rollout_alignment",
                "--matrix-csv",
                str(matrix),
            ),
        ),
        "frt-teacher-traces": Stage(
            name="frt-teacher-traces",
            description="Build per-step FRT teacher traces from calibrated matrix outputs.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.datasets.build_hpt_frt_teacher_traces",
                "--matrix-csv",
                str(matrix),
                "--trace-csv",
                str(trace),
            ),
        ),
        "reward-alignment": Stage(
            name="reward-alignment",
            description="Measure whether calibrated proxy reward ranks actions like switch-level FRT metrics.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.calibration.measure_hpt_reward_alignment",
                "--matrix-csv",
                str(matrix),
            ),
        ),
        "reward-correction": Stage(
            name="reward-correction",
            description="Train and evaluate a switch-level reward correction model for proxy action ranking.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.calibration.train_hpt_reward_correction",
            ),
        ),
        "control-comparison-smoke": Stage(
            name="control-comparison-smoke",
            description="Run a switch-level legacy/strong-conventional/SAC comparison for topology1 sag_0p90.",
            command=_matlab_batch(
                "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); "
                "hpt_compare_topology='topology1'; "
                "hpt_compare_scenario_type='fault'; "
                "hpt_compare_case_name='sag_0p90'; "
                "hpt_compare_modes={'legacy_conventional','conventional_dq','sac_actor_raw_guard0'}; "
                "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"
            ),
        ),
        "control-comparison-summary": Stage(
            name="control-comparison-summary",
            description="Summarize the latest switch-level control comparison CSV.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.summaries.summarize_hpt_control_comparison",
            ),
        ),
        "fault-specialists-smoke": Stage(
            name="fault-specialists-smoke",
            description="Run a short topology2 sag_0p90 specialist smoke test.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_case_specialists",
                "--topology",
                "topology2",
                "--scenario-type",
                "fault",
                "--case-name",
                "sag_0p90",
                "--epochs",
                "20",
                "--repeat",
                "64",
                "--energy-enable",
                "1.0",
            ),
        ),
        "boundary-full-action-dataset": Stage(
            name="boundary-full-action-dataset",
            description="Build boundary-centered full-action dataset for beat-conventional SAC.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.datasets.build_hpt_boundary_full_action_dataset",
                "--conventional-csv",
                str(conventional_boundary),
                "--matrix-csv",
                str(expanded_matrix),
                "--candidate-selection",
                "near_boundary_depths",
            ),
        ),
        "boundary-bc-reproduction-smoke": Stage(
            name="boundary-bc-reproduction-smoke",
            description="BC-only full-action reproduction gate on one topology1 LVRT boundary group.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_fault_specialists_vs_baseline",
                "--baseline-csv",
                str(conventional_boundary),
                "--run-id",
                "hpt_boundary_bc_reproduction_smoke",
                "--topology",
                "topology1",
                "--category",
                "LVRT",
                "--duration-ms",
                "80",
                "--max-specialists",
                "1",
                "--steps",
                "0",
                "--bc-warmstart-epochs",
                "40",
                "--bc-episodes-per-scenario",
                "2",
                "--bc-teacher-source",
                "conventional_csv",
            ),
        ),
        "boundary-sac-regularized-smoke": Stage(
            name="boundary-sac-regularized-smoke",
            description="Short behavior-anchored full-action SAC smoke on one topology1 LVRT group.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_fault_specialists_vs_baseline",
                "--baseline-csv",
                str(conventional_boundary),
                "--run-id",
                "hpt_boundary_sac_regularized_smoke",
                "--topology",
                "topology1",
                "--category",
                "LVRT",
                "--duration-ms",
                "80",
                "--max-specialists",
                "1",
                "--steps",
                "1000",
                "--bc-warmstart-epochs",
                "80",
                "--bc-episodes-per-scenario",
                "2",
                "--bc-teacher-source",
                "conventional_csv",
                "--teacher-prior-weight",
                "30",
                "--learning-rate",
                "0.0001",
                "--ent-coef",
                "auto_0.1",
                "--behavior-anchor-epochs",
                "20",
                "--behavior-anchor-interval-steps",
                "100",
            ),
        ),
        "offline-full-action-smoke": Stage(
            name="offline-full-action-smoke",
            description="Train TD3+BC/AWAC-style offline full-action baselines on one boundary group.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_offline_full_action_baselines",
                "--run-id",
                "hpt_offline_full_action_smoke",
                "--topology",
                "topology1",
                "--category",
                "LVRT",
                "--duration-ms",
                "80",
                "--max-cases",
                "2",
                "--epochs",
                "300",
                "--batch-size",
                "32",
                "--algorithms",
                "auto",
                "--specialist-mode",
                "trajectory",
                "--controller-heads",
                "split",
            ),
        ),
        "offline-full-action-boundary": Stage(
            name="offline-full-action-boundary",
            description="Train offline full-action baselines on all selected boundary rows.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_offline_full_action_baselines",
                "--run-id",
                "hpt_offline_full_action_boundary",
                "--topology",
                "all",
                "--category",
                "all",
                "--duration-ms",
                "all",
                "--max-cases",
                "0",
                "--epochs",
                "500",
                "--batch-size",
                "64",
                "--algorithms",
                "auto",
                "--specialist-mode",
                "trajectory",
                "--controller-heads",
                "split",
            ),
        ),
        "offline-full-action-group-boundary": Stage(
            name="offline-full-action-group-boundary",
            description="Train one offline full-action specialist per topology/category/duration group.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_offline_full_action_baselines",
                "--run-id",
                "hpt_offline_full_action_group_boundary",
                "--topology",
                "all",
                "--category",
                "all",
                "--duration-ms",
                "all",
                "--max-cases",
                "0",
                "--epochs",
                "500",
                "--batch-size",
                "32",
                "--algorithms",
                "auto",
                "--specialist-mode",
                "trajectory",
                "--controller-heads",
                "split",
                "--group-specialists",
            ),
        ),
        "offline-full-action-switch-validate": Stage(
            name="offline-full-action-switch-validate",
            description="Validate proxy-beating offline full-action AWAC candidates in switch-level Simulink.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.validate_hpt_offline_actions_switchlevel",
                "--case-results-csv",
                str(RESULTS / "hpt_offline_full_action_group_boundary" / "case_results.csv"),
                "--run-id",
                "hpt_offline_full_action_switch_validation",
                "--topology",
                "topology1",
                "--category",
                "HVRT",
                "--algorithm-contains",
                "awac_style",
                "--max-cases",
                "8",
            ),
        ),
        "fault-specialists-full": Stage(
            name="fault-specialists-full",
            description="Run the full per-topology/per-fault specialist campaign.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_case_specialists",
                "--all-cases",
                "--scenario-type",
                "fault",
                "--max-specialists",
                "999",
                "--epochs",
                "60",
                "--repeat",
                "128",
                "--energy-enable",
                "1.0",
            ),
        ),
    }


def _format_command(command: tuple[str, ...]) -> str:
    return subprocess.list2cmdline(command)


def print_stages(stages: dict[str, Stage]) -> None:
    for stage in stages.values():
        print(f"{stage.name}: {stage.description}")
        print("  " + _format_command(stage.command))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List available stages and commands.")
    parser.add_argument("--stage", choices=None, help="Stage name to run.")
    parser.add_argument("--matrix-csv", help="Override FRT matrix CSV for dependent stages.")
    parser.add_argument("--trace-csv", help="Override FRT trace CSV for dependent stages.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without running it.")
    args = parser.parse_args()

    stages = build_stages(args.matrix_csv, args.trace_csv)
    if args.list or not args.stage:
        print_stages(stages)
        return 0

    if args.stage not in stages:
        valid = ", ".join(stages)
        raise SystemExit(f"Unknown stage {args.stage!r}. Valid stages: {valid}")

    stage = stages[args.stage]
    print(f"[{stage.name}] {stage.description}")
    print(_format_command(stage.command))
    if args.dry_run:
        return 0
    completed = subprocess.run(stage.command, cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
