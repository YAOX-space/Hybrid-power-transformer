"""Measure the gap between HPT switch-level sweeps and the current proxy.

This script is the first proxy-governance gate for the direct SAC research
line.  It compares fixed-action Simulink sweep CSVs against the calibrated
averaged proxy tables and linear fits stored in ``hpt_proxy_calibration.json``.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from version_2.sac.experiment_metadata import write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_CALIBRATION = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"
DEFAULT_PROXY_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_proxy_sweep"
DEFAULT_ENERGY_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_energy_sweep"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_proxy_gap"


def latest_csv(directory: Path, pattern: str) -> Path | None:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value is None:
                    row[key] = value
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
            rows.append(row)
    return rows


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
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


def interp_response_table(
    table: list[dict[str, Any]],
    grid_pu: float,
    reg_d: float,
    value_key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({round(float(row["grid_pu"]), 9) for row in table})
    values_by_grid: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            x = float(row["reg_d_mean"])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        values_by_grid.append(float(np.interp(float(reg_d), xs, ys)))
        used_grids.append(grid)
    if not used_grids:
        return None
    return float(np.interp(float(grid_pu), np.asarray(used_grids), np.asarray(values_by_grid)))


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
    grids = sorted({round(float(row["grid_pu"]), 9) for row in table})
    values_by_grid: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            if abs(float(row[other_axis_key])) > 1e-9:
                continue
            x = float(row[axis_key])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        values_by_grid.append(float(np.interp(float(action_value), xs, ys)))
        used_grids.append(grid)
    if not used_grids:
        return None
    return float(np.interp(float(grid_pu), np.asarray(used_grids), np.asarray(values_by_grid)))


def interp_energy_response(
    table: list[dict[str, Any]],
    grid_pu: float,
    energy_d: float,
    energy_q: float,
    value_key: str,
) -> float | None:
    baseline = interp_energy_axis(
        table, grid_pu, 0.0, "energy_d_mean", "energy_q_mean", value_key
    )
    d_axis = interp_energy_axis(
        table, grid_pu, energy_d, "energy_d_mean", "energy_q_mean", value_key
    )
    q_axis = interp_energy_axis(
        table, grid_pu, energy_q, "energy_q_mean", "energy_d_mean", value_key
    )
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def projected_reg_command(cmd_m_reg_d: float, grid_pu: float) -> float:
    cmd = float(np.clip(cmd_m_reg_d, -0.8, 0.8))
    if grid_pu < 0.92 and cmd < 0.0:
        return 0.0
    if grid_pu > 1.08 and cmd > 0.0:
        return 0.0
    return cmd


def analyze_reg_sweep(rows: Iterable[dict[str, Any]], calibration: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        topology = str(row["topology"])
        cal = calibration["topologies"][topology]
        grid_pu = f(row, "grid_pu")
        cmd_reg_d = f(row, "cmd_m_reg_d", f(row, "reg_d_mean"))
        proxy_reg_d = projected_reg_command(cmd_reg_d, grid_pu)
        actual_lv = f(row, "lv_pu_mean")
        actual_vdc = f(row, "vdc_mean") / 800.0
        table_lv = interp_response_table(cal.get("response_table", []), grid_pu, proxy_reg_d, "lv_pu_mean")
        table_vdc = interp_response_table(cal.get("response_table", []), grid_pu, proxy_reg_d, "vdc_pu_mean")
        linear_lv = (
            float(cal["source_gain"]) * grid_pu
            + float(cal["source_bias"])
            + float(cal["reg_gain"]) * proxy_reg_d
        )
        linear_vdc = float(cal["vdc_base_pu"]) - float(cal.get("vdc_reg_abs_cost", 0.0)) * abs(proxy_reg_d)
        out.append(
            {
                "sweep": "reg",
                "model": row.get("model", ""),
                "topology": topology,
                "grid_pu": grid_pu,
                "cmd_m_reg_d": cmd_reg_d,
                "sim_reg_d_mean": f(row, "reg_d_mean"),
                "proxy_reg_d": proxy_reg_d,
                "sim_lv_pu": actual_lv,
                "proxy_table_lv_pu": table_lv,
                "proxy_linear_lv_pu": linear_lv,
                "err_table_lv_pu": None if table_lv is None else table_lv - actual_lv,
                "err_linear_lv_pu": linear_lv - actual_lv,
                "sim_vdc_pu": actual_vdc,
                "proxy_table_vdc_pu": table_vdc,
                "proxy_linear_vdc_pu": linear_vdc,
                "err_table_vdc_pu": None if table_vdc is None else table_vdc - actual_vdc,
                "err_linear_vdc_pu": linear_vdc - actual_vdc,
                "sim_vdc_min_pu": f(row, "vdc_min") / 800.0,
                "sim_lv_unbalance_pu": f(row, "lv_unbalance") / max(f(row, "target_phase_rms", 207.0), 1.0),
            }
        )
    return out


def analyze_energy_sweep(rows: Iterable[dict[str, Any]], calibration: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        topology = str(row["topology"])
        cal = calibration["topologies"][topology]
        table = cal.get("energy_response_table", [])
        fit = cal.get("energy_fit", {})
        grid_pu = f(row, "grid_pu")
        energy_d = f(row, "energy_d_mean", f(row, "cmd_m_energy_d"))
        energy_q = f(row, "energy_q_mean", f(row, "cmd_m_energy_q"))
        actual_vdc = f(row, "vdc_mean") / 800.0
        actual_i = f(row, "energy_i_rms_mean")
        table_vdc = interp_energy_response(table, grid_pu, energy_d, energy_q, "vdc_pu_mean")
        table_i = interp_energy_response(table, grid_pu, energy_d, energy_q, "energy_i_rms_mean")
        fit_vdc = None
        fit_i = None
        if fit:
            fit_vdc = (
                float(fit.get("vdc_bias", 0.0))
                + float(fit.get("vdc_grid_gain", 0.0)) * grid_pu
                + float(fit.get("vdc_energy_d_gain", 0.0)) * energy_d
                + float(fit.get("vdc_energy_q_gain", 0.0)) * energy_q
                - float(fit.get("vdc_abs_energy_d_cost", 0.0)) * abs(energy_d)
                - float(fit.get("vdc_abs_energy_q_cost", 0.0)) * abs(energy_q)
            )
            fit_i = (
                float(fit.get("energy_i_bias", 0.0))
                + float(fit.get("energy_i_abs_d_gain", 0.0)) * abs(energy_d)
                + float(fit.get("energy_i_abs_q_gain", 0.0)) * abs(energy_q)
            )
        out.append(
            {
                "sweep": "energy",
                "model": row.get("model", ""),
                "topology": topology,
                "grid_pu": grid_pu,
                "cmd_m_energy_d": f(row, "cmd_m_energy_d"),
                "cmd_m_energy_q": f(row, "cmd_m_energy_q"),
                "sim_energy_d_mean": energy_d,
                "sim_energy_q_mean": energy_q,
                "sim_vdc_pu": actual_vdc,
                "proxy_table_vdc_pu": table_vdc,
                "proxy_fit_vdc_pu": fit_vdc,
                "err_table_vdc_pu": None if table_vdc is None else table_vdc - actual_vdc,
                "err_fit_vdc_pu": None if fit_vdc is None else fit_vdc - actual_vdc,
                "sim_energy_i_rms": actual_i,
                "proxy_table_energy_i_rms": table_i,
                "proxy_fit_energy_i_rms": fit_i,
                "err_table_energy_i_rms": None if table_i is None else table_i - actual_i,
                "err_fit_energy_i_rms": None if fit_i is None else fit_i - actual_i,
                "sim_vdc_min_pu": f(row, "vdc_min") / 800.0,
                "sim_vdc_max_pu": f(row, "vdc_max") / 800.0,
            }
        )
    return out


def rmse(values: Iterable[float | None]) -> float | None:
    arr = np.asarray([float(v) for v in values if v is not None], dtype=float)
    if arr.size == 0:
        return None
    return float(np.sqrt(np.mean(arr * arr)))


def max_abs(values: Iterable[float | None]) -> float | None:
    arr = np.asarray([float(v) for v in values if v is not None], dtype=float)
    if arr.size == 0:
        return None
    return float(np.max(np.abs(arr)))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sweep: dict[str, list[dict[str, Any]]] = {}
    by_topology: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_sweep.setdefault(str(row["sweep"]), []).append(row)
        by_topology.setdefault(str(row["topology"]), []).append(row)

    def block(part: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "rows": len(part),
            "reg_table_lv_rmse_pu": rmse(row.get("err_table_lv_pu") for row in part),
            "reg_linear_lv_rmse_pu": rmse(row.get("err_linear_lv_pu") for row in part),
            "reg_table_vdc_rmse_pu": rmse(row.get("err_table_vdc_pu") for row in part),
            "reg_linear_vdc_rmse_pu": rmse(row.get("err_linear_vdc_pu") for row in part),
            "energy_table_vdc_rmse_pu": rmse(row.get("err_table_vdc_pu") for row in part if row["sweep"] == "energy"),
            "energy_fit_vdc_rmse_pu": rmse(row.get("err_fit_vdc_pu") for row in part),
            "max_abs_lv_error_pu": max_abs(
                [row.get("err_table_lv_pu") for row in part]
                + [row.get("err_linear_lv_pu") for row in part]
            ),
            "min_sim_vdc_pu": min((float(row.get("sim_vdc_min_pu", 999.0)) for row in part), default=None),
        }

    return {
        "schema": "hpt-v2-proxy-gap-v1",
        "total_rows": len(rows),
        "by_sweep": {name: block(part) for name, part in sorted(by_sweep.items())},
        "by_topology": {name: block(part) for name, part in sorted(by_topology.items())},
        "worst_rows": sorted(
            rows,
            key=lambda row: max(
                abs(float(row.get("err_table_lv_pu") or 0.0)),
                abs(float(row.get("err_linear_lv_pu") or 0.0)),
                abs(float(row.get("err_table_vdc_pu") or 0.0)),
                abs(float(row.get("err_linear_vdc_pu") or 0.0)),
                abs(float(row.get("err_fit_vdc_pu") or 0.0)),
            ),
            reverse=True,
        )[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--proxy-sweep-csv", type=Path, default=None)
    parser.add_argument("--energy-sweep-csv", type=Path, default=None)
    parser.add_argument("--proxy-sweep-dir", type=Path, default=DEFAULT_PROXY_SWEEP_DIR)
    parser.add_argument("--energy-sweep-dir", type=Path, default=DEFAULT_ENERGY_SWEEP_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
    proxy_csv = args.proxy_sweep_csv or latest_csv(args.proxy_sweep_dir, "hpt_v2_sac_proxy_sweep_*.csv")
    energy_csv = args.energy_sweep_csv or latest_csv(args.energy_sweep_dir, "hpt_v2_sac_energy_sweep_*.csv")
    if proxy_csv is None and energy_csv is None:
        raise FileNotFoundError("No proxy or energy sweep CSV found")

    rows: list[dict[str, Any]] = []
    if proxy_csv is not None:
        rows.extend(analyze_reg_sweep(read_csv_rows(proxy_csv), calibration))
    if energy_csv is not None:
        rows.extend(analyze_energy_sweep(read_csv_rows(energy_csv), calibration))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = args.out_dir / f"proxy_gap_{stamp}"
    csv_out = run_dir / "proxy_gap_rows.csv"
    json_out = run_dir / "summary.json"
    summary = summarize(rows)
    summary.update(
        {
            "calibration": str(args.calibration),
            "proxy_sweep_csv": str(proxy_csv) if proxy_csv is not None else None,
            "energy_sweep_csv": str(energy_csv) if energy_csv is not None else None,
            "rows_csv": str(csv_out),
        }
    )
    write_csv_rows(csv_out, rows)
    json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_proxy_gap_measurement",
        config={
            "calibration": str(args.calibration),
            "proxy_sweep_csv": str(proxy_csv) if proxy_csv is not None else None,
            "energy_sweep_csv": str(energy_csv) if energy_csv is not None else None,
        },
        dataset_manifest=None,
        extra={"summary_path": str(json_out), "rows_csv": str(csv_out)},
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()


