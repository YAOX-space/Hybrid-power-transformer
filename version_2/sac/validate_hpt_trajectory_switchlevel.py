"""Validate time-varying HPT action trajectories in switch-level Simulink.

This runner is the first dynamic-control gate after fixed-action validation.
It generates a trajectory MAT file, runs ``eval_hpt_v2_control_comparison``
with ``trajectory_action`` mode, and compares the waveform-level result against
both ``conventional_dq`` and a fixed action with the same target command.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .build_hpt_action_trajectory import TrajectorySpec, make_trajectory, write_csv, write_mat
from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
SIMULINK_DIR = ROOT / "version_2" / "simulink"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def latest_control_csv(before: set[Path]) -> Path:
    after = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    all_files = sorted(after, key=lambda p: p.stat().st_mtime)
    if not all_files:
        raise FileNotFoundError(f"No control comparison CSVs under {CONTROL_DIR}")
    return all_files[-1]


def result_by_mode(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("mode", ""): row for row in rows}


def score_improved(policy: dict[str, str], baseline: dict[str, str]) -> bool:
    ps = to_float(policy.get("control_score"))
    bs = to_float(baseline.get("control_score"))
    return math.isfinite(ps) and math.isfinite(bs) and ps < bs


def summarize_modes(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_mode = result_by_mode(rows)
    baseline = by_mode.get("conventional_dq", {})
    fixed = by_mode.get("fixed_action", {})
    traj = by_mode.get("trajectory_action", {})
    fixed_pass = truthy(fixed.get("voltage_survival_pass", ""))
    traj_pass = truthy(traj.get("voltage_survival_pass", ""))
    baseline_pass = truthy(baseline.get("voltage_survival_pass", ""))
    summary = {
        "baseline_voltage_pass": baseline_pass,
        "fixed_voltage_pass": fixed_pass,
        "trajectory_voltage_pass": traj_pass,
        "fixed_beats_baseline": bool(
            (fixed_pass and not baseline_pass)
            or (fixed_pass and baseline_pass and score_improved(fixed, baseline))
        ),
        "trajectory_beats_baseline": bool(
            (traj_pass and not baseline_pass)
            or (traj_pass and baseline_pass and score_improved(traj, baseline))
        ),
        "trajectory_score": to_float(traj.get("control_score")),
        "fixed_score": to_float(fixed.get("control_score")),
        "baseline_score": to_float(baseline.get("control_score")),
        "trajectory_lv_mean": to_float(traj.get("lv_mean")),
        "trajectory_lv_recovery_mean": to_float(traj.get("lv_recovery_mean")),
        "trajectory_vdc_min": to_float(traj.get("vdc_min")),
        "trajectory_vdc_max": to_float(traj.get("vdc_max")),
        "trajectory_reason": traj.get("voltage_survival_reason", traj.get("full_frt_reason", "")),
    }
    if fixed and traj:
        summary["constant_equivalence_score_gap"] = abs(
            to_float(traj.get("control_score")) - to_float(fixed.get("control_score"))
        )
        summary["constant_equivalence_lv_gap"] = abs(
            to_float(traj.get("lv_recovery_mean")) - to_float(fixed.get("lv_recovery_mean"))
        )
        summary["constant_equivalence_vdc_min_gap"] = abs(
            to_float(traj.get("vdc_min")) - to_float(fixed.get("vdc_min"))
        )
    return summary


def write_report(run_dir: Path, summary: dict[str, Any], rows: list[dict[str, str]]) -> None:
    lines = [
        "# HPT Trajectory Switch-Level Validation",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Modes",
            "",
            "| Mode | Voltage Pass | Full FRT Pass | Score | LV mean | LV recovery | Vdc min/max | Reason |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row.get('mode','')}` | {row.get('voltage_survival_pass','')} | "
            f"{row.get('full_frt_pass','')} | {row.get('control_score','')} | "
            f"{row.get('lv_mean','')} | {row.get('lv_recovery_mean','')} | "
            f"{row.get('vdc_min','')}/{row.get('vdc_max','')} | "
            f"`{row.get('voltage_survival_reason', row.get('full_frt_reason',''))}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_matlab_case(args: argparse.Namespace, run_dir: Path, trajectory_file: Path) -> tuple[Path, str, str, int]:
    modes = "{'conventional_dq','fixed_action','trajectory_action'}"
    action = [float(x) for x in args.action]
    case_name = args.case_name or f"lvrt_{int(round(args.duration_s * 1000)):03d}ms_{args.fault_pu:.3f}pu".replace(".", "p")
    label = safe_token(f"traj_{args.topology}_{args.preset}_{case_name}")
    statement = "; ".join(
        [
            f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
            f"hpt_compare_topology={matlab_string(args.topology)}",
            "hpt_compare_scenario_type='fault'",
            f"hpt_compare_modes=string({modes})",
            f"hpt_compare_faults={{ {matlab_string(case_name)}, {args.fault_pu:.12g}, {args.duration_s:.12g} }}",
            f"hpt_compare_fault_start={args.fault_start:.12g}",
            f"hpt_compare_fault_stop_margin={args.fault_stop_margin:.12g}",
            f"hpt_compare_run_label={matlab_string(label)}",
            "hpt_compare_fixed_action=[" + " ".join(f"{x:.12g}" for x in action) + "]",
            f"hpt_compare_trajectory_file={matlab_string(str(trajectory_file).replace(chr(92), '/'))}",
            "eval_hpt_v2_control_comparison",
        ]
    )
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    proc = subprocess.run(
        [args.matlab_cmd, "-batch", statement],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.timeout_s,
    )
    log_text = "STDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr
    log_path = run_dir / "matlab.log"
    log_path.write_text(log_text, encoding="utf-8")
    if proc.returncode != 0:
        return Path(), proc.stdout, proc.stderr, proc.returncode
    return latest_control_csv(before), proc.stdout, proc.stderr, proc.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2", choices=["topology1", "topology2"])
    parser.add_argument(
        "--preset",
        default="constant",
        choices=["zero", "constant", "step", "ramp", "two_stage", "two_stage_window", "fault_window"],
    )
    parser.add_argument("--fault-pu", type=float, default=0.95)
    parser.add_argument("--duration-s", type=float, default=0.08)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument("--action", type=float, nargs=4, default=[0.172, 0.0, 0.022, 0.002])
    parser.add_argument("--start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--step-time", type=float, default=0.035)
    parser.add_argument("--ramp-start", type=float, default=0.035)
    parser.add_argument("--ramp-end", type=float, default=0.055)
    parser.add_argument("--down-start", type=float, default=None)
    parser.add_argument("--down-end", type=float, default=None)
    parser.add_argument("--case-name", default="")
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or f"hpt_traj_switch_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
    spec = TrajectorySpec(
        preset=args.preset,
        dt=args.decision_dt,
        stop_time=stop_time,
        base_action=tuple(args.base_action),
        start_action=tuple(args.start_action),
        action=tuple(args.action),
        step_time=args.step_time,
        ramp_start=args.ramp_start,
        ramp_end=args.ramp_end,
        down_start=args.down_start,
        down_end=args.down_end,
    )
    t, action = make_trajectory(spec)
    trajectory_file = run_dir / "hpt_sac_trajectory.mat"
    write_mat(trajectory_file, t, action)
    write_csv(run_dir / "hpt_sac_trajectory.csv", t, action)

    csv_path, stdout, stderr, returncode = run_matlab_case(args, run_dir, trajectory_file)
    if returncode != 0:
        summary = {
            "schema": "hpt-trajectory-switch-validation-v1",
            "run_id": run_id,
            "matlab_returncode": returncode,
            "trajectory_file": str(trajectory_file),
            "error": "matlab_failed",
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return returncode

    rows = read_csv(csv_path)
    write_csv_rows(run_dir / "control_comparison_rows.csv", rows)
    summary = summarize_modes(rows)
    summary.update(
        {
            "schema": "hpt-trajectory-switch-validation-v1",
            "run_id": run_id,
            "control_csv": str(csv_path),
            "trajectory_file": str(trajectory_file),
            "topology": args.topology,
            "preset": args.preset,
            "fault_pu": args.fault_pu,
            "duration_s": args.duration_s,
            "decision_dt": args.decision_dt,
            "target_action": [float(x) for x in args.action],
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(run_dir, summary, rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trajectory_switch_validation",
        config=summary,
        dataset_manifest=trajectory_file,
        extra={"stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]},
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
