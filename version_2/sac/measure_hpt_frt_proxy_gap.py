"""Measure FRT proxy gap against the switch-level calibration matrix.

The key holdout is ``joint_sweep``: it is not stored in the proxy tables, so
the predictor must combine the regulating and energy response tables.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_CALIBRATION = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_proxy_gap"


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
    return float(value)


def interp_response(table: list[dict[str, Any]], grid_pu: float, reg_d: float, key: str) -> float | None:
    if not table:
        return None
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    vals: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = defaultdict(list)
        for row in table:
            if abs(f(row, "grid_pu") - grid) > 1e-9:
                continue
            bucket[f(row, "reg_d_mean")].append(f(row, key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        vals.append(float(np.interp(reg_d, xs, ys)))
        used_grids.append(grid)
    if not vals:
        return None
    return float(np.interp(grid_pu, np.asarray(used_grids), np.asarray(vals)))


def interp_by_grid(table: list[dict[str, Any]], grid_pu: float, key: str) -> float | None:
    if not table:
        return None
    bucket: dict[float, list[float]] = defaultdict(list)
    for row in table:
        bucket[round(f(row, "grid_pu"), 9)].append(f(row, key))
    if not bucket:
        return None
    xs = np.asarray(sorted(bucket), dtype=float)
    ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
    return float(np.interp(grid_pu, xs, ys))


def interp_energy_axis(
    table: list[dict[str, Any]],
    grid_pu: float,
    action_value: float,
    axis_key: str,
    other_axis_key: str,
    value_key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    vals: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = defaultdict(list)
        for row in table:
            if abs(f(row, "grid_pu") - grid) > 1e-9:
                continue
            if abs(f(row, other_axis_key)) > 1e-9:
                continue
            bucket[f(row, axis_key)].append(f(row, value_key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        vals.append(float(np.interp(action_value, xs, ys)))
        used_grids.append(grid)
    if not vals:
        return None
    return float(np.interp(grid_pu, np.asarray(used_grids), np.asarray(vals)))


def interp_energy(table: list[dict[str, Any]], grid_pu: float, ed: float, eq: float, key: str) -> float | None:
    baseline = interp_energy_axis(table, grid_pu, 0.0, "energy_d_mean", "energy_q_mean", key)
    d_axis = interp_energy_axis(table, grid_pu, ed, "energy_d_mean", "energy_q_mean", key)
    q_axis = interp_energy_axis(table, grid_pu, eq, "energy_q_mean", "energy_d_mean", key)
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def analyze(rows: list[dict[str, Any]], calibration: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        topology = str(row["topology"])
        top = calibration["topologies"][topology]
        mode = str(row["mode"])
        raw_reg_q = f(row, "raw_m_reg_q")
        mode_label = mode
        if mode == "reg_sweep" and abs(raw_reg_q) > 1e-9:
            mode_label = "reg_q_sweep"
        grid = f(row, "grid_pu", f(row, "fault_pu"))
        reg = f(row, "reg_d_mean", f(row, "raw_m_reg_d"))
        reg_q = f(row, "reg_q_mean", raw_reg_q)
        ed = f(row, "energy_d_mean", f(row, "raw_m_energy_d"))
        eq = f(row, "energy_q_mean", f(row, "raw_m_energy_q"))
        reg_table = top.get("fault_response_table", [])
        energy_table = top.get("fault_energy_response_table", [])
        baseline_table = top.get("fault_baseline_table", [])
        pred_lv = interp_response(reg_table, grid, reg, "lv_pu_mean")
        pred_vdc = interp_response(reg_table, grid, reg, "vdc_pu_mean")
        pred_lv_energy = interp_energy(energy_table, grid, ed, eq, "lv_pu_mean")
        pred_vdc_energy = interp_energy(energy_table, grid, ed, eq, "vdc_pu_mean")
        pred_i_energy = interp_energy(energy_table, grid, ed, eq, "energy_i_rms_mean")
        if mode == "baseline":
            pred_lv = interp_by_grid(baseline_table, grid, "lv_pu_mean")
            pred_vdc = interp_by_grid(baseline_table, grid, "vdc_pu_mean")
        elif mode in {"energy_sweep"}:
            pred_lv = pred_lv_energy
            pred_vdc = pred_vdc_energy
        elif mode in {"joint_sweep"}:
            if pred_lv is not None and pred_lv_energy is not None:
                zero_lv = interp_energy(energy_table, grid, 0.0, 0.0, "lv_pu_mean")
                if zero_lv is not None:
                    pred_lv = pred_lv + (pred_lv_energy - zero_lv)
            if pred_vdc is not None and pred_vdc_energy is not None:
                zero_energy = interp_energy(energy_table, grid, 0.0, 0.0, "vdc_pu_mean")
                if zero_energy is not None:
                    pred_vdc = pred_vdc + (pred_vdc_energy - zero_energy)
        out.append(
            {
                "topology": topology,
                "category": row.get("category", ""),
                "fault": row.get("fault", row.get("case_name", "")),
                "mode": mode_label,
                "grid_pu": grid,
                "reg_d": reg,
                "reg_q": reg_q,
                "energy_d": ed,
                "energy_q": eq,
                "sim_lv_pu": f(row, "lv_pu_mean"),
                "proxy_lv_pu": pred_lv,
                "err_lv_pu": None if pred_lv is None else pred_lv - f(row, "lv_pu_mean"),
                "sim_vdc_pu": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "proxy_vdc_pu": pred_vdc,
                "err_vdc_pu": None if pred_vdc is None else pred_vdc - f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "sim_energy_i_rms": f(row, "energy_i_rms_mean"),
                "proxy_energy_i_rms": pred_i_energy,
                "err_energy_i_rms": None if pred_i_energy is None else pred_i_energy - f(row, "energy_i_rms_mean"),
            }
        )
    return out


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["topology"]), str(row["category"]), str(row["mode"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (topology, category, mode), data in sorted(groups.items()):
        lv_err = np.asarray([f(r, "err_lv_pu", np.nan) for r in data], dtype=float)
        vdc_err = np.asarray([f(r, "err_vdc_pu", np.nan) for r in data], dtype=float)
        i_err = np.asarray([f(r, "err_energy_i_rms", np.nan) for r in data], dtype=float)
        summary.append(
            {
                "topology": topology,
                "category": category,
                "mode": mode,
                "n": len(data),
                "lv_mae_pu": float(np.nanmean(np.abs(lv_err))),
                "lv_max_abs_pu": float(np.nanmax(np.abs(lv_err))),
                "vdc_mae_pu": float(np.nanmean(np.abs(vdc_err))),
                "vdc_max_abs_pu": float(np.nanmax(np.abs(vdc_err))),
                "energy_i_mae": float(np.nanmean(np.abs(i_err))) if np.any(~np.isnan(i_err)) else float("nan"),
            }
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_*.csv")
    rows = read_csv(matrix_csv)
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    detail = analyze(rows, calibration)
    summary = summarize(detail)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(matrix_csv).stem.replace("frt_calibration_matrix_", "frt_proxy_gap_")
    detail_csv = args.out_dir / f"{stem}_detail.csv"
    summary_csv = args.out_dir / f"{stem}_summary.csv"
    summary_json = args.out_dir / f"{stem}_summary.json"
    write_csv(detail_csv, detail)
    write_csv(summary_csv, summary)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"detail_csv": str(detail_csv), "summary_csv": str(summary_csv)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
