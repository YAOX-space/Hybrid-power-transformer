"""Convert switch-level fixed-action validation rows into FRT calibration rows.

The FRT proxy is calibrated from matrix-like switch-level CSVs.  Offline
full-action validation produces a different, comparison-oriented CSV with
``switch_fixed_*`` columns.  This bridge keeps the data flow auditable by
turning each fixed-action validation result into a calibration-compatible
``joint_sweep`` row, so later proxy calibration can learn from actions that
failed in the real switch-level model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from .experiment_metadata import sha256_file, write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
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


def f(row: dict[str, str], key: str, default: float = float("nan")) -> float:
    try:
        value = row.get(key, default)
        if value in ("", None):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def b(row: dict[str, str], key: str) -> bool:
    text = str(row.get(key, "")).strip().lower()
    return text in {"1", "1.0", "true", "yes", "y"}


def finite_or_blank(value: float) -> float | str:
    return float(value) if math.isfinite(float(value)) else ""


def pu(value: float, base: float) -> float | str:
    return finite_or_blank(value / base) if math.isfinite(float(value)) else ""


def convert_row(row: dict[str, str], index: int) -> dict[str, Any]:
    fault_pu = f(row, "fault_pu", 1.0)
    duration_s = f(row, "duration_ms", 0.0) / 1000.0
    fault_start = 0.035
    vdc_min = f(row, "switch_fixed_vdc_min")
    vdc_max = f(row, "switch_fixed_vdc_max")
    vdc_mean = 0.5 * (vdc_min + vdc_max) if math.isfinite(vdc_min) and math.isfinite(vdc_max) else float("nan")
    case_name = row.get("case_name", f"switchval_{index:04d}")
    return {
        "scenario_type": "fault",
        "mode": "joint_sweep",
        "source": "switch_validation_fixed_action",
        "fault": case_name,
        "case_name": case_name,
        "topology": row.get("topology", ""),
        "category": row.get("category", "LVRT" if fault_pu < 1.0 else "HVRT"),
        "gbt_category": row.get("category", "LVRT" if fault_pu < 1.0 else "HVRT"),
        "grid_pu": fault_pu,
        "fault_pu": fault_pu,
        "fault_start": fault_start,
        "fault_clear": fault_start + duration_s,
        "fault_duration_s": duration_s,
        "raw_m_reg_d": f(row, "action_m_reg_d", 0.0),
        "raw_m_reg_q": f(row, "action_m_reg_q", 0.0),
        "raw_m_energy_d": f(row, "action_m_energy_d", 0.0),
        "raw_m_energy_q": f(row, "action_m_energy_q", 0.0),
        "cmd_m_reg_d_mean": f(row, "switch_fixed_cmd_m_reg_d_mean", f(row, "action_m_reg_d", 0.0)),
        "cmd_m_reg_q_mean": f(row, "switch_fixed_cmd_m_reg_q_mean", f(row, "action_m_reg_q", 0.0)),
        "cmd_m_energy_d_mean": f(row, "switch_fixed_cmd_m_energy_d_mean", f(row, "action_m_energy_d", 0.0)),
        "cmd_m_energy_q_mean": f(row, "switch_fixed_cmd_m_energy_q_mean", f(row, "action_m_energy_q", 0.0)),
        "meas_reg_d_mean": f(row, "switch_fixed_meas_reg_d_mean", f(row, "switch_fixed_reg_d_mean", 0.0)),
        "meas_reg_q_mean": f(row, "switch_fixed_meas_reg_q_mean", f(row, "switch_fixed_reg_q_mean", 0.0)),
        "meas_energy_d_mean": f(row, "switch_fixed_meas_energy_d_mean", f(row, "switch_fixed_energy_d_mean", 0.0)),
        "meas_energy_q_mean": f(row, "switch_fixed_meas_energy_q_mean", f(row, "switch_fixed_energy_q_mean", 0.0)),
        "reg_d_mean": f(row, "switch_fixed_reg_d_mean", f(row, "switch_fixed_meas_reg_d_mean", 0.0)),
        "reg_q_mean": f(row, "switch_fixed_reg_q_mean", f(row, "switch_fixed_meas_reg_q_mean", 0.0)),
        "energy_d_mean": f(row, "switch_fixed_energy_d_mean", f(row, "switch_fixed_meas_energy_d_mean", 0.0)),
        "energy_q_mean": f(row, "switch_fixed_energy_q_mean", f(row, "switch_fixed_meas_energy_q_mean", 0.0)),
        "lv_pu_mean": pu(f(row, "switch_fixed_lv_mean"), 207.0),
        "lv_recovery_pu_mean": pu(f(row, "switch_fixed_lv_recovery_mean"), 207.0),
        "lv_peak_pu": pu(f(row, "switch_fixed_lv_peak"), 207.0),
        "lv_min_pu": pu(f(row, "switch_fixed_lv_min"), 207.0),
        "lv_unbalance_pu": "",
        "vdc_pu_mean": pu(vdc_mean, 800.0),
        "vdc_min_pu": pu(vdc_min, 800.0),
        "vdc_max_pu": pu(vdc_max, 800.0),
        "vdc_mean": finite_or_blank(vdc_mean),
        "vdc_min": finite_or_blank(vdc_min),
        "vdc_max": finite_or_blank(vdc_max),
        "energy_i_rms_mean": "",
        "action_max_abs": f(row, "switch_fixed_action_max_abs", f(row, "action_m_energy_d", 0.0)),
        "cmd_action_max_abs": f(row, "switch_fixed_cmd_action_max_abs", f(row, "action_m_energy_d", 0.0)),
        "bridge_modulation_abs_max": f(row, "switch_fixed_bridge_modulation_abs_max", f(row, "switch_fixed_action_max_abs", 0.0)),
        "control_score": f(row, "switch_fixed_control_score"),
        "survival_score": f(row, "switch_fixed_control_score"),
        "voltage_survival_pass": b(row, "switch_fixed_voltage_survival_pass"),
        "full_frt_pass": b(row, "switch_fixed_full_frt_pass"),
        "grid_iq_shortfall_max_pu": f(row, "switch_fixed_grid_iq_shortfall_max_pu"),
        "grid_current_peak_pu": f(row, "switch_fixed_grid_current_peak_pu"),
        "gbt_reactive_status": row.get("switch_fixed_gbt_reactive_status", ""),
        "gbt_reactive_pass": "",
        "gbt_grid_current_limit_pass": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--switch-validation-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    source_rows = read_csv(args.switch_validation_csv)
    rows = [convert_row(row, idx) for idx, row in enumerate(source_rows, start=1)]
    run_id = args.run_id or f"switchval_augmented_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_csv = args.out_dir / f"frt_calibration_matrix_{run_id}.csv"
    write_csv(out_csv, rows)
    manifest = {
        "schema": "hpt-switch-validation-augmented-matrix-v1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_csv": str(args.switch_validation_csv),
        "source_hash": sha256_file(args.switch_validation_csv),
        "out_csv": str(out_csv),
        "row_count": len(rows),
    }
    manifest_path = out_csv.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_experiment_metadata(
        out_csv.parent / run_id,
        experiment_name="hpt_switch_validation_augmented_matrix",
        config=manifest,
        dataset_manifest=manifest_path,
        extra=manifest,
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
