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


def _matlab_batch(statement: str) -> tuple[str, ...]:
    return ("matlab", "-batch", statement)


def build_stages(matrix_csv: str | None, trace_csv: str | None) -> dict[str, Stage]:
    matrix = Path(matrix_csv) if matrix_csv else _latest("frt_calibration_matrix_full_all_*.csv")
    trace = Path(trace_csv) if trace_csv else _latest("frt_calibration_traces_full_all_*.csv")

    frt_matrix_cmd = _matlab_batch(
        "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); "
        "hpt_calib_mode='full'; hpt_calib_topology='all'; "
        "collect_hpt_v2_frt_calibration_matrix;"
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
                "version_2.sac.calibrate_hpt_frt_proxy_from_matrix",
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
                "version_2.sac.measure_hpt_frt_proxy_gap",
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
                "version_2.sac.build_hpt_frt_teacher_traces",
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
                "version_2.sac.measure_hpt_reward_alignment",
                "--matrix-csv",
                str(matrix),
            ),
        ),
        "fault-specialists-smoke": Stage(
            name="fault-specialists-smoke",
            description="Run a short topology2 sag_0p90 specialist smoke test.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.train_hpt_case_specialists",
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
        "fault-specialists-full": Stage(
            name="fault-specialists-full",
            description="Run the full per-topology/per-fault specialist campaign.",
            command=(
                sys.executable,
                "-m",
                "version_2.sac.train_hpt_case_specialists",
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
