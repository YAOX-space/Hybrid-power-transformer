"""Build boundary-centered full-action HPT data for beat-conventional training.

The output is a compact, auditable dataset for the final direct controller:

    observation/context -> [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

Rows come from two switch-level sources:

* the conventional-dq boundary sweep, used as the baseline to beat;
* the calibrated FRT fixed-action matrix, used as candidate action evidence.

This script does not train a controller.  It creates the shared data contract
for BC warm start, TD3+BC/IQL/CQL baselines, and behavior-regularized SAC.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from version_2.sac.experiment_metadata import sha256_file, write_experiment_metadata
from version_2.sac.frt_envelope import DEFAULT_SOLVER_TOL_PU


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"
MATRIX_DIR = RESULTS / "hpt_v2_frt_calibration_matrix"
DEFAULT_OUT_ROOT = ROOT / "version_2" / "data" / "hpt_boundary_full_action"

ACTION_NAMES = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]

KNOWN_STALE_INPUT_STEMS = {
    "frt_calibration_matrix_local_sweep_topology2_lvrt80_095_20260718_0210",
    "frt_calibration_matrix_success_bc_topology2_lvrt80_095_20260718_0210",
    "frt_calibration_matrix_switchval_counterexamples_topology2_lvrt_20260718_0156",
}

FEATURE_NAMES = [
    "topology1",
    "topology2",
    "is_lvrt",
    "is_hvrt",
    "fault_pu",
    "fault_depth",
    "duration_s",
    "fault_start_s",
    "stop_time_s",
    "mode_baseline",
    "mode_conventional",
    "mode_reg_sweep",
    "mode_reg_q_sweep",
    "mode_energy_sweep",
    "mode_joint_sweep",
    "action_m_reg_d",
    "action_m_reg_q",
    "action_m_energy_d",
    "action_m_energy_q",
]

METRIC_NAMES = [
    "lv_fault_rms_mean",
    "lv_recovery_rms_mean",
    "lv_peak_rms",
    "lv_min_rms",
    "vdc_mean",
    "vdc_min",
    "vdc_max",
    "action_max_abs",
    "cmd_action_max_abs",
    "bridge_modulation_abs_max",
    "cmd_m_reg_d_mean",
    "cmd_m_reg_q_mean",
    "cmd_m_energy_d_mean",
    "cmd_m_energy_q_mean",
    "cmd_m_reg_d_fault_mean",
    "cmd_m_reg_q_fault_mean",
    "cmd_m_energy_d_fault_mean",
    "cmd_m_energy_q_fault_mean",
    "cmd_m_reg_d_recovery_mean",
    "cmd_m_reg_q_recovery_mean",
    "cmd_m_energy_d_recovery_mean",
    "cmd_m_energy_q_recovery_mean",
    "meas_reg_d_mean",
    "meas_reg_q_mean",
    "meas_energy_d_mean",
    "meas_energy_q_mean",
    "meas_reg_d_fault_mean",
    "meas_reg_q_fault_mean",
    "meas_energy_d_fault_mean",
    "meas_energy_q_fault_mean",
    "meas_reg_d_recovery_mean",
    "meas_reg_q_recovery_mean",
    "meas_energy_d_recovery_mean",
    "meas_energy_q_recovery_mean",
    "grid_iq_mean_pu",
    "grid_iq_ref_mean_pu",
    "grid_iq_shortfall_max_pu",
    "grid_current_peak_pu",
    "fault_lv_band_violation_max_pu",
    "fault_lv_band_violation_mean_pu",
    "fault_lv_band_violation_duration_s",
    "envelope_violation_max_pu",
    "envelope_violation_mean_pu",
    "envelope_violation_duration_s",
    "envelope_margin_min_pu",
    "recovery_violation_max_pu",
    "recovery_violation_mean_pu",
    "recovery_violation_duration_s",
    "survival_score",
    "voltage_survival_pass",
    "full_frt_pass",
]


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(
        (
            p
            for p in Path(directory).glob(pattern)
            if "_summary" not in p.stem and p.stem not in KNOWN_STALE_INPUT_STEMS
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, Any]]:
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


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    return str(default if value is None else value)


def b(row: dict[str, Any], key: str) -> bool:
    value = row.get(key, "")
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def is_known_stale_path(path: Path) -> bool:
    return Path(path).stem in KNOWN_STALE_INPUT_STEMS


def has_envelope_metrics(row: dict[str, Any]) -> bool:
    return "envelope_violation_max_pu" in row and str(row.get("envelope_violation_max_pu", "")).strip() != ""


def finite(value: float, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def category_from_pu(pu: float) -> str:
    return "LVRT" if float(pu) < 1.0 else "HVRT"


def severity_from_pu(pu: float) -> float:
    pu = float(pu)
    return 1.0 - pu if pu < 1.0 else pu - 1.0


def fault_tag(pu: float) -> str:
    return ("sag_" if pu < 1.0 else "swell_") + f"{pu:.3f}".replace(".", "p").rstrip("0").rstrip("p")


def normalize_duration_ms(value_s: float) -> int:
    return int(round(1000.0 * finite(value_s)))


def baseline_duration(row: dict[str, Any]) -> float:
    return finite(f(row, "fault_duration_s"), 0.0)


def matrix_duration(row: dict[str, Any]) -> float:
    if "fault_duration_s" in row and str(row.get("fault_duration_s", "")).strip():
        return finite(f(row, "fault_duration_s"), 0.0)
    return max(0.0, finite(f(row, "fault_clear"), 0.0) - finite(f(row, "fault_start"), 0.0))


def pass_flag(row: dict[str, Any], column: str) -> bool:
    if column in row:
        return b(row, column)
    if column == "voltage_survival_pass":
        return voltage_survival_pass_from_metrics(row)
    return False


def voltage_survival_pass_from_metrics(row: dict[str, Any]) -> bool:
    lv_mean = metric_value(row, "lv_fault_rms_mean")
    lv_rec = metric_value(row, "lv_recovery_rms_mean")
    lv_peak = metric_value(row, "lv_peak_rms")
    lv_min = metric_value(row, "lv_min_rms")
    vdc_min = metric_value(row, "vdc_min")
    vdc_max = metric_value(row, "vdc_max")
    action_max = metric_value(row, "action_max_abs")
    fault_band_violation = metric_value(row, "fault_lv_band_violation_max_pu")
    envelope_violation = metric_value(row, "envelope_violation_max_pu")
    recovery_violation = metric_value(row, "recovery_violation_max_pu")
    timestep_ok = True
    if math.isfinite(fault_band_violation):
        timestep_ok = timestep_ok and fault_band_violation <= DEFAULT_SOLVER_TOL_PU
    if math.isfinite(envelope_violation):
        timestep_ok = timestep_ok and envelope_violation <= DEFAULT_SOLVER_TOL_PU
    if math.isfinite(recovery_violation):
        timestep_ok = timestep_ok and recovery_violation <= DEFAULT_SOLVER_TOL_PU
    return bool(
        176.0 <= lv_mean <= 238.0
        and 180.0 <= lv_rec <= 235.0
        and lv_min >= 180.0
        and lv_peak <= 235.0
        and vdc_min >= 650.0
        and vdc_max <= 1000.0
        and action_max <= 0.9501
        and timestep_ok
    )


def metric_value(row: dict[str, Any], canonical: str) -> float:
    aliases = {
        "lv_fault_rms_mean": ("lv_fault_rms_mean", "lv_mean"),
        "lv_recovery_rms_mean": ("lv_recovery_rms_mean", "lv_recovery_mean"),
        "lv_peak_rms": ("lv_peak_rms", "lv_peak"),
        "lv_min_rms": ("lv_min_rms", "lv_min"),
        "vdc_mean": ("vdc_mean",),
        "vdc_min": ("vdc_min",),
        "vdc_max": ("vdc_max",),
        "action_max_abs": ("action_max_abs",),
        "cmd_action_max_abs": ("cmd_action_max_abs",),
        "bridge_modulation_abs_max": ("bridge_modulation_abs_max", "action_max_abs"),
        "cmd_m_reg_d_mean": ("cmd_m_reg_d_mean", "raw_m_reg_d"),
        "cmd_m_reg_q_mean": ("cmd_m_reg_q_mean", "raw_m_reg_q"),
        "cmd_m_energy_d_mean": ("cmd_m_energy_d_mean", "raw_m_energy_d"),
        "cmd_m_energy_q_mean": ("cmd_m_energy_q_mean", "raw_m_energy_q"),
        "meas_reg_d_mean": ("meas_reg_d_mean", "reg_d_mean"),
        "meas_reg_q_mean": ("meas_reg_q_mean", "reg_q_mean"),
        "meas_energy_d_mean": ("meas_energy_d_mean", "energy_d_mean"),
        "meas_energy_q_mean": ("meas_energy_q_mean", "energy_q_mean"),
        "grid_iq_mean_pu": ("grid_iq_mean_pu",),
        "grid_iq_ref_mean_pu": ("grid_iq_ref_mean_pu",),
        "grid_iq_shortfall_max_pu": ("grid_iq_shortfall_max_pu",),
        "grid_current_peak_pu": ("grid_current_peak_pu",),
        "fault_lv_band_violation_max_pu": (
            "fault_lv_band_violation_max_pu",
            "fault_band_violation_max_pu",
        ),
        "fault_lv_band_violation_mean_pu": (
            "fault_lv_band_violation_mean_pu",
            "fault_band_violation_mean_pu",
        ),
        "fault_lv_band_violation_duration_s": (
            "fault_lv_band_violation_duration_s",
            "fault_band_violation_duration_s",
        ),
        "envelope_violation_max_pu": ("envelope_violation_max_pu",),
        "envelope_violation_mean_pu": ("envelope_violation_mean_pu",),
        "envelope_violation_duration_s": ("envelope_violation_duration_s",),
        "envelope_margin_min_pu": ("envelope_margin_min_pu", "gbt_voltage_margin_min"),
        "recovery_violation_max_pu": ("recovery_violation_max_pu",),
        "recovery_violation_mean_pu": ("recovery_violation_mean_pu",),
        "recovery_violation_duration_s": ("recovery_violation_duration_s",),
    }
    for key in aliases.get(canonical, (canonical,)):
        value = f(row, key, float("nan"))
        if math.isfinite(value):
            return value
    if canonical.startswith("lv_"):
        pu_key = canonical.replace("_rms", "").replace("fault_", "")
        if pu_key in row:
            return f(row, pu_key, 1.0) * 207.0
    return float("nan")


def survival_score(row: dict[str, Any], *, pass_column: str = "voltage_survival_pass") -> float:
    pass_ok = pass_flag(row, pass_column)
    lv_mean = metric_value(row, "lv_fault_rms_mean")
    lv_rec = metric_value(row, "lv_recovery_rms_mean")
    lv_peak = metric_value(row, "lv_peak_rms")
    lv_min = metric_value(row, "lv_min_rms")
    vdc_min = metric_value(row, "vdc_min")
    vdc_max = metric_value(row, "vdc_max")
    action_max = metric_value(row, "action_max_abs")
    iq_short = finite(metric_value(row, "grid_iq_shortfall_max_pu"), 0.0)
    i_peak = finite(metric_value(row, "grid_current_peak_pu"), 0.0)
    fault_band_violation = finite(metric_value(row, "fault_lv_band_violation_max_pu"), 0.0)
    envelope_violation = finite(metric_value(row, "envelope_violation_max_pu"), 0.0)
    recovery_violation = finite(metric_value(row, "recovery_violation_max_pu"), 0.0)
    fault_band_duration = finite(metric_value(row, "fault_lv_band_violation_duration_s"), 0.0)
    envelope_duration = finite(metric_value(row, "envelope_violation_duration_s"), 0.0)
    recovery_duration = finite(metric_value(row, "recovery_violation_duration_s"), 0.0)
    score = 0.0 if pass_ok else 100.0
    score += abs(finite(lv_mean, 207.0) - 207.0) / 5.0
    score += abs(finite(lv_rec, 207.0) - 207.0) / 5.0
    score += max(0.0, finite(lv_peak, 207.0) - 235.0) / 3.0
    score += max(0.0, 180.0 - finite(lv_min, 207.0)) / 3.0
    score += max(0.0, 650.0 - finite(vdc_min, 800.0)) / 10.0
    score += max(0.0, finite(vdc_max, 800.0) - 1000.0) / 10.0
    score += max(0.0, finite(action_max, 0.0) - 0.9501) * 100.0
    score += 40.0 * max(0.0, iq_short)
    score += 50.0 * max(0.0, i_peak - 1.5)
    score += 180.0 * max(0.0, fault_band_violation) ** 2
    score += 300.0 * max(0.0, envelope_violation) ** 2
    score += 120.0 * max(0.0, recovery_violation) ** 2
    score += 35.0 * max(0.0, fault_band_duration)
    score += 60.0 * max(0.0, envelope_duration)
    score += 30.0 * max(0.0, recovery_duration)
    if b(row, "grid_iq_wrong_sign"):
        score += 8.0
    return float(score)


def action_from_row(row: dict[str, Any], source: str) -> tuple[float, float, float, float]:
    if source == "matrix":
        return (
            finite(f(row, "raw_m_reg_d", f(row, "cmd_m_reg_d_mean", 0.0))),
            finite(f(row, "raw_m_reg_q", f(row, "cmd_m_reg_q_mean", 0.0))),
            finite(f(row, "raw_m_energy_d", f(row, "cmd_m_energy_d_mean", 0.0))),
            finite(f(row, "raw_m_energy_q", f(row, "cmd_m_energy_q_mean", 0.0))),
        )
    return (
        finite(f(row, "cmd_m_reg_d_fault_mean", f(row, "cmd_m_reg_d_mean", f(row, "reg_d_mean", 0.0)))),
        finite(f(row, "cmd_m_reg_q_fault_mean", f(row, "cmd_m_reg_q_mean", f(row, "reg_q_mean", 0.0)))),
        finite(f(row, "cmd_m_energy_d_fault_mean", f(row, "cmd_m_energy_d_mean", f(row, "energy_d_mean", 0.0)))),
        finite(f(row, "cmd_m_energy_q_fault_mean", f(row, "cmd_m_energy_q_mean", f(row, "energy_q_mean", 0.0)))),
    )


def group_key(topology: str, category: str, duration_s: float) -> tuple[str, str, int]:
    return topology, category, normalize_duration_ms(duration_s)


def select_conventional_rows(
    rows: list[dict[str, Any]],
    *,
    pass_column: str,
    selection: str,
) -> list[tuple[dict[str, Any], str]]:
    rows = [
        row
        for row in rows
        if s(row, "scenario_type") == "fault" and s(row, "mode") == "conventional_dq"
    ]
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pu = f(row, "fault_pu")
        key = group_key(s(row, "topology"), category_from_pu(pu), baseline_duration(row))
        groups[key].append(row)

    selected: list[tuple[dict[str, Any], str]] = []
    for _key, group in sorted(groups.items()):
        group = sorted(group, key=lambda r: severity_from_pu(f(r, "fault_pu")))
        if selection == "all":
            selected.extend((row, "conventional_all") for row in group)
            continue

        last_pass: dict[str, Any] | None = None
        first_fail: dict[str, Any] | None = None
        for row in group:
            if pass_flag(row, pass_column):
                last_pass = row
            elif last_pass is not None and first_fail is None:
                first_fail = row
                break
        if last_pass is not None:
            selected.append((last_pass, "conventional_last_pass"))
        if first_fail is not None:
            selected.append((first_fail, "conventional_first_fail"))
        if last_pass is None and first_fail is None and group:
            selected.append((group[0], "conventional_all_fail_start"))
    return selected


def canonical_row(
    row: dict[str, Any],
    *,
    row_source: str,
    role: str,
    pass_column: str,
    require_envelope_metrics: bool = True,
) -> dict[str, Any]:
    source = "matrix" if row_source == "switch_matrix" else "conventional"
    pu = f(row, "fault_pu", f(row, "grid_pu", 1.0))
    category = s(row, "category", category_from_pu(pu))
    if not category:
        category = category_from_pu(pu)
    duration_s = matrix_duration(row) if source == "matrix" else baseline_duration(row)
    start_s = f(row, "fault_start", f(row, "fault_start_s", 0.035))
    stop_s = f(row, "stop_time", f(row, "stop_time_s", start_s + duration_s + 0.125))
    mode = s(row, "mode", "")
    action = action_from_row(row, source)
    if mode == "reg_sweep" and abs(action[1]) > 1e-9:
        mode = "reg_q_sweep"
    survival_pass = pass_flag(row, pass_column)
    missing_envelope = source in {"matrix", "conventional"} and not has_envelope_metrics(row)
    if missing_envelope and require_envelope_metrics:
        survival_pass = False
    full_pass = b(row, "full_frt_pass") or b(row, "gbt_certifiable")
    if missing_envelope and require_envelope_metrics:
        full_pass = False
    score = survival_score(row, pass_column=pass_column)
    if missing_envelope and require_envelope_metrics:
        score += 500.0
    out: dict[str, Any] = {
        "schema": "hpt-boundary-full-action-row-v2",
        "row_source": row_source,
        "role": role,
        "topology": s(row, "topology"),
        "scenario_type": "fault",
        "category": category,
        "condition_class": s(row, "condition_class", category.lower()),
        "case_name": s(row, "case_name", fault_tag(pu)),
        "fault_pu": pu,
        "fault_depth": severity_from_pu(pu),
        "fault_duration_s": duration_s,
        "duration_ms": normalize_duration_ms(duration_s),
        "fault_start_s": start_s,
        "stop_time_s": stop_s,
        "mode": mode,
        "target_action_source": source,
        "action_m_reg_d": action[0],
        "action_m_reg_q": action[1],
        "action_m_energy_d": action[2],
        "action_m_energy_q": action[3],
        "lv_fault_rms_mean": metric_value(row, "lv_fault_rms_mean"),
        "lv_recovery_rms_mean": metric_value(row, "lv_recovery_rms_mean"),
        "lv_peak_rms": metric_value(row, "lv_peak_rms"),
        "lv_min_rms": metric_value(row, "lv_min_rms"),
        "vdc_mean": metric_value(row, "vdc_mean"),
        "vdc_min": metric_value(row, "vdc_min"),
        "vdc_max": metric_value(row, "vdc_max"),
        "action_max_abs": metric_value(row, "action_max_abs"),
        "cmd_action_max_abs": metric_value(row, "cmd_action_max_abs"),
        "bridge_modulation_abs_max": metric_value(row, "bridge_modulation_abs_max"),
        "cmd_m_reg_d_mean": metric_value(row, "cmd_m_reg_d_mean"),
        "cmd_m_reg_q_mean": metric_value(row, "cmd_m_reg_q_mean"),
        "cmd_m_energy_d_mean": metric_value(row, "cmd_m_energy_d_mean"),
        "cmd_m_energy_q_mean": metric_value(row, "cmd_m_energy_q_mean"),
        "meas_reg_d_mean": metric_value(row, "meas_reg_d_mean"),
        "meas_reg_q_mean": metric_value(row, "meas_reg_q_mean"),
        "meas_energy_d_mean": metric_value(row, "meas_energy_d_mean"),
        "meas_energy_q_mean": metric_value(row, "meas_energy_q_mean"),
        "grid_iq_mean_pu": metric_value(row, "grid_iq_mean_pu"),
        "grid_iq_ref_mean_pu": metric_value(row, "grid_iq_ref_mean_pu"),
        "grid_iq_shortfall_max_pu": metric_value(row, "grid_iq_shortfall_max_pu"),
        "grid_current_peak_pu": metric_value(row, "grid_current_peak_pu"),
        "grid_iq_wrong_sign": bool(b(row, "grid_iq_wrong_sign")),
        "envelope_violation_max_pu": metric_value(row, "envelope_violation_max_pu"),
        "envelope_violation_mean_pu": metric_value(row, "envelope_violation_mean_pu"),
        "envelope_violation_duration_s": metric_value(row, "envelope_violation_duration_s"),
        "envelope_margin_min_pu": metric_value(row, "envelope_margin_min_pu"),
        "recovery_violation_max_pu": metric_value(row, "recovery_violation_max_pu"),
        "recovery_violation_mean_pu": metric_value(row, "recovery_violation_mean_pu"),
        "recovery_violation_duration_s": metric_value(row, "recovery_violation_duration_s"),
        "missing_envelope_metrics": bool(missing_envelope),
        "voltage_survival_pass": bool(survival_pass),
        "full_frt_pass": bool(full_pass),
        "survival_score": score,
        "control_score": f(row, "control_score", score),
        "reason": (
            s(row, "voltage_survival_reason", s(row, "full_frt_reason", ""))
            + (";missing_timestep_envelope_metrics" if missing_envelope and require_envelope_metrics else "")
        ).strip(";"),
    }
    return out


def include_matrix_row(row: dict[str, Any], candidate_selection: str, selected_conv: list[dict[str, Any]]) -> bool:
    if candidate_selection == "none":
        return False
    if s(row, "scenario_type") != "fault":
        return False
    if candidate_selection == "all":
        return True
    selected_keys = {
        (s(r, "topology"), category_from_pu(f(r, "fault_pu")))
        for r in selected_conv
    }
    key = (s(row, "topology"), s(row, "category", category_from_pu(f(row, "fault_pu"))))
    if key not in selected_keys:
        return False
    if candidate_selection == "same_category":
        return True
    selected_depths = [f(r, "fault_pu") for r in selected_conv if s(r, "topology") == key[0] and category_from_pu(f(r, "fault_pu")) == key[1]]
    if not selected_depths:
        return False
    pu = f(row, "fault_pu", f(row, "grid_pu", 1.0))
    return min(abs(pu - d) for d in selected_depths) <= 0.16


def build_arrays(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X: list[list[float]] = []
    A: list[list[float]] = []
    Y: list[list[float]] = []
    for row in rows:
        topology = s(row, "topology")
        category = s(row, "category")
        mode = s(row, "mode")
        action = [float(row[f"action_{name}"]) for name in ACTION_NAMES]
        features = [
            1.0 if topology == "topology1" else 0.0,
            1.0 if topology == "topology2" else 0.0,
            1.0 if category == "LVRT" else 0.0,
            1.0 if category == "HVRT" else 0.0,
            float(row["fault_pu"]),
            float(row["fault_depth"]),
            float(row["fault_duration_s"]),
            float(row["fault_start_s"]),
            float(row["stop_time_s"]),
            1.0 if mode == "baseline" else 0.0,
            1.0 if mode == "conventional_dq" else 0.0,
            1.0 if mode == "reg_sweep" else 0.0,
            1.0 if mode == "reg_q_sweep" else 0.0,
            1.0 if mode == "energy_sweep" else 0.0,
            1.0 if mode == "joint_sweep" else 0.0,
            *action,
        ]
        metrics = [
            finite(float(row[name]), 0.0) if name not in {"voltage_survival_pass", "full_frt_pass"} else float(bool(row[name]))
            for name in METRIC_NAMES
        ]
        X.append(features)
        A.append(action)
        Y.append(metrics)
    return (
        np.asarray(X, dtype=np.float32),
        np.asarray(A, dtype=np.float32),
        np.asarray(Y, dtype=np.float32),
    )


def split_indices(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    if n < 3:
        return {"train": idx, "val": np.asarray([], dtype=int), "test": np.asarray([], dtype=int)}
    n_train = max(1, int(round(0.70 * n)))
    n_val = max(1, int(round(0.15 * n)))
    if n_train + n_val >= n:
        n_train = n - 2
        n_val = 1
    return {
        "train": np.sort(idx[:n_train]),
        "val": np.sort(idx[n_train : n_train + n_val]),
        "test": np.sort(idx[n_train + n_val :]),
    }


def write_report(path: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    role_counts = Counter(s(row, "role") for row in rows)
    source_counts = Counter(s(row, "row_source") for row in rows)
    group_counts = Counter(
        (s(row, "topology"), s(row, "category"), int(row["duration_ms"]))
        for row in rows
    )
    lines = [
        "# HPT Boundary Full-Action Dataset",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Rows: `{manifest['row_count']}`",
        f"- Conventional CSV: `{manifest['conventional_boundary_csv']}`",
        f"- Matrix CSV: `{manifest['matrix_csv']}`",
        f"- Dataset CSV: `{manifest['dataset_csv']}`",
        f"- Dataset NPZ: `{manifest['dataset_npz']}`",
        "",
        "## Source Counts",
        "",
    ]
    for key, value in sorted(source_counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Role Counts", ""])
    for key, value in sorted(role_counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Groups",
            "",
            "| Topology | Category | Duration | Rows |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for (topology, category, duration_ms), count in sorted(group_counts.items()):
        lines.append(f"| {topology} | {category} | {duration_ms} ms | {count} |")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conventional-csv", type=Path, default=None)
    parser.add_argument(
        "--matrix-csv",
        type=Path,
        nargs="+",
        default=None,
        help="One or more switch-level FRT calibration matrices to use as candidate action evidence.",
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--pass-column", default="voltage_survival_pass")
    parser.add_argument("--selection", choices=["near_boundary", "all"], default="near_boundary")
    parser.add_argument(
        "--candidate-selection",
        choices=["none", "all", "same_category", "near_boundary_depths"],
        default="all",
    )
    parser.add_argument(
        "--allow-legacy-no-envelope",
        action="store_true",
        help="Allow pre-envelope CSV inputs.  Default is to reject them for new training data.",
    )
    parser.add_argument(
        "--allow-stale-input",
        action="store_true",
        help="Allow known stale/corrupt matrix stems.  Use only for forensic diagnostics.",
    )
    args = parser.parse_args()

    conventional_csv = args.conventional_csv or latest_csv(
        CONTROL_DIR, "control_comparison_*conventional_boundary*.csv"
    )
    matrix_csvs = args.matrix_csv or [latest_csv(MATRIX_DIR, "frt_calibration_matrix_*_all_*.csv")]
    if not args.allow_stale_input:
        stale = [str(path) for path in [conventional_csv, *matrix_csvs] if is_known_stale_path(path)]
        if stale:
            raise RuntimeError(
                "Refusing known stale/corrupt inputs.  Re-run the switch-level matrix or pass "
                f"--allow-stale-input only for diagnostics: {stale}"
            )
    run_id = args.run_id or f"hpt_boundary_full_action_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    conventional_rows = read_csv(conventional_csv)
    selected_pairs = select_conventional_rows(
        conventional_rows,
        pass_column=args.pass_column,
        selection=args.selection,
    )
    selected_conv_rows = [row for row, _role in selected_pairs]
    rows: list[dict[str, Any]] = [
        canonical_row(
            row,
            row_source="conventional_boundary",
            role=role,
            pass_column=args.pass_column,
            require_envelope_metrics=not args.allow_legacy_no_envelope,
        )
        for row, role in selected_pairs
    ]

    matrix_rows: list[dict[str, Any]] = []
    for matrix_csv in matrix_csvs:
        matrix_rows.extend(read_csv(matrix_csv))
    for row in matrix_rows:
        if not include_matrix_row(row, args.candidate_selection, selected_conv_rows):
            continue
        rows.append(
            canonical_row(
                row,
                row_source="switch_matrix",
                role=f"candidate_{s(row, 'mode', 'unknown')}",
                pass_column=args.pass_column,
                require_envelope_metrics=not args.allow_legacy_no_envelope,
            )
        )

    if not rows:
        raise RuntimeError("No dataset rows selected")
    if not args.allow_legacy_no_envelope:
        legacy_rows = [row for row in rows if b(row, "missing_envelope_metrics")]
        if legacy_rows:
            raise RuntimeError(
                "Selected inputs do not include timestep envelope metrics.  Re-run "
                "eval_hpt_v2_control_comparison.m and collect_hpt_v2_frt_calibration_matrix.m "
                "after this patch, or pass --allow-legacy-no-envelope for diagnostics only."
            )

    X, A, Y = build_arrays(rows)
    splits = split_indices(len(rows), args.seed)
    dataset_csv = out_dir / "dataset.csv"
    dataset_npz = out_dir / "dataset.npz"
    write_csv(dataset_csv, rows)
    np.savez_compressed(
        dataset_npz,
        X=X,
        A=A,
        Y=Y,
        train_idx=splits["train"],
        val_idx=splits["val"],
        test_idx=splits["test"],
        feature_names=np.asarray(FEATURE_NAMES, dtype=object),
        action_names=np.asarray(ACTION_NAMES, dtype=object),
        metric_names=np.asarray(METRIC_NAMES, dtype=object),
    )
    manifest = {
        "schema": "hpt-boundary-full-action-dataset-v2",
        "run_id": run_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "conventional_boundary_csv": str(conventional_csv),
        "matrix_csv": [str(path) for path in matrix_csvs],
        "conventional_boundary_hash": sha256_file(conventional_csv),
        "matrix_hash": [sha256_file(path) for path in matrix_csvs],
        "dataset_csv": str(dataset_csv),
        "dataset_npz": str(dataset_npz),
        "report": str(out_dir / "REPORT.md"),
        "row_count": len(rows),
        "feature_names": FEATURE_NAMES,
        "action_names": ACTION_NAMES,
        "metric_names": METRIC_NAMES,
        "split_counts": {name: int(len(idx)) for name, idx in splits.items()},
        "selection": args.selection,
        "candidate_selection": args.candidate_selection,
        "pass_column": args.pass_column,
        "requires_timestep_envelope_metrics": not args.allow_legacy_no_envelope,
        "known_stale_input_stems": sorted(KNOWN_STALE_INPUT_STEMS),
        "role_counts": dict(Counter(s(row, "role") for row in rows)),
        "source_counts": dict(Counter(s(row, "row_source") for row in rows)),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_report(out_dir / "REPORT.md", rows, manifest)
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_boundary_full_action_dataset",
        config={
            "selection": args.selection,
            "candidate_selection": args.candidate_selection,
            "pass_column": args.pass_column,
            "seed": args.seed,
            "matrix_csv": [str(path) for path in matrix_csvs],
        },
        dataset_manifest=out_dir / "manifest.json",
        extra=manifest,
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


