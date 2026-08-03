"""Fit the HPT averaged SAC proxy from switch-level fixed-action sweeps.

The input is produced by
``version_2/simulink/sweeps/sweep_hpt_v2_sac_action_response.m``.  The fitted model is
intentionally simple and deployable:

    v_lv_pu ~= source_gain * grid_pu + source_bias + reg_gain * m_reg_d

The calibration file is consumed by ``hpt_voltage_sac_env.py`` so SAC training
sees the same action sign and approximate voltage authority as the physical
switch-level Simulink models.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_proxy_sweep"
DEFAULT_OUT = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"


@dataclass
class TopologyFit:
    topology: str
    source_gain: float
    source_bias: float
    reg_gain: float
    vdc_base_pu: float
    vdc_reg_abs_cost: float
    samples: int
    fit_rmse_pu: float
    reg_sign: float
    stable_reg_limit: float


def _latest_csv(directory: Path) -> Path:
    files = sorted(directory.glob("hpt_v2_sac_proxy_sweep_*.csv"))
    if not files:
        raise FileNotFoundError(f"No sweep CSV files found in {directory}")
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
                    try:
                        row[key] = float(value)
                    except (TypeError, ValueError):
                        row[key] = value
            rows.append(row)
    if not rows:
        raise ValueError(f"Sweep CSV is empty: {path}")
    return rows


def _scenario_class(grid_pu: float) -> str:
    if grid_pu < 0.95:
        return "sag"
    if grid_pu > 1.05:
        return "swell"
    return "nominal"


def _fit_topology(topology: str, rows: Iterable[dict[str, float | str]]) -> TopologyFit:
    data = list(rows)
    grid = np.asarray([float(r["grid_pu"]) for r in data], dtype=float)
    action = np.asarray([float(r["reg_d_mean"]) for r in data], dtype=float)
    lv = np.asarray([float(r["lv_pu_mean"]) for r in data], dtype=float)
    vdc_pu = np.asarray([float(r["vdc_mean"]) / 800.0 for r in data], dtype=float)

    x = np.column_stack([grid, np.ones_like(grid), action])
    coef, *_ = np.linalg.lstsq(x, lv, rcond=None)
    pred = x @ coef
    rmse = float(np.sqrt(np.mean((lv - pred) ** 2)))

    vdc_x = np.column_stack([np.ones_like(action), np.abs(action)])
    vdc_coef, *_ = np.linalg.lstsq(vdc_x, vdc_pu, rcond=None)

    reg_gain = float(coef[2])
    reg_sign = 1.0 if reg_gain >= 0.0 else -1.0
    max_seen = float(np.max(np.abs(action))) if action.size else 0.0
    stable_reg_limit = min(0.80, max(0.10, max_seen))

    return TopologyFit(
        topology=topology,
        source_gain=float(coef[0]),
        source_bias=float(coef[1]),
        reg_gain=reg_gain,
        vdc_base_pu=float(vdc_coef[0]),
        vdc_reg_abs_cost=float(max(0.0, -vdc_coef[1])),
        samples=len(data),
        fit_rmse_pu=rmse,
        reg_sign=reg_sign,
        stable_reg_limit=stable_reg_limit,
    )


def _response_table(rows: Iterable[dict[str, float | str]]) -> list[dict[str, float]]:
    table = []
    for r in rows:
        vdc_mean = float(r["vdc_mean"])
        table.append(
            {
                "grid_pu": float(r["grid_pu"]),
                "cmd_m_reg_d": float(r["cmd_m_reg_d"]),
                "reg_d_mean": float(r["reg_d_mean"]),
                "lv_pu_mean": float(r["lv_pu_mean"]),
                "vdc_pu_mean": vdc_mean / 800.0,
                "lv_unbalance_pu": float(r["lv_unbalance"]) / max(float(r["target_phase_rms"]), 1.0),
                "vdc_min_pu": float(r["vdc_min"]) / 800.0,
            }
        )
    return sorted(table, key=lambda x: (x["grid_pu"], x["reg_d_mean"], x["cmd_m_reg_d"]))


def build_calibration(sweep_csv: Path) -> dict:
    rows = _read_rows(sweep_csv)
    by_topology: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for row in rows:
        by_topology[str(row["topology"])].append(row)

    fits = {name: _fit_topology(name, data) for name, data in sorted(by_topology.items())}
    target_phase_rms = float(rows[0].get("target_phase_rms", 207.0))
    grid_classes = {
        f"{float(r['grid_pu']):.3f}": _scenario_class(float(r["grid_pu"]))
        for r in rows
    }

    topologies = {}
    for name, fit in fits.items():
        record = asdict(fit)
        record["response_table"] = _response_table(by_topology[name])
        topologies[name] = record

    return {
        "schema": "hpt_proxy_calibration_v1",
        "source_csv": str(sweep_csv),
        "target_phase_rms": target_phase_rms,
        "action_contract": "[m_reg_d, m_reg_q, m_energy_d, m_energy_q]",
        "energy_bridge_mode": "conventional_dc_loop_during_calibration",
        "classifier": {
            "sag_grid_pu_lt": 0.95,
            "swell_grid_pu_gt": 1.05,
            "grid_classes": grid_classes,
        },
        "topologies": topologies,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep-csv", type=Path, default=None)
    parser.add_argument("--sweep-dir", type=Path, default=DEFAULT_SWEEP_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    sweep_csv = args.sweep_csv or _latest_csv(args.sweep_dir)
    calibration = build_calibration(sweep_csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(json.dumps(calibration, indent=2), flush=True)


if __name__ == "__main__":
    main()



