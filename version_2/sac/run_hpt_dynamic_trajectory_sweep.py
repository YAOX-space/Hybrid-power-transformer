"""Run switch-level dynamic trajectory sweeps for HPT FRT research.

This script is intentionally a thin orchestration layer over
``validate_hpt_trajectory_switchlevel``.  It builds two-stage trajectory
families such as:

    base -> voltage-support action -> voltage+reactive-support action

and records the switch-level metrics that matter for promotion:
voltage-survival, control score, Vdc limits, grid current, and GB/T reactive
status.  The output is a compact CSV plus a JSON summary under ``lab/results``.
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

from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"


def parse_grid(text: str) -> list[float]:
    values = [float(item.strip()) for item in str(text).split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("grid must contain at least one value")
    return values


def safe_token(value: Any) -> str:
    text = str(value).replace("-", "m").replace(".", "p")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


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
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def metric_row(summary: dict[str, Any]) -> dict[str, Any]:
    control_csv = Path(summary["control_csv"])
    rows = read_csv(control_csv)
    by_mode = {row.get("mode", ""): row for row in rows}
    traj = by_mode.get("trajectory_action", {})
    baseline = by_mode.get("conventional_dq", {})
    fixed = by_mode.get("fixed_action", {})
    return {
        "control_csv": str(control_csv),
        "baseline_voltage_pass": truthy(baseline.get("voltage_survival_pass", "")),
        "baseline_score": f(baseline, "control_score"),
        "fixed_voltage_pass": truthy(fixed.get("voltage_survival_pass", "")),
        "fixed_score": f(fixed, "control_score"),
        "trajectory_voltage_pass": truthy(traj.get("voltage_survival_pass", "")),
        "trajectory_full_frt_pass": truthy(traj.get("full_frt_pass", "")),
        "trajectory_score": f(traj, "control_score"),
        "trajectory_voltage_reason": traj.get("voltage_survival_reason", ""),
        "trajectory_full_frt_reason": traj.get("full_frt_reason", ""),
        "trajectory_lv_mean": f(traj, "lv_mean"),
        "trajectory_lv_recovery_mean": f(traj, "lv_recovery_mean"),
        "trajectory_vdc_min": f(traj, "vdc_min"),
        "trajectory_vdc_max": f(traj, "vdc_max"),
        "trajectory_grid_iq_shortfall_max_pu": f(traj, "grid_iq_shortfall_max_pu"),
        "trajectory_grid_current_peak_pu": f(traj, "grid_current_peak_pu"),
        "trajectory_gbt_reactive_status": traj.get("gbt_reactive_status", ""),
        "trajectory_cmd_m_reg_d_mean": f(traj, "cmd_m_reg_d_mean"),
        "trajectory_cmd_m_reg_q_mean": f(traj, "cmd_m_reg_q_mean"),
        "trajectory_cmd_m_energy_d_mean": f(traj, "cmd_m_energy_d_mean"),
        "trajectory_cmd_m_energy_q_mean": f(traj, "cmd_m_energy_q_mean"),
    }


def run_validation(args: argparse.Namespace, run_dir: Path, case: dict[str, Any]) -> dict[str, Any]:
    run_id = f"{args.run_id}_{case['token']}"
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        run_id,
        "--topology",
        args.topology,
        "--fault-pu",
        str(args.fault_pu),
        "--duration-s",
        str(args.duration_s),
        "--fault-start",
        str(args.fault_start),
        "--fault-stop-margin",
        str(args.fault_stop_margin),
        "--preset",
        case["preset"],
        "--base-action",
        *[str(v) for v in case["base_action"]],
        "--start-action",
        *[str(v) for v in case["start_action"]],
        "--action",
        *[str(v) for v in case["action"]],
        "--ramp-start",
        str(case["ramp_start"]),
        "--step-time",
        str(case["step_time"]),
        "--ramp-end",
        str(case["ramp_end"]),
        "--matlab-cmd",
        args.matlab_cmd,
        "--timeout-s",
        str(args.timeout_s),
    ]
    if case["preset"] == "two_stage_window":
        cmd += ["--down-start", str(case["down_start"]), "--down-end", str(case["down_end"])]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.timeout_s + 90,
    )
    log_path = run_dir / f"{case['token']}.log"
    log_path.write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    result: dict[str, Any] = {
        **case,
        "validation_run_id": run_id,
        "returncode": proc.returncode,
        "log_path": str(log_path),
    }
    if proc.returncode != 0:
        result["error"] = "validation_failed"
        return result
    summary_path = RESULTS / run_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    result.update(metric_row(summary))
    result["summary_path"] = str(summary_path)
    return result


def build_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    max_cases = args.max_cases
    for reg_d in args.reg_d_grid:
        for reg_q in args.reg_q_grid:
            for energy_d in args.energy_d_grid:
                for energy_q in args.energy_q_grid:
                    for d_ramp_ms in args.d_ramp_ms_grid:
                        for q_ramp_ms in args.q_ramp_ms_grid:
                            for down_ms in args.down_ms_grid:
                                ramp_start = args.fault_start
                                step_time = ramp_start + d_ramp_ms / 1000.0
                                ramp_end = step_time + q_ramp_ms / 1000.0
                                preset = "two_stage"
                                down_start = float("nan")
                                down_end = float("nan")
                                if down_ms > 0:
                                    preset = "two_stage_window"
                                    down_start = args.fault_start + args.duration_s
                                    down_end = down_start + down_ms / 1000.0
                                token = (
                                    f"{preset}_rd{safe_token(reg_d)}_rq{safe_token(reg_q)}_"
                                    f"ed{safe_token(energy_d)}_eq{safe_token(energy_q)}_"
                                    f"dr{safe_token(d_ramp_ms)}_qr{safe_token(q_ramp_ms)}_"
                                    f"down{safe_token(down_ms)}"
                                )
                                cases.append(
                                    {
                                        "token": token,
                                        "preset": preset,
                                        "reg_d": reg_d,
                                        "reg_q": reg_q,
                                        "energy_d": energy_d,
                                        "energy_q": energy_q,
                                        "d_ramp_ms": d_ramp_ms,
                                        "q_ramp_ms": q_ramp_ms,
                                        "down_ms": down_ms,
                                        "base_action": [0.0, 0.0, 0.0, 0.0],
                                        "start_action": [reg_d, 0.0, energy_d, energy_q],
                                        "action": [reg_d, reg_q, energy_d, energy_q],
                                        "ramp_start": ramp_start,
                                        "step_time": step_time,
                                        "ramp_end": ramp_end,
                                        "down_start": down_start,
                                        "down_end": down_end,
                                    }
                                )
                                if max_cases > 0 and len(cases) >= max_cases:
                                    return cases
    return cases


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"hpt_dynamic_traj_sweep_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--fault-pu", type=float, default=0.90)
    parser.add_argument("--duration-s", type=float, default=0.08)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--reg-d-grid", type=parse_grid, default=parse_grid("0.172"))
    parser.add_argument("--reg-q-grid", type=parse_grid, default=parse_grid("0,-0.2,-0.3,-0.4"))
    parser.add_argument("--energy-d-grid", type=parse_grid, default=parse_grid("0.010,-0.020"))
    parser.add_argument("--energy-q-grid", type=parse_grid, default=parse_grid("0.002"))
    parser.add_argument("--d-ramp-ms-grid", type=parse_grid, default=parse_grid("20"))
    parser.add_argument("--q-ramp-ms-grid", type=parse_grid, default=parse_grid("40"))
    parser.add_argument("--down-ms-grid", type=parse_grid, default=parse_grid("0"))
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=1200)
    args = parser.parse_args()

    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases(args)
    manifest_path = run_dir / "case_manifest.csv"
    write_csv(manifest_path, cases)

    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, 1):
        print(f"[{idx}/{len(cases)}] {case['token']}", flush=True)
        rows.append(run_validation(args, run_dir, case))
        write_csv(run_dir / "trajectory_sweep_results.csv", rows)

    successful = [
        row
        for row in rows
        if row.get("returncode") == 0 and row.get("trajectory_voltage_pass") is True
    ]
    full_frt = [row for row in successful if row.get("trajectory_full_frt_pass") is True]
    best_by_score = sorted(
        [row for row in rows if finite(row.get("trajectory_score"))],
        key=lambda row: float(row["trajectory_score"]),
    )[:10]
    summary = {
        "schema": "hpt-dynamic-trajectory-sweep-v1",
        "run_id": args.run_id,
        "case_count": len(cases),
        "completed_count": sum(int(row.get("returncode") == 0) for row in rows),
        "voltage_survival_pass_count": len(successful),
        "full_frt_pass_count": len(full_frt),
        "case_manifest": str(manifest_path),
        "result_csv": str(run_dir / "trajectory_sweep_results.csv"),
        "best_by_score": best_by_score,
        "config": vars(args),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_dynamic_trajectory_sweep",
        config=summary["config"],
        dataset_manifest=manifest_path,
        extra={"summary_path": str(run_dir / "summary.json")},
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
