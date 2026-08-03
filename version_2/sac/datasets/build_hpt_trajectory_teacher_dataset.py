"""Build a switch-validated HPT trajectory teacher/candidate dataset.

This script indexes trajectory-search runs produced by
``search_hpt_frt_trajectory_cem.py``.  It keeps trajectory-level candidates
separate from the older fixed-action FRT matrix, and records whether each
candidate is:

* ``strict_pass``: passed the switch-level voltage-survival gate.
* ``near_pass``: voltage envelope passed, but the run missed the strict gate by
  only a small DC-link margin.  These rows are useful for proxy calibration and
  plant debugging, but are not accepted as final SAC teachers.

The output is intentionally lightweight: a CSV manifest plus a JSON summary.
Training scripts can consume only ``accepted_for_training`` rows, while proxy
alignment scripts can also inspect ``accepted_for_calibration`` rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from version_2.sac.experiment_metadata import write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
DEFAULT_OUT_DIR = RESULTS / "hpt_trajectory_teacher_dataset"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def infer_topology(run_dir: Path, row: dict[str, str]) -> str:
    text = " ".join([run_dir.name, str(row.get("switch_csv", "")), str(row.get("switch_candidate_dir", ""))])
    match = re.search(r"topology[12]", text, flags=re.IGNORECASE)
    return match.group(0).lower() if match else "unknown"


def infer_fault_family(run_dir: Path, row: dict[str, str], fault_pu: float) -> str:
    if fault_pu == fault_pu:
        return "hvrt" if fault_pu > 1.0 else "lvrt"
    text = " ".join(
        [
            run_dir.name,
            str(row.get("switch_csv", "")),
            str(row.get("trajectory_manifest", "")),
        ]
    ).lower()
    if "hvrt" in text:
        return "hvrt"
    if "lvrt" in text or "sag" in text:
        return "lvrt"
    return "unknown"


def infer_fault_pu(run_dir: Path, row: dict[str, str]) -> float:
    text = " ".join([run_dir.name, str(row.get("switch_csv", "")), str(row.get("trajectory_manifest", ""))])
    patterns = [
        r"(\d+)p(\d+)pu",
        r"(\d+)p(\d+)",
        r"fault[_-]?pu[_-]?(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            if len(match.groups()) == 2:
                return float(f"{match.group(1)}.{match.group(2)}")
            return float(match.group(1))
    return float("nan")


def infer_duration_s(run_dir: Path, row: dict[str, str]) -> float:
    text = " ".join([run_dir.name, str(row.get("switch_csv", "")), str(row.get("trajectory_manifest", ""))])
    match = re.search(r"(\d+)ms", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000.0
    return float("nan")


def existing_file(candidate_dir: Path, name: str) -> str:
    path = candidate_dir / name
    return str(path) if path.exists() else ""


def classify_row(
    row: dict[str, str],
    *,
    dc_min_v: float,
    dc_max_v: float,
    near_dc_tol_v: float,
    envelope_tol_pu: float,
) -> dict[str, Any]:
    strict_pass = truthy(row.get("switch_trajectory_voltage_pass"))
    envelope_violation = to_float(row.get("switch_trajectory_envelope_violation_max_pu"), 999.0)
    recovery_violation = to_float(row.get("switch_trajectory_recovery_violation_max_pu"), 999.0)
    vdc_min = to_float(row.get("switch_trajectory_vdc_min"), -1e9)
    vdc_max = to_float(row.get("switch_trajectory_vdc_max"), 1e9)
    voltage_envelope_pass = envelope_violation <= envelope_tol_pu and recovery_violation <= envelope_tol_pu
    dc_near = (vdc_min >= dc_min_v - near_dc_tol_v) and (vdc_max <= dc_max_v + near_dc_tol_v)
    near_pass = bool((not strict_pass) and voltage_envelope_pass and dc_near)
    dc_margin_low_v = vdc_min - dc_min_v
    dc_margin_high_v = dc_max_v - vdc_max
    reason = str(row.get("switch_trajectory_reason", ""))
    if strict_pass:
        status = "strict_pass"
    elif near_pass:
        status = "near_pass_dc_margin"
    elif voltage_envelope_pass:
        status = "voltage_pass_dc_fail"
    else:
        status = "fail"
    return {
        "strict_pass": strict_pass,
        "near_pass": near_pass,
        "voltage_envelope_pass": voltage_envelope_pass,
        "dc_near": dc_near,
        "dc_margin_low_v": dc_margin_low_v,
        "dc_margin_high_v": dc_margin_high_v,
        "status": status,
        "failure_reason": reason,
    }


def row_from_candidate(
    run_dir: Path,
    row: dict[str, str],
    *,
    dc_min_v: float,
    dc_max_v: float,
    near_dc_tol_v: float,
    envelope_tol_pu: float,
) -> dict[str, Any]:
    candidate_dir = Path(row.get("switch_candidate_dir") or "")
    classification = classify_row(
        row,
        dc_min_v=dc_min_v,
        dc_max_v=dc_max_v,
        near_dc_tol_v=near_dc_tol_v,
        envelope_tol_pu=envelope_tol_pu,
    )
    fault_pu = infer_fault_pu(run_dir, row)
    topology = infer_topology(run_dir, row)
    fault_family = infer_fault_family(run_dir, row, fault_pu)
    duration_s = infer_duration_s(run_dir, row)
    out: dict[str, Any] = {
        "schema": "hpt-trajectory-teacher-row-v1",
        "source_run": run_dir.name,
        "source_switch_candidates_csv": str(run_dir / "switch_candidates.csv"),
        "topology": topology,
        "fault_family": fault_family,
        "fault_pu": fault_pu,
        "duration_s": duration_s,
        "case_key": f"{topology}_{fault_family}_{duration_s:.3f}s_{fault_pu:.3f}pu",
        "candidate_index": row.get("candidate_index", ""),
        "iteration": row.get("iteration", ""),
        "switch_rank": row.get("switch_rank", ""),
        "candidate_dir": str(candidate_dir) if str(candidate_dir) else "",
        "trajectory_mat": existing_file(candidate_dir, "hpt_sac_trajectory.mat"),
        "trajectory_csv": existing_file(candidate_dir, "hpt_sac_trajectory.csv"),
        "trajectory_manifest_json": existing_file(candidate_dir, "trajectory_manifest.json"),
        "switch_summary_csv": row.get("switch_csv", ""),
        "proxy_score": row.get("proxy_score", ""),
        "switch_trajectory_score": row.get("switch_trajectory_score", ""),
        "switch_baseline_score": row.get("switch_baseline_score", ""),
        "switch_trajectory_beats_baseline": truthy(row.get("switch_trajectory_beats_baseline")),
        "lv_mean_v": row.get("switch_trajectory_lv_mean", ""),
        "lv_recovery_mean_v": row.get("switch_trajectory_lv_recovery_mean", ""),
        "vdc_min_v": row.get("switch_trajectory_vdc_min", ""),
        "vdc_max_v": row.get("switch_trajectory_vdc_max", ""),
        "envelope_violation_max_pu": row.get("switch_trajectory_envelope_violation_max_pu", ""),
        "recovery_violation_max_pu": row.get("switch_trajectory_recovery_violation_max_pu", ""),
        "reg_boost": row.get("param_reg_boost", ""),
        "reg_recovery": row.get("param_reg_recovery", ""),
        "energy_d_boost": row.get("param_energy_d_boost", ""),
        "energy_d_recovery": row.get("param_energy_d_recovery", ""),
        "reg_q_boost": row.get("param_reg_q_boost", ""),
        "energy_q_boost": row.get("param_energy_q_boost", ""),
        "trajectory_manifest": row.get("trajectory_manifest", ""),
    }
    out.update(classification)
    out["accepted_for_training"] = bool(out["strict_pass"])
    out["accepted_for_calibration"] = bool(out["strict_pass"] or out["near_pass"])
    return out


def discover_runs(root: Path, pattern: str) -> list[Path]:
    runs: list[Path] = []
    for path in sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime):
        if (path / "switch_candidates.csv").exists():
            runs.append(path)
    return runs


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["status"]) for row in rows)
    by_case: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_case[str(row["case_key"])][str(row["status"])] += 1
    best_by_case: dict[str, dict[str, Any]] = {}
    for case_key in sorted(by_case):
        case_rows = [row for row in rows if row["case_key"] == case_key]
        accepted = [row for row in case_rows if row["accepted_for_training"]]
        near = [row for row in case_rows if row["near_pass"]]
        if accepted:
            pool = accepted
            selected_status = "strict_pass"
        elif near:
            pool = near
            selected_status = "near_pass"
        else:
            pool = case_rows
            selected_status = "diagnostic"
        best = min(pool, key=lambda r: to_float(r.get("switch_trajectory_score"), 1e9))
        best_by_case[case_key] = {
            "selected_status": selected_status,
            "source_run": best.get("source_run"),
            "candidate_index": best.get("candidate_index"),
            "switch_rank": best.get("switch_rank"),
            "switch_trajectory_score": best.get("switch_trajectory_score"),
            "lv_mean_v": best.get("lv_mean_v"),
            "lv_recovery_mean_v": best.get("lv_recovery_mean_v"),
            "vdc_min_v": best.get("vdc_min_v"),
            "vdc_max_v": best.get("vdc_max_v"),
            "dc_margin_high_v": best.get("dc_margin_high_v"),
            "trajectory_csv": best.get("trajectory_csv"),
            "trajectory_mat": best.get("trajectory_mat"),
        }
    return {
        "schema": "hpt-trajectory-teacher-dataset-summary-v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rows": len(rows),
        "status_counts": dict(counts),
        "accepted_for_training": sum(1 for row in rows if row["accepted_for_training"]),
        "accepted_for_calibration": sum(1 for row in rows if row["accepted_for_calibration"]),
        "case_count": len(by_case),
        "by_case": {case: dict(counter) for case, counter in sorted(by_case.items())},
        "best_by_case": best_by_case,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=RESULTS)
    parser.add_argument("--pattern", default="hpt_cem_traj_*")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dc-min-v", type=float, default=650.0)
    parser.add_argument("--dc-max-v", type=float, default=1000.0)
    parser.add_argument(
        "--near-dc-tol-v",
        type=float,
        default=5.0,
        help="Near-pass tolerance around DC-link bounds for calibration-only rows.",
    )
    parser.add_argument("--envelope-tol-pu", type=float, default=1e-3)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("trajectory_teacher_dataset_%Y%m%d_%H%M%S")
    run_dir = args.out_dir / safe_token(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    runs = discover_runs(args.results_root, args.pattern)
    rows: list[dict[str, Any]] = []
    for run in runs:
        for raw in read_csv(run / "switch_candidates.csv"):
            rows.append(
                row_from_candidate(
                    run,
                    raw,
                    dc_min_v=args.dc_min_v,
                    dc_max_v=args.dc_max_v,
                    near_dc_tol_v=args.near_dc_tol_v,
                    envelope_tol_pu=args.envelope_tol_pu,
                )
            )

    rows = sorted(
        rows,
        key=lambda r: (
            str(r["case_key"]),
            0 if r["strict_pass"] else 1 if r["near_pass"] else 2,
            to_float(r.get("switch_trajectory_score"), 1e9),
        ),
    )
    dataset_csv = run_dir / "trajectory_teacher_dataset.csv"
    strict_csv = run_dir / "trajectory_teacher_strict_pass.csv"
    calibration_csv = run_dir / "trajectory_teacher_calibration_rows.csv"
    write_csv(dataset_csv, rows)
    write_csv(strict_csv, [row for row in rows if row["accepted_for_training"]])
    write_csv(calibration_csv, [row for row in rows if row["accepted_for_calibration"]])
    summary = summarize(rows)
    summary.update(
        {
            "run_dir": str(run_dir),
            "dataset_csv": str(dataset_csv),
            "strict_csv": str(strict_csv),
            "calibration_csv": str(calibration_csv),
            "source_runs": [str(path) for path in runs],
            "config": {
                "dc_min_v": args.dc_min_v,
                "dc_max_v": args.dc_max_v,
                "near_dc_tol_v": args.near_dc_tol_v,
                "envelope_tol_pu": args.envelope_tol_pu,
            },
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trajectory_teacher_dataset",
        config=summary["config"],
        dataset_manifest=dataset_csv,
        extra={
            "strict_csv": str(strict_csv),
            "calibration_csv": str(calibration_csv),
            "source_run_count": len(runs),
        },
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


