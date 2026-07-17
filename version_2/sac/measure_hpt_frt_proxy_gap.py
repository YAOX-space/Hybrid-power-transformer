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
INTERP_EPS = 1e-6


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


def has_numeric(row: dict[str, Any], key: str) -> bool:
    if key not in row or row.get(key) in ("", None):
        return False
    try:
        return bool(np.isfinite(float(row[key])))
    except (TypeError, ValueError):
        return False


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
            if not has_numeric(row, key):
                continue
            bucket[f(row, "reg_d_mean")].append(f(row, key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(reg_d) < float(xs[0]) - INTERP_EPS or float(reg_d) > float(xs[-1]) + INTERP_EPS:
            continue
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
        if not has_numeric(row, key):
            continue
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
            if not has_numeric(row, value_key):
                continue
            bucket[f(row, axis_key)].append(f(row, value_key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(action_value) < float(xs[0]) - INTERP_EPS or float(action_value) > float(xs[-1]) + INTERP_EPS:
            continue
        vals.append(float(np.interp(action_value, xs, ys)))
        used_grids.append(grid)
    if not vals:
        return None
    return float(np.interp(grid_pu, np.asarray(used_grids), np.asarray(vals)))


def interp_energy(table: list[dict[str, Any]], grid_pu: float, ed: float, eq: float, key: str) -> float | None:
    coupled = interp_grid_axes(
        table,
        grid_pu,
        ["energy_d_mean", "energy_q_mean"],
        [ed, eq],
        key,
    )
    if coupled is not None:
        return coupled

    baseline = interp_energy_axis(table, grid_pu, 0.0, "energy_d_mean", "energy_q_mean", key)
    d_axis = interp_energy_axis(table, grid_pu, ed, "energy_d_mean", "energy_q_mean", key)
    q_axis = interp_energy_axis(table, grid_pu, eq, "energy_q_mean", "energy_d_mean", key)
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def interp_axes(rows: list[dict[str, Any]], axis_keys: list[str], axis_values: list[float], key: str) -> float | None:
    if not rows:
        return None
    if not axis_keys:
        vals = [f(row, key, np.nan) for row in rows]
        vals = [value for value in vals if np.isfinite(value)]
        if not vals:
            return None
        return float(np.mean(vals))

    axis_key = axis_keys[0]
    target = float(axis_values[0])
    bucket: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket[f(row, axis_key)].append(row)
    if not bucket:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for x in sorted(bucket):
        value = interp_axes(bucket[x], axis_keys[1:], axis_values[1:], key)
        if value is None:
            continue
        xs.append(float(x))
        ys.append(float(value))
    if not xs:
        return None
    if target < min(xs) - INTERP_EPS or target > max(xs) + INTERP_EPS:
        return None
    return float(np.interp(target, np.asarray(xs), np.asarray(ys)))


def interp_grid_axes(
    table: list[dict[str, Any]],
    grid_pu: float,
    axis_keys: list[str],
    axis_values: list[float],
    key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    xs: list[float] = []
    ys: list[float] = []
    for grid in grids:
        rows = [row for row in table if abs(f(row, "grid_pu") - grid) <= 1e-9]
        value = interp_axes(rows, axis_keys, axis_values, key)
        if value is None:
            continue
        xs.append(float(grid))
        ys.append(float(value))
    if not xs:
        return None
    if float(grid_pu) < min(xs) - INTERP_EPS or float(grid_pu) > max(xs) + INTERP_EPS:
        return None
    return float(np.interp(float(grid_pu), np.asarray(xs), np.asarray(ys)))


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
        reg_table = top.get("fault_reg_response_table", top.get("fault_response_table", []))
        reg_d_axis_table = top.get("fault_response_table", [])
        energy_table = top.get("fault_energy_response_table", [])
        joint_table = top.get("fault_joint_response_table", [])
        baseline_table = top.get("fault_baseline_table", [])

        def predict_metric(key: str) -> float | None:
            pred = interp_grid_axes(
                reg_table, grid, ["reg_d_mean", "reg_q_mean"], [reg, reg_q], key
            )
            if pred is None:
                pred = interp_response(reg_d_axis_table, grid, reg, key)
            pred_energy = interp_energy(energy_table, grid, ed, eq, key)
            if mode == "baseline":
                return interp_by_grid(baseline_table, grid, key)
            if mode in {"energy_sweep"}:
                return pred_energy
            if mode in {"joint_sweep"}:
                joint = interp_grid_axes(
                    joint_table,
                    grid,
                    ["reg_d_mean", "energy_d_mean", "energy_q_mean"],
                    [reg, ed, eq],
                    key,
                )
                if joint is not None:
                    return joint
                if pred is not None and pred_energy is not None:
                    zero_energy = interp_energy(energy_table, grid, 0.0, 0.0, key)
                    if zero_energy is not None:
                        return pred + (pred_energy - zero_energy)
            return pred

        pred_lv = predict_metric("lv_pu_mean")
        pred_lv_recovery = predict_metric("lv_recovery_pu_mean")
        pred_lv_peak = predict_metric("lv_peak_pu")
        pred_lv_min = predict_metric("lv_min_pu")
        pred_lv_unbalance = predict_metric("lv_unbalance_pu")
        pred_vdc = predict_metric("vdc_pu_mean")
        pred_vdc_min = predict_metric("vdc_min_pu")
        pred_vdc_max = predict_metric("vdc_max_pu")
        pred_action_max = predict_metric("action_max_abs")
        pred_i_energy = predict_metric("energy_i_rms_mean")
        pred_grid_vpos = predict_metric("grid_vpos_pu_mean")
        pred_grid_iq = predict_metric("grid_iq_mean_pu")
        pred_grid_iq_ref = predict_metric("grid_iq_ref_mean_pu")
        pred_grid_iq_shortfall = predict_metric("grid_iq_shortfall_max_pu")
        pred_grid_iq_wrong_sign = predict_metric("grid_iq_wrong_sign")
        pred_grid_current = predict_metric("grid_current_peak_pu")
        pred_grid_idq = predict_metric("grid_idq_peak_pu")
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
                "sim_lv_recovery_pu": f(row, "lv_recovery_pu_mean", np.nan),
                "proxy_lv_recovery_pu": pred_lv_recovery,
                "err_lv_recovery_pu": None if pred_lv_recovery is None else pred_lv_recovery - f(row, "lv_recovery_pu_mean", np.nan),
                "sim_lv_peak_pu": f(row, "lv_peak_pu", np.nan),
                "proxy_lv_peak_pu": pred_lv_peak,
                "err_lv_peak_pu": None if pred_lv_peak is None else pred_lv_peak - f(row, "lv_peak_pu", np.nan),
                "sim_lv_min_pu": f(row, "lv_min_pu", np.nan),
                "proxy_lv_min_pu": pred_lv_min,
                "err_lv_min_pu": None if pred_lv_min is None else pred_lv_min - f(row, "lv_min_pu", np.nan),
                "sim_lv_unbalance_pu": f(row, "lv_unbalance_pu", np.nan),
                "proxy_lv_unbalance_pu": pred_lv_unbalance,
                "err_lv_unbalance_pu": None if pred_lv_unbalance is None else pred_lv_unbalance - f(row, "lv_unbalance_pu", np.nan),
                "sim_vdc_pu": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "proxy_vdc_pu": pred_vdc,
                "err_vdc_pu": None if pred_vdc is None else pred_vdc - f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "sim_vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "proxy_vdc_min_pu": pred_vdc_min,
                "err_vdc_min_pu": None if pred_vdc_min is None else pred_vdc_min - f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "sim_vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "proxy_vdc_max_pu": pred_vdc_max,
                "err_vdc_max_pu": None if pred_vdc_max is None else pred_vdc_max - f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "sim_action_max_abs": f(row, "action_max_abs", np.nan),
                "proxy_action_max_abs": pred_action_max,
                "err_action_max_abs": None if pred_action_max is None else pred_action_max - f(row, "action_max_abs", np.nan),
                "sim_energy_i_rms": f(row, "energy_i_rms_mean"),
                "proxy_energy_i_rms": pred_i_energy,
                "err_energy_i_rms": None if pred_i_energy is None else pred_i_energy - f(row, "energy_i_rms_mean"),
                "sim_grid_vpos_pu": f(row, "grid_vpos_pu_mean", np.nan),
                "proxy_grid_vpos_pu": pred_grid_vpos,
                "err_grid_vpos_pu": None if pred_grid_vpos is None else pred_grid_vpos - f(row, "grid_vpos_pu_mean", np.nan),
                "sim_grid_iq_pu": f(row, "grid_iq_mean_pu", np.nan),
                "proxy_grid_iq_pu": pred_grid_iq,
                "err_grid_iq_pu": None if pred_grid_iq is None else pred_grid_iq - f(row, "grid_iq_mean_pu", np.nan),
                "sim_grid_iq_ref_pu": f(row, "grid_iq_ref_mean_pu", np.nan),
                "proxy_grid_iq_ref_pu": pred_grid_iq_ref,
                "err_grid_iq_ref_pu": None if pred_grid_iq_ref is None else pred_grid_iq_ref - f(row, "grid_iq_ref_mean_pu", np.nan),
                "sim_grid_iq_shortfall_pu": f(row, "grid_iq_shortfall_max_pu", np.nan),
                "proxy_grid_iq_shortfall_pu": pred_grid_iq_shortfall,
                "err_grid_iq_shortfall_pu": None if pred_grid_iq_shortfall is None else pred_grid_iq_shortfall - f(row, "grid_iq_shortfall_max_pu", np.nan),
                "sim_grid_iq_wrong_sign": f(row, "grid_iq_wrong_sign", np.nan),
                "proxy_grid_iq_wrong_sign": pred_grid_iq_wrong_sign,
                "err_grid_iq_wrong_sign": None if pred_grid_iq_wrong_sign is None else pred_grid_iq_wrong_sign - f(row, "grid_iq_wrong_sign", np.nan),
                "sim_grid_current_peak_pu": f(row, "grid_current_peak_pu", np.nan),
                "proxy_grid_current_peak_pu": pred_grid_current,
                "err_grid_current_peak_pu": None if pred_grid_current is None else pred_grid_current - f(row, "grid_current_peak_pu", np.nan),
                "sim_grid_idq_peak_pu": f(row, "grid_idq_peak_pu", np.nan),
                "proxy_grid_idq_peak_pu": pred_grid_idq,
                "err_grid_idq_peak_pu": None if pred_grid_idq is None else pred_grid_idq - f(row, "grid_idq_peak_pu", np.nan),
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
        lv_recovery_err = np.asarray([f(r, "err_lv_recovery_pu", np.nan) for r in data], dtype=float)
        lv_peak_err = np.asarray([f(r, "err_lv_peak_pu", np.nan) for r in data], dtype=float)
        lv_min_err = np.asarray([f(r, "err_lv_min_pu", np.nan) for r in data], dtype=float)
        vdc_err = np.asarray([f(r, "err_vdc_pu", np.nan) for r in data], dtype=float)
        vdc_min_err = np.asarray([f(r, "err_vdc_min_pu", np.nan) for r in data], dtype=float)
        vdc_max_err = np.asarray([f(r, "err_vdc_max_pu", np.nan) for r in data], dtype=float)
        i_err = np.asarray([f(r, "err_energy_i_rms", np.nan) for r in data], dtype=float)
        grid_iq_err = np.asarray([f(r, "err_grid_iq_pu", np.nan) for r in data], dtype=float)
        grid_iq_shortfall_err = np.asarray([f(r, "err_grid_iq_shortfall_pu", np.nan) for r in data], dtype=float)
        grid_iq_wrong_err = np.asarray([f(r, "err_grid_iq_wrong_sign", np.nan) for r in data], dtype=float)
        grid_current_err = np.asarray([f(r, "err_grid_current_peak_pu", np.nan) for r in data], dtype=float)
        summary.append(
            {
                "topology": topology,
                "category": category,
                "mode": mode,
                "n": len(data),
                "lv_mae_pu": float(np.nanmean(np.abs(lv_err))),
                "lv_max_abs_pu": float(np.nanmax(np.abs(lv_err))),
                "lv_recovery_mae_pu": float(np.nanmean(np.abs(lv_recovery_err))) if np.any(~np.isnan(lv_recovery_err)) else float("nan"),
                "lv_peak_mae_pu": float(np.nanmean(np.abs(lv_peak_err))) if np.any(~np.isnan(lv_peak_err)) else float("nan"),
                "lv_min_mae_pu": float(np.nanmean(np.abs(lv_min_err))) if np.any(~np.isnan(lv_min_err)) else float("nan"),
                "vdc_mae_pu": float(np.nanmean(np.abs(vdc_err))),
                "vdc_max_abs_pu": float(np.nanmax(np.abs(vdc_err))),
                "vdc_min_mae_pu": float(np.nanmean(np.abs(vdc_min_err))) if np.any(~np.isnan(vdc_min_err)) else float("nan"),
                "vdc_max_mae_pu": float(np.nanmean(np.abs(vdc_max_err))) if np.any(~np.isnan(vdc_max_err)) else float("nan"),
                "energy_i_mae": float(np.nanmean(np.abs(i_err))) if np.any(~np.isnan(i_err)) else float("nan"),
                "grid_iq_mae_pu": float(np.nanmean(np.abs(grid_iq_err))) if np.any(~np.isnan(grid_iq_err)) else float("nan"),
                "grid_iq_shortfall_mae_pu": float(np.nanmean(np.abs(grid_iq_shortfall_err))) if np.any(~np.isnan(grid_iq_shortfall_err)) else float("nan"),
                "grid_iq_wrong_sign_mae": float(np.nanmean(np.abs(grid_iq_wrong_err))) if np.any(~np.isnan(grid_iq_wrong_err)) else float("nan"),
                "grid_current_mae_pu": float(np.nanmean(np.abs(grid_current_err))) if np.any(~np.isnan(grid_current_err)) else float("nan"),
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
