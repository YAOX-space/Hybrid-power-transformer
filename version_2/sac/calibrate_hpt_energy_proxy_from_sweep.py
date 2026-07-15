"""Merge switch-level energy-converter sweeps into the HPT proxy calibration."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_energy_sweep"
DEFAULT_CALIBRATION = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"


def _latest_csv(directory: Path) -> Path:
    files = sorted(directory.glob("hpt_v2_sac_energy_sweep_*.csv"))
    if not files:
        raise FileNotFoundError(f"No energy sweep CSV files found in {directory}")
    return files[-1]


def _read_rows(path: Path) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, float | str] = {}
            for key, value in raw.items():
                if key in {"model", "topology"}:
                    row[key] = value
                else:
                    row[key] = float(value)
            rows.append(row)
    if not rows:
        raise ValueError(f"Energy sweep CSV is empty: {path}")
    return rows


def _safe_float(row: dict[str, float | str], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    return float(value)


def _energy_table(rows: list[dict[str, float | str]]) -> list[dict[str, float]]:
    table = []
    for r in rows:
        target = max(_safe_float(r, "target_phase_rms", 207.0), 1.0)
        table.append(
            {
                "grid_pu": _safe_float(r, "grid_pu"),
                "cmd_m_energy_d": _safe_float(r, "cmd_m_energy_d"),
                "cmd_m_energy_q": _safe_float(r, "cmd_m_energy_q"),
                "energy_d_mean": _safe_float(r, "energy_d_mean"),
                "energy_q_mean": _safe_float(r, "energy_q_mean"),
                "lv_pu_mean": _safe_float(r, "lv_pu_mean"),
                "lv_unbalance_pu": _safe_float(r, "lv_unbalance") / target,
                "vdc_pu_mean": _safe_float(r, "vdc_mean") / 800.0,
                "vdc_min_pu": _safe_float(r, "vdc_min") / 800.0,
                "vdc_max_pu": _safe_float(r, "vdc_max") / 800.0,
                "energy_i_rms_mean": _safe_float(r, "energy_i_rms_mean"),
                "energy_i_unbalance": _safe_float(r, "energy_i_unbalance"),
            }
        )
    return sorted(
        table,
        key=lambda x: (x["grid_pu"], x["energy_d_mean"], x["energy_q_mean"]),
    )


def _fit_energy(rows: list[dict[str, float | str]]) -> dict[str, float]:
    grid = np.asarray([_safe_float(r, "grid_pu") for r in rows], dtype=float)
    ed = np.asarray([_safe_float(r, "energy_d_mean") for r in rows], dtype=float)
    eq = np.asarray([_safe_float(r, "energy_q_mean") for r in rows], dtype=float)
    vdc = np.asarray([_safe_float(r, "vdc_mean") / 800.0 for r in rows], dtype=float)
    i_rms = np.asarray([_safe_float(r, "energy_i_rms_mean") for r in rows], dtype=float)

    x = np.column_stack([np.ones_like(grid), grid, ed, eq, np.abs(ed), np.abs(eq)])
    coef, *_ = np.linalg.lstsq(x, vdc, rcond=None)
    pred = x @ coef
    rmse = float(np.sqrt(np.mean((vdc - pred) ** 2)))
    i_x = np.column_stack([np.ones_like(grid), np.abs(ed), np.abs(eq)])
    i_coef, *_ = np.linalg.lstsq(i_x, i_rms, rcond=None)
    return {
        "vdc_bias": float(coef[0]),
        "vdc_grid_gain": float(coef[1]),
        "vdc_energy_d_gain": float(coef[2]),
        "vdc_energy_q_gain": float(coef[3]),
        "vdc_abs_energy_d_cost": float(-coef[4]),
        "vdc_abs_energy_q_cost": float(-coef[5]),
        "energy_i_bias": float(i_coef[0]),
        "energy_i_abs_d_gain": float(i_coef[1]),
        "energy_i_abs_q_gain": float(i_coef[2]),
        "fit_rmse_pu": rmse,
        "samples": len(rows),
    }


def merge_energy_calibration(calibration_path: Path, energy_csv: Path) -> dict:
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration.get("schema") != "hpt_proxy_calibration_v1":
        raise ValueError(f"Unsupported calibration schema: {calibration.get('schema')}")

    rows = _read_rows(energy_csv)
    by_topology: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for row in rows:
        by_topology[str(row["topology"])].append(row)

    for topology, data in sorted(by_topology.items()):
        if topology not in calibration.get("topologies", {}):
            calibration.setdefault("topologies", {})[topology] = {}
        calibration["topologies"][topology]["energy_response_table"] = _energy_table(data)
        calibration["topologies"][topology]["energy_fit"] = _fit_energy(data)

    calibration["energy_source_csv"] = str(energy_csv)
    calibration["energy_bridge_mode"] = "calibrated_direct_energy_bridge_available"
    return calibration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--energy-csv", type=Path, default=None)
    parser.add_argument("--energy-dir", type=Path, default=DEFAULT_SWEEP_DIR)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--out", type=Path, default=DEFAULT_CALIBRATION)
    args = parser.parse_args()

    energy_csv = args.energy_csv or _latest_csv(args.energy_dir)
    calibration = merge_energy_calibration(args.calibration, energy_csv)
    args.out.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "energy_csv": str(energy_csv),
        "topologies": sorted(calibration.get("topologies", {}).keys()),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
