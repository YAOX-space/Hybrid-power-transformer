"""Merge switch-level FRT calibration matrix data into the HPT proxy.

Input aggregate CSV is produced by
``version_2/simulink/collect_hpt_v2_frt_calibration_matrix.m``.  The merged
calibration keeps the existing steady response table and adds:

    fault_response_table
    fault_energy_response_table

Both are consumed by ``hpt_voltage_sac_env.py`` only when the active scenario
category is not ``steady``.
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
DEFAULT_CONTROL_DIR = ROOT / "lab" / "results" / "hpt_v2_control_comparison"
DEFAULT_CALIBRATION = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def latest_boundary_csv(directory: Path) -> Path:
    files = sorted(
        (
            p
            for p in Path(directory).glob("control_comparison_*conventional_boundary*.csv")
            if "_summary" not in p.stem
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise FileNotFoundError(f"No conventional boundary CSV found in {directory}")
    return files[-1]


def read_rows(path: Path) -> list[dict[str, Any]]:
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
    if not rows:
        raise ValueError(f"FRT matrix CSV is empty: {path}")
    return rows


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


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    return str(value)


def grid_metric_values(row: dict[str, Any]) -> dict[str, float | bool | str]:
    return {
        "grid_vpos_pu_min": f(row, "grid_vpos_pu_min", float("nan")),
        "grid_vpos_pu_mean": f(row, "grid_vpos_pu_mean", float("nan")),
        "grid_id_mean_pu": f(row, "grid_id_mean_pu", float("nan")),
        "grid_iq_mean_pu": f(row, "grid_iq_mean_pu", float("nan")),
        "grid_iq_ref_mean_pu": f(row, "grid_iq_ref_mean_pu", float("nan")),
        "grid_iq_shortfall_max_pu": f(row, "grid_iq_shortfall_max_pu", float("nan")),
        "grid_iq_met_fraction": f(row, "grid_iq_met_fraction", float("nan")),
        "grid_iq_wrong_sign": bool(f(row, "grid_iq_wrong_sign", 0.0)),
        "grid_current_peak_pu": f(row, "grid_current_peak_pu", float("nan")),
        "grid_idq_peak_pu": f(row, "grid_idq_peak_pu", float("nan")),
        "gbt_reactive_status": s(row, "gbt_reactive_status"),
        "gbt_reactive_pass": bool(f(row, "gbt_reactive_pass", 0.0)),
        "gbt_grid_current_limit_pass": bool(f(row, "gbt_grid_current_limit_pass", 0.0)),
    }


def boundary_category(row: dict[str, Any]) -> str:
    category = s(row, "gbt_category", "")
    if category:
        return category
    return "LVRT" if f(row, "fault_pu", 1.0) < 1.0 else "HVRT"


def conventional_response_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if s(row, "mode") != "conventional_dq":
            continue
        if s(row, "scenario_type") != "fault":
            continue
        table.append(
            {
                "fault": s(row, "case_name"),
                "category": boundary_category(row),
                "grid_pu": f(row, "fault_pu"),
                "fault_duration_s": f(row, "fault_duration_s", 0.0),
                "reg_d_mean": f(row, "reg_d_mean"),
                "reg_q_mean": f(row, "reg_q_mean"),
                "energy_d_mean": f(row, "energy_d_mean"),
                "energy_q_mean": f(row, "energy_q_mean"),
                "lv_pu_mean": f(row, "lv_mean") / 207.0,
                "lv_recovery_pu_mean": f(row, "lv_recovery_mean") / 207.0,
                "lv_peak_pu": f(row, "lv_peak") / 207.0,
                "lv_min_pu": f(row, "lv_min") / 207.0,
                "lv_unbalance_pu": f(row, "lv_unbalance", float("nan")) / 207.0,
                "vdc_pu_mean": f(row, "vdc_mean") / 800.0,
                "vdc_min_pu": f(row, "vdc_min") / 800.0,
                "vdc_max_pu": f(row, "vdc_max") / 800.0,
                "action_max_abs": f(row, "action_max_abs"),
                "control_score": f(row, "control_score", float("nan")),
                "voltage_survival_pass": bool(f(row, "voltage_survival_pass", 0.0)),
                "full_frt_pass": bool(f(row, "full_frt_pass", 0.0)),
                **grid_metric_values(row),
            }
        )
    return sorted(
        table,
        key=lambda x: (
            x["category"],
            x["fault_duration_s"],
            x["grid_pu"],
            x["reg_d_mean"],
            x["energy_d_mean"],
        ),
    )


def fault_response_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        mode = s(row, "mode")
        if mode != "reg_sweep":
            continue
        if abs(f(row, "raw_m_reg_q")) > 1e-9:
            continue
        table.append(
            {
                "fault": s(row, "fault", s(row, "case_name")),
                "category": s(row, "category"),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "cmd_m_reg_d": f(row, "raw_m_reg_d"),
                "cmd_m_reg_q": f(row, "raw_m_reg_q"),
                "reg_d_mean": f(row, "reg_d_mean"),
                "reg_q_mean": f(row, "reg_q_mean"),
                "lv_pu_mean": f(row, "lv_pu_mean"),
                "lv_recovery_pu_mean": f(row, "lv_recovery_pu_mean"),
                "lv_peak_pu": f(row, "lv_peak_pu"),
                "lv_min_pu": f(row, "lv_min_pu"),
                "lv_unbalance_pu": f(row, "lv_unbalance_pu"),
                "vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "energy_i_rms_mean": f(row, "energy_i_rms_mean", float("nan")),
                "action_max_abs": f(row, "action_max_abs"),
                **grid_metric_values(row),
            }
        )
    return sorted(table, key=lambda x: (x["grid_pu"], x["reg_d_mean"], x["cmd_m_reg_d"]))


def fault_reg_response_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if s(row, "mode") != "reg_sweep":
            continue
        table.append(
            {
                "fault": s(row, "fault", s(row, "case_name")),
                "category": s(row, "category"),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "cmd_m_reg_d": f(row, "raw_m_reg_d"),
                "cmd_m_reg_q": f(row, "raw_m_reg_q"),
                "reg_d_mean": f(row, "reg_d_mean"),
                "reg_q_mean": f(row, "reg_q_mean"),
                "lv_pu_mean": f(row, "lv_pu_mean"),
                "lv_recovery_pu_mean": f(row, "lv_recovery_pu_mean"),
                "lv_peak_pu": f(row, "lv_peak_pu"),
                "lv_min_pu": f(row, "lv_min_pu"),
                "lv_unbalance_pu": f(row, "lv_unbalance_pu"),
                "vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "energy_i_rms_mean": f(row, "energy_i_rms_mean", float("nan")),
                "action_max_abs": f(row, "action_max_abs"),
                **grid_metric_values(row),
            }
        )
    return sorted(table, key=lambda x: (x["grid_pu"], x["reg_d_mean"], x["reg_q_mean"]))


def fault_baseline_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if s(row, "mode") != "baseline":
            continue
        table.append(
            {
                "fault": s(row, "fault", s(row, "case_name")),
                "category": s(row, "category"),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "lv_pu_mean": f(row, "lv_pu_mean"),
                "lv_recovery_pu_mean": f(row, "lv_recovery_pu_mean"),
                "lv_peak_pu": f(row, "lv_peak_pu"),
                "lv_min_pu": f(row, "lv_min_pu"),
                "lv_unbalance_pu": f(row, "lv_unbalance_pu"),
                "vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "energy_i_rms_mean": f(row, "energy_i_rms_mean", float("nan")),
                "action_max_abs": f(row, "action_max_abs"),
                **grid_metric_values(row),
            }
        )
    return sorted(table, key=lambda x: (x["grid_pu"], x["fault"]))


def fault_energy_response_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if s(row, "mode") != "energy_sweep":
            continue
        table.append(
            {
                "fault": s(row, "fault", s(row, "case_name")),
                "category": s(row, "category"),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "cmd_m_energy_d": f(row, "raw_m_energy_d"),
                "cmd_m_energy_q": f(row, "raw_m_energy_q"),
                "energy_d_mean": f(row, "energy_d_mean"),
                "energy_q_mean": f(row, "energy_q_mean"),
                "lv_pu_mean": f(row, "lv_pu_mean"),
                "lv_recovery_pu_mean": f(row, "lv_recovery_pu_mean"),
                "lv_peak_pu": f(row, "lv_peak_pu"),
                "lv_min_pu": f(row, "lv_min_pu"),
                "lv_unbalance_pu": f(row, "lv_unbalance_pu"),
                "vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "energy_i_rms_mean": f(row, "energy_i_rms_mean"),
                "action_max_abs": f(row, "action_max_abs"),
                **grid_metric_values(row),
            }
        )
    return sorted(table, key=lambda x: (x["grid_pu"], x["energy_d_mean"], x["energy_q_mean"]))


def fault_joint_response_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if s(row, "mode") != "joint_sweep":
            continue
        table.append(
            {
                "fault": s(row, "fault", s(row, "case_name")),
                "category": s(row, "category"),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "cmd_m_reg_d": f(row, "raw_m_reg_d"),
                "cmd_m_reg_q": f(row, "raw_m_reg_q"),
                "cmd_m_energy_d": f(row, "raw_m_energy_d"),
                "cmd_m_energy_q": f(row, "raw_m_energy_q"),
                "reg_d_mean": f(row, "reg_d_mean"),
                "reg_q_mean": f(row, "reg_q_mean"),
                "energy_d_mean": f(row, "energy_d_mean"),
                "energy_q_mean": f(row, "energy_q_mean"),
                "lv_pu_mean": f(row, "lv_pu_mean"),
                "lv_recovery_pu_mean": f(row, "lv_recovery_pu_mean"),
                "lv_peak_pu": f(row, "lv_peak_pu"),
                "lv_min_pu": f(row, "lv_min_pu"),
                "lv_unbalance_pu": f(row, "lv_unbalance_pu"),
                "vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "energy_i_rms_mean": f(row, "energy_i_rms_mean"),
                "action_max_abs": f(row, "action_max_abs"),
                **grid_metric_values(row),
            }
        )
    return sorted(
        table,
        key=lambda x: (
            x["grid_pu"],
            x["reg_d_mean"],
            x["reg_q_mean"],
            x["energy_d_mean"],
            x["energy_q_mean"],
        ),
    )


def fit_fault_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reg_rows = [
        r for r in rows
        if s(r, "mode") == "reg_sweep" and abs(f(r, "raw_m_reg_q")) <= 1e-9
    ]
    if len(reg_rows) < 3:
        return {"samples": len(reg_rows)}
    grid = np.asarray([f(r, "grid_pu", f(r, "fault_pu")) for r in reg_rows], dtype=float)
    reg = np.asarray([f(r, "reg_d_mean") for r in reg_rows], dtype=float)
    lv = np.asarray([f(r, "lv_pu_mean") for r in reg_rows], dtype=float)
    vdc = np.asarray([f(r, "vdc_pu_mean", f(r, "vdc_mean") / 800.0) for r in reg_rows], dtype=float)

    x = np.column_stack([grid, np.ones_like(grid), reg])
    coef, *_ = np.linalg.lstsq(x, lv, rcond=None)
    pred = x @ coef
    vdc_x = np.column_stack([np.ones_like(reg), grid, np.abs(reg)])
    vdc_coef, *_ = np.linalg.lstsq(vdc_x, vdc, rcond=None)
    return {
        "samples": len(reg_rows),
        "lv_source_gain": float(coef[0]),
        "lv_source_bias": float(coef[1]),
        "lv_reg_gain": float(coef[2]),
        "lv_fit_rmse_pu": float(np.sqrt(np.mean((lv - pred) ** 2))),
        "vdc_bias": float(vdc_coef[0]),
        "vdc_grid_gain": float(vdc_coef[1]),
        "vdc_abs_reg_cost": float(-vdc_coef[2]),
    }


def merge_frt_calibration(calibration_path: Path, matrix_csv: Path) -> dict[str, Any]:
    calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    if calibration.get("schema") != "hpt_proxy_calibration_v1":
        raise ValueError(f"Unsupported calibration schema: {calibration.get('schema')}")

    rows = read_rows(matrix_csv)
    by_topology: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_topology[s(row, "topology")].append(row)

    calibration["frt_source_csv"] = str(matrix_csv)
    calibration["frt_matrix"] = {
        "fault_depths": sorted({f(r, "grid_pu", f(r, "fault_pu")) for r in rows}),
        "categories": sorted({s(r, "category") for r in rows}),
        "modes": sorted({s(r, "mode") for r in rows}),
    }
    for topology, data in sorted(by_topology.items()):
        top = calibration.setdefault("topologies", {}).setdefault(topology, {})
        top["fault_baseline_table"] = fault_baseline_table(data)
        top["fault_response_table"] = fault_response_table(data)
        top["fault_reg_response_table"] = fault_reg_response_table(data)
        top["fault_energy_response_table"] = fault_energy_response_table(data)
        top["fault_joint_response_table"] = fault_joint_response_table(data)
        top["fault_fit"] = fit_fault_summary(data)
    return calibration


def merge_conventional_boundary(calibration: dict[str, Any], boundary_csv: Path | None) -> dict[str, Any]:
    if boundary_csv is None:
        return calibration
    rows = read_rows(boundary_csv)
    by_topology: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if s(row, "mode") != "conventional_dq" or s(row, "scenario_type") != "fault":
            continue
        by_topology[s(row, "topology")].append(row)
    calibration["conventional_source_csv"] = str(boundary_csv)
    for topology, data in sorted(by_topology.items()):
        top = calibration.setdefault("topologies", {}).setdefault(topology, {})
        top["fault_conventional_response_table"] = conventional_response_table(data)
    return calibration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--conventional-csv", type=Path, default=None)
    parser.add_argument("--control-dir", type=Path, default=DEFAULT_CONTROL_DIR)
    parser.add_argument("--skip-conventional", action="store_true")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--out", type=Path, default=DEFAULT_CALIBRATION)
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_*.csv")
    calibration = merge_frt_calibration(args.calibration, matrix_csv)
    conventional_csv = None if args.skip_conventional else (args.conventional_csv or latest_boundary_csv(args.control_dir))
    calibration = merge_conventional_boundary(calibration, conventional_csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "matrix_csv": str(matrix_csv),
                "conventional_csv": str(conventional_csv) if conventional_csv is not None else None,
                "topologies": sorted(calibration.get("topologies", {}).keys()),
                "fault_depths": calibration.get("frt_matrix", {}).get("fault_depths", []),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
