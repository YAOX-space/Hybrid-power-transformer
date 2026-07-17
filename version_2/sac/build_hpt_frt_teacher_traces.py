"""Build per-case FRT teacher traces from the switch-level calibration matrix.

The calibration matrix contains many fixed actions.  This script selects one
best aggregate action per topology/fault case, then exports only the matching
2-ms trace rows with ``action_01..04`` teacher columns for BC/SAC warm start.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_teacher_traces"


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value in ("", None):
                    row[key] = value
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
            rows.append(row)
    return rows


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


def f(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return float(default)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "yes"}:
            return 1.0
        if lower in {"false", "no"}:
            return 0.0
    return float(value)


def key_for(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["topology"]), str(row.get("fault", row.get("case_name", "")))


def action_key(row: dict[str, Any]) -> tuple[str, float, float, float, float]:
    return (
        str(row["mode"]),
        round(f(row, "raw_m_reg_d"), 9),
        round(f(row, "raw_m_reg_q"), 9),
        round(f(row, "raw_m_energy_d"), 9),
        round(f(row, "raw_m_energy_q"), 9),
    )


def score_candidate(row: dict[str, Any]) -> float:
    lv = f(row, "lv_pu_mean")
    rec = f(row, "lv_recovery_pu_mean", lv)
    vdc_min = f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0)
    vdc_max = f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0)
    action = f(row, "action_max_abs")
    reg_mag = abs(f(row, "raw_m_reg_d")) + 0.3 * abs(f(row, "raw_m_reg_q"))
    energy_mag = abs(f(row, "raw_m_energy_d")) + abs(f(row, "raw_m_energy_q"))
    vdc_violation = max(0.0, 0.75 - vdc_min) + max(0.0, vdc_max - 1.25)
    reactive_shortfall = f(row, "grid_iq_shortfall_max_pu", 0.0)
    if reactive_shortfall != reactive_shortfall:
        reactive_shortfall = 0.0
    grid_current = f(row, "grid_current_peak_pu", 0.0)
    if grid_current != grid_current:
        grid_current = 0.0
    grid_current_violation = max(0.0, grid_current - 1.5)
    grid_wrong_sign = f(row, "grid_iq_wrong_sign", 0.0) > 0.5
    return (
        18.0 * abs(lv - 1.0)
        + 8.0 * abs(rec - 1.0)
        + 45.0 * vdc_violation
        + 40.0 * reactive_shortfall
        + 50.0 * grid_current_violation
        + (8.0 if grid_wrong_sign else 0.0)
        + 0.8 * max(0.0, action - 0.95)
        + 0.06 * reg_mag
        + 0.08 * energy_mag
    )


def select_best_actions(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    allowed_modes = {"reg_sweep", "joint_sweep"}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("mode")) not in allowed_modes:
            continue
        if abs(f(row, "raw_m_reg_q")) > 1e-9:
            continue
        grouped[key_for(row)].append(row)
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for key, data in sorted(grouped.items()):
        best = min(data, key=score_candidate)
        best = dict(best)
        best["teacher_score"] = score_candidate(best)
        selected[key] = best
    return selected


def match_trace(row: dict[str, Any], selected: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    sel = selected.get(key_for(row))
    if sel is None:
        return None
    if action_key(row) != action_key(sel):
        return None
    out = dict(row)
    out["action_01"] = f(sel, "raw_m_reg_d")
    out["action_02"] = f(sel, "raw_m_reg_q")
    out["action_03"] = f(sel, "raw_m_energy_d")
    out["action_04"] = f(sel, "raw_m_energy_q")
    out["target_action_01"] = out["action_01"]
    out["target_action_02"] = out["action_02"]
    out["target_action_03"] = out["action_03"]
    out["target_action_04"] = out["action_04"]
    out["teacher_score"] = f(sel, "teacher_score")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--trace-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_full_all_*.csv")
    trace_csv = args.trace_csv or latest_csv(args.matrix_dir, "frt_calibration_traces_full_all_*.csv")
    matrix_rows = read_csv(matrix_csv)
    trace_rows = read_csv(trace_csv)
    selected = select_best_actions(matrix_rows)
    teacher_rows = [r for r in (match_trace(row, selected) for row in trace_rows) if r is not None]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(matrix_csv).stem.replace("frt_calibration_matrix_", "frt_teacher_")
    selected_csv = args.out_dir / f"{stem}_selected_actions.csv"
    teacher_csv = args.out_dir / f"{stem}_traces.csv"
    selected_rows = []
    for (topology, fault), row in sorted(selected.items()):
        out = dict(row)
        out["selected_topology"] = topology
        out["selected_fault"] = fault
        selected_rows.append(out)
    write_csv(selected_csv, selected_rows)
    write_csv(teacher_csv, teacher_rows)
    summary = {
        "matrix_csv": str(matrix_csv),
        "trace_csv": str(trace_csv),
        "selected_actions_csv": str(selected_csv),
        "teacher_csv": str(teacher_csv),
        "selected_cases": len(selected_rows),
        "teacher_rows": len(teacher_rows),
    }
    (args.out_dir / f"{stem}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
