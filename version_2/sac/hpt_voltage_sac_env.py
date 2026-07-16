"""Topology-neutral SAC surrogate for HPT voltage regulation and FRT transitions.

This environment targets the final HPT switch-level models in
``version_2/simulink``.  It keeps the final 4-D direct-action contract and
extends the observation from the early steady-regulation 16-D vector to a
fault-transition-aware 24-D vector:

    obs = [
        v_lv_rms_pu, v_pos_pu, v_neg_pu, vdc_pu, vdc_err_pu, v_err_pu,
        energy_id_pu, energy_iq_pu,
        last_m_reg_d, last_m_reg_q, last_i_energy_d_ref, last_i_energy_q_ref,
        sag_flag, swell_flag, topology1_flag, topology2_flag,
        fault_active_est, recovery_active_est, t_fault_est_pu, t_recovery_est_pu,
        v_fault_min_pu, v_fault_max_pu, dv_pos_dt_pu, d_vdc_dt_pu,
    ]

    act = [m_reg_d, m_reg_q, i_energy_d_ref_pu, i_energy_q_ref_pu]

The fault detector and scenario coverage are intentionally borrowed from the
older ``src/hpt_frt/device`` FRT SAC design: online measured-voltage detection,
LVRT/HVRT depth sweeps, asymmetric negative-sequence cases, and recovery
segments.  The dynamics remain a fast averaged proxy; the switch-level Simulink
models are still the source of record.  The energy action is intentionally a
normalized dq current-reference command; the Simulink switch-level controller
turns it into TPFBVSC PWM modulation through a physical current loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable

import gymnasium as gym
import joblib
import numpy as np
from gymnasium import spaces


OBS_DIM_HPT = 24
ACT_DIM_HPT = 4
DEFAULT_PROXY_CALIBRATION = Path(__file__).with_name("hpt_proxy_calibration.json")


@dataclass(frozen=True)
class HPTVoltageScenario:
    """One averaged HPT voltage/FRT scenario.

    ``grid_pu`` is the disturbed source voltage during the fault window.  The
    default ``fault_start_s=0`` preserves the old steady sag/swell behavior for
    small unit tests and hand-constructed scenarios.
    """

    topology: str
    grid_pu: float
    neg_seq_pu: float = 0.0
    duration_s: float = 0.20
    load_pu: float = 1.0
    category: str = "steady"
    fault_type: str = "steady"
    pre_fault_pu: float = 1.0
    post_fault_pu: float = 1.0
    fault_start_s: float = 0.0
    fault_duration_s: float | None = None
    recovery_tau_s: float = 0.05
    scr: float = 3.0
    xr_ratio: float = 3.0


@dataclass(frozen=True)
class HPTVoltageEnvConfig:
    """Tunable surrogate parameters."""

    dt: float = 2e-3
    v_ref_phase_rms: float = 207.0
    vdc_ref: float = 800.0
    reg_limit: float = 0.80
    energy_limit: float = 0.95
    v_tau: float = 0.012
    vdc_tau: float = 0.018
    use_switch_calibration: bool = True
    calibration_path: str = str(DEFAULT_PROXY_CALIBRATION)
    source_gain_topology1: float = 1.0
    source_bias_topology1: float = 0.0
    source_gain_topology2: float = 1.0
    source_bias_topology2: float = 0.0
    reg_gain_topology1: float = 0.33
    reg_gain_topology2: float = 0.27
    vdc_base_pu_topology1: float = 1.0
    vdc_base_pu_topology2: float = 1.0
    energy_q_gain: float = 0.04
    energy_d_gain: float = 0.10
    reg_dc_cost: float = 0.23
    energy_q_dc_cost: float = 0.04
    energy_d_dc_gain: float = 0.15
    load_dc_cost: float = 0.025
    action_slew_weight: float = 0.03
    sag_entry: float = 0.92
    sag_exit: float = 0.97
    swell_entry: float = 1.08
    swell_exit: float = 1.03
    neg_seq_entry: float = 0.04
    neg_seq_exit: float = 0.025
    recovery_hold_s: float = 0.08
    fault_time_norm_s: float = 0.50
    recovery_time_norm_s: float = 0.50
    derivative_norm: float = 50.0
    dynamic_reg_limit_topology1: float = 0.80
    dynamic_reg_limit_topology2: float = 0.60
    topology2_dynamic_soft_reg_limit: float = 0.25
    topology2_dynamic_stress_weight: float = 35.0
    topology2_dynamic_slew_weight: float = 8.0
    safety_classifier_path: str = ""
    safety_penalty_weight: float = 8.0
    safety_unsafe_terminal: bool = False
    teacher_prior_weight: float = 0.0


@lru_cache(maxsize=4)
def _load_proxy_calibration(path: str) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "hpt_proxy_calibration_v1":
        return {}
    return data


@lru_cache(maxsize=4)
def _load_safety_classifier(path: str) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = joblib.load(p)
    if data.get("schema") != "hpt-safety-classifier-v1":
        return {}
    return data


def classify_hpt_operating_condition(
    v_pos_pu: float,
    v_neg_pu: float,
    *,
    grid_pu: float | None = None,
    config: HPTVoltageEnvConfig | None = None,
) -> str:
    """Online-friendly HPT condition classifier used by the proxy.

    The classifier uses measured positive/negative sequence voltage and, in
    the proxy only, the known source-voltage profile.  The deployed Simulink
    controller still uses measured voltage features only.
    """

    cfg = config or HPTVoltageEnvConfig()
    if v_neg_pu > cfg.neg_seq_entry:
        if grid_pu is not None and grid_pu > cfg.swell_entry:
            return "asymmetric_swell"
        return "asymmetric_sag"
    probe = float(grid_pu) if grid_pu is not None else float(v_pos_pu)
    if probe < cfg.sag_entry:
        return "sag"
    if probe > cfg.swell_entry:
        return "swell"
    return "nominal"


def _interp_response_table(
    table: list[dict],
    grid_pu: float,
    reg_d: float,
    value_key: str,
) -> float | None:
    if not table:
        return None

    grids = sorted({float(row["grid_pu"]) for row in table})
    values_by_grid: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            x = float(row["reg_d_mean"])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            return None
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        values_by_grid.append(float(np.interp(float(reg_d), xs, ys)))

    return float(np.interp(float(grid_pu), np.asarray(grids, dtype=float), np.asarray(values_by_grid, dtype=float)))


def _interp_energy_axis(
    table: list[dict],
    grid_pu: float,
    action_value: float,
    axis_key: str,
    other_axis_key: str,
    value_key: str,
) -> float | None:
    if not table:
        return None

    grids = sorted({float(row["grid_pu"]) for row in table})
    values_by_grid: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            if abs(float(row[other_axis_key])) > 1e-6:
                continue
            x = float(row[axis_key])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            return None
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        values_by_grid.append(float(np.interp(float(action_value), xs, ys)))

    return float(np.interp(float(grid_pu), np.asarray(grids, dtype=float), np.asarray(values_by_grid, dtype=float)))


def _interp_energy_response(
    table: list[dict],
    grid_pu: float,
    energy_d: float,
    energy_q: float,
    value_key: str,
) -> float | None:
    baseline = _interp_energy_axis(
        table, grid_pu, 0.0, "energy_d_mean", "energy_q_mean", value_key
    )
    d_axis = _interp_energy_axis(
        table, grid_pu, energy_d, "energy_d_mean", "energy_q_mean", value_key
    )
    q_axis = _interp_energy_axis(
        table, grid_pu, energy_q, "energy_q_mean", "energy_d_mean", value_key
    )
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def _interp_axes(rows: list[dict], axis_keys: list[str], axis_values: list[float], value_key: str) -> float | None:
    if not rows:
        return None
    if not axis_keys:
        vals = [float(row[value_key]) for row in rows if value_key in row]
        if not vals:
            return None
        return float(np.mean(vals))

    axis_key = axis_keys[0]
    target = float(axis_values[0])
    bucket: dict[float, list[dict]] = {}
    for row in rows:
        if axis_key not in row:
            continue
        bucket.setdefault(float(row[axis_key]), []).append(row)
    if not bucket:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for x in sorted(bucket):
        value = _interp_axes(bucket[x], axis_keys[1:], axis_values[1:], value_key)
        if value is None:
            continue
        xs.append(float(x))
        ys.append(float(value))
    if not xs:
        return None
    return float(np.interp(target, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))


def _interp_grid_axes_table(
    table: list[dict],
    grid_pu: float,
    axis_keys: list[str],
    axis_values: list[float],
    value_key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({float(row["grid_pu"]) for row in table if "grid_pu" in row})
    if not grids:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for grid in grids:
        rows = [row for row in table if abs(float(row["grid_pu"]) - grid) <= 1e-9]
        value = _interp_axes(rows, axis_keys, axis_values, value_key)
        if value is None:
            continue
        xs.append(float(grid))
        ys.append(float(value))
    if not xs:
        return None
    return float(np.interp(float(grid_pu), np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))


def _neg_seq_for_fault(fault_type: str, target: float) -> float:
    depth = abs(1.0 - target)
    if fault_type in {"1ph_g", "swell_1ph"}:
        return min(0.18, 0.33 * depth)
    if fault_type == "2ph":
        return min(0.14, 0.25 * depth)
    if fault_type == "2ph_g":
        return min(0.16, 0.28 * depth)
    return 0.0


def default_hpt_voltage_scenarios() -> list[HPTVoltageScenario]:
    """Return a mixed topology/FRT curriculum inspired by the main FRT SAC.

    Coverage includes steady regulation, LVRT residual-voltage bins, HVRT swell
    bins, asymmetric negative-sequence cases, weak/strong grid proxies, and
    short/long fault durations.
    """

    scenarios: list[HPTVoltageScenario] = []
    lvrt_types = ("sym3ph", "1ph_g", "2ph", "2ph_g")
    hvrt_types = ("swell_3ph", "swell_1ph")
    lvrt_residuals = (0.20, 0.50, 0.75, 0.85, 0.90)
    hvrt_levels = (1.10, 1.20, 1.25, 1.30)
    durations = (0.12, 0.25)
    grid_strengths = (("weak", 3.0, 1.08), ("strong", 10.0, 0.92))

    for topology in ("topology1", "topology2"):
        for grid_pu in (0.90, 1.00, 1.10):
            scenarios.append(
                HPTVoltageScenario(
                    topology=topology,
                    grid_pu=grid_pu,
                    duration_s=0.22,
                    category="steady",
                    fault_type="steady",
                )
            )

        for fault_type in lvrt_types:
            for target in lvrt_residuals:
                for duration in durations:
                    for _grid_name, scr, load_pu in grid_strengths:
                        scenarios.append(
                            HPTVoltageScenario(
                                topology=topology,
                                grid_pu=target,
                                neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                                duration_s=0.08 + duration + 0.16,
                                load_pu=load_pu,
                                category="LVRT",
                                fault_type=fault_type,
                                fault_start_s=0.04,
                                fault_duration_s=duration,
                                scr=scr,
                            )
                        )

        for fault_type in hvrt_types:
            for target in hvrt_levels:
                for duration in durations:
                    for _grid_name, scr, load_pu in grid_strengths:
                        scenarios.append(
                            HPTVoltageScenario(
                                topology=topology,
                                grid_pu=target,
                                neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                                duration_s=0.08 + duration + 0.16,
                                load_pu=load_pu,
                                category="HVRT",
                                fault_type=fault_type,
                                fault_start_s=0.04,
                                fault_duration_s=duration,
                                scr=scr,
                            )
                        )
    return scenarios


class HPTOnlineFaultDetector:
    """Online detector using only measured sequence voltage and local time."""

    def __init__(self, cfg: HPTVoltageEnvConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.fault_active = False
        self.recovery_active = False
        self.onset_t = 0.0
        self.clear_t = 0.0
        self.v_fault_min = 1.0
        self.v_fault_max = 1.0
        self.prev_v_pos: float | None = None
        self.prev_vdc: float | None = None
        self.dv_pos_dt = 0.0
        self.d_vdc_dt = 0.0

    def update(self, t: float, v_pos: float, v_neg: float, vdc: float, dt: float) -> None:
        cfg = self.cfg
        if self.prev_v_pos is None:
            self.dv_pos_dt = 0.0
            self.d_vdc_dt = 0.0
        else:
            self.dv_pos_dt = (v_pos - self.prev_v_pos) / max(dt, 1e-9)
            self.d_vdc_dt = (vdc - self.prev_vdc) / max(dt, 1e-9)
        self.prev_v_pos = float(v_pos)
        self.prev_vdc = float(vdc)

        measured_fault = (
            v_pos < cfg.sag_entry or v_pos > cfg.swell_entry or v_neg > cfg.neg_seq_entry
        )
        normal_band = (
            cfg.sag_exit <= v_pos <= cfg.swell_exit and v_neg <= cfg.neg_seq_exit
        )

        if measured_fault:
            if not self.fault_active:
                self.onset_t = float(t)
                self.v_fault_min = float(v_pos)
                self.v_fault_max = float(v_pos)
            self.fault_active = True
            self.recovery_active = False
            self.v_fault_min = min(self.v_fault_min, float(v_pos))
            self.v_fault_max = max(self.v_fault_max, float(v_pos))
            return

        if self.fault_active:
            self.fault_active = False
            self.recovery_active = True
            self.clear_t = float(t)
            return

        if self.recovery_active and normal_band and (t - self.clear_t) >= cfg.recovery_hold_s:
            self.recovery_active = False
            self.v_fault_min = 1.0
            self.v_fault_max = 1.0

    def features(self, t: float) -> tuple[float, float, float, float, float, float, float, float]:
        cfg = self.cfg
        t_fault = (t - self.onset_t) if self.fault_active else 0.0
        t_recovery = (t - self.clear_t) if self.recovery_active else 0.0
        return (
            float(self.fault_active),
            float(self.recovery_active),
            min(1.0, max(0.0, t_fault / max(cfg.fault_time_norm_s, 1e-9))),
            min(1.0, max(0.0, t_recovery / max(cfg.recovery_time_norm_s, 1e-9))),
            self.v_fault_min,
            self.v_fault_max,
            self.dv_pos_dt / max(cfg.derivative_norm, 1e-9),
            self.d_vdc_dt / max(cfg.derivative_norm, 1e-9),
        )


class HPTVoltageSACEnv(gym.Env):
    """Fast averaged HPT voltage-regulation and transition environment."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        scenarios: Iterable[HPTVoltageScenario] | None = None,
        *,
        config: HPTVoltageEnvConfig | None = None,
        seed: int = 0,
        train_mode: bool = True,
    ) -> None:
        super().__init__()
        self.config = config or HPTVoltageEnvConfig()
        self._calibration = (
            _load_proxy_calibration(self.config.calibration_path)
            if self.config.use_switch_calibration
            else {}
        )
        self._safety_classifier = _load_safety_classifier(self.config.safety_classifier_path)
        self.scenarios = list(scenarios or default_hpt_voltage_scenarios())
        if not self.scenarios:
            raise ValueError("HPTVoltageSACEnv requires at least one scenario")
        self.rng = np.random.default_rng(seed)
        self.train_mode = train_mode
        low = np.array(
            [
                -self.config.reg_limit,
                -self.config.reg_limit,
                -self.config.energy_limit,
                -self.config.energy_limit,
            ],
            dtype=np.float32,
        )
        high = -low
        self.action_space = spaces.Box(low=low, high=high, dtype=np.float32)
        self.observation_space = spaces.Box(-5.0, 5.0, shape=(OBS_DIM_HPT,), dtype=np.float32)
        self._scenario_index = 0
        self._sc = self.scenarios[0]
        self._last_action = np.zeros(ACT_DIM_HPT, dtype=np.float32)
        self._detector = HPTOnlineFaultDetector(self.config)
        self._reset_states()

    def _reset_states(self) -> None:
        self.t = 0.0
        self.v_lv = 1.0
        self.v_pos = 1.0
        self.v_neg = 0.0
        self.vdc = 1.0
        self.energy_id = 0.0
        self.energy_iq = 0.0
        self._detector.reset()

    def reset(self, *, seed: int | None = None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if self.train_mode:
            self._sc = self.scenarios[int(self.rng.integers(0, len(self.scenarios)))]
        else:
            self._sc = self.scenarios[self._scenario_index % len(self.scenarios)]
            self._scenario_index += 1
        self._last_action = np.zeros(ACT_DIM_HPT, dtype=np.float32)
        self._reset_states()
        grid_now, neg_now = self._grid_profile(self.t)
        if float(self._sc.fault_start_s) > 0.0:
            self.v_lv = float(self._sc.pre_fault_pu)
        else:
            calibrated_lv = self._calibrated_lv_target(grid_now, 0.0)
            self.v_lv = calibrated_lv if calibrated_lv is not None else self._source_base_voltage(grid_now)
        self.v_pos = self.v_lv
        self.v_neg = neg_now
        self._detector.update(self.t, grid_now, neg_now, self.vdc, self.config.dt)
        return self._obs(), {}

    def _fault_duration(self) -> float:
        if self._sc.fault_duration_s is not None:
            return float(self._sc.fault_duration_s)
        return max(0.0, float(self._sc.duration_s) - float(self._sc.fault_start_s))

    def _grid_profile(self, t: float) -> tuple[float, float]:
        sc = self._sc
        start = float(sc.fault_start_s)
        end = start + self._fault_duration()
        if t < start:
            return float(sc.pre_fault_pu), 0.0
        if t <= end:
            return float(sc.grid_pu), float(sc.neg_seq_pu)

        tau = max(float(sc.recovery_tau_s), 1e-9)
        w = 1.0 - float(np.exp(-(t - end) / tau))
        grid = float(sc.grid_pu) + (float(sc.post_fault_pu) - float(sc.grid_pu)) * w
        neg = float(sc.neg_seq_pu) * float(np.exp(-(t - end) / tau))
        return grid, neg

    def _reg_gain(self) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal["reg_gain"])
        if self._topology_name() == "topology2":
            return self.config.reg_gain_topology2
        return self.config.reg_gain_topology1

    def _topology_name(self) -> str:
        return self._sc.topology.lower()

    def _topology_calibration(self) -> dict:
        topologies = self._calibration.get("topologies", {})
        return dict(topologies.get(self._topology_name(), {}))

    def _source_base_voltage(self, grid_pu: float) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal["source_gain"]) * float(grid_pu) + float(cal["source_bias"])
        if self._topology_name() == "topology2":
            return self.config.source_gain_topology2 * float(grid_pu) + self.config.source_bias_topology2
        return self.config.source_gain_topology1 * float(grid_pu) + self.config.source_bias_topology1

    def _vdc_base_pu(self) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal.get("vdc_base_pu", 1.0))
        if self._topology_name() == "topology2":
            return self.config.vdc_base_pu_topology2
        return self.config.vdc_base_pu_topology1

    def _reg_dc_cost(self) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal.get("vdc_reg_abs_cost", self.config.reg_dc_cost))
        return self.config.reg_dc_cost

    def _calibrated_lv_target(self, grid_pu: float, reg_d: float, reg_q: float = 0.0) -> float | None:
        cal = self._topology_calibration()
        table: list[dict] = []
        if cal:
            if self._sc.category != "steady":
                reg_table = cal.get("fault_reg_response_table", [])
                value = _interp_grid_axes_table(
                    reg_table,
                    grid_pu,
                    ["reg_d_mean", "reg_q_mean"],
                    [reg_d, reg_q],
                    "lv_pu_mean",
                )
                if value is not None:
                    return value
                table = cal.get("fault_response_table", [])
            if not table:
                table = cal.get("response_table", [])
        return _interp_response_table(table, grid_pu, reg_d, "lv_pu_mean")

    def _calibrated_vdc_target(self, grid_pu: float, reg_d: float, reg_q: float = 0.0) -> float | None:
        cal = self._topology_calibration()
        table: list[dict] = []
        if cal:
            if self._sc.category != "steady":
                reg_table = cal.get("fault_reg_response_table", [])
                value = _interp_grid_axes_table(
                    reg_table,
                    grid_pu,
                    ["reg_d_mean", "reg_q_mean"],
                    [reg_d, reg_q],
                    "vdc_pu_mean",
                )
                if value is not None:
                    return value
                table = cal.get("fault_response_table", [])
            if not table:
                table = cal.get("response_table", [])
        return _interp_response_table(table, grid_pu, reg_d, "vdc_pu_mean")

    def _calibrated_joint_target(
        self,
        grid_pu: float,
        reg_d: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        cal = self._topology_calibration()
        if not cal or self._sc.category == "steady":
            return None
        return _interp_grid_axes_table(
            cal.get("fault_joint_response_table", []),
            grid_pu,
            ["reg_d_mean", "energy_d_mean", "energy_q_mean"],
            [reg_d, energy_d, energy_q],
            value_key,
        )

    def _calibrated_energy_target(
        self,
        grid_pu: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        cal = self._topology_calibration()
        table = []
        if cal:
            if self._sc.category != "steady":
                table = cal.get("fault_energy_response_table", [])
            if not table:
                table = cal.get("energy_response_table", [])
        return _interp_energy_response(table, grid_pu, energy_d, energy_q, value_key)

    def _obs(self) -> np.ndarray:
        cfg = self.config
        v_err = 1.0 - self.v_lv
        vdc_err = 1.0 - self.vdc
        topology1_flag = 1.0 if self._topology_name() == "topology1" else 0.0
        topology2_flag = 1.0 if self._topology_name() == "topology2" else 0.0
        obs = np.array(
            [
                self.v_lv,
                self.v_pos,
                self.v_neg,
                self.vdc,
                vdc_err,
                v_err,
                self.energy_id,
                self.energy_iq,
                *self._last_action,
                float(self.v_pos < cfg.sag_entry),
                float(self.v_pos > cfg.swell_entry),
                topology1_flag,
                topology2_flag,
                *self._detector.features(self.t),
            ],
            dtype=np.float32,
        )
        assert obs.shape == (OBS_DIM_HPT,), obs.shape
        return np.clip(obs, -5.0, 5.0)

    def _table_teacher_action(self, grid_pu: float) -> np.ndarray:
        """Best supported regulation command from the calibrated switch sweep.

        The table is intentionally based on switch-level fixed-action data, not
        on the learned/SAC proxy.  It gives SAC a local action prior while still
        allowing the actor to learn deviations when the reward supports them.
        """

        candidates = np.linspace(-self.config.reg_limit, self.config.reg_limit, 81)
        best_score = float("inf")
        best_reg_d = 0.0
        if self._topology_name() == "topology2":
            lv_low, lv_high = 198.0 / 207.0, 212.0 / 207.0
            vdc_low, vdc_high = 760.0 / 800.0, 930.0 / 800.0
        else:
            lv_low, lv_high = 200.0 / 207.0, 210.0 / 207.0
            vdc_low, vdc_high = 760.0 / 800.0, 920.0 / 800.0

        for raw_reg_d in candidates:
            projected = self._project_action(
                np.asarray([raw_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)
            )
            reg_d = float(projected[0])
            lv_target = self._calibrated_lv_target(grid_pu, reg_d)
            vdc_target = self._calibrated_vdc_target(grid_pu, reg_d)
            if lv_target is None:
                continue
            vdc_target = 1.0 if vdc_target is None else float(vdc_target)
            lv_penalty = max(0.0, lv_low - float(lv_target)) ** 2
            lv_penalty += max(0.0, float(lv_target) - lv_high) ** 2
            vdc_penalty = max(0.0, vdc_low - vdc_target) ** 2
            vdc_penalty += max(0.0, vdc_target - vdc_high) ** 2
            tracking_bias = 0.05 * abs(float(lv_target) - 1.0)
            dc_bias = 0.03 * abs(vdc_target - 1.0)
            action_penalty = 0.003 * abs(reg_d)
            score = 35.0 * lv_penalty + 30.0 * vdc_penalty + tracking_bias + dc_bias + action_penalty
            if score < best_score:
                best_score = score
                best_reg_d = reg_d

        if not np.isfinite(best_score):
            fallback = teacher_action(
                self._obs(),
                reg_limit=self.config.reg_limit,
                energy_limit=self.config.energy_limit,
            )
            return fallback.astype(np.float32)

        return np.asarray([best_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    def _project_action(self, action: np.ndarray) -> np.ndarray:
        projected = np.asarray(action, dtype=np.float32).copy()
        cfg = self.config
        if (self.v_pos < cfg.sag_entry or self.v_lv < 0.98) and projected[0] < 0.0:
            projected[0] = 0.0
        elif self.v_pos > cfg.swell_entry and projected[0] > 0.0:
            projected[0] = 0.0

        if self.vdc < 0.95:
            projected[0] *= np.clip((self.vdc - 0.75) / 0.20, 0.0, 1.0)
            projected[2] = max(projected[2], min(cfg.energy_limit, 0.20 + 1.2 * (0.82 - self.vdc)))
        elif self.vdc > 1.12:
            projected[2] = min(projected[2], -0.05)
        dynamic_fault = (
            float(self._sc.fault_start_s) > 0.02
            and (self._detector.fault_active or self._detector.recovery_active)
        )
        if dynamic_fault:
            dyn_limit = (
                cfg.dynamic_reg_limit_topology2
                if self._topology_name() == "topology2"
                else cfg.dynamic_reg_limit_topology1
            )
            projected[0] = float(np.clip(projected[0], -dyn_limit, dyn_limit))
        return projected

    def _safety_feature(
        self,
        *,
        grid_pu: float,
        raw_action: np.ndarray,
        projected_action: np.ndarray,
        sweep: str,
    ) -> np.ndarray:
        names = list(self._safety_classifier.get("feature_names", []))
        values = {
            "topology1": 1.0 if self._topology_name() == "topology1" else 0.0,
            "topology2": 1.0 if self._topology_name() == "topology2" else 0.0,
            "grid_pu": float(grid_pu),
            "raw_m_reg_d": float(raw_action[0]),
            "raw_m_reg_q": float(raw_action[1]),
            "raw_m_energy_d": float(raw_action[2]),
            "raw_m_energy_q": float(raw_action[3]),
            "effective_m_reg_d": float(projected_action[0]),
            "effective_m_reg_q": float(projected_action[1]),
            "effective_m_energy_d": float(projected_action[2]),
            "effective_m_energy_q": float(projected_action[3]),
            "controller_enabled": 1.0,
            "is_reg_sweep": 1.0 if sweep == "reg" else 0.0,
            "is_energy_sweep": 1.0 if sweep == "energy" else 0.0,
            "is_fault_sweep": 1.0 if sweep == "fault" else 0.0,
        }
        return np.asarray([values.get(name, 0.0) for name in names], dtype=np.float32).reshape(1, -1)

    def _safety_score(
        self,
        *,
        grid_pu: float,
        raw_action: np.ndarray,
        projected_action: np.ndarray,
        fault_or_recovery: float,
    ) -> tuple[float, float, bool]:
        if not self._safety_classifier:
            return 1.0, 0.0, False
        clf = self._safety_classifier["classifier"]
        threshold = float(self._safety_classifier.get("safe_probability_threshold", 0.75))
        reg_mag = float(np.hypot(projected_action[0], projected_action[1]))
        energy_mag = float(np.hypot(projected_action[2], projected_action[3]))
        sweeps = ["fault"] if fault_or_recovery > 0.5 else ["reg"]
        if energy_mag > 0.05 or energy_mag >= reg_mag:
            sweeps.append("energy")
        probs = []
        for sweep in dict.fromkeys(sweeps):
            feature = self._safety_feature(
                grid_pu=grid_pu,
                raw_action=raw_action,
                projected_action=projected_action,
                sweep=sweep,
            )
            probs.append(float(clf.predict_proba(feature)[0, 1]))
        safe_probability = min(probs) if probs else 1.0
        return safe_probability, threshold, bool(safe_probability < threshold)

    def step(self, action):
        cfg = self.config
        raw_action = np.asarray(action, dtype=np.float32)
        raw_action = np.clip(raw_action, self.action_space.low, self.action_space.high)
        action = self._project_action(raw_action)
        m_reg_d, m_reg_q, m_energy_d, m_energy_q = [float(v) for v in action]

        grid_now, neg_now = self._grid_profile(self.t)
        calibrated_lv = self._calibrated_lv_target(grid_now, m_reg_d, m_reg_q)
        load_drop = 0.010 * max(0.0, float(self._sc.load_pu) - 1.0)
        if calibrated_lv is None:
            base_lv = self._source_base_voltage(grid_now)
            reg_effect = self._reg_gain() * m_reg_d
            q_effect = 0.0 if self._calibration else cfg.energy_q_gain * m_energy_q
            calibrated_lv = base_lv + reg_effect + q_effect
        joint_lv = self._calibrated_joint_target(
            grid_now, m_reg_d, m_energy_d, m_energy_q, "lv_pu_mean"
        )
        joint_lv_zero = self._calibrated_joint_target(
            grid_now, m_reg_d, 0.0, 0.0, "lv_pu_mean"
        )
        if joint_lv is not None and abs(m_reg_q) <= 1e-6:
            calibrated_lv = joint_lv
        elif joint_lv is not None and joint_lv_zero is not None:
            calibrated_lv += joint_lv - joint_lv_zero
        else:
            energy_lv = self._calibrated_energy_target(grid_now, m_energy_d, m_energy_q, "lv_pu_mean")
            energy_lv_zero = self._calibrated_energy_target(grid_now, 0.0, 0.0, "lv_pu_mean")
            if energy_lv is not None and energy_lv_zero is not None:
                calibrated_lv += energy_lv - energy_lv_zero
        v_target = max(0.0, calibrated_lv - load_drop)
        self.v_lv += (v_target - self.v_lv) * (cfg.dt / cfg.v_tau)
        self.v_pos = max(0.0, self.v_lv)
        self.v_neg += (neg_now + 0.02 * abs(m_reg_q) - self.v_neg) * (cfg.dt / cfg.v_tau)

        calibrated_i = self._calibrated_energy_target(
            grid_now, m_energy_d, m_energy_q, "energy_i_rms_mean"
        )
        if calibrated_i is None:
            energy_direct_scale = 0.0 if self._calibration else 1.0
            target_energy_id = energy_direct_scale * cfg.energy_d_gain * m_energy_d
            target_energy_iq = energy_direct_scale * cfg.energy_q_gain * m_energy_q
        else:
            current_scale = 200.0
            target_energy_id = np.sign(m_energy_d) * min(2.0, abs(calibrated_i) / current_scale)
            target_energy_iq = np.sign(m_energy_q) * min(2.0, abs(calibrated_i) / current_scale)
        self.energy_id += (target_energy_id - self.energy_id) * 0.25
        self.energy_iq += (target_energy_iq - self.energy_iq) * 0.25
        calibrated_vdc = self._calibrated_vdc_target(grid_now, m_reg_d, m_reg_q)
        if calibrated_vdc is None:
            calibrated_vdc = (
                self._vdc_base_pu()
                - self._reg_dc_cost() * max(0.0, abs(m_reg_d))
                - 0.04 * max(0.0, 1.0 - grid_now)
            )
        joint_vdc = self._calibrated_joint_target(
            grid_now, m_reg_d, m_energy_d, m_energy_q, "vdc_pu_mean"
        )
        joint_vdc_zero = self._calibrated_joint_target(
            grid_now, m_reg_d, 0.0, 0.0, "vdc_pu_mean"
        )
        if joint_vdc is not None and abs(m_reg_q) <= 1e-6:
            energy_direct_scale = 0.0
            energy_vdc_delta = joint_vdc - calibrated_vdc
        elif joint_vdc is not None and joint_vdc_zero is not None:
            energy_direct_scale = 0.0
            energy_vdc_delta = joint_vdc - joint_vdc_zero
        else:
            energy_vdc = self._calibrated_energy_target(grid_now, m_energy_d, m_energy_q, "vdc_pu_mean")
            energy_vdc_zero = self._calibrated_energy_target(grid_now, 0.0, 0.0, "vdc_pu_mean")
            if energy_vdc is not None and energy_vdc_zero is not None:
                energy_direct_scale = 0.0
                energy_vdc_delta = energy_vdc - energy_vdc_zero
            else:
                energy_direct_scale = 0.0 if self._calibration else 1.0
                energy_vdc_delta = energy_direct_scale * cfg.energy_d_dc_gain * m_energy_d
        vdc_target = (
            calibrated_vdc
            + energy_vdc_delta
            - energy_direct_scale * cfg.energy_q_dc_cost * abs(m_energy_q)
            - cfg.load_dc_cost * max(0.0, float(self._sc.load_pu) - 1.0)
        )
        self.vdc += (vdc_target - self.vdc) * (cfg.dt / cfg.vdc_tau)
        self.vdc = float(np.clip(self.vdc, 0.05, 1.30))

        self.t += cfg.dt
        detector_grid, detector_neg = self._grid_profile(self.t)
        self._detector.update(self.t, detector_grid, detector_neg, self.vdc, cfg.dt)

        voltage_err = self.v_lv - 1.0
        unbalance = self.v_neg
        vdc_low_limit = 0.95 if self._calibration else 0.82
        vdc_soft = max(0.0, vdc_low_limit - self.vdc) + max(0.0, self.vdc - 1.12)
        reg_mag = float(np.hypot(m_reg_d, m_reg_q))
        energy_mag = float(np.hypot(m_energy_d, m_energy_q))
        energy_weight = 0.60 if self._calibration else 0.08
        slew = float(np.linalg.norm(action - self._last_action))
        fault_or_recovery = float(self._detector.fault_active or self._detector.recovery_active)
        teacher_prior = self._table_teacher_action(grid_now)
        teacher_gap = float((m_reg_d - teacher_prior[0]) ** 2) if cfg.teacher_prior_weight > 0.0 else 0.0
        safe_probability, safety_threshold, safety_unsafe = self._safety_score(
            grid_pu=grid_now,
            raw_action=raw_action,
            projected_action=action,
            fault_or_recovery=fault_or_recovery,
        )
        safety_gap = max(0.0, safety_threshold - safe_probability)
        wrong_sign = float(
            (self.v_pos < cfg.sag_entry and m_reg_d < -1e-4)
            or (self.v_pos > cfg.swell_entry and m_reg_d > 1e-4)
        )
        topology2_dynamic = float(self._topology_name() == "topology2" and fault_or_recovery > 0.5)
        topology2_reg_excess = max(0.0, abs(m_reg_d) - cfg.topology2_dynamic_soft_reg_limit)
        topology2_dynamic_stress = topology2_dynamic * (
            cfg.topology2_dynamic_stress_weight * topology2_reg_excess * topology2_reg_excess
            + cfg.topology2_dynamic_slew_weight * slew * slew
            + 2.0 * abs(m_reg_q)
        )
        reward = (
            -(90.0 + 35.0 * fault_or_recovery) * voltage_err * voltage_err
            -45.0 * unbalance * unbalance
            -55.0 * vdc_soft * vdc_soft
            -8.0 * wrong_sign
            -topology2_dynamic_stress
            -0.20 * reg_mag * reg_mag
            -energy_weight * energy_mag * energy_mag
            -cfg.action_slew_weight * slew * slew
            -cfg.safety_penalty_weight * safety_gap * safety_gap
            -cfg.teacher_prior_weight * teacher_gap
            + 1.0
        )
        if 0.98 <= self.v_lv <= 1.02 and 0.85 <= self.vdc <= 1.10:
            reward += 1.0
        if self._detector.recovery_active and 0.97 <= self.v_lv <= 1.03:
            reward += 0.5

        self._last_action = action.copy()
        terminated = bool(self.vdc < 0.65 or self.vdc > 1.25 or self.v_lv < 0.45 or self.v_lv > 1.40)
        if cfg.safety_unsafe_terminal and safety_unsafe:
            terminated = True
        truncated = bool(self.t >= float(self._sc.duration_s))
        info = {
            "topology": self._sc.topology,
            "category": self._sc.category,
            "fault_type": self._sc.fault_type,
            "grid_pu": grid_now,
            "v_lv_pu": self.v_lv,
            "vdc_pu": self.vdc,
            "v_neg_pu": self.v_neg,
            "condition": classify_hpt_operating_condition(
                self.v_pos, self.v_neg, grid_pu=grid_now, config=cfg
            ),
            "uses_switch_calibration": bool(self._calibration),
            "fault_active_est": self._detector.fault_active,
            "recovery_active_est": self._detector.recovery_active,
            "safety_safe_probability": safe_probability,
            "safety_threshold": safety_threshold,
            "safety_unsafe": safety_unsafe,
            "teacher_m_reg_d": float(teacher_prior[0]),
            "action": action.copy(),
        }
        return self._obs(), float(reward), terminated, truncated, info


def teacher_action(obs: np.ndarray, *, reg_limit: float = 0.80, energy_limit: float = 0.95) -> np.ndarray:
    """Rule-based bootstrap action using the same SAC action contract."""

    obs = np.asarray(obs, dtype=np.float32)
    vpu = float(obs[0])
    vpos = float(obs[1])
    v_err = float(obs[5])
    vdc_err = float(obs[4])
    vneg = float(obs[2])
    fault_active = float(obs[16]) if obs.size > 16 else float(vpos < 0.92 or vpos > 1.08)
    recovery_active = float(obs[17]) if obs.size > 17 else 0.0
    boost = 1.0 + 0.35 * fault_active + 0.15 * recovery_active

    m_reg_d = np.clip(2.2 * boost * v_err, -reg_limit, reg_limit)
    if vpos < 0.92 and m_reg_d < 0.0:
        m_reg_d = 0.0
    elif vpos > 1.08 and m_reg_d > 0.0:
        m_reg_d = 0.0

    m_reg_q = np.clip(-0.9 * vneg, -reg_limit, reg_limit)
    m_energy_d = np.clip(1.4 * vdc_err + 0.22 * abs(m_reg_d), -energy_limit, energy_limit)
    if vpu < 0.92:
        m_energy_d = max(m_energy_d, min(energy_limit, 0.10 + 0.25 * (0.92 - vpu)))
    m_energy_q = np.clip(0.25 * v_err - 0.35 * vneg, -energy_limit, energy_limit)
    return np.array([m_reg_d, m_reg_q, m_energy_d, m_energy_q], dtype=np.float32)


def execution_guard_teacher_action(
    obs: np.ndarray,
    *,
    reg_limit: float = 0.80,
    energy_limit: float = 0.95,
    dynamic_mode: bool = False,
    dynamic_reg_limit_topology1: float = 0.80,
    dynamic_reg_limit_topology2: float = 0.60,
) -> np.ndarray:
    """Teacher target copied from the guarded Simulink execution layer.

    This function exists only to create training labels.  Final switch-level
    promotion must run with the corresponding Simulink guard disabled.
    """

    obs = np.asarray(obs, dtype=np.float32)
    vpu = float(obs[0])
    vpos = float(obs[1])
    vdcpu = float(obs[3])
    topology1 = bool(obs.size > 14 and obs[14] > 0.5)
    topology2 = bool(obs.size > 15 and obs[15] > 0.5)

    if topology2 and dynamic_mode:
        dyn_lim = float(np.clip(dynamic_reg_limit_topology2, 0.0, reg_limit))
        m_reg_d = float(np.clip(20.0 * (1.0 - vpu), -dyn_lim, dyn_lim))
        return np.asarray([m_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    if topology1 and not dynamic_mode:
        m_reg_d = 0.32 + 2.35 * (1.0 - vpu)
        if vpu > 0.995:
            m_reg_d = 0.26
        m_reg_d = float(np.clip(m_reg_d, 0.22, 0.46))
        return np.asarray([m_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    action = teacher_action(obs, reg_limit=reg_limit, energy_limit=energy_limit)
    if vpos < 0.92 and action[0] < 0.0:
        action[0] = 0.0
    if vpos > 1.08 and action[0] > 0.0:
        action[0] = 0.0
    if vpu < 0.98 and action[0] < 0.0:
        action[0] = 0.0
    if vdcpu < 0.95:
        action[0] *= float(np.clip((vdcpu - 0.75) / 0.20, 0.0, 1.0))
        action[2] = max(action[2], min(energy_limit, 0.20 + 1.2 * (0.82 - vdcpu)))
    elif vdcpu > 1.12:
        action[2] = min(action[2], -0.05)
    if dynamic_mode:
        dyn_lim = dynamic_reg_limit_topology2 if topology2 else dynamic_reg_limit_topology1
        dyn_lim = float(np.clip(dyn_lim, 0.0, reg_limit))
        action[0] = float(np.clip(action[0], -dyn_lim, dyn_lim))
        action[1] = float(np.clip(action[1], -dyn_lim, dyn_lim))
    action[0] = float(np.clip(action[0], -reg_limit, reg_limit))
    action[1] = float(np.clip(action[1], -reg_limit, reg_limit))
    action[2] = float(np.clip(action[2], -energy_limit, energy_limit))
    action[3] = float(np.clip(action[3], -energy_limit, energy_limit))
    return action.astype(np.float32)
