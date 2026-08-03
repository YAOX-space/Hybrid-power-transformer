"""Search HPT FRT action trajectories with proxy-guided CEM.

This is a trajectory-level bridge between hand-designed fixed actions and
direct SAC control.  It samples piecewise-linear trajectories for the final
4-D action contract

    [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

scores them in the calibrated proxy, then validates the best candidates in the
switch-level Simulink model through ``eval_hpt_v2_control_comparison``.

The goal is not to certify the proxy.  The proxy is only a cheap proposal
mechanism; switch-level validation remains the source of truth.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .build_hpt_action_trajectory import write_csv, write_mat
from .experiment_metadata import write_experiment_metadata
from .hpt_voltage_sac_env import HPTVoltageEnvConfig, HPTVoltageSACEnv, HPTVoltageScenario
from .validate_hpt_trajectory_switchlevel import (
    latest_control_csv,
    make_case_name,
    matlab_fault_cell,
    matlab_string,
    read_csv,
    safe_token,
    summarize_modes,
)


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
SIMULINK_DIR = ROOT / "version_2" / "simulink"
DEFAULT_CALIBRATION = ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json"


def phase_key_from_vector(values: list[float] | None) -> str:
    """Return the calibration phase key for an A/B/C fault vector."""

    if not values:
        return "abc"
    phases = [abs(float(v) - 1.0) > 1e-6 for v in values]
    if phases == [True, False, False]:
        return "a"
    if phases == [False, True, False]:
        return "b"
    if phases == [False, False, True]:
        return "c"
    if phases == [True, True, False]:
        return "ab"
    if phases == [False, True, True]:
        return "bc"
    if phases == [True, False, True]:
        return "ca"
    return "abc" if len(set(round(float(v), 6) for v in values)) == 1 else "custom"


def neg_seq_from_phase_vector(values: list[float] | None) -> float:
    """Approximate negative-sequence magnitude from per-phase RMS multipliers."""

    if not values:
        return 0.0
    va = complex(float(values[0]), 0.0)
    vb = float(values[1]) * complex(-0.5, -np.sqrt(3.0) / 2.0)
    vc = float(values[2]) * complex(-0.5, np.sqrt(3.0) / 2.0)
    alpha = complex(-0.5, np.sqrt(3.0) / 2.0)
    vpos = (va + alpha * vb + alpha**2 * vc) / 3.0
    vneg = (va + alpha**2 * vb + alpha * vc) / 3.0
    return float(abs(vneg) / max(abs(vpos), 1e-9))


PARAM_NAMES = [
    "reg_pre",
    "reg_boost",
    "reg_recovery",
    "reg_q_boost",
    "reg_q_recovery",
    "energy_d_boost",
    "energy_d_recovery",
    "energy_q_boost",
    "energy_q_recovery",
    "ramp_in_ms",
    "recovery_taper_ms",
    "final_taper_ms",
]


@dataclass(frozen=True)
class Candidate:
    """One normalized CEM sample and its mapped trajectory parameters."""

    index: int
    iteration: int
    latent: np.ndarray
    params: dict[str, float]


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def finite(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def param_bounds(fault_pu: float, *, allow_prebias: bool) -> dict[str, tuple[float, float]]:
    """Return conservative search bounds for one FRT category."""

    if fault_pu < 1.0:
        reg_pre = (0.0, 0.30) if allow_prebias else (0.0, 0.0)
        return {
            "reg_pre": reg_pre,
            "reg_boost": (0.10, 0.80),
            "reg_recovery": (-0.10, 0.55),
            "reg_q_boost": (-0.30, 0.30),
            "reg_q_recovery": (-0.25, 0.25),
            "energy_d_boost": (-0.45, 0.45),
            "energy_d_recovery": (-0.45, 0.45),
            "energy_q_boost": (-0.45, 0.45),
            "energy_q_recovery": (-0.45, 0.45),
            "ramp_in_ms": (2.0, 22.0),
            "recovery_taper_ms": (5.0, 90.0),
            "final_taper_ms": (20.0, 120.0),
        }
    # HVRT polarity is topology- and winding-orientation dependent in the
    # switch-level HPT models.  Earlier searches constrained ``reg_boost`` to
    # the negative half-plane, which excluded the known topology1 balanced-HVRT
    # operating region near positive d-axis injection.  Keep the negative
    # region, but allow positive candidates and let switch-level validation
    # decide.
    reg_pre = (-0.30, 0.30) if allow_prebias else (0.0, 0.0)
    return {
        "reg_pre": reg_pre,
        "reg_boost": (-0.80, 0.55),
        "reg_recovery": (-0.55, 0.55),
        "reg_q_boost": (-0.30, 0.30),
        "reg_q_recovery": (-0.25, 0.25),
        "energy_d_boost": (-0.45, 0.45),
        "energy_d_recovery": (-0.45, 0.45),
        "energy_q_boost": (-0.45, 0.45),
        "energy_q_recovery": (-0.45, 0.45),
        "ramp_in_ms": (2.0, 22.0),
        "recovery_taper_ms": (5.0, 90.0),
        "final_taper_ms": (20.0, 120.0),
    }


def latent_to_params(latent: np.ndarray, bounds: dict[str, tuple[float, float]]) -> dict[str, float]:
    vals: dict[str, float] = {}
    for i, name in enumerate(PARAM_NAMES):
        low, high = bounds[name]
        vals[name] = float(low + np.clip(latent[i], 0.0, 1.0) * (high - low))
    return vals


def params_to_latent(params: dict[str, float], bounds: dict[str, tuple[float, float]]) -> np.ndarray:
    values = []
    for name in PARAM_NAMES:
        low, high = bounds[name]
        if abs(high - low) < 1e-12:
            values.append(0.0)
        else:
            values.append(float(np.clip((float(params[name]) - low) / (high - low), 0.0, 1.0)))
    return np.asarray(values, dtype=float)


def anchor_params(fault_pu: float, *, topology: str, allow_prebias: bool) -> list[dict[str, float]]:
    """Return deterministic trajectory proposals near known physical regions."""

    common = {
        "reg_pre": 0.0,
        "reg_q_boost": 0.0,
        "reg_q_recovery": 0.0,
        "energy_d_boost": 0.0,
        "energy_d_recovery": 0.0,
        "energy_q_boost": 0.0,
        "energy_q_recovery": 0.0,
        "ramp_in_ms": 2.0,
        "recovery_taper_ms": 35.0,
        "final_taper_ms": 120.0,
    }
    topology = str(topology).lower()
    if fault_pu < 1.0 and topology == "topology2":
        anchors = [
            {
                **common,
                "reg_pre": 0.18 if allow_prebias else 0.0,
                "reg_boost": 0.18,
                "reg_recovery": 0.14,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 0.5,
                "recovery_taper_ms": 45.0,
            },
            {
                **common,
                "reg_pre": 0.20 if allow_prebias else 0.0,
                "reg_boost": 0.20,
                "reg_recovery": 0.16,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 0.5,
                "recovery_taper_ms": 50.0,
            },
            {
                **common,
                "reg_pre": 0.22 if allow_prebias else 0.0,
                "reg_boost": 0.22,
                "reg_recovery": 0.16,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.018,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 1.0,
                "recovery_taper_ms": 55.0,
            },
            {
                **common,
                "reg_pre": 0.20 if allow_prebias else 0.0,
                "reg_boost": 0.20,
                "reg_recovery": 0.10,
                "energy_d_boost": -0.06,
                "energy_d_recovery": 0.018,
                "energy_q_boost": 0.04,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 1.0,
                "recovery_taper_ms": 45.0,
            },
            {
                **common,
                "reg_pre": 0.0,
                "reg_boost": 0.285,
                "reg_recovery": 0.10,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 45.0,
            },
            {
                **common,
                "reg_pre": 0.0,
                "reg_boost": 0.285,
                "reg_recovery": 0.14,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 60.0,
            },
            {
                **common,
                "reg_pre": 0.0,
                "reg_boost": 0.295,
                "reg_recovery": 0.10,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 45.0,
            },
            {
                **common,
                "reg_pre": 0.0,
                "reg_boost": 0.295,
                "reg_recovery": 0.14,
                "energy_d_boost": 0.022,
                "energy_d_recovery": 0.022,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.002,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 60.0,
            },
            {**common, "reg_pre": 0.14 if allow_prebias else 0.0, "reg_boost": 0.14, "reg_recovery": -0.04, "ramp_in_ms": 2.0, "recovery_taper_ms": 20.0},
            {**common, "reg_pre": 0.16 if allow_prebias else 0.0, "reg_boost": 0.16, "reg_recovery": -0.02, "ramp_in_ms": 2.0, "recovery_taper_ms": 25.0},
            {
                **common,
                "reg_pre": 0.172 if allow_prebias else 0.0,
                "reg_boost": 0.172,
                "reg_recovery": 0.00,
                "energy_d_boost": 0.014,
                "energy_d_recovery": 0.00,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.0,
                "ramp_in_ms": 2.0,
                "recovery_taper_ms": 20.0,
            },
            {**common, "reg_pre": 0.20 if allow_prebias else 0.0, "reg_boost": 0.20, "reg_recovery": -0.02, "ramp_in_ms": 2.0, "recovery_taper_ms": 20.0},
            {**common, "reg_pre": 0.24 if allow_prebias else 0.0, "reg_boost": 0.24, "reg_recovery": 0.00, "ramp_in_ms": 2.0, "recovery_taper_ms": 25.0},
            {**common, "reg_boost": 0.14, "reg_recovery": -0.04, "ramp_in_ms": 3.0, "recovery_taper_ms": 20.0},
            {**common, "reg_boost": 0.16, "reg_recovery": -0.02, "ramp_in_ms": 3.0, "recovery_taper_ms": 25.0},
            {
                **common,
                "reg_boost": 0.172,
                "reg_recovery": 0.00,
                "energy_d_boost": 0.014,
                "energy_d_recovery": 0.00,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.0,
                "ramp_in_ms": 3.0,
                "recovery_taper_ms": 20.0,
            },
            {
                **common,
                "reg_boost": 0.19,
                "reg_recovery": -0.04,
                "energy_d_boost": 0.014,
                "energy_d_recovery": -0.02,
                "energy_q_boost": 0.002,
                "energy_q_recovery": 0.0,
                "ramp_in_ms": 3.0,
                "recovery_taper_ms": 20.0,
            },
            {**common, "reg_boost": 0.20, "reg_recovery": 0.00, "ramp_in_ms": 4.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.24, "reg_recovery": 0.00, "ramp_in_ms": 4.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.28, "reg_recovery": 0.04, "ramp_in_ms": 4.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.32, "reg_recovery": 0.06, "ramp_in_ms": 5.0, "recovery_taper_ms": 35.0},
            {
                **common,
                "reg_boost": 0.32,
                "reg_recovery": 0.06,
                "energy_d_boost": -0.05,
                "energy_d_recovery": -0.05,
                "ramp_in_ms": 5.0,
                "recovery_taper_ms": 35.0,
            },
            {
                **common,
                "reg_boost": 0.32,
                "reg_recovery": 0.06,
                "energy_d_boost": -0.10,
                "energy_d_recovery": -0.08,
                "ramp_in_ms": 5.0,
                "recovery_taper_ms": 35.0,
            },
            {**common, "reg_boost": 0.36, "reg_recovery": 0.08, "ramp_in_ms": 6.0, "recovery_taper_ms": 40.0},
            {
                **common,
                "reg_boost": 0.36,
                "reg_recovery": 0.08,
                "energy_d_boost": -0.05,
                "energy_d_recovery": -0.05,
                "ramp_in_ms": 6.0,
                "recovery_taper_ms": 40.0,
            },
            {**common, "reg_boost": 0.40, "reg_recovery": 0.10, "ramp_in_ms": 7.0, "recovery_taper_ms": 45.0},
            {
                **common,
                "reg_boost": 0.40,
                "reg_recovery": 0.10,
                "energy_d_boost": -0.05,
                "energy_d_recovery": -0.05,
                "ramp_in_ms": 7.0,
                "recovery_taper_ms": 45.0,
            },
            {**common, "reg_boost": 0.44, "reg_recovery": 0.12, "ramp_in_ms": 8.0, "recovery_taper_ms": 50.0},
            {**common, "reg_boost": 0.48, "reg_recovery": 0.16, "ramp_in_ms": 10.0, "recovery_taper_ms": 55.0},
            {**common, "reg_boost": 0.32, "reg_recovery": -0.04, "ramp_in_ms": 5.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.36, "reg_recovery": -0.04, "ramp_in_ms": 6.0, "recovery_taper_ms": 40.0},
            {**common, "reg_boost": 0.65, "reg_recovery": 0.26, "ramp_in_ms": 4.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.70, "reg_recovery": 0.30, "ramp_in_ms": 4.0, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.75, "reg_recovery": 0.34, "ramp_in_ms": 4.0, "recovery_taper_ms": 40.0},
            {**common, "reg_boost": 0.80, "reg_recovery": 0.38, "ramp_in_ms": 4.0, "recovery_taper_ms": 45.0},
            {
                **common,
                "reg_boost": 0.75,
                "reg_recovery": 0.32,
                "energy_d_boost": 0.05,
                "energy_d_recovery": 0.02,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 40.0,
            },
            {
                **common,
                "reg_boost": 0.80,
                "reg_recovery": 0.36,
                "energy_d_boost": 0.08,
                "energy_d_recovery": 0.03,
                "ramp_in_ms": 4.0,
                "recovery_taper_ms": 45.0,
            },
        ]
        return anchors
    if fault_pu < 1.0:
        anchors = [
            {**common, "reg_boost": 0.36, "reg_recovery": 0.36, "recovery_taper_ms": 90.0},
            {**common, "reg_boost": 0.48, "reg_recovery": 0.36, "recovery_taper_ms": 55.0},
            {**common, "reg_boost": 0.48, "reg_recovery": 0.30, "recovery_taper_ms": 45.0},
            {**common, "reg_boost": 0.48, "reg_recovery": 0.24, "recovery_taper_ms": 45.0},
            {**common, "reg_boost": 0.52, "reg_recovery": 0.30, "recovery_taper_ms": 40.0},
            {**common, "reg_boost": 0.52, "reg_recovery": 0.24, "recovery_taper_ms": 40.0},
            {**common, "reg_boost": 0.56, "reg_recovery": 0.28, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.56, "reg_recovery": 0.22, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.60, "reg_recovery": 0.36, "recovery_taper_ms": 35.0},
            {**common, "reg_boost": 0.65, "reg_recovery": 0.30, "recovery_taper_ms": 45.0},
            {
                **common,
                "reg_boost": 0.60,
                "reg_recovery": 0.36,
                "energy_d_boost": 0.12,
                "energy_d_recovery": 0.04,
                "recovery_taper_ms": 35.0,
            },
        ]
        if allow_prebias:
            anchors.append({**common, "reg_pre": 0.25, "reg_boost": 0.65, "reg_recovery": 0.30})
        return anchors
    anchors = [
        {**common, "reg_boost": 0.12, "reg_recovery": 0.00, "recovery_taper_ms": 12.0, "final_taper_ms": 40.0},
        {**common, "reg_boost": 0.18, "reg_recovery": 0.00, "recovery_taper_ms": 12.0, "final_taper_ms": 40.0},
        {**common, "reg_boost": 0.24, "reg_recovery": 0.00, "recovery_taper_ms": 12.0, "final_taper_ms": 40.0},
        {**common, "reg_boost": 0.30, "reg_recovery": 0.00, "recovery_taper_ms": 12.0, "final_taper_ms": 40.0},
        {**common, "reg_boost": 0.18, "reg_recovery": -0.04, "recovery_taper_ms": 16.0, "final_taper_ms": 45.0},
        {**common, "reg_boost": 0.24, "reg_recovery": -0.04, "recovery_taper_ms": 16.0, "final_taper_ms": 45.0},
        {
            **common,
            "reg_boost": 0.249,
            "reg_recovery": 0.00,
            "energy_d_boost": -0.005,
            "energy_d_recovery": 0.00,
            "recovery_taper_ms": 14.0,
            "final_taper_ms": 45.0,
        },
        {**common, "reg_boost": 0.00, "reg_recovery": 0.12, "recovery_taper_ms": 18.0},
        {**common, "reg_boost": 0.00, "reg_recovery": 0.18, "recovery_taper_ms": 24.0},
        {**common, "reg_boost": 0.00, "reg_recovery": 0.24, "recovery_taper_ms": 20.0},
        {**common, "reg_boost": 0.00, "reg_recovery": 0.30, "recovery_taper_ms": 18.0},
        {**common, "reg_boost": -0.04, "reg_recovery": 0.12, "recovery_taper_ms": 18.0},
        {**common, "reg_boost": -0.04, "reg_recovery": 0.18, "recovery_taper_ms": 24.0},
        {**common, "reg_boost": -0.04, "reg_recovery": 0.24, "recovery_taper_ms": 20.0},
        {**common, "reg_boost": -0.04, "reg_recovery": 0.30, "recovery_taper_ms": 18.0},
        {**common, "reg_boost": -0.08, "reg_recovery": 0.12, "recovery_taper_ms": 20.0},
        {**common, "reg_boost": -0.08, "reg_recovery": 0.18, "recovery_taper_ms": 26.0},
        {
            **common,
            "reg_boost": 0.00,
            "reg_recovery": 0.12,
            "energy_d_boost": -0.05,
            "energy_d_recovery": -0.05,
            "recovery_taper_ms": 18.0,
        },
        {
            **common,
            "reg_boost": -0.04,
            "reg_recovery": 0.14,
            "energy_d_boost": -0.05,
            "energy_d_recovery": -0.05,
            "recovery_taper_ms": 20.0,
        },
        {**common, "reg_pre": -0.16 if allow_prebias else 0.0, "reg_boost": -0.22, "reg_recovery": 0.12, "recovery_taper_ms": 20.0},
        {**common, "reg_pre": -0.24 if allow_prebias else 0.0, "reg_boost": -0.35, "reg_recovery": 0.18, "recovery_taper_ms": 25.0},
        {**common, "reg_pre": -0.32 if allow_prebias else 0.0, "reg_boost": -0.48, "reg_recovery": 0.24, "recovery_taper_ms": 30.0},
        {**common, "reg_boost": -0.22, "reg_recovery": -0.16, "recovery_taper_ms": 45.0},
        {**common, "reg_boost": -0.35, "reg_recovery": -0.20, "recovery_taper_ms": 55.0},
        {**common, "reg_boost": -0.48, "reg_recovery": -0.25, "recovery_taper_ms": 65.0},
        {**common, "reg_boost": -0.22, "reg_recovery": 0.12, "recovery_taper_ms": 20.0},
        {**common, "reg_boost": -0.35, "reg_recovery": 0.18, "recovery_taper_ms": 25.0},
        {**common, "reg_boost": -0.48, "reg_recovery": 0.24, "recovery_taper_ms": 30.0},
        {
            **common,
            "reg_boost": -0.35,
            "reg_recovery": -0.20,
            "energy_d_boost": -0.10,
            "energy_d_recovery": -0.04,
            "recovery_taper_ms": 55.0,
        },
        {
            **common,
            "reg_boost": -0.35,
            "reg_recovery": 0.20,
            "energy_d_boost": -0.10,
            "energy_d_recovery": 0.02,
            "recovery_taper_ms": 25.0,
        },
    ]
    if allow_prebias:
        anchors.append({**common, "reg_pre": -0.12, "reg_boost": -0.35, "reg_recovery": -0.20})
    return anchors


def _append_knot(times: list[float], values: list[np.ndarray], t: float, action: np.ndarray) -> None:
    t = float(max(0.0, t))
    if times and t <= times[-1] + 1e-12:
        times[-1] = max(times[-1], t)
        values[-1] = action.copy()
    else:
        times.append(t)
        values.append(action.copy())


def make_piecewise_trajectory(
    params: dict[str, float],
    *,
    dt: float,
    fault_start: float,
    fault_duration: float,
    fault_stop_margin: float,
    return_to_zero: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Create a 4-D piecewise-linear control trajectory from CEM parameters."""

    fault_clear = float(fault_start) + float(fault_duration)
    stop_time = fault_clear + float(fault_stop_margin)
    n = int(np.floor(stop_time / dt)) + 1
    t = np.arange(n, dtype=float) * dt
    if not np.isclose(t[-1], stop_time):
        t = np.append(t, stop_time)

    pre = np.asarray([params["reg_pre"], 0.0, 0.0, 0.0], dtype=float)
    boost = np.asarray(
        [
            params["reg_boost"],
            params["reg_q_boost"],
            params["energy_d_boost"],
            params["energy_q_boost"],
        ],
        dtype=float,
    )
    recovery = np.asarray(
        [
            params["reg_recovery"],
            params["reg_q_recovery"],
            params["energy_d_recovery"],
            params["energy_q_recovery"],
        ],
        dtype=float,
    )
    ramp_in = params["ramp_in_ms"] / 1000.0
    recovery_taper = params["recovery_taper_ms"] / 1000.0
    final_taper = params["final_taper_ms"] / 1000.0
    t_boost = min(stop_time, fault_start + ramp_in)
    t_recovery = min(stop_time, fault_clear + recovery_taper)
    t_final = max(t_recovery, stop_time - final_taper)

    times: list[float] = []
    values: list[np.ndarray] = []
    _append_knot(times, values, 0.0, pre)
    _append_knot(times, values, fault_start, pre)
    _append_knot(times, values, t_boost, boost)
    _append_knot(times, values, fault_clear, boost)
    _append_knot(times, values, t_recovery, recovery)
    if return_to_zero:
        zero = np.zeros(4, dtype=float)
        _append_knot(times, values, t_final, recovery)
        _append_knot(times, values, stop_time, zero)
    else:
        _append_knot(times, values, stop_time, recovery)

    xp = np.asarray(times, dtype=float)
    fp = np.vstack(values)
    action = np.column_stack([np.interp(t, xp, fp[:, dim]) for dim in range(4)])
    low = np.asarray([-0.8, -0.8, -0.95, -0.95], dtype=float)
    high = np.asarray([0.8, 0.8, 0.95, 0.95], dtype=float)
    action = np.clip(action, low, high)
    manifest = {
        "knots": [
            {
                "t": float(tt),
                "m_reg_d": float(aa[0]),
                "m_reg_q": float(aa[1]),
                "m_energy_d": float(aa[2]),
                "m_energy_q": float(aa[3]),
            }
            for tt, aa in zip(xp, fp)
        ],
        "n_points": int(t.size),
        "stop_time": float(stop_time),
        "fault_clear": float(fault_clear),
    }
    return t.reshape(-1, 1), action, manifest


def make_scenario(args: argparse.Namespace) -> HPTVoltageScenario:
    category = "HVRT" if args.fault_pu > 1.0 else "LVRT"
    stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
    phase_key = phase_key_from_vector(args.fault_phase_pu)
    neg_seq = neg_seq_from_phase_vector(args.fault_phase_pu)
    return HPTVoltageScenario(
        topology=args.topology,
        grid_pu=args.fault_pu,
        neg_seq_pu=neg_seq,
        fault_phase_key=phase_key,
        duration_s=stop_time,
        category=category,
        fault_type=args.case_name or make_case_name(args.duration_s, args.fault_pu),
        fault_start_s=args.fault_start,
        fault_duration_s=args.duration_s,
        calibration_mode="joint_sweep",
    )


def proxy_score(
    candidate: Candidate,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run one candidate trajectory through the calibrated proxy."""

    t, action, manifest = make_piecewise_trajectory(
        candidate.params,
        dt=args.decision_dt,
        fault_start=args.fault_start,
        fault_duration=args.duration_s,
        fault_stop_margin=args.fault_stop_margin,
        return_to_zero=args.return_to_zero,
    )
    config = HPTVoltageEnvConfig(
        dt=args.decision_dt,
        calibration_path=str(args.calibration),
        fault_settle_s=args.fault_settle_s,
        action_projection_enable=False,
        envelope_terminal=False,
    )
    env = HPTVoltageSACEnv([make_scenario(args)], config=config, train_mode=False)
    env_seed = int(args.seed + candidate.index + 1000 * max(0, candidate.iteration))
    env.reset(seed=env_seed)

    reward_sum = 0.0
    terminated = False
    truncated = False
    infos: list[dict[str, Any]] = []
    for a in action:
        _, reward, terminated, truncated, info = env.step(a.astype(np.float32))
        reward_sum += float(reward)
        infos.append(info)
        if terminated or truncated:
            break

    lv = np.asarray([finite(info.get("v_lv_pu")) for info in infos], dtype=float)
    vdc = np.asarray([finite(info.get("vdc_pu")) for info in infos], dtype=float)
    iq_shortfall = np.asarray(
        [finite(info.get("grid_iq_shortfall_reward_pu"), 0.0) for info in infos],
        dtype=float,
    )
    current = np.asarray([finite(info.get("grid_current_peak_pu"), 0.0) for info in infos], dtype=float)
    support = np.asarray([finite(info.get("calibration_support_violation"), 0.0) for info in infos], dtype=float)
    final_info = infos[-1] if infos else {}
    envelope = finite(final_info.get("envelope_violation_max_pu"), 9.0)
    recovery = finite(final_info.get("recovery_violation_max_pu"), 9.0)
    support_max = float(np.nanmax(support)) if support.size else 9.0
    vdc_min = float(np.nanmin(vdc)) if vdc.size else 0.0
    vdc_max = float(np.nanmax(vdc)) if vdc.size else 9.0
    current_peak = float(np.nanmax(current)) if current.size else 9.0
    shortfall_max = float(np.nanmax(iq_shortfall)) if iq_shortfall.size else 9.0

    score = -reward_sum / max(1, len(infos))
    score += args.proxy_envelope_weight * (envelope * envelope + recovery * recovery)
    score += args.proxy_support_weight * support_max * support_max
    score += args.proxy_current_weight * max(0.0, current_peak - 1.50) ** 2
    score += args.proxy_vdc_weight * (
        max(0.0, 650.0 / 800.0 - vdc_min) ** 2 + max(0.0, vdc_max - 1000.0 / 800.0) ** 2
    )
    score += args.proxy_iq_weight * shortfall_max

    return {
        "candidate_index": candidate.index,
        "iteration": candidate.iteration,
        "proxy_score": float(score),
        "proxy_reward_mean": float(reward_sum / max(1, len(infos))),
        "proxy_steps": int(len(infos)),
        "proxy_terminated": bool(terminated),
        "proxy_truncated": bool(truncated),
        "proxy_lv_min_pu": float(np.nanmin(lv)) if lv.size else float("nan"),
        "proxy_lv_mean_pu": float(np.nanmean(lv)) if lv.size else float("nan"),
        "proxy_vdc_min_pu": vdc_min,
        "proxy_vdc_max_pu": vdc_max,
        "proxy_envelope_violation_max_pu": float(envelope),
        "proxy_recovery_violation_max_pu": float(recovery),
        "proxy_support_violation": support_max,
        "proxy_grid_current_peak_pu": current_peak,
        "proxy_grid_iq_shortfall_max_pu": shortfall_max,
        "trajectory_manifest": manifest,
        **{f"param_{k}": float(v) for k, v in candidate.params.items()},
    }


def sample_candidates(
    *,
    mean: np.ndarray,
    std: np.ndarray,
    bounds: dict[str, tuple[float, float]],
    iteration: int,
    population: int,
    rng: np.random.Generator,
) -> list[Candidate]:
    latent = np.clip(rng.normal(mean[None, :], std[None, :], size=(population, len(PARAM_NAMES))), 0.0, 1.0)
    return [
        Candidate(
            index=i,
            iteration=iteration,
            latent=latent[i].astype(float),
            params=latent_to_params(latent[i], bounds),
        )
        for i in range(population)
    ]


def run_matlab_trajectory(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    candidate: Candidate,
    trajectory_file: Path,
    fixed_action: np.ndarray,
) -> tuple[Path | None, str, str, int]:
    modes = "{'conventional_dq','fixed_action','trajectory_action'}"
    case_name = args.case_name or make_case_name(args.duration_s, args.fault_pu)
    label = safe_token(
        f"cem_traj_{args.topology}_{case_name}_it{candidate.iteration:02d}_c{candidate.index:03d}"
    )
    base_rchop = (800.0**2) / 120e3
    statement = "; ".join(
        [
            f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
            f"hpt_compare_topology={matlab_string(args.topology)}",
            "hpt_compare_scenario_type='fault'",
            f"hpt_compare_modes=string({modes})",
            f"hpt_compare_faults={matlab_fault_cell(case_name, args.fault_pu, args.duration_s, args.fault_phase_pu)}",
            "hpt_compare_model_params=struct("
            f"'hpt_chopper_threshold',{args.chopper_threshold:.12g},"
            f"'hpt_rchop',{base_rchop * args.rchop_scale:.12g})",
            f"hpt_compare_fault_start={args.fault_start:.12g}",
            f"hpt_compare_fault_stop_margin={args.fault_stop_margin:.12g}",
            f"hpt_compare_fault_settle_s={args.fault_settle_s:.12g}",
            f"hpt_compare_run_label={matlab_string(label)}",
            "hpt_compare_fixed_action=[" + " ".join(f"{float(x):.12g}" for x in fixed_action) + "]",
            f"hpt_compare_trajectory_file={matlab_string(str(trajectory_file).replace(chr(92), '/'))}",
            "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
        ]
    )
    before = set((RESULTS / "hpt_v2_control_comparison").glob("control_comparison_*.csv"))
    proc = subprocess.run(
        [args.matlab_cmd, "-batch", statement],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.timeout_s,
    )
    (run_dir / "matlab_statement.txt").write_text(statement, encoding="utf-8")
    (run_dir / "matlab.log").write_text(
        "STDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return None, proc.stdout, proc.stderr, proc.returncode
    return latest_control_csv(before), proc.stdout, proc.stderr, proc.returncode


def validate_switch_candidates(
    selected: list[tuple[Candidate, dict[str, Any]]],
    *,
    args: argparse.Namespace,
    run_dir: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, (candidate, proxy_row) in enumerate(selected):
        cand_dir = run_dir / f"switch_candidate_{rank:03d}_it{candidate.iteration:02d}_c{candidate.index:03d}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        t, action, manifest = make_piecewise_trajectory(
            candidate.params,
            dt=args.decision_dt,
            fault_start=args.fault_start,
            fault_duration=args.duration_s,
            fault_stop_margin=args.fault_stop_margin,
            return_to_zero=args.return_to_zero,
        )
        trajectory_file = cand_dir / "hpt_sac_trajectory.mat"
        write_mat(trajectory_file, t, action)
        write_csv(cand_dir / "hpt_sac_trajectory.csv", t, action)
        (cand_dir / "trajectory_manifest.json").write_text(
            json.dumps({"params": candidate.params, **manifest}, indent=2),
            encoding="utf-8",
        )
        fixed_action = np.asarray(
            [
                candidate.params["reg_boost"],
                candidate.params["reg_q_boost"],
                candidate.params["energy_d_boost"],
                candidate.params["energy_q_boost"],
            ],
            dtype=float,
        )
        try:
            csv_path, _stdout, stderr, returncode = run_matlab_trajectory(
                args=args,
                run_dir=cand_dir,
                candidate=candidate,
                trajectory_file=trajectory_file,
                fixed_action=fixed_action,
            )
        except subprocess.TimeoutExpired as exc:
            rows.append(
                {
                    **proxy_row,
                    "switch_rank": rank,
                    "switch_returncode": -999,
                    "switch_error": f"timeout after {exc.timeout}s",
                }
            )
            continue
        if returncode != 0 or csv_path is None:
            rows.append(
                {
                    **proxy_row,
                    "switch_rank": rank,
                    "switch_returncode": returncode,
                    "switch_error": stderr[-1000:],
                }
            )
            continue
        sim_rows = read_csv(csv_path)
        summary = summarize_modes(sim_rows)
        rows.append(
            {
                **proxy_row,
                "switch_rank": rank,
                "switch_returncode": returncode,
                "switch_csv": str(csv_path),
                "switch_candidate_dir": str(cand_dir),
                **{f"switch_{k}": v for k, v in summary.items()},
            }
        )
    return rows


def write_report(run_dir: Path, *, config: dict[str, Any], proxy_rows: list[dict[str, Any]], switch_rows: list[dict[str, Any]]) -> None:
    best_proxy = min(proxy_rows, key=lambda r: finite(r.get("proxy_score"), 1e99)) if proxy_rows else {}
    accepted = [
        row
        for row in switch_rows
        if str(row.get("switch_trajectory_voltage_pass", "")).lower() in {"true", "1", "1.0"}
    ]
    lines = [
        "# HPT Trajectory CEM Search",
        "",
        "## Configuration",
        "",
        "```json",
        json.dumps(config, indent=2),
        "```",
        "",
        "## Current Result",
        "",
        f"- Proxy candidates evaluated: `{len(proxy_rows)}`",
        f"- Switch-level candidates evaluated: `{len(switch_rows)}`",
        f"- Switch-level voltage-survival passes: `{len(accepted)}`",
    ]
    if best_proxy:
        lines.extend(
            [
                f"- Best proxy score: `{best_proxy.get('proxy_score')}`",
                f"- Best proxy params: `{ {k.replace('param_', ''): best_proxy[k] for k in best_proxy if k.startswith('param_')} }`",
            ]
        )
    if switch_rows:
        lines.extend(["", "## Switch Candidates", ""])
        lines.append(
            "| Rank | Pass | Score | LV mean | Recovery mean | Vdc min | Env viol | Rec viol | Proxy score | Dir |"
        )
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for row in switch_rows:
            lines.append(
                f"| {row.get('switch_rank','')} | "
                f"{row.get('switch_trajectory_voltage_pass','')} | "
                f"{row.get('switch_trajectory_score','')} | "
                f"{row.get('switch_trajectory_lv_mean','')} | "
                f"{row.get('switch_trajectory_lv_recovery_mean','')} | "
                f"{row.get('switch_trajectory_vdc_min','')} | "
                f"{row.get('switch_trajectory_envelope_violation_max_pu','')} | "
                f"{row.get('switch_trajectory_recovery_violation_max_pu','')} | "
                f"{row.get('proxy_score','')} | "
                f"`{row.get('switch_candidate_dir','')}` |"
            )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology1", choices=["topology1", "topology2"])
    parser.add_argument("--fault-pu", type=float, default=0.90)
    parser.add_argument("--fault-phase-pu", type=float, nargs=3, default=None)
    parser.add_argument("--duration-s", type=float, default=0.060)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.020)
    parser.add_argument("--chopper-threshold", type=float, default=850.0)
    parser.add_argument("--rchop-scale", type=float, default=1.0)
    parser.add_argument("--case-name", default="")
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--population", type=int, default=32)
    parser.add_argument("--elite-frac", type=float, default=0.25)
    parser.add_argument("--switch-top-k", type=int, default=3)
    parser.add_argument("--allow-prebias", action="store_true")
    parser.add_argument("--no-anchors", action="store_true")
    parser.add_argument(
        "--no-force-switch-anchors",
        action="store_true",
        help="Let proxy ranking choose switch-level candidates instead of validating anchors first.",
    )
    parser.add_argument(
        "--return-to-zero",
        action="store_true",
        help="Ramp back to zero before StopTime. By default recovery action is held through StopTime.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=1200)
    parser.add_argument("--proxy-envelope-weight", type=float, default=1200.0)
    parser.add_argument("--proxy-support-weight", type=float, default=250.0)
    parser.add_argument("--proxy-vdc-weight", type=float, default=900.0)
    parser.add_argument("--proxy-current-weight", type=float, default=120.0)
    parser.add_argument("--proxy-iq-weight", type=float, default=80.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.iterations < 0 or args.population <= 0:
        raise ValueError("iterations must be nonnegative and population must be positive")
    if args.iterations == 0 and args.no_anchors:
        raise ValueError("iterations=0 requires anchors")
    run_id = args.run_id or f"hpt_cem_trajectory_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    bounds = param_bounds(args.fault_pu, allow_prebias=args.allow_prebias)
    rng = np.random.default_rng(args.seed)
    mean = np.full(len(PARAM_NAMES), 0.5, dtype=float)
    std = np.full(len(PARAM_NAMES), 0.28, dtype=float)
    # Do not waste variance on disabled pre-bias.
    if bounds["reg_pre"][0] == bounds["reg_pre"][1]:
        mean[0] = 0.0
        std[0] = 0.0

    all_proxy_rows: list[dict[str, Any]] = []
    scored_candidates: list[tuple[Candidate, dict[str, Any]]] = []
    if not args.no_anchors:
        anchors = [
            Candidate(
                index=i,
                iteration=-1,
                latent=params_to_latent(params, bounds),
                params=params,
            )
            for i, params in enumerate(
                anchor_params(args.fault_pu, topology=args.topology, allow_prebias=args.allow_prebias)
            )
        ]
        anchor_rows = [proxy_score(c, args=args) for c in anchors]
        all_proxy_rows.extend(anchor_rows)
        scored_candidates.extend((c, r) for c, r in zip(anchors, anchor_rows))

    for iteration in range(args.iterations):
        candidates = sample_candidates(
            mean=mean,
            std=std,
            bounds=bounds,
            iteration=iteration,
            population=args.population,
            rng=rng,
        )
        rows = [proxy_score(c, args=args) for c in candidates]
        rows.sort(key=lambda r: finite(r.get("proxy_score"), 1e99))
        all_proxy_rows.extend(rows)
        by_key = {(c.iteration, c.index): c for c in candidates}
        elite_count = max(2, int(math.ceil(args.population * args.elite_frac)))
        elites = rows[:elite_count]
        elite_latent = np.vstack([by_key[(int(r["iteration"]), int(r["candidate_index"]))].latent for r in elites])
        mean = np.mean(elite_latent, axis=0)
        std = np.clip(np.std(elite_latent, axis=0), 0.05, 0.35)
        if bounds["reg_pre"][0] == bounds["reg_pre"][1]:
            mean[0] = 0.0
            std[0] = 0.0
        scored_candidates.extend((by_key[(int(r["iteration"]), int(r["candidate_index"]))], r) for r in rows)
        (run_dir / f"cem_iteration_{iteration:02d}.json").write_text(
            json.dumps(
                {
                    "iteration": iteration,
                    "mean": mean.tolist(),
                    "std": std.tolist(),
                    "best_proxy_score": rows[0]["proxy_score"],
                    "best_params": {
                        k.replace("param_", ""): rows[0][k] for k in rows[0] if k.startswith("param_")
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    all_proxy_rows.sort(key=lambda r: finite(r.get("proxy_score"), 1e99))
    write_csv_rows(run_dir / "proxy_candidates.csv", all_proxy_rows)

    seen: set[tuple[int, int]] = set()
    selected: list[tuple[Candidate, dict[str, Any]]] = []
    if args.switch_top_k > 0:
        ordered: list[tuple[Candidate, dict[str, Any]]] = []
        if not args.no_force_switch_anchors:
            ordered.extend(
                sorted(
                    [(c, r) for c, r in scored_candidates if c.iteration == -1],
                    key=lambda cr: finite(cr[1].get("proxy_score"), 1e99),
                )
            )
        ordered.extend(
            sorted(
                [
                    (c, r)
                    for c, r in scored_candidates
                    if args.no_force_switch_anchors or c.iteration != -1
                ],
                key=lambda cr: finite(cr[1].get("proxy_score"), 1e99),
            )
        )
        for candidate, row in ordered:
            key = (candidate.iteration, candidate.index)
            if key in seen:
                continue
            seen.add(key)
            selected.append((candidate, row))
            if len(selected) >= args.switch_top_k:
                break

    switch_rows = validate_switch_candidates(selected, args=args, run_dir=run_dir)
    write_csv_rows(run_dir / "switch_candidates.csv", switch_rows)

    config = {
        **vars(args),
        "calibration": str(args.calibration),
        "bounds": bounds,
        "param_names": PARAM_NAMES,
    }
    write_report(run_dir, config=config, proxy_rows=all_proxy_rows, switch_rows=switch_rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_cem_trajectory_search",
        config=config,
        topology_models={
            "topology1": ROOT / "version_2" / "simulink" / "topoloty1" / "hpt_v2_1to1_switchlevel.slx",
            "topology2": ROOT / "version_2" / "simulink" / "topology2" / "hpt_v2_topology2_paper.slx",
        },
        dataset_manifest=run_dir / "proxy_candidates.csv",
    )
    print(json.dumps({"run_dir": str(run_dir), "switch_rows": len(switch_rows)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
