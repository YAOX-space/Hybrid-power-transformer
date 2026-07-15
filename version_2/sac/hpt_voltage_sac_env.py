"""Topology-neutral SAC surrogate for HPT voltage regulation and FRT transitions.

This environment targets the final HPT switch-level models in
``version_2/simulink``.  It keeps the final 4-D modulation-action contract and
extends the observation from the early steady-regulation 16-D vector to a
fault-transition-aware 24-D vector:

    obs = [
        v_lv_rms_pu, v_pos_pu, v_neg_pu, vdc_pu, vdc_err_pu, v_err_pu,
        energy_id_pu, energy_iq_pu,
        last_m_reg_d, last_m_reg_q, last_m_energy_d, last_m_energy_q,
        sag_flag, swell_flag, reg_headroom, energy_headroom,
        fault_active_est, recovery_active_est, t_fault_est_pu, t_recovery_est_pu,
        v_fault_min_pu, v_fault_max_pu, dv_pos_dt_pu, d_vdc_dt_pu,
    ]

    act = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

The fault detector and scenario coverage are intentionally borrowed from the
older ``src/hpt_frt/device`` FRT SAC design: online measured-voltage detection,
LVRT/HVRT depth sweeps, asymmetric negative-sequence cases, and recovery
segments.  The dynamics remain a fast averaged proxy; the switch-level Simulink
models are still the source of record.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable

import gymnasium as gym
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
    dynamic_reg_limit_topology2: float = 0.605
    topology2_dynamic_soft_reg_limit: float = 0.25
    topology2_dynamic_stress_weight: float = 35.0
    topology2_dynamic_slew_weight: float = 8.0


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
    lvrt_residuals = (0.70, 0.85, 0.90)
    hvrt_levels = (1.10, 1.15, 1.20)
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
        self._detector.update(self.t, self.v_pos, self.v_neg, self.vdc, self.config.dt)
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

    def _calibrated_lv_target(self, grid_pu: float, reg_d: float) -> float | None:
        cal = self._topology_calibration()
        table = cal.get("response_table", []) if cal else []
        return _interp_response_table(table, grid_pu, reg_d, "lv_pu_mean")

    def _calibrated_vdc_target(self, grid_pu: float, reg_d: float) -> float | None:
        cal = self._topology_calibration()
        table = cal.get("response_table", []) if cal else []
        return _interp_response_table(table, grid_pu, reg_d, "vdc_pu_mean")

    def _calibrated_energy_target(
        self,
        grid_pu: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        cal = self._topology_calibration()
        table = cal.get("energy_response_table", []) if cal else []
        return _interp_energy_response(table, grid_pu, energy_d, energy_q, value_key)

    def _obs(self) -> np.ndarray:
        cfg = self.config
        v_err = 1.0 - self.v_lv
        vdc_err = 1.0 - self.vdc
        reg_mag = float(np.hypot(self._last_action[0], self._last_action[1]))
        energy_mag = float(np.hypot(self._last_action[2], self._last_action[3]))
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
                max(0.0, 1.0 - reg_mag / max(cfg.reg_limit, 1e-6)),
                max(0.0, 1.0 - energy_mag / max(cfg.energy_limit, 1e-6)),
                *self._detector.features(self.t),
            ],
            dtype=np.float32,
        )
        assert obs.shape == (OBS_DIM_HPT,), obs.shape
        return np.clip(obs, -5.0, 5.0)

    def _project_action(self, action: np.ndarray) -> np.ndarray:
        projected = np.asarray(action, dtype=np.float32).copy()
        cfg = self.config
        if (self.v_pos < cfg.sag_entry or self.v_lv < 0.98) and projected[0] < 0.0:
            projected[0] = 0.0
        elif (self.v_pos > cfg.swell_entry or self.v_lv > 1.00) and projected[0] > 0.0:
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

    def step(self, action):
        cfg = self.config
        action = np.asarray(action, dtype=np.float32)
        action = np.clip(action, self.action_space.low, self.action_space.high)
        action = self._project_action(action)
        m_reg_d, m_reg_q, m_energy_d, m_energy_q = [float(v) for v in action]

        grid_now, neg_now = self._grid_profile(self.t)
        calibrated_lv = self._calibrated_lv_target(grid_now, m_reg_d)
        load_drop = 0.010 * max(0.0, float(self._sc.load_pu) - 1.0)
        if calibrated_lv is None:
            base_lv = self._source_base_voltage(grid_now)
            reg_effect = self._reg_gain() * m_reg_d
            q_effect = 0.0 if self._calibration else cfg.energy_q_gain * m_energy_q
            calibrated_lv = base_lv + reg_effect + q_effect
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
        calibrated_vdc = self._calibrated_vdc_target(grid_now, m_reg_d)
        if calibrated_vdc is None:
            calibrated_vdc = (
                self._vdc_base_pu()
                - self._reg_dc_cost() * max(0.0, abs(m_reg_d))
                - 0.04 * max(0.0, 1.0 - grid_now)
            )
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
        self._detector.update(self.t, self.v_pos, self.v_neg, self.vdc, cfg.dt)

        voltage_err = self.v_lv - 1.0
        unbalance = self.v_neg
        vdc_low_limit = 0.95 if self._calibration else 0.82
        vdc_soft = max(0.0, vdc_low_limit - self.vdc) + max(0.0, self.vdc - 1.12)
        reg_mag = float(np.hypot(m_reg_d, m_reg_q))
        energy_mag = float(np.hypot(m_energy_d, m_energy_q))
        energy_weight = 0.60 if self._calibration else 0.08
        slew = float(np.linalg.norm(action - self._last_action))
        fault_or_recovery = float(self._detector.fault_active or self._detector.recovery_active)
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
            + 1.0
        )
        if 0.98 <= self.v_lv <= 1.02 and 0.85 <= self.vdc <= 1.10:
            reward += 1.0
        if self._detector.recovery_active and 0.97 <= self.v_lv <= 1.03:
            reward += 0.5

        self._last_action = action.copy()
        terminated = bool(self.vdc < 0.65 or self.vdc > 1.25 or self.v_lv < 0.45 or self.v_lv > 1.40)
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
