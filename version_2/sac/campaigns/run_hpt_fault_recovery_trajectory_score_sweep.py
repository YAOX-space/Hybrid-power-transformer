"""Focused switch-level sweep for fault/recovery HPT action trajectories.

This campaign is for cases where a fixed action survives but scores poorly
because the recovery command is too high.  Each candidate uses a two-level
trajectory:

    base -> fault_action during the fault -> recovery_action after clearing

and is validated by the canonical switch-level comparison runner.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from version_2.sac.build_hpt_action_trajectory import TrajectorySpec, make_trajectory, write_csv as write_traj_csv, write_mat
from version_2.sac.experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"


def parse_grid(text: str) -> list[float]:
    values = [float(item.strip()) for item in str(text).split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("grid must contain at least one value")
    return values


def safe_token(value: Any) -> str:
    return str(value).replace("-", "m").replace(".", "p").replace(" ", "")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
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


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def phase_args(values: list[float] | None) -> list[str]:
    if not values:
        return []
    return ["--fault-phase-pu", *[str(v) for v in values]]


def metric_row(summary: dict[str, Any]) -> dict[str, Any]:
    rows = read_csv(Path(summary["control_csv"]))
    by_mode = {row.get("mode", ""): row for row in rows}
    traj = by_mode.get("trajectory_action", {})
    baseline = by_mode.get("conventional_dq", {})
    return {
        "control_csv": summary["control_csv"],
        "baseline_voltage_pass": truthy(baseline.get("voltage_survival_pass", "")),
        "baseline_score": f(baseline, "control_score"),
        "baseline_lv_mean": f(baseline, "lv_mean"),
        "baseline_lv_recovery_mean": f(baseline, "lv_recovery_mean"),
        "trajectory_voltage_pass": truthy(traj.get("voltage_survival_pass", "")),
        "trajectory_score": f(traj, "control_score"),
        "trajectory_beats_baseline": bool(
            truthy(traj.get("voltage_survival_pass", ""))
            and (
                not truthy(baseline.get("voltage_survival_pass", ""))
                or f(traj, "control_score") < f(baseline, "control_score")
            )
        ),
        "trajectory_lv_mean": f(traj, "lv_mean"),
        "trajectory_lv_recovery_mean": f(traj, "lv_recovery_mean"),
        "trajectory_vdc_min": f(traj, "vdc_min"),
        "trajectory_vdc_max": f(traj, "vdc_max"),
        "trajectory_envelope_violation_max_pu": f(traj, "envelope_violation_max_pu"),
        "trajectory_recovery_violation_max_pu": f(traj, "recovery_violation_max_pu"),
        "trajectory_fault_lv_band_violation_max_pu": f(traj, "fault_lv_band_violation_max_pu"),
        "trajectory_reason": traj.get("voltage_survival_reason", ""),
        "trajectory_full_frt_reason": traj.get("full_frt_reason", ""),
        "trajectory_cmd_m_reg_d_fault_mean": f(traj, "cmd_m_reg_d_fault_mean"),
        "trajectory_cmd_m_reg_d_recovery_mean": f(traj, "cmd_m_reg_d_recovery_mean"),
    }


def build_trajectory(args: argparse.Namespace, case_dir: Path, case: dict[str, Any]) -> Path:
    stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
    fault_clear = args.fault_start + args.duration_s
    spec = TrajectorySpec(
        preset="fault_recovery",
        dt=args.decision_dt,
        stop_time=stop_time,
        base_action=(case["pre_reg_d"], 0.0, case["pre_energy_d"], 0.0),
        start_action=(case["fault_reg_d"], case["fault_reg_q"], case["fault_energy_d"], case["fault_energy_q"]),
        action=(
            case["recovery_reg_d"],
            case["recovery_reg_q"],
            case["recovery_energy_d"],
            case["recovery_energy_q"],
        ),
        step_time=args.fault_start + args.ramp_in_ms / 1000.0,
        ramp_start=args.fault_start,
        ramp_end=fault_clear,
        down_start=fault_clear + args.recovery_ramp_ms / 1000.0,
    )
    t, action = make_trajectory(spec)
    mat_path = case_dir / "hpt_sac_trajectory.mat"
    write_mat(mat_path, t, action)
    write_traj_csv(case_dir / "hpt_sac_trajectory.csv", t, action)
    (case_dir / "trajectory_spec.json").write_text(
        json.dumps({"spec": spec.__dict__, "case": case}, indent=2),
        encoding="utf-8",
    )
    return mat_path


def run_case(args: argparse.Namespace, run_dir: Path, case: dict[str, Any]) -> dict[str, Any]:
    case_dir = run_dir / case["token"]
    case_dir.mkdir(parents=True, exist_ok=True)
    traj = build_trajectory(args, case_dir, case)
    validation_id = f"{args.run_id}_{case['token']}"
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        validation_id,
        "--topology",
        args.topology,
        "--fault-pu",
        str(args.fault_pu),
        *phase_args(args.fault_phase_pu),
        "--duration-s",
        str(args.duration_s),
        "--fault-start",
        str(args.fault_start),
        "--fault-stop-margin",
        str(args.fault_stop_margin),
        "--fault-settle-s",
        str(args.fault_settle_s),
        "--chopper-threshold",
        str(args.chopper_threshold),
        "--rchop-scale",
        str(args.rchop_scale),
        "--trajectory-file",
        str(traj),
        "--action",
        "0",
        "0",
        "0",
        "0",
        "--timeout-s",
        str(args.timeout_s),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.timeout_s + 90,
    )
    (case_dir / "validate.log").write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    result = {**case, "validation_run_id": validation_id, "returncode": proc.returncode}
    if proc.returncode != 0:
        result["error"] = "validation_failed"
        return result
    summary_path = RESULTS / validation_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result.update(metric_row(summary))
    result["summary_path"] = str(summary_path)
    return result


def build_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for pre_reg_d in args.pre_reg_d_grid:
        for fault_reg_d in args.fault_reg_d_grid:
            for recovery_reg_d in args.recovery_reg_d_grid:
                for fault_energy_d in args.fault_energy_d_grid:
                    for recovery_energy_d in args.recovery_energy_d_grid:
                        token = (
                            f"prd{safe_token(pre_reg_d)}_frd{safe_token(fault_reg_d)}_"
                            f"rrd{safe_token(recovery_reg_d)}_fed{safe_token(fault_energy_d)}_"
                            f"red{safe_token(recovery_energy_d)}_fq{safe_token(args.fault_reg_q)}_"
                            f"rq{safe_token(args.recovery_reg_q)}"
                        )
                        cases.append(
                            {
                                "token": token,
                                "pre_reg_d": pre_reg_d,
                                "pre_energy_d": args.pre_energy_d,
                                "fault_reg_d": fault_reg_d,
                                "fault_reg_q": args.fault_reg_q,
                                "fault_energy_d": fault_energy_d,
                                "fault_energy_q": args.fault_energy_q,
                                "recovery_reg_d": recovery_reg_d,
                                "recovery_reg_q": args.recovery_reg_q,
                                "recovery_energy_d": recovery_energy_d,
                                "recovery_energy_q": args.recovery_energy_q,
                            }
                        )
    if args.max_cases > 0:
        return cases[: args.max_cases]
    return cases


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"hpt_fault_recovery_traj_sweep_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology1")
    parser.add_argument("--fault-pu", type=float, default=0.90)
    parser.add_argument("--fault-phase-pu", type=float, nargs=3, default=None)
    parser.add_argument("--duration-s", type=float, default=0.060)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.020)
    parser.add_argument("--decision-dt", type=float, default=0.002)
    parser.add_argument("--ramp-in-ms", type=float, default=2.0)
    parser.add_argument("--recovery-ramp-ms", type=float, default=10.0)
    parser.add_argument("--pre-reg-d-grid", type=parse_grid, default=parse_grid("0"))
    parser.add_argument("--pre-energy-d", type=float, default=0.0)
    parser.add_argument("--fault-reg-d-grid", type=parse_grid, default=parse_grid("0.36,0.40,0.44"))
    parser.add_argument("--recovery-reg-d-grid", type=parse_grid, default=parse_grid("0.20,0.24,0.28"))
    parser.add_argument("--fault-reg-q", type=float, default=0.0)
    parser.add_argument("--recovery-reg-q", type=float, default=0.0)
    parser.add_argument("--fault-energy-d-grid", type=parse_grid, default=parse_grid("0"))
    parser.add_argument("--recovery-energy-d-grid", type=parse_grid, default=parse_grid("0"))
    parser.add_argument("--fault-energy-q", type=float, default=0.0)
    parser.add_argument("--recovery-energy-q", type=float, default=0.0)
    parser.add_argument("--chopper-threshold", type=float, default=850.0)
    parser.add_argument("--rchop-scale", type=float, default=1.0)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--timeout-s", type=int, default=1200)
    args = parser.parse_args()

    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases(args)
    write_csv(run_dir / "case_manifest.csv", cases)
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, 1):
        print(f"[{idx}/{len(cases)}] {case['token']}", flush=True)
        rows.append(run_case(args, run_dir, case))
        write_csv(run_dir / "sweep_results.csv", rows)

    complete = [row for row in rows if row.get("returncode") == 0]
    passed = [row for row in complete if row.get("trajectory_voltage_pass") is True]
    beat = [row for row in passed if row.get("trajectory_beats_baseline") is True]
    best = sorted(
        [row for row in complete if finite(row.get("trajectory_score"))],
        key=lambda row: float(row["trajectory_score"]),
    )[:10]
    summary = {
        "schema": "hpt-fault-recovery-trajectory-score-sweep-v1",
        "run_id": args.run_id,
        "case_count": len(cases),
        "completed_count": len(complete),
        "voltage_pass_count": len(passed),
        "beat_conventional_count": len(beat),
        "result_csv": str(run_dir / "sweep_results.csv"),
        "best_by_score": best,
        "config": vars(args),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_fault_recovery_trajectory_score_sweep",
        config=summary["config"],
        dataset_manifest=run_dir / "case_manifest.csv",
    )
    lines = [
        "# HPT Fault/Recovery Trajectory Score Sweep",
        "",
        f"- Cases: `{len(cases)}`",
        f"- Completed: `{len(complete)}`",
        f"- Voltage pass: `{len(passed)}`",
        f"- Beat conventional: `{len(beat)}`",
        "",
        "| Rank | Pass | Beat | Score | Baseline | LV | Recovery | Vdc min/max | frd | rrd | Reason |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for rank, row in enumerate(best):
        lines.append(
            f"| {rank} | {row.get('trajectory_voltage_pass')} | "
            f"{row.get('trajectory_beats_baseline')} | {row.get('trajectory_score')} | "
            f"{row.get('baseline_score')} | {row.get('trajectory_lv_mean')} | "
            f"{row.get('trajectory_lv_recovery_mean')} | "
            f"{row.get('trajectory_vdc_min')}/{row.get('trajectory_vdc_max')} | "
            f"{row.get('fault_reg_d')} | {row.get('recovery_reg_d')} | "
            f"`{row.get('trajectory_reason','')}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
