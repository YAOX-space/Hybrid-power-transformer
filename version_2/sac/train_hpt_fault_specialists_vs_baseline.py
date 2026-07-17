"""Train fault-specialist SAC actors and compare them with conventional DQ.

This runner is intentionally separated from the older case-specialist scripts.
It treats the latest switch-level conventional boundary sweep as the baseline
dataset, then trains one SAC actor per fault family, e.g.
``topology1/LVRT/80 ms``.  The first comparison is done in the calibrated
proxy environment using the same voltage-survival thresholds as the Simulink
FRT evaluator.  Actors that look promising here should be exported and checked
again in the switch-level Simulink model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from .experiment_metadata import write_experiment_metadata
from .hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)
from .pretrain_hpt_actor_bc import collect_teacher_samples, train_actor_bc
from hpt_frt.device.train_common import pick_device


RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"
SIMULINK_V2 = ROOT / "version_2" / "simulink"
TOPOLOGY_MODELS = {
    "topology1": SIMULINK_V2 / "topoloty1" / "hpt_v2_1to1_switchlevel.slx",
    "topology2": SIMULINK_V2 / "topology2" / "hpt_v2_topology2_paper.slx",
}


@dataclass(frozen=True)
class BaselineCase:
    row: dict[str, Any]

    @property
    def topology(self) -> str:
        return str(self.row["topology"])

    @property
    def case_name(self) -> str:
        return str(self.row["case_name"])

    @property
    def fault_pu(self) -> float:
        return float(self.row["fault_pu"])

    @property
    def duration_s(self) -> float:
        return float(self.row["fault_duration_s"])

    @property
    def duration_ms(self) -> int:
        return int(round(1000.0 * self.duration_s))

    @property
    def category(self) -> str:
        return "LVRT" if self.fault_pu < 1.0 else "HVRT"


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    topology: str
    category: str
    duration_s: float
    cases: tuple[BaselineCase, ...]

    @property
    def duration_ms(self) -> int:
        return int(round(1000.0 * self.duration_s))


@dataclass
class EvalMetrics:
    topology: str
    category: str
    duration_ms: int
    case_name: str
    fault_pu: float
    pass_flag: bool
    reason: str
    score: float
    lv_mean: float
    lv_recovery_mean: float
    lv_peak: float
    lv_min: float
    vdc_min: float
    vdc_max: float
    action_max_abs: float
    grid_iq_shortfall_max_pu: float
    grid_current_peak_pu: float
    grid_iq_wrong_sign: bool
    calibration_support_violation: float = 0.0
    calibrated_survival_violation: float = 0.0
    action_reg_d_mean: float = 0.0
    action_reg_q_mean: float = 0.0
    action_energy_d_mean: float = 0.0
    action_energy_q_mean: float = 0.0
    action_reg_d_abs_max: float = 0.0
    action_reg_q_abs_max: float = 0.0
    action_energy_d_abs_max: float = 0.0
    action_energy_q_abs_max: float = 0.0
    teacher_gap_mean: float = 0.0
    teacher_gap_max: float = 0.0


@dataclass
class SpecialistResult:
    spec: dict[str, Any]
    model_path: str
    train_steps: int
    train_elapsed_s: float
    bc_metrics: dict[str, Any] | None
    baseline_pass_n: int
    sac_proxy_pass_n: int
    beat_n: int
    improved_n: int
    case_results: list[dict[str, Any]]


def latest_boundary_csv(directory: Path = CONTROL_DIR) -> Path:
    files = sorted(
        (
            p
            for p in directory.glob("control_comparison_*conventional_boundary*.csv")
            if "_summary" not in p.stem
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise FileNotFoundError(f"No conventional boundary CSV found under {directory}")
    return files[-1]


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
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
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def b(row: dict[str, Any], key: str) -> bool:
    value = row.get(key, "")
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def finite(value: float, default: float = 0.0) -> float:
    return float(value) if math.isfinite(float(value)) else float(default)


def parse_action_weights(value: str) -> tuple[float, float, float, float]:
    parts = [float(item.strip()) for item in str(value).split(",") if item.strip()]
    if len(parts) != ACT_DIM_HPT:
        raise argparse.ArgumentTypeError("Expected four comma-separated action weights")
    return tuple(parts)  # type: ignore[return-value]


def parse_ent_coef(value: str) -> str | float:
    value = str(value).strip()
    if value.startswith("auto"):
        return value
    try:
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Expected ent_coef like auto, auto_0.1, or a float"
        ) from exc


def conventional_action_from_case(case: BaselineCase) -> np.ndarray:
    action = np.asarray(
        [
            f(case.row, "reg_d_mean", 0.0),
            f(case.row, "reg_q_mean", 0.0),
            f(case.row, "energy_d_mean", 0.0),
            f(case.row, "energy_q_mean", 0.0),
        ],
        dtype=np.float32,
    )
    return np.nan_to_num(action, nan=0.0, posinf=0.0, neginf=0.0)


def collect_conventional_teacher_samples(
    cases: tuple[BaselineCase, ...],
    config: HPTVoltageEnvConfig,
    *,
    episodes_per_case: int,
    noise_std: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    observations: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    if episodes_per_case <= 0:
        return (
            np.zeros((0, OBS_DIM_HPT), dtype=np.float32),
            np.zeros((0, ACT_DIM_HPT), dtype=np.float32),
        )

    action_low = np.asarray(
        [
            -config.reg_d_limit,
            -config.reg_q_limit,
            -config.energy_d_limit,
            -config.energy_q_limit,
        ],
        dtype=np.float32,
    )
    action_high = np.asarray(
        [
            config.reg_d_limit,
            config.reg_q_limit,
            config.energy_d_limit,
            config.energy_q_limit,
        ],
        dtype=np.float32,
    )
    for case in cases:
        scenario = scenario_from_case(case)
        target = np.clip(conventional_action_from_case(case), action_low, action_high)
        env = HPTVoltageSACEnv([scenario], config=config, seed=seed, train_mode=False)
        for _ in range(episodes_per_case):
            obs, _ = env.reset()
            done = False
            while not done:
                observations.append(np.asarray(obs, dtype=np.float32))
                targets.append(np.asarray(target, dtype=np.float32))
                noisy_action = target + rng.normal(0.0, noise_std, size=ACT_DIM_HPT).astype(np.float32)
                noisy_action = np.clip(noisy_action, action_low, action_high)
                obs, _, terminated, truncated, _ = env.step(noisy_action)
                done = bool(terminated or truncated)

    X = np.asarray(observations, dtype=np.float32)
    Y = np.asarray(targets, dtype=np.float32)
    if X.ndim != 2 or X.shape[1] != OBS_DIM_HPT:
        raise RuntimeError(f"Bad conventional teacher observation shape: {X.shape}")
    if Y.ndim != 2 or Y.shape[1] != ACT_DIM_HPT:
        raise RuntimeError(f"Bad conventional teacher action shape: {Y.shape}")
    return X, Y


def severity(case: BaselineCase) -> float:
    return 1.0 - case.fault_pu if case.fault_pu < 1.0 else case.fault_pu - 1.0


def select_baseline_cases(
    baseline_csv: Path,
    *,
    topology: str,
    category: str,
    duration_ms: int | None,
) -> list[BaselineCase]:
    cases = [
        BaselineCase(row)
        for row in read_csv_rows(baseline_csv)
        if str(row.get("mode", "")) == "conventional_dq"
        and str(row.get("scenario_type", "")) == "fault"
    ]
    if topology != "all":
        cases = [case for case in cases if case.topology == topology]
    if category != "all":
        cases = [case for case in cases if case.category == category]
    if duration_ms is not None:
        cases = [case for case in cases if case.duration_ms == duration_ms]
    return cases


def group_cases(cases: Iterable[BaselineCase]) -> dict[tuple[str, str, int], list[BaselineCase]]:
    groups: dict[tuple[str, str, int], list[BaselineCase]] = {}
    for case in cases:
        key = (case.topology, case.category, case.duration_ms)
        groups.setdefault(key, []).append(case)
    for key in groups:
        groups[key] = sorted(groups[key], key=severity)
    return dict(sorted(groups.items()))


def near_boundary_cases(cases: list[BaselineCase], pass_column: str) -> list[BaselineCase]:
    last_pass: BaselineCase | None = None
    first_fail_after_pass: BaselineCase | None = None
    for case in sorted(cases, key=severity):
        if b(case.row, pass_column):
            last_pass = case
            continue
        if last_pass is not None and first_fail_after_pass is None:
            first_fail_after_pass = case
            break
    if last_pass is not None and first_fail_after_pass is not None:
        return [last_pass, first_fail_after_pass]
    passing = [case for case in cases if b(case.row, pass_column)]
    failing = [case for case in cases if not b(case.row, pass_column)]
    if passing and failing:
        return [passing[-1], failing[0]]
    if failing:
        return [failing[0]]
    if passing:
        return [passing[-1]]
    return []


def build_specs(
    cases: list[BaselineCase],
    *,
    pass_column: str,
    selection: str,
    granularity: str,
    max_specialists: int,
) -> list[SpecialistSpec]:
    specs: list[SpecialistSpec] = []
    for (topology, category, duration_ms), group in group_cases(cases).items():
        selected = near_boundary_cases(group, pass_column) if selection == "near_boundary" else group
        if not selected:
            continue
        if granularity == "case":
            for case in selected:
                fault_tag = case.case_name.replace(".", "p")
                specs.append(
                    SpecialistSpec(
                        name=f"{topology}_{category.lower()}_{duration_ms}ms_{fault_tag}",
                        topology=topology,
                        category=category,
                        duration_s=case.duration_s,
                        cases=(case,),
                    )
                )
        else:
            specs.append(
                SpecialistSpec(
                    name=f"{topology}_{category.lower()}_{duration_ms}ms",
                    topology=topology,
                    category=category,
                    duration_s=selected[0].duration_s,
                    cases=tuple(selected),
                )
            )
    return specs[: max(0, max_specialists)]


def scenario_from_case(case: BaselineCase) -> HPTVoltageScenario:
    row = case.row
    fault_start = finite(f(row, "fault_start_s"), 0.035)
    fault_duration = finite(f(row, "fault_duration_s"), case.duration_s)
    stop_time = finite(f(row, "stop_time_s"), fault_start + fault_duration + 0.125)
    fault_type = "sym3ph" if case.category == "LVRT" else "swell_3ph"
    return HPTVoltageScenario(
        topology=case.topology,
        grid_pu=case.fault_pu,
        duration_s=stop_time,
        category=case.category,
        fault_type=fault_type,
        pre_fault_pu=1.0,
        post_fault_pu=1.0,
        fault_start_s=fault_start,
        fault_duration_s=fault_duration,
        recovery_tau_s=0.035,
        calibration_mode="joint_sweep",
    )


def baseline_metrics(case: BaselineCase, pass_column: str) -> EvalMetrics:
    row = case.row
    pass_flag = b(row, pass_column)
    reason_col = "voltage_survival_reason" if pass_column == "voltage_survival_pass" else "full_frt_reason"
    metrics = EvalMetrics(
        topology=case.topology,
        category=case.category,
        duration_ms=case.duration_ms,
        case_name=case.case_name,
        fault_pu=case.fault_pu,
        pass_flag=pass_flag,
        reason=str(row.get(reason_col, "")),
        score=0.0,
        lv_mean=f(row, "lv_mean"),
        lv_recovery_mean=f(row, "lv_recovery_mean"),
        lv_peak=f(row, "lv_peak"),
        lv_min=f(row, "lv_min"),
        vdc_min=f(row, "vdc_min"),
        vdc_max=f(row, "vdc_max"),
        action_max_abs=f(row, "action_max_abs"),
        grid_iq_shortfall_max_pu=finite(f(row, "grid_iq_shortfall_max_pu"), 0.0),
        grid_current_peak_pu=finite(f(row, "grid_current_peak_pu"), 0.0),
        grid_iq_wrong_sign=b(row, "grid_iq_wrong_sign"),
    )
    metrics.score = score_metrics(metrics)
    return metrics


def score_metrics(metrics: EvalMetrics) -> float:
    score = 0.0
    if not metrics.pass_flag:
        score += 100.0
    score += abs(metrics.lv_mean - 207.0) / 5.0
    score += abs(metrics.lv_recovery_mean - 207.0) / 5.0
    score += max(0.0, metrics.lv_peak - 235.0) / 3.0
    score += max(0.0, 180.0 - metrics.lv_min) / 3.0
    score += max(0.0, 650.0 - metrics.vdc_min) / 10.0
    score += max(0.0, metrics.vdc_max - 1000.0) / 10.0
    score += max(0.0, metrics.action_max_abs - 0.9501) * 100.0
    score += 40.0 * max(0.0, finite(metrics.grid_iq_shortfall_max_pu))
    score += 50.0 * max(0.0, finite(metrics.grid_current_peak_pu) - 1.5)
    score += 220.0 * max(0.0, finite(metrics.calibration_support_violation)) ** 2
    score += 140.0 * max(0.0, finite(metrics.calibrated_survival_violation))
    if metrics.grid_iq_wrong_sign:
        score += 8.0
    return float(score)


def voltage_survival_pass(metrics: EvalMetrics) -> tuple[bool, str]:
    reasons: list[str] = []
    if not (176.0 <= metrics.lv_mean <= 238.0):
        reasons.append("lv_fault_mean_bounds")
    if not (180.0 <= metrics.lv_recovery_mean <= 235.0):
        reasons.append("lv_recovery_mean_bounds")
    if not (metrics.vdc_min >= 650.0 and metrics.vdc_max <= 1000.0):
        reasons.append("dc_link_bounds")
    if not (metrics.action_max_abs <= 0.9501):
        reasons.append("action_limit")
    if metrics.calibration_support_violation > 1e-6:
        reasons.append("proxy_ood_action")
    return (not reasons), ";".join(reasons)


def train_sac_specialist(
    spec: SpecialistSpec,
    *,
    steps: int,
    n_envs: int,
    seed: int,
    run_dir: Path,
    env_config: HPTVoltageEnvConfig,
    init_model: Path | None = None,
    learning_rate: float = 3e-4,
    sac_batch_size: int = 128,
    sac_buffer_size: int | None = None,
    sac_learning_starts: int | None = None,
    ent_coef: str | float = "auto",
    bc_warmstart_epochs: int = 0,
    bc_episodes_per_scenario: int = 2,
    bc_batch_size: int = 512,
    bc_lr: float = 1e-4,
    bc_noise_std: float = 0.02,
    bc_teacher_source: str = "table",
    bc_action_weights: tuple[float, float, float, float] = (6.0, 4.0, 12.0, 12.0),
    behavior_anchor_epochs: int = 0,
    behavior_anchor_interval_steps: int = 250,
    behavior_anchor_lr: float | None = None,
) -> tuple[SAC, Path, float, dict[str, Any] | None]:
    scenarios = [scenario_from_case(case) for case in spec.cases]

    def make_env(idx: int):
        return lambda: HPTVoltageSACEnv(
            scenarios,
            config=env_config,
            seed=seed + idx,
            train_mode=True,
        )

    vec = DummyVecEnv([make_env(i) for i in range(n_envs)])
    assert vec.observation_space.shape == (OBS_DIM_HPT,)
    assert vec.action_space.shape == (ACT_DIM_HPT,)
    if init_model is not None:
        if not init_model.exists():
            raise FileNotFoundError(f"Warm-start model not found: {init_model}")
        model = SAC.load(str(init_model), env=vec, device=pick_device())
        model.set_env(vec)
    else:
        buffer_size_value = int(sac_buffer_size or max(steps * 4, 20_000))
        learning_starts_value = int(
            sac_learning_starts
            if sac_learning_starts is not None
            else min(1000, max(100, steps // 10))
        )
        model = SAC(
            "MlpPolicy",
            vec,
            learning_rate=learning_rate,
            buffer_size=buffer_size_value,
            batch_size=sac_batch_size,
            tau=0.005,
            gamma=0.99,
            train_freq=1,
            gradient_steps=1,
            learning_starts=learning_starts_value,
            ent_coef=ent_coef,
            # Keep this architecture aligned with export_hpt_sac_actor.py and the
            # Simulink MATLAB Function forward pass.  Smaller smoke-test networks
            # are faster, but cannot be exported into the switch-level models.
            policy_kwargs=dict(net_arch=[256, 256, 256]),
            device=pick_device(),
            seed=seed,
            verbose=0,
        )
    bc_metrics: dict[str, Any] | None = None
    bc_x: np.ndarray | None = None
    bc_y: np.ndarray | None = None
    if bc_warmstart_epochs > 0 or behavior_anchor_epochs > 0:
        if bc_teacher_source == "conventional_csv":
            bc_x, bc_y = collect_conventional_teacher_samples(
                spec.cases,
                env_config,
                episodes_per_case=bc_episodes_per_scenario,
                noise_std=bc_noise_std,
                seed=seed,
            )
        else:
            bc_x, bc_y = collect_teacher_samples(
                scenarios,
                env_config,
                episodes_per_scenario=bc_episodes_per_scenario,
                noise_std=bc_noise_std,
                feedback_gain_topology1=0.0,
                feedback_gain_topology2=0.0,
                feedforward_scale_topology1=1.0,
                feedforward_scale_topology2=1.0,
                teacher_source=bc_teacher_source,
                seed=seed,
            )
    if bc_warmstart_epochs > 0:
        if bc_x is None or bc_y is None:
            raise RuntimeError("BC dataset was not built")
        bc_metrics = train_actor_bc(
            model,
            bc_x,
            bc_y,
            epochs=bc_warmstart_epochs,
            batch_size=bc_batch_size,
            lr=bc_lr,
            seed=seed,
            action_weights=bc_action_weights,
        )
    start = time.time()
    if steps > 0:
        if behavior_anchor_epochs > 0:
            if bc_x is None or bc_y is None:
                raise RuntimeError("Behavior-anchor dataset was not built")
            interval = max(1, int(behavior_anchor_interval_steps))
            anchor_metrics: list[dict[str, Any]] = []
            trained = 0
            while trained < steps:
                chunk = min(interval, steps - trained)
                model.learn(total_timesteps=chunk, reset_num_timesteps=(trained == 0))
                trained += chunk
                anchor_metrics.append(
                    train_actor_bc(
                        model,
                        bc_x,
                        bc_y,
                        epochs=behavior_anchor_epochs,
                        batch_size=bc_batch_size,
                        lr=behavior_anchor_lr if behavior_anchor_lr is not None else bc_lr,
                        seed=seed + trained,
                        action_weights=bc_action_weights,
                    )
                )
            if bc_metrics is None:
                bc_metrics = {}
            bc_metrics["behavior_anchor_epochs"] = int(behavior_anchor_epochs)
            bc_metrics["behavior_anchor_interval_steps"] = int(interval)
            bc_metrics["behavior_anchor_updates"] = len(anchor_metrics)
            if anchor_metrics:
                bc_metrics["behavior_anchor_last"] = anchor_metrics[-1]
        else:
            model.learn(total_timesteps=steps)
    elapsed = time.time() - start
    model_path = MODELS / "hpt_fault_specialists" / f"{run_dir.name}_{spec.name}.zip"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))
    return model, model_path, elapsed, bc_metrics


def evaluate_proxy_case(
    model: SAC,
    case: BaselineCase,
    *,
    env_config: HPTVoltageEnvConfig,
) -> EvalMetrics:
    scenario = scenario_from_case(case)
    env = HPTVoltageSACEnv([scenario], config=env_config, seed=0, train_mode=False)
    obs, _ = env.reset()
    done = False
    total_reward = 0.0
    rows: list[dict[str, Any]] = []
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += float(reward)
        rows.append(
            {
                "t": float(env.t),
                "v_lv": float(info["v_lv_pu"]) * env_config.v_ref_phase_rms,
                "vdc": float(info["vdc_pu"]) * env_config.vdc_ref,
                "action_reg_d": float(info["action"][0]),
                "action_reg_q": float(info["action"][1]),
                "action_energy_d": float(info["action"][2]),
                "action_energy_q": float(info["action"][3]),
                "action_max": float(np.max(np.abs(info["action"]))),
                "teacher_gap": float(info.get("teacher_gap", 0.0)),
                "grid_iq_shortfall": float(info["grid_iq_shortfall_pu"]),
                "grid_current_peak": float(info["grid_current_peak_pu"]),
                "grid_wrong_sign": bool(info["grid_reactive_wrong_sign"]),
                "support_violation": float(info.get("calibration_support_violation", 0.0)),
                "survival_violation": float(info.get("calibrated_survival_violation", 0.0)),
                "cal_lv_recovery": float(info.get("calibrated_lv_recovery_pu", float("nan"))),
                "cal_lv_peak": float(info.get("calibrated_lv_peak_pu", float("nan"))),
                "cal_lv_min": float(info.get("calibrated_lv_min_pu", float("nan"))),
                "cal_vdc_min": float(info.get("calibrated_vdc_min_pu", float("nan"))),
                "cal_vdc_max": float(info.get("calibrated_vdc_max_pu", float("nan"))),
            }
        )
        done = bool(terminated or truncated)

    fault_start = scenario.fault_start_s
    fault_clear = scenario.fault_start_s + float(scenario.fault_duration_s or case.duration_s)
    fault_rows = [r for r in rows if fault_start <= r["t"] <= fault_clear] or rows
    recovery_rows = [r for r in rows if r["t"] >= fault_clear] or rows
    v_all = np.asarray([r["v_lv"] for r in rows], dtype=float)
    vdc_all = np.asarray([r["vdc"] for r in rows], dtype=float)
    actions_all = np.asarray(
        [
            [
                r["action_reg_d"],
                r["action_reg_q"],
                r["action_energy_d"],
                r["action_energy_q"],
            ]
            for r in rows
        ],
        dtype=float,
    )
    cal_lv_recovery = np.asarray([r["cal_lv_recovery"] for r in rows], dtype=float)
    cal_lv_peak = np.asarray([r["cal_lv_peak"] for r in rows], dtype=float)
    cal_lv_min = np.asarray([r["cal_lv_min"] for r in rows], dtype=float)
    cal_vdc_min = np.asarray([r["cal_vdc_min"] for r in rows], dtype=float)
    cal_vdc_max = np.asarray([r["cal_vdc_max"] for r in rows], dtype=float)

    def finite_mean_or(values: np.ndarray, default: float) -> float:
        vals = values[np.isfinite(values)]
        return float(np.mean(vals)) if vals.size else float(default)

    def finite_min_or(values: np.ndarray, default: float) -> float:
        vals = values[np.isfinite(values)]
        return float(np.min(vals)) if vals.size else float(default)

    def finite_max_or(values: np.ndarray, default: float) -> float:
        vals = values[np.isfinite(values)]
        return float(np.max(vals)) if vals.size else float(default)

    recovery_mean_default = float(np.mean([r["v_lv"] for r in recovery_rows]))
    metrics = EvalMetrics(
        topology=case.topology,
        category=case.category,
        duration_ms=case.duration_ms,
        case_name=case.case_name,
        fault_pu=case.fault_pu,
        pass_flag=False,
        reason="",
        score=0.0,
        lv_mean=float(np.mean([r["v_lv"] for r in fault_rows])),
        lv_recovery_mean=finite_mean_or(cal_lv_recovery, recovery_mean_default)
        * env_config.v_ref_phase_rms
        if np.isfinite(finite_mean_or(cal_lv_recovery, float("nan")))
        else recovery_mean_default,
        lv_peak=max(float(np.max(v_all)), finite_max_or(cal_lv_peak, float(np.max(v_all)) * 0.0) * env_config.v_ref_phase_rms),
        lv_min=min(float(np.min(v_all)), finite_min_or(cal_lv_min, float(np.min(v_all)) / env_config.v_ref_phase_rms) * env_config.v_ref_phase_rms),
        vdc_min=min(float(np.min(vdc_all)), finite_min_or(cal_vdc_min, float(np.min(vdc_all)) / env_config.vdc_ref) * env_config.vdc_ref),
        vdc_max=max(float(np.max(vdc_all)), finite_max_or(cal_vdc_max, float(np.max(vdc_all)) / env_config.vdc_ref) * env_config.vdc_ref),
        action_max_abs=float(np.max([r["action_max"] for r in rows])),
        grid_iq_shortfall_max_pu=float(np.max([r["grid_iq_shortfall"] for r in rows])),
        grid_current_peak_pu=float(np.max([r["grid_current_peak"] for r in rows])),
        grid_iq_wrong_sign=any(bool(r["grid_wrong_sign"]) for r in rows),
        calibration_support_violation=float(np.max([r["support_violation"] for r in rows])),
        calibrated_survival_violation=float(np.max([r["survival_violation"] for r in rows])),
        action_reg_d_mean=float(np.mean(actions_all[:, 0])),
        action_reg_q_mean=float(np.mean(actions_all[:, 1])),
        action_energy_d_mean=float(np.mean(actions_all[:, 2])),
        action_energy_q_mean=float(np.mean(actions_all[:, 3])),
        action_reg_d_abs_max=float(np.max(np.abs(actions_all[:, 0]))),
        action_reg_q_abs_max=float(np.max(np.abs(actions_all[:, 1]))),
        action_energy_d_abs_max=float(np.max(np.abs(actions_all[:, 2]))),
        action_energy_q_abs_max=float(np.max(np.abs(actions_all[:, 3]))),
        teacher_gap_mean=float(np.mean([r["teacher_gap"] for r in rows])),
        teacher_gap_max=float(np.max([r["teacher_gap"] for r in rows])),
    )
    metrics.pass_flag, metrics.reason = voltage_survival_pass(metrics)
    metrics.score = score_metrics(metrics)
    return metrics


def beats_sac_over_baseline(sac: EvalMetrics, baseline: EvalMetrics) -> bool:
    if sac.pass_flag and not baseline.pass_flag:
        return True
    if sac.pass_flag and baseline.pass_flag:
        return sac.score < baseline.score
    return False


def result_rows(results: list[SpecialistResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for item in result.case_results:
            row = {
                "specialist": result.spec["name"],
                "model_path": result.model_path,
                "train_steps": result.train_steps,
                "train_elapsed_s": result.train_elapsed_s,
            }
            row.update(item)
            rows.append(row)
    return rows


def write_report(run_dir: Path, results: list[SpecialistResult], baseline_csv: Path) -> None:
    total_cases = sum(len(r.case_results) for r in results)
    baseline_pass = sum(r.baseline_pass_n for r in results)
    sac_pass = sum(r.sac_proxy_pass_n for r in results)
    beat = sum(r.beat_n for r in results)
    improved = sum(r.improved_n for r in results)
    lines = [
        "# HPT Fault-Specialist SAC vs Conventional DQ",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Conventional baseline CSV: `{baseline_csv}`",
        f"- Specialists: `{len(results)}`",
        f"- Cases: `{total_cases}`",
        f"- Conventional voltage-survival pass: `{baseline_pass} / {total_cases}`",
        f"- SAC proxy voltage-survival pass: `{sac_pass} / {total_cases}`",
        f"- SAC beats conventional by pass/score: `{beat} / {total_cases}`",
        f"- SAC improves score: `{improved} / {total_cases}`",
        "",
        "| Specialist | Cases | Baseline Pass | SAC Proxy Pass | Beat | Improved | Train Steps | Train Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| `{result.spec['name']}` | {len(result.case_results)} | "
            f"{result.baseline_pass_n} | {result.sac_proxy_pass_n} | {result.beat_n} | "
            f"{result.improved_n} | {result.train_steps} | {result.train_elapsed_s:.1f}s |"
        )
    lines.extend(["", "## Case Details", ""])
    for result in results:
        lines.append(f"### `{result.spec['name']}`")
        for item in result.case_results:
            lines.append(
                f"- `{item['case_name']}` conventional `{item['baseline_pass']}` "
                f"score `{item['baseline_score']:.3f}` -> SAC proxy `{item['sac_pass']}` "
                f"score `{item['sac_score']:.3f}`, beat `{item['beat']}`, "
                f"reason `{item['sac_reason']}`"
            )
        lines.append("")
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-csv", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--steps", type=int, default=8_000)
    parser.add_argument("--n-envs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--topology", choices=["all", "topology1", "topology2"], default="all")
    parser.add_argument("--category", choices=["all", "LVRT", "HVRT"], default="all")
    parser.add_argument("--duration-ms", type=int, default=None)
    parser.add_argument("--max-specialists", type=int, default=4)
    parser.add_argument(
        "--selection",
        choices=["near_boundary", "all_cases"],
        default="near_boundary",
        help="near_boundary trains on the last conventional pass and first fail in each group.",
    )
    parser.add_argument(
        "--granularity",
        choices=["group", "case"],
        default="group",
        help="group trains one expert per topology/category/duration; case trains one per fault case.",
    )
    parser.add_argument("--pass-column", default="voltage_survival_pass")
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument("--reg-d-limit", type=float, default=0.80)
    parser.add_argument("--reg-q-limit", type=float, default=0.40)
    parser.add_argument("--energy-d-limit", type=float, default=0.40)
    parser.add_argument("--energy-q-limit", type=float, default=0.20)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--sac-batch-size", type=int, default=128)
    parser.add_argument("--sac-buffer-size", type=int, default=None)
    parser.add_argument("--sac-learning-starts", type=int, default=None)
    parser.add_argument(
        "--ent-coef",
        type=parse_ent_coef,
        default="auto",
        help="Stable-Baselines3 SAC entropy coefficient: auto, auto_0.1, or a float.",
    )
    parser.add_argument(
        "--teacher-prior-weight",
        type=float,
        default=0.0,
        help="Behavior constraint strength toward the calibrated switch-level teacher action.",
    )
    parser.add_argument(
        "--action-projection",
        action="store_true",
        help="Enable the execution-layer action projection during proxy training/evaluation.",
    )
    parser.add_argument(
        "--init-model",
        type=Path,
        default=None,
        help="Optional SAC actor zip used as a warm-start before specialist fine-tuning.",
    )
    parser.add_argument("--bc-warmstart-epochs", type=int, default=0)
    parser.add_argument("--bc-episodes-per-scenario", type=int, default=2)
    parser.add_argument("--bc-batch-size", type=int, default=512)
    parser.add_argument("--bc-lr", type=float, default=1e-4)
    parser.add_argument("--bc-noise-std", type=float, default=0.02)
    parser.add_argument(
        "--behavior-anchor-epochs",
        type=int,
        default=0,
        help="Run this many BC epochs after every SAC chunk to keep actor in labeled support.",
    )
    parser.add_argument("--behavior-anchor-interval-steps", type=int, default=250)
    parser.add_argument("--behavior-anchor-lr", type=float, default=None)
    parser.add_argument("--calibration-ood-reward-weight", type=float, default=220.0)
    parser.add_argument("--calibrated-survival-reward-weight", type=float, default=140.0)
    parser.add_argument("--grid-reactive-reward-weight", type=float, default=40.0)
    parser.add_argument("--grid-current-reward-weight", type=float, default=50.0)
    parser.add_argument(
        "--bc-action-weights",
        type=parse_action_weights,
        default=(6.0, 4.0, 12.0, 12.0),
        help="Comma-separated BC weights for [m_reg_d,m_reg_q,m_energy_d,m_energy_q].",
    )
    parser.add_argument(
        "--bc-teacher-source",
        choices=["table", "execution_guard", "conventional_csv"],
        default="conventional_csv",
    )
    args = parser.parse_args()

    baseline_csv = args.baseline_csv or latest_boundary_csv()
    run_id = args.run_id or f"hpt_fault_specialists_vs_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cases = select_baseline_cases(
        baseline_csv,
        topology=args.topology,
        category=args.category,
        duration_ms=args.duration_ms,
    )
    specs = build_specs(
        cases,
        pass_column=args.pass_column,
        selection=args.selection,
        granularity=args.granularity,
        max_specialists=args.max_specialists,
    )
    if not specs:
        raise RuntimeError("No specialist specs selected")

    env_config = HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        reg_d_limit=args.reg_d_limit,
        reg_q_limit=args.reg_q_limit,
        energy_d_limit=args.energy_d_limit,
        energy_q_limit=args.energy_q_limit,
        teacher_prior_weight=args.teacher_prior_weight,
        action_projection_enable=args.action_projection,
        calibration_ood_reward_weight=args.calibration_ood_reward_weight,
        calibrated_survival_reward_weight=args.calibrated_survival_reward_weight,
        grid_reactive_reward_weight=args.grid_reactive_reward_weight,
        grid_current_reward_weight=args.grid_current_reward_weight,
    )
    results: list[SpecialistResult] = []
    for idx, spec in enumerate(specs):
        model, model_path, elapsed, bc_metrics = train_sac_specialist(
            spec,
            steps=args.steps,
            n_envs=args.n_envs,
            seed=args.seed + 1000 * idx,
            run_dir=run_dir,
            env_config=env_config,
            init_model=args.init_model,
            learning_rate=args.learning_rate,
            sac_batch_size=args.sac_batch_size,
            sac_buffer_size=args.sac_buffer_size,
            sac_learning_starts=args.sac_learning_starts,
            ent_coef=args.ent_coef,
            bc_warmstart_epochs=args.bc_warmstart_epochs,
            bc_episodes_per_scenario=args.bc_episodes_per_scenario,
            bc_batch_size=args.bc_batch_size,
            bc_lr=args.bc_lr,
            bc_noise_std=args.bc_noise_std,
            bc_teacher_source=args.bc_teacher_source,
            bc_action_weights=args.bc_action_weights,
            behavior_anchor_epochs=args.behavior_anchor_epochs,
            behavior_anchor_interval_steps=args.behavior_anchor_interval_steps,
            behavior_anchor_lr=args.behavior_anchor_lr,
        )
        case_results: list[dict[str, Any]] = []
        baseline_pass_n = 0
        sac_pass_n = 0
        beat_n = 0
        improved_n = 0
        for case in spec.cases:
            base = baseline_metrics(case, args.pass_column)
            sac = evaluate_proxy_case(model, case, env_config=env_config)
            beat = beats_sac_over_baseline(sac, base)
            improved = sac.score < base.score
            baseline_pass_n += int(base.pass_flag)
            sac_pass_n += int(sac.pass_flag)
            beat_n += int(beat)
            improved_n += int(improved)
            case_results.append(
                {
                    "topology": case.topology,
                    "category": case.category,
                    "duration_ms": case.duration_ms,
                    "case_name": case.case_name,
                    "fault_pu": case.fault_pu,
                    "baseline_pass": base.pass_flag,
                    "baseline_reason": base.reason,
                    "baseline_score": base.score,
                    "baseline_lv_mean": base.lv_mean,
                    "baseline_lv_recovery_mean": base.lv_recovery_mean,
                    "baseline_vdc_min": base.vdc_min,
                    "baseline_vdc_max": base.vdc_max,
                    "sac_pass": sac.pass_flag,
                    "sac_reason": sac.reason,
                    "sac_score": sac.score,
                    "sac_lv_mean": sac.lv_mean,
                    "sac_lv_recovery_mean": sac.lv_recovery_mean,
                    "sac_vdc_min": sac.vdc_min,
                    "sac_vdc_max": sac.vdc_max,
                    "sac_action_max_abs": sac.action_max_abs,
                    "sac_action_reg_d_mean": sac.action_reg_d_mean,
                    "sac_action_reg_q_mean": sac.action_reg_q_mean,
                    "sac_action_energy_d_mean": sac.action_energy_d_mean,
                    "sac_action_energy_q_mean": sac.action_energy_q_mean,
                    "sac_action_reg_d_abs_max": sac.action_reg_d_abs_max,
                    "sac_action_reg_q_abs_max": sac.action_reg_q_abs_max,
                    "sac_action_energy_d_abs_max": sac.action_energy_d_abs_max,
                    "sac_action_energy_q_abs_max": sac.action_energy_q_abs_max,
                    "sac_teacher_gap_mean": sac.teacher_gap_mean,
                    "sac_teacher_gap_max": sac.teacher_gap_max,
                    "sac_grid_iq_shortfall_max_pu": sac.grid_iq_shortfall_max_pu,
                    "sac_grid_current_peak_pu": sac.grid_current_peak_pu,
                    "sac_calibration_support_violation": sac.calibration_support_violation,
                    "sac_calibrated_survival_violation": sac.calibrated_survival_violation,
                    "beat": beat,
                    "improved": improved,
                }
            )
        result = SpecialistResult(
            spec={
                "name": spec.name,
                "topology": spec.topology,
                "category": spec.category,
                "duration_s": spec.duration_s,
                "duration_ms": spec.duration_ms,
                "cases": [case.case_name for case in spec.cases],
            },
            model_path=str(model_path),
            train_steps=args.steps,
            train_elapsed_s=elapsed,
            bc_metrics=bc_metrics,
            baseline_pass_n=baseline_pass_n,
            sac_proxy_pass_n=sac_pass_n,
            beat_n=beat_n,
            improved_n=improved_n,
            case_results=case_results,
        )
        results.append(result)
        (run_dir / "status.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2),
            encoding="utf-8",
        )
        write_csv(run_dir / "case_results.csv", result_rows(results))
        write_report(run_dir, results, baseline_csv)

    summary = {
        "run_id": run_id,
        "baseline_csv": str(baseline_csv),
        "run_dir": str(run_dir),
        "n_specialists": len(results),
        "n_cases": sum(len(r.case_results) for r in results),
        "baseline_pass_n": sum(r.baseline_pass_n for r in results),
        "sac_proxy_pass_n": sum(r.sac_proxy_pass_n for r in results),
        "beat_n": sum(r.beat_n for r in results),
        "improved_n": sum(r.improved_n for r in results),
        "case_results_csv": str(run_dir / "case_results.csv"),
        "report": str(run_dir / "REPORT.md"),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    metadata_config = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }
    metadata_config["baseline_csv"] = str(baseline_csv)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_fault_specialists_vs_conventional",
        config=metadata_config,
        topology_models=TOPOLOGY_MODELS,
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
