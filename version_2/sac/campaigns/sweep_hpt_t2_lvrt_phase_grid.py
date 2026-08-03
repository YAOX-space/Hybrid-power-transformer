"""Small switch-level grid for topology2 LVRT phase-aware trajectories.

This runner is deliberately narrower than the historical full-action sweep:
it only tests hand-sized fault/recovery trajectory teachers around the latest
topology2 LVRT 0.90 pu / 60 ms boundary.  The purpose is to find a teacher with
more switch-level voltage margin before spending time on another actor.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..experiment_metadata import write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
STRONG_DQ_PROFILES = {"none", "t2_bal_lvrt090_currentgate"}


@dataclass(frozen=True)
class TrajectoryCase:
    case_id: str
    fault_reg_d: float
    recovery_reg_d: float
    fault_energy_d: float = 0.30
    recovery_energy_d: float = 0.10
    fault_reg_q: float = 0.0
    recovery_reg_q: float = 0.0
    fault_energy_q: float = 0.0
    recovery_energy_q: float = 0.0


DEFAULT_CASES = [
    # Known pass-like region, with lower recovery energy to avoid DC collapse.
    TrajectoryCase("fr052_rr016_fe030_re010", 0.52, 0.16, 0.30, 0.10),
    TrajectoryCase("fr052_rr015_fe030_re010", 0.52, 0.15, 0.30, 0.10),
    TrajectoryCase("fr051_rr015_fe030_re010", 0.51, 0.15, 0.30, 0.10),
    TrajectoryCase("fr051_rr014_fe030_re010", 0.51, 0.14, 0.30, 0.10),
    # Reduced recovery energy variants: test if 0.08 gives more voltage margin
    # while retaining DC-link survival.
    TrajectoryCase("fr052_rr016_fe030_re008", 0.52, 0.16, 0.30, 0.08),
    TrajectoryCase("fr051_rr015_fe030_re008", 0.51, 0.15, 0.30, 0.08),
    # Conservative lower-regulating variants bracket the undervoltage edge.
    TrajectoryCase("fr050_rr014_fe030_re010", 0.50, 0.14, 0.30, 0.10),
    TrajectoryCase("fr050_rr015_fe030_re010", 0.50, 0.15, 0.30, 0.10),
]


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def run_command(
    cmd: list[str],
    *,
    run_dir: Path,
    log_name: str,
    timeout_s: int,
    allow_nonzero: bool = False,
) -> subprocess.CompletedProcess[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    (run_dir / log_name).write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0 and not allow_nonzero:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def build_trajectory(case: TrajectoryCase, case_dir: Path, args: argparse.Namespace) -> Path:
    mat_path = case_dir / "hpt_sac_trajectory.mat"
    if mat_path.exists() and not args.force:
        return mat_path
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.build_hpt_action_trajectory",
        "--out",
        str(mat_path),
        "--preset",
        "fault_recovery",
        "--dt",
        f"{args.decision_dt:.12g}",
        "--stop-time",
        f"{args.stop_time:.12g}",
        "--base-action",
        "0",
        "0",
        "0",
        "0",
        "--start-action",
        f"{case.fault_reg_d:.12g}",
        f"{case.fault_reg_q:.12g}",
        f"{case.fault_energy_d:.12g}",
        f"{case.fault_energy_q:.12g}",
        "--action",
        f"{case.recovery_reg_d:.12g}",
        f"{case.recovery_reg_q:.12g}",
        f"{case.recovery_energy_d:.12g}",
        f"{case.recovery_energy_q:.12g}",
        "--ramp-start",
        f"{args.ramp_start:.12g}",
        "--step-time",
        f"{args.fault_start:.12g}",
        "--ramp-end",
        f"{args.fault_clear:.12g}",
        "--down-start",
        f"{args.recovery_ramp_end:.12g}",
        "--write-csv",
        "--metadata-dir",
        str(case_dir),
    ]
    run_command(cmd, run_dir=case_dir, log_name="build_trajectory.log", timeout_s=120)
    return mat_path


def validate_case(case: TrajectoryCase, mat_path: Path, run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    result_dir = RESULTS / run_id
    summary_path = result_dir / "summary.json"
    if summary_path.exists() and not args.force:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        run_id,
        "--topology",
        "topology2",
        "--fault-pu",
        f"{args.fault_pu:.12g}",
        "--duration-s",
        f"{args.duration_s:.12g}",
        "--fault-start",
        f"{args.fault_start:.12g}",
        "--fault-stop-margin",
        f"{args.fault_stop_margin:.12g}",
        "--fault-settle-s",
        f"{args.fault_settle_s:.12g}",
        "--trajectory-file",
        str(mat_path),
        *(
            ["--voltage-survival-current-gate"]
            if args.voltage_survival_current_gate
            else []
        ),
        "--strong-dq-profile",
        args.strong_dq_profile,
        "--phase-override",
        "--chopper-threshold",
        f"{args.chopper_threshold:.12g}",
        "--rchop-scale",
        f"{args.rchop_scale:.12g}",
        "--timeout-s",
        str(args.matlab_timeout_s),
    ]
    run_command(
        cmd,
        run_dir=mat_path.parent,
        log_name="validate_switchlevel.log",
        timeout_s=args.matlab_timeout_s + 120,
        allow_nonzero=True,
    )
    if not summary_path.exists():
        raise FileNotFoundError(f"Validation did not produce summary: {summary_path}")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def summarize_case(case: TrajectoryCase, run_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "run_id": run_id,
        "fault_reg_d": case.fault_reg_d,
        "recovery_reg_d": case.recovery_reg_d,
        "fault_energy_d": case.fault_energy_d,
        "recovery_energy_d": case.recovery_energy_d,
        "trajectory_voltage_pass": truthy(summary.get("trajectory_voltage_pass")),
        "trajectory_beats_baseline": truthy(summary.get("trajectory_beats_baseline")),
        "trajectory_score": to_float(summary.get("trajectory_score")),
        "baseline_score": to_float(summary.get("baseline_score")),
        "trajectory_lv_mean": to_float(summary.get("trajectory_lv_mean")),
        "trajectory_lv_recovery_mean": to_float(summary.get("trajectory_lv_recovery_mean")),
        "trajectory_vdc_min": to_float(summary.get("trajectory_vdc_min")),
        "trajectory_vdc_max": to_float(summary.get("trajectory_vdc_max")),
        "trajectory_envelope_violation_max_pu": to_float(
            summary.get("trajectory_envelope_violation_max_pu")
        ),
        "trajectory_recovery_violation_max_pu": to_float(
            summary.get("trajectory_recovery_violation_max_pu")
        ),
        "trajectory_timestep_envelope_pass": truthy(
            summary.get("trajectory_timestep_envelope_pass")
        ),
        "trajectory_reason": summary.get("trajectory_reason", ""),
    }


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


def candidate_rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        not row["trajectory_voltage_pass"],
        not row["trajectory_beats_baseline"],
        row["trajectory_envelope_violation_max_pu"],
        row["trajectory_recovery_violation_max_pu"],
        abs(row["trajectory_lv_recovery_mean"] - 207.0),
        row["trajectory_score"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", default=f"hpt_t2_lvrt090_phase_grid_{time.strftime('%Y%m%d_%H%M')}")
    parser.add_argument("--case-limit", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fault-pu", type=float, default=0.90)
    parser.add_argument("--duration-s", type=float, default=0.060)
    parser.add_argument("--fault-start", type=float, default=0.080)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.020)
    parser.add_argument("--decision-dt", type=float, default=0.002)
    parser.add_argument("--ramp-start", type=float, default=0.078)
    parser.add_argument("--recovery-ramp-end", type=float, default=0.142)
    parser.add_argument("--chopper-threshold", type=float, default=780.0)
    parser.add_argument("--rchop-scale", type=float, default=0.65)
    parser.add_argument(
        "--strong-dq-profile",
        choices=sorted(STRONG_DQ_PROFILES),
        default="none",
        help="Optional named conventional-DQ parameter set to inject into validation.",
    )
    parser.add_argument(
        "--voltage-survival-current-gate",
        action="store_true",
        help="Require grid-current limit pass in the staged voltage-survival gate.",
    )
    parser.add_argument("--matlab-timeout-s", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.fault_clear = args.fault_start + args.duration_s
    args.stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
    campaign_dir = RESULTS / args.campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    cases = DEFAULT_CASES[: max(0, int(args.case_limit))]
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, 1):
        case_run_id = f"{args.campaign_id}_{idx:02d}_{case.case_id}"
        case_dir = campaign_dir / case.case_id
        mat_path = build_trajectory(case, case_dir, args)
        summary = validate_case(case, mat_path, case_run_id, args)
        row = summarize_case(case, case_run_id, summary)
        rows.append(row)
        write_csv_rows(campaign_dir / "trajectory_grid_results.csv", rows)
        (campaign_dir / "status.json").write_text(
            json.dumps(
                {
                    "schema": "hpt-t2-lvrt-phase-grid-status-v1",
                    "campaign_id": args.campaign_id,
                    "completed": idx,
                    "total": len(cases),
                    "latest_case": case.case_id,
                    "latest_row": row,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    ranked = sorted(rows, key=candidate_rank_key)
    summary = {
        "schema": "hpt-t2-lvrt-phase-grid-summary-v1",
        "campaign_id": args.campaign_id,
        "config": vars(args),
        "rows": rows,
        "best_candidate": ranked[0] if ranked else None,
        "pass_count": sum(bool(row["trajectory_voltage_pass"]) for row in rows),
        "beat_count": sum(bool(row["trajectory_beats_baseline"]) for row in rows),
    }
    (campaign_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv_rows(campaign_dir / "trajectory_grid_results_ranked.csv", ranked)
    write_experiment_metadata(
        campaign_dir,
        experiment_name="hpt_t2_lvrt_phase_grid",
        config=summary["config"],
        dataset_manifest=campaign_dir / "trajectory_grid_results.csv",
        extra={"summary_path": str(campaign_dir / "summary.json")},
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
