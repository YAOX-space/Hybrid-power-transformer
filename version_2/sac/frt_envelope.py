"""Shared GB/T-style FRT voltage-envelope helpers for HPT SAC research.

The switch-level MATLAB evaluators and the Python SAC proxy both need one
definition of "the voltage trace stayed inside the required envelope at every
control step".  This module keeps that definition explicit and small enough to
audit.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np


DEFAULT_PHASE_RMS = 207.0
DEFAULT_VDC = 800.0
DEFAULT_SOLVER_TOL_PU = 1e-3


@dataclass(frozen=True)
class EnvelopeMetrics:
    """Compressed per-step envelope result for one FRT trajectory."""

    category: str
    envelope_violation_max_pu: float
    envelope_violation_mean_pu: float
    envelope_violation_duration_s: float
    envelope_margin_min_pu: float
    envelope_pass: bool
    fault_band_violation_max_pu: float
    fault_band_violation_mean_pu: float
    fault_band_violation_duration_s: float
    fault_band_pass: bool
    fault_lv_min_pu: float
    fault_lv_max_pu: float
    recovery_violation_max_pu: float
    recovery_violation_mean_pu: float
    recovery_violation_duration_s: float
    recovery_envelope_pass: bool
    recovery_lv_min_pu: float
    recovery_lv_max_pu: float
    timestep_envelope_pass: bool

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def lvrt_lower_envelope(t_rel: np.ndarray | float, residual_pu: float) -> np.ndarray:
    """GB/T-inspired LVRT lower voltage boundary."""

    t = np.asarray(t_rel, dtype=float)
    residual = max(0.20, float(residual_pu))
    y = np.full_like(t, 0.90, dtype=float)
    y = np.where((t >= 0.0) & (t <= 0.625), residual, y)
    ramp = residual + (0.90 - residual) * (t - 0.625) / (2.0 - 0.625)
    y = np.where((t > 0.625) & (t <= 2.0), ramp, y)
    return y


def hvrt_upper_envelope(t_rel: np.ndarray | float) -> np.ndarray:
    """GB/T-inspired HVRT upper voltage boundary."""

    t = np.asarray(t_rel, dtype=float)
    y = np.full_like(t, 1.10, dtype=float)
    y = np.where((t >= 0.0) & (t <= 0.5), 1.30, y)
    y = np.where((t > 0.5) & (t <= 1.0), 1.20, y)
    return y


def voltage_envelope_arrays(
    t_s: np.ndarray,
    lv_pu: np.ndarray,
    *,
    fault_pu: float,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float | None = None,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = 0.035,
    recovery_band_pu: float = 0.07,
) -> dict[str, np.ndarray | str]:
    """Return per-sample envelope bounds and violations.

    LVRT is assessed against a lower bound.  HVRT is assessed against an upper
    bound.  The recovery band is assessed separately after the short settling
    interval used by the switch-level scripts.
    """

    t = np.asarray(t_s, dtype=float).reshape(-1)
    v = np.asarray(lv_pu, dtype=float).reshape(-1)
    if t.shape != v.shape:
        raise ValueError(f"t_s and lv_pu shape mismatch: {t.shape} vs {v.shape}")
    stop = float(stop_time_s) if stop_time_s is not None else (float(t[-1]) if t.size else 0.0)
    fault_assess_start = float(fault_start_s) + max(0.0, float(fault_settle_s))
    active = (t >= fault_assess_start) & (t <= stop)
    t_rel = t - float(fault_start_s)

    if float(fault_pu) < 1.0:
        category = "LVRT"
        lower = lvrt_lower_envelope(t_rel, float(fault_pu))
        upper = np.full_like(lower, np.inf, dtype=float)
        margin = v - lower
        violation = np.maximum(0.0, lower - v)
    else:
        category = "HVRT"
        upper = hvrt_upper_envelope(t_rel)
        lower = np.full_like(upper, -np.inf, dtype=float)
        margin = upper - v
        violation = np.maximum(0.0, v - upper)

    violation = np.where(active, violation, 0.0)
    margin = np.where(active, margin, np.inf)

    recovery = (t >= float(fault_clear_s) + float(recovery_settle_s)) & (t <= stop)
    recovery_violation = np.maximum(0.0, np.abs(v - 1.0) - float(recovery_band_pu))
    recovery_violation = np.where(recovery, recovery_violation, 0.0)

    fault_band = (t >= fault_assess_start) & (t <= float(fault_clear_s))
    fault_lo = 176.0 / DEFAULT_PHASE_RMS
    fault_hi = 238.0 / DEFAULT_PHASE_RMS
    fault_band_violation = np.maximum(
        np.maximum(0.0, fault_lo - v),
        np.maximum(0.0, v - fault_hi),
    )
    fault_band_violation = np.where(fault_band, fault_band_violation, 0.0)

    return {
        "category": category,
        "lower_pu": lower,
        "upper_pu": upper,
        "margin_pu": margin,
        "violation_pu": violation,
        "active": active,
        "fault_band_violation_pu": fault_band_violation,
        "fault_band_active": fault_band,
        "recovery_violation_pu": recovery_violation,
        "recovery_active": recovery,
    }


def summarize_voltage_envelope(
    t_s: np.ndarray,
    lv_pu: np.ndarray,
    *,
    fault_pu: float,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float | None = None,
    tolerance_pu: float = DEFAULT_SOLVER_TOL_PU,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = 0.035,
    recovery_band_pu: float = 0.07,
) -> EnvelopeMetrics:
    """Compute pass/fail and violation magnitudes over all sampled steps."""

    arrays = voltage_envelope_arrays(
        t_s,
        lv_pu,
        fault_pu=fault_pu,
        fault_start_s=fault_start_s,
        fault_clear_s=fault_clear_s,
        stop_time_s=stop_time_s,
        fault_settle_s=fault_settle_s,
        recovery_settle_s=recovery_settle_s,
        recovery_band_pu=recovery_band_pu,
    )
    t = np.asarray(t_s, dtype=float).reshape(-1)
    dt = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    active = np.asarray(arrays["active"], dtype=bool)
    recovery = np.asarray(arrays["recovery_active"], dtype=bool)
    violation = np.asarray(arrays["violation_pu"], dtype=float)
    recovery_violation = np.asarray(arrays["recovery_violation_pu"], dtype=float)
    margins = np.asarray(arrays["margin_pu"], dtype=float)

    active_violation = violation[active]
    recovery_active_violation = recovery_violation[recovery]
    active_margins = margins[active]
    fault_band = np.asarray(arrays["fault_band_active"], dtype=bool)
    fault_band_violation = np.asarray(arrays["fault_band_violation_pu"], dtype=float)
    fault_band_active_violation = fault_band_violation[fault_band]

    max_violation = float(np.max(active_violation)) if active_violation.size else 0.0
    mean_violation = float(np.mean(active_violation)) if active_violation.size else 0.0
    violation_duration = float(dt * np.count_nonzero(active_violation > tolerance_pu))
    margin_min = float(np.min(active_margins)) if active_margins.size else float("inf")
    fault_band_max = (
        float(np.max(fault_band_active_violation)) if fault_band_active_violation.size else 0.0
    )
    fault_band_mean = (
        float(np.mean(fault_band_active_violation)) if fault_band_active_violation.size else 0.0
    )
    fault_band_duration = float(
        dt * np.count_nonzero(fault_band_active_violation > tolerance_pu)
    )
    fault_lv = np.asarray(lv_pu, dtype=float).reshape(-1)[fault_band]
    fault_lv_min = float(np.min(fault_lv)) if fault_lv.size else float("nan")
    fault_lv_max = float(np.max(fault_lv)) if fault_lv.size else float("nan")
    recovery_max = (
        float(np.max(recovery_active_violation)) if recovery_active_violation.size else 0.0
    )
    recovery_mean = (
        float(np.mean(recovery_active_violation)) if recovery_active_violation.size else 0.0
    )
    recovery_duration = float(dt * np.count_nonzero(recovery_active_violation > tolerance_pu))
    recovery_lv = np.asarray(lv_pu, dtype=float).reshape(-1)[recovery]
    recovery_lv_min = float(np.min(recovery_lv)) if recovery_lv.size else float("nan")
    recovery_lv_max = float(np.max(recovery_lv)) if recovery_lv.size else float("nan")
    envelope_pass = bool(max_violation <= tolerance_pu)
    recovery_pass = bool(recovery_max <= tolerance_pu)
    fault_band_pass = bool(fault_band_max <= tolerance_pu)
    return EnvelopeMetrics(
        category=str(arrays["category"]),
        envelope_violation_max_pu=max_violation,
        envelope_violation_mean_pu=mean_violation,
        envelope_violation_duration_s=violation_duration,
        envelope_margin_min_pu=margin_min,
        envelope_pass=envelope_pass,
        fault_band_violation_max_pu=fault_band_max,
        fault_band_violation_mean_pu=fault_band_mean,
        fault_band_violation_duration_s=fault_band_duration,
        fault_band_pass=fault_band_pass,
        fault_lv_min_pu=fault_lv_min,
        fault_lv_max_pu=fault_lv_max,
        recovery_violation_max_pu=recovery_max,
        recovery_violation_mean_pu=recovery_mean,
        recovery_violation_duration_s=recovery_duration,
        recovery_envelope_pass=recovery_pass,
        recovery_lv_min_pu=recovery_lv_min,
        recovery_lv_max_pu=recovery_lv_max,
        timestep_envelope_pass=bool(envelope_pass and recovery_pass and fault_band_pass),
    )


def sample_voltage_envelope(
    *,
    t_s: float,
    lv_pu: float,
    fault_pu: float,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float,
    tolerance_pu: float = DEFAULT_SOLVER_TOL_PU,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = 0.035,
    recovery_band_pu: float = 0.07,
) -> dict[str, float | bool | str]:
    """Evaluate one control step against the same envelope definition."""

    metrics = summarize_voltage_envelope(
        np.asarray([float(t_s)], dtype=float),
        np.asarray([float(lv_pu)], dtype=float),
        fault_pu=fault_pu,
        fault_start_s=fault_start_s,
        fault_clear_s=fault_clear_s,
        stop_time_s=stop_time_s,
        tolerance_pu=tolerance_pu,
        fault_settle_s=fault_settle_s,
        recovery_settle_s=recovery_settle_s,
        recovery_band_pu=recovery_band_pu,
    )
    return metrics.asdict()
