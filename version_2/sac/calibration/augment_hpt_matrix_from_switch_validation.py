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

from version_2.sac.experiment_metadata import sha256_file, write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
_SWITCH_CSV_CACHE: dict[str, dict[str, str]] = {}


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


def fixed_switch_row(row: dict[str, str]) -> dict[str, str]:
    """Return the original Simulink fixed-action row when available.

    Older switch-validation CSVs did not copy every grid-current metric into the
    comparison row.  They do store ``switch_csv``, so augmentation can recover
    the missing source-of-truth fields without rerunning Simulink.
    """

    csv_path = row.get("switch_csv", "")
    if not csv_path:
        return {}
    if csv_path in _SWITCH_CSV_CACHE:
        return _SWITCH_CSV_CACHE[csv_path]
    path = Path(csv_path)
    if not path.exists():
        _SWITCH_CSV_CACHE[csv_path] = {}
        return {}
    for sim_row in read_csv(path):
        if sim_row.get("mode", "") == "fixed_action":
            _SWITCH_CSV_CACHE[csv_path] = sim_row
            return sim_row
    _SWITCH_CSV_CACHE[csv_path] = {}
    return {}


def switch_value(row: dict[str, str], key: str, default: str = "") -> str:
    direct = row.get(f"switch_fixed_{key}", "")
    if direct not in ("", None):
        return str(direct)
    return str(fixed_switch_row(row).get(key, default))


def sf(row: dict[str, str], key: str, default: float = float("nan")) -> float:
    try:
        value = switch_value(row, key, "")
        if value in ("", None):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def sb(row: dict[str, str], key: str) -> bool | str:
    value = switch_value(row, key, "")
    if value in ("", None):
        return ""
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def convert_row(row: dict[str, str], index: int) -> dict[str, Any]:
    fault_pu = f(row, "fault_pu", 1.0)
    duration_s = f(row, "duration_ms", 0.0) / 1000.0
    # Recover the actual switch-level fault timing whenever the validator's
    # source CSV is available.  Deep-family campaigns use 80 ms rather than
    # the historical 35 ms default, and mixing those timings corrupts the
    # family proxy's phase/state alignment.
    fault_start = sf(row, "fault_start_s", f(row, "fault_start_s", 0.08))
    vdc_min = sf(row, "vdc_min")
    vdc_max = sf(row, "vdc_max")
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
        "fault_a_pu": sf(row, "fault_a_pu", fault_pu),
        "fault_b_pu": sf(row, "fault_b_pu", fault_pu),
        "fault_c_pu": sf(row, "fault_c_pu", fault_pu),
        "fault_phase_key": row.get("phase_key", ""),
        "fault_start": fault_start,
        "fault_clear": fault_start + duration_s,
        "fault_duration_s": duration_s,
        "raw_m_reg_d": f(row, "action_m_reg_d", 0.0),
        "raw_m_reg_q": f(row, "action_m_reg_q", 0.0),
        "raw_m_energy_d": f(row, "action_m_energy_d", 0.0),
        "raw_m_energy_q": f(row, "action_m_energy_q", 0.0),
        "cmd_m_reg_d_mean": sf(row, "cmd_m_reg_d_mean", f(row, "action_m_reg_d", 0.0)),
        "cmd_m_reg_q_mean": sf(row, "cmd_m_reg_q_mean", f(row, "action_m_reg_q", 0.0)),
        "cmd_m_energy_d_mean": sf(row, "cmd_m_energy_d_mean", f(row, "action_m_energy_d", 0.0)),
        "cmd_m_energy_q_mean": sf(row, "cmd_m_energy_q_mean", f(row, "action_m_energy_q", 0.0)),
        "meas_reg_d_mean": sf(row, "meas_reg_d_mean", sf(row, "reg_d_mean", 0.0)),
        "meas_reg_q_mean": sf(row, "meas_reg_q_mean", sf(row, "reg_q_mean", 0.0)),
        "meas_energy_d_mean": sf(row, "meas_energy_d_mean", sf(row, "energy_d_mean", 0.0)),
        "meas_energy_q_mean": sf(row, "meas_energy_q_mean", sf(row, "energy_q_mean", 0.0)),
        "reg_d_mean": sf(row, "reg_d_mean", sf(row, "meas_reg_d_mean", 0.0)),
        "reg_q_mean": sf(row, "reg_q_mean", sf(row, "meas_reg_q_mean", 0.0)),
        "energy_d_mean": sf(row, "energy_d_mean", sf(row, "meas_energy_d_mean", 0.0)),
        "energy_q_mean": sf(row, "energy_q_mean", sf(row, "meas_energy_q_mean", 0.0)),
        "lv_pu_mean": pu(sf(row, "lv_mean"), 207.0),
        "lv_recovery_pu_mean": pu(sf(row, "lv_recovery_mean"), 207.0),
        "lv_peak_pu": pu(sf(row, "lv_peak"), 207.0),
        "lv_min_pu": pu(sf(row, "lv_min"), 207.0),
        "lv_unbalance_pu": pu(sf(row, "lv_unbalance"), 207.0),
        "vdc_pu_mean": pu(vdc_mean, 800.0),
        "vdc_min_pu": pu(vdc_min, 800.0),
        "vdc_max_pu": pu(vdc_max, 800.0),
        "vdc_mean": finite_or_blank(vdc_mean),
        "vdc_min": finite_or_blank(vdc_min),
        "vdc_max": finite_or_blank(vdc_max),
        "energy_i_rms_mean": sf(row, "energy_i_rms_mean"),
        "action_max_abs": sf(
            row,
            "action_max_abs",
            max(
                abs(f(row, "action_m_reg_d", 0.0)),
                abs(f(row, "action_m_reg_q", 0.0)),
                abs(f(row, "action_m_energy_d", 0.0)),
                abs(f(row, "action_m_energy_q", 0.0)),
            ),
        ),
        "cmd_action_max_abs": sf(
            row,
            "cmd_action_max_abs",
            max(
                abs(f(row, "action_m_reg_d", 0.0)),
                abs(f(row, "action_m_reg_q", 0.0)),
                abs(f(row, "action_m_energy_d", 0.0)),
                abs(f(row, "action_m_energy_q", 0.0)),
            ),
        ),
        "bridge_modulation_abs_max": sf(row, "bridge_modulation_abs_max", sf(row, "action_max_abs", 0.0)),
        "control_score": sf(row, "control_score"),
        "survival_score": sf(row, "control_score"),
        "voltage_survival_pass": b(row, "switch_fixed_voltage_survival_pass"),
        "full_frt_pass": b(row, "switch_fixed_full_frt_pass"),
        "full_frt_reason": switch_value(row, "full_frt_reason", ""),
        "grid_vpos_pu_min": sf(row, "grid_vpos_pu_min"),
        "grid_vpos_pu_mean": sf(row, "grid_vpos_pu_mean"),
        "grid_id_mean_pu": sf(row, "grid_id_mean_pu"),
        "grid_iq_mean_pu": sf(row, "grid_iq_mean_pu"),
        "grid_iq_ref_mean_pu": sf(row, "grid_iq_ref_mean_pu"),
        "grid_iq_shortfall_max_pu": sf(row, "grid_iq_shortfall_max_pu"),
        "grid_iq_met_fraction": sf(row, "grid_iq_met_fraction"),
        "grid_iq_wrong_sign": sb(row, "grid_iq_wrong_sign"),
        "grid_current_peak_pu": sf(row, "grid_current_peak_pu"),
        "grid_idq_peak_pu": sf(row, "grid_idq_peak_pu"),
        "gbt_reactive_status": switch_value(row, "gbt_reactive_status", ""),
        "gbt_reactive_pass": sb(row, "gbt_reactive_pass"),
        "gbt_grid_current_limit_pass": sb(row, "gbt_grid_current_limit_pass"),
        "envelope_violation_max_pu": sf(row, "envelope_violation_max_pu"),
        "envelope_violation_mean_pu": sf(row, "envelope_violation_mean_pu"),
        "envelope_violation_duration_s": sf(row, "envelope_violation_duration_s"),
        "envelope_margin_min_pu": sf(row, "envelope_margin_min_pu"),
        "envelope_pass": sb(row, "envelope_pass"),
        "fault_lv_band_violation_max_pu": sf(row, "fault_lv_band_violation_max_pu"),
        "fault_lv_band_violation_mean_pu": sf(row, "fault_lv_band_violation_mean_pu"),
        "fault_lv_band_violation_duration_s": sf(row, "fault_lv_band_violation_duration_s"),
        "fault_lv_band_pass": sb(row, "fault_lv_band_pass"),
        "fault_lv_min_pu": sf(row, "fault_lv_min_pu", sf(row, "fault_lv_min") / 207.0),
        "fault_lv_max_pu": sf(row, "fault_lv_max_pu", sf(row, "fault_lv_max") / 207.0),
        "recovery_violation_max_pu": sf(row, "recovery_violation_max_pu"),
        "recovery_violation_mean_pu": sf(row, "recovery_violation_mean_pu"),
        "recovery_violation_duration_s": sf(row, "recovery_violation_duration_s"),
        "recovery_envelope_pass": sb(row, "recovery_envelope_pass"),
        "timestep_envelope_pass": sb(row, "timestep_envelope_pass"),
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


