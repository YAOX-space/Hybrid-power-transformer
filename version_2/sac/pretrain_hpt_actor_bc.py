"""Behavior-clone the HPT SAC actor from the switch-sweep table teacher.

This is a warm-start utility, not a replacement controller.  It preserves the
SAC checkpoint/export format while pulling the deterministic actor output into
the action region proven useful by switch-level fixed-action sweeps.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpt_frt.device.train_common import pick_device
from .experiment_metadata import write_experiment_metadata
from .hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    execution_guard_teacher_action,
)
from .train_hpt_voltage_sac import MODELS, RESULTS, TOPOLOGY_MODELS, scenario_summary, select_scenarios


def make_env_config(args: argparse.Namespace) -> HPTVoltageEnvConfig:
    return HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        teacher_prior_weight=args.teacher_prior_weight,
    )


def collect_teacher_samples(
    scenarios,
    config: HPTVoltageEnvConfig,
    *,
    episodes_per_scenario: int,
    noise_std: float,
    feedback_gain_topology1: float,
    feedback_gain_topology2: float,
    feedforward_scale_topology1: float,
    feedforward_scale_topology2: float,
    teacher_source: str,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    observations: list[np.ndarray] = []
    targets: list[np.ndarray] = []

    for scenario in scenarios:
        env = HPTVoltageSACEnv([scenario], config=config, seed=seed, train_mode=False)
        for _ in range(episodes_per_scenario):
            obs, _ = env.reset()
            done = False
            while not done:
                grid_now, _ = env._grid_profile(env.t)
                dynamic_mode = float(scenario.fault_start_s) > 0.02 and scenario.category != "steady"
                if teacher_source == "execution_guard":
                    target = execution_guard_teacher_action(
                        obs,
                        reg_limit=config.reg_limit,
                        energy_limit=config.energy_limit,
                        dynamic_mode=dynamic_mode,
                        dynamic_reg_limit_topology1=config.dynamic_reg_limit_topology1,
                        dynamic_reg_limit_topology2=config.dynamic_reg_limit_topology2,
                    )
                else:
                    target = env._table_teacher_action(grid_now)
                    if scenario.topology.lower() == "topology1":
                        target[0] *= feedforward_scale_topology1
                        target[0] += feedback_gain_topology1 * (1.0 - float(obs[0]))
                    elif scenario.topology.lower() == "topology2":
                        target[0] *= feedforward_scale_topology2
                        target[0] += feedback_gain_topology2 * (1.0 - float(obs[0]))
                    target = env._project_action(target)
                observations.append(np.asarray(obs, dtype=np.float32))
                targets.append(np.asarray(target, dtype=np.float32))
                noisy_action = target + rng.normal(0.0, noise_std, size=ACT_DIM_HPT).astype(np.float32)
                noisy_action[2:] *= 0.25
                obs, _, terminated, truncated, _ = env.step(noisy_action)
                done = bool(terminated or truncated)

    X = np.asarray(observations, dtype=np.float32)
    Y = np.asarray(targets, dtype=np.float32)
    if X.ndim != 2 or X.shape[1] != OBS_DIM_HPT:
        raise RuntimeError(f"Bad observation dataset shape: {X.shape}")
    if Y.ndim != 2 or Y.shape[1] != ACT_DIM_HPT:
        raise RuntimeError(f"Bad target dataset shape: {Y.shape}")
    return X, Y


def append_step4_corrections(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    reg_limit: float,
) -> tuple[np.ndarray, np.ndarray]:
    if csv_path is None:
        return X, Y
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("mode") != "sac_actor":
                continue
            model = str(row.get("model", "")).lower()
            topology1 = 1.0 if "1to1" in model else 0.0
            topology2 = 1.0 - topology1
            lv = float(row["lv_rms_mean"])
            vdc = float(row["vdc_mean"])
            current_reg = float(row["reg_d_mean"])

            target_reg = current_reg
            if topology1 > 0.5:
                obs_vpu = float(row.get("obs_vpu_mean") or (lv / 207.0))
                target_reg = 0.38 + 2.0 * (0.99 - obs_vpu)
                target_reg -= 0.8 * max(0.0, lv - 210.0) / 207.0
                target_reg += 0.4 * max(0.0, 200.0 - lv) / 207.0
                target_reg -= 0.8 * max(0.0, 760.0 - vdc) / 800.0
            else:
                target_reg += 1.0 * max(0.0, lv - 212.0) / 207.0
                target_reg -= 1.0 * max(0.0, 198.0 - lv) / 207.0
                target_reg -= 0.4 * max(0.0, 760.0 - vdc) / 800.0
            target_reg = float(np.clip(target_reg, -reg_limit, reg_limit))

            obs = np.zeros(OBS_DIM_HPT, dtype=np.float32)
            obs[0] = float(row.get("obs_vpu_mean") or (lv / 207.0))
            obs[1] = float(row.get("obs_vpos_mean") or obs[0])
            obs[2] = 0.0
            obs[3] = float(row.get("obs_vdcpu_mean") or (vdc / 800.0))
            obs[4] = 1.0 - obs[3]
            obs[5] = float(row.get("obs_verr_mean") or (1.0 - obs[0]))
            obs[8] = float(row.get("obs_last_reg_d_mean") or current_reg)
            obs[12] = float(row.get("obs_sag_flag_mean") or 0.0)
            obs[13] = float(row.get("obs_swell_flag_mean") or 0.0)
            obs[14] = float(row.get("obs_topology1_flag_mean") or topology1)
            obs[15] = float(row.get("obs_topology2_flag_mean") or topology2)
            obs[20] = 1.0
            obs[21] = 1.0

            target = np.asarray([target_reg, 0.0, 0.0, 0.0], dtype=np.float32)
            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
    )


def _scenario_type_allowed(row: dict[str, str], scenario_types: str) -> bool:
    if scenario_types == "all":
        return True
    scenario_type = str(row.get("scenario_type", "")).lower()
    if scenario_types == "steady":
        return scenario_type == "steady"
    if scenario_types == "fault":
        return scenario_type != "steady"
    raise ValueError(f"Unknown scenario type filter: {scenario_types}")


def _csv_filter_allowed(value: str, allowed_csv: str) -> bool:
    allowed_csv = str(allowed_csv or "all").strip().lower()
    if allowed_csv in {"", "all", "*"}:
        return True
    allowed = {item.strip().lower() for item in allowed_csv.split(",") if item.strip()}
    return str(value or "").strip().lower() in allowed


def _contains_filter_allowed(value: str, needle_csv: str) -> bool:
    needle_csv = str(needle_csv or "all").strip().lower()
    if needle_csv in {"", "all", "*"}:
        return True
    value_l = str(value or "").lower()
    needles = [item.strip().lower() for item in needle_csv.split(",") if item.strip()]
    return any(needle in value_l for needle in needles)


def _trace_row_allowed(
    row: dict[str, str],
    *,
    scenario_types: str,
    topologies: str,
    condition_classes: str,
    case_contains: str,
) -> bool:
    return (
        _scenario_type_allowed(row, scenario_types)
        and _csv_filter_allowed(row.get("topology", ""), topologies)
        and _csv_filter_allowed(row.get("condition_class", ""), condition_classes)
        and _contains_filter_allowed(row.get("case_name", ""), case_contains)
    )


def append_switch_trace_samples(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
    topologies: str,
    condition_classes: str,
    case_contains: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not _trace_row_allowed(
                row,
                scenario_types=scenario_types,
                topologies=topologies,
                condition_classes=condition_classes,
                case_contains=case_contains,
            ):
                continue
            obs = np.asarray(
                [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM_HPT + 1)],
                dtype=np.float32,
            )
            target = np.asarray(
                [float(row[f"action_{idx:02d}"]) for idx in range(1, ACT_DIM_HPT + 1)],
                dtype=np.float32,
            )
            if (
                topology2_phase_equivalent
                and str(row.get("topology", "")).lower() == "topology2"
                and float(row.get("actor_select_mode", 0.0) or 0.0) >= 1.5
                and target[0] < 0.0
            ):
                reg_d = float(target[0])
                target[0] = reg_d * np.cos(phase_shift_rad)
                target[1] = reg_d * np.sin(phase_shift_rad)
            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def append_raw_smoke_corrections(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    energy_limit: float,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("mode") != "sac_actor_raw_guard0":
                continue
            if not _scenario_type_allowed(row, scenario_types):
                continue
            topology = str(row.get("topology", "")).lower()
            scenario_type = str(row.get("scenario_type", "")).lower()
            lv_mean = float(row.get("lv_mean") or 207.0)
            vpu = lv_mean / 207.0
            vpos = vpu
            obs_vdcpu = float(row.get("obs_vdcpu_mean") or 1.0)
            vdc_min_pu = float(row.get("vdc_min") or 800.0) / 800.0
            vdcpu = min(obs_vdcpu, vdc_min_pu)
            current_reg_d = float(row.get("reg_d_mean") or 0.0)
            current_reg_q = float(row.get("reg_q_mean") or 0.0)
            current_energy_d = float(row.get("energy_d_mean") or 0.0)
            current_energy_q = float(row.get("energy_q_mean") or 0.0)

            obs = np.zeros(OBS_DIM_HPT, dtype=np.float32)
            obs[0] = vpu
            obs[1] = vpos
            obs[2] = 0.0
            obs[3] = vdcpu
            obs[4] = 1.0 - vdcpu
            obs[5] = 1.0 - vpu
            obs[8] = current_reg_d
            obs[9] = current_reg_q
            obs[10] = current_energy_d
            obs[11] = current_energy_q
            obs[12] = 1.0 if vpos < 0.92 else 0.0
            obs[13] = 1.0 if vpos > 1.08 else 0.0
            obs[14] = 1.0 if topology == "topology1" else 0.0
            obs[15] = 1.0 if topology == "topology2" else 0.0
            obs[16] = float(row.get("obs_fault_flag_mean") or 0.0)
            obs[17] = float(row.get("obs_recovery_flag_mean") or 0.0)
            obs[20] = min(vpos, 1.0)
            obs[21] = max(vpos, 1.0)

            if topology == "topology1":
                reg_d = 0.32 + 2.35 * (1.0 - vpu)
                if vpu > 0.995:
                    reg_d = 0.26
                reg_d = float(np.clip(reg_d, 0.22, 0.46))
            elif scenario_type == "fault":
                reg_d = float(np.clip(20.0 * (1.0 - vpu), -0.60, 0.60))
            else:
                reg_d = current_reg_d + 1.8 * ((207.0 - lv_mean) / 207.0)
                reg_d = float(np.clip(reg_d, -0.60, 0.60))

            energy_d = 0.0
            if vdcpu < 0.95:
                dc_scale = float(np.clip((vdcpu - 0.75) / 0.20, 0.0, 1.0))
                reg_d *= dc_scale
                energy_d = min(energy_limit, 0.20 + 1.2 * (0.82 - vdcpu))
            elif vdcpu > 1.12:
                energy_d = max(-energy_limit, -0.05)

            target = np.asarray([reg_d, 0.0, energy_d, 0.0], dtype=np.float32)
            if (
                topology2_phase_equivalent
                and topology == "topology2"
                and scenario_type == "fault"
                and target[0] < 0.0
            ):
                raw_reg = float(target[0])
                target[0] = raw_reg * np.cos(phase_shift_rad)
                target[1] = raw_reg * np.sin(phase_shift_rad)

            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def append_energy_teacher_trace_samples(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    reg_limit: float,
    energy_limit: float,
    dynamic_reg_limit_topology1: float,
    dynamic_reg_limit_topology2: float,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
    min_time: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not _scenario_type_allowed(row, scenario_types):
                continue
            if min_time > 0.0 and float(row.get("t") or 0.0) < min_time:
                continue
            obs = np.asarray(
                [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM_HPT + 1)],
                dtype=np.float32,
            )
            topology = str(row.get("topology", "")).lower()
            dynamic_mode = str(row.get("scenario_type", "")).lower() != "steady"
            if "target_action_01" in row and str(row.get("target_action_01", "")).strip():
                target = np.zeros(ACT_DIM_HPT, dtype=np.float32)
                target[0] = float(np.clip(float(row.get("target_action_01") or 0.0), -reg_limit, reg_limit))
                target[1] = float(np.clip(float(row.get("target_action_02") or 0.0), -reg_limit, reg_limit))
            else:
                target = execution_guard_teacher_action(
                    obs,
                    reg_limit=reg_limit,
                    energy_limit=energy_limit,
                    dynamic_mode=dynamic_mode,
                    dynamic_reg_limit_topology1=dynamic_reg_limit_topology1,
                    dynamic_reg_limit_topology2=dynamic_reg_limit_topology2,
                )
                if (
                    topology2_phase_equivalent
                    and topology == "topology2"
                    and dynamic_mode
                    and target[0] < 0.0
                ):
                    raw_reg = float(target[0])
                    target[0] = raw_reg * np.cos(phase_shift_rad)
                    target[1] = raw_reg * np.sin(phase_shift_rad)

            target[2] = float(
                np.clip(float(row.get("target_action_03") or 0.0), -energy_limit, energy_limit)
            )
            target[3] = float(
                np.clip(float(row.get("target_action_04") or 0.0), -energy_limit, energy_limit)
            )
            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target.astype(np.float32))

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def build_or_load_model(args: argparse.Namespace, scenarios, config: HPTVoltageEnvConfig) -> SAC:
    vec = DummyVecEnv(
        [
            lambda: HPTVoltageSACEnv(
                scenarios,
                config=config,
                seed=args.seed,
                train_mode=True,
            )
        ]
    )
    if args.init_model is not None and args.init_model.exists():
        return SAC.load(str(args.init_model), env=vec, device=pick_device())
    return SAC(
        "MlpPolicy",
        vec,
        learning_rate=3e-4,
        buffer_size=100_000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        train_freq=1,
        gradient_steps=1,
        policy_kwargs=dict(net_arch=[256, 256, 256]),
        device=pick_device(),
        seed=args.seed,
        verbose=0,
    )


def train_actor_bc(
    model: SAC,
    X: np.ndarray,
    Y: np.ndarray,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
) -> dict:
    device = model.policy.device
    obs = torch.as_tensor(X, dtype=torch.float32, device=device)
    target_action = torch.as_tensor(Y, dtype=torch.float32, device=device)
    act_low = torch.as_tensor(model.action_space.low, dtype=torch.float32, device=device)
    act_high = torch.as_tensor(model.action_space.high, dtype=torch.float32, device=device)
    target = 2.0 * (target_action - act_low) / torch.clamp(act_high - act_low, min=1e-6) - 1.0
    target = torch.clamp(target, -1.0, 1.0)
    weights = torch.as_tensor([4.0, 1.0, 0.5, 0.5], dtype=torch.float32, device=device)
    opt = torch.optim.Adam(model.policy.actor.parameters(), lr=lr)
    rng = np.random.default_rng(seed)
    losses: list[float] = []
    n = X.shape[0]
    for _ in range(epochs):
        order = rng.permutation(n)
        for start in range(0, n, batch_size):
            idx = torch.as_tensor(order[start : start + batch_size], dtype=torch.long, device=device)
            pred = model.policy.actor(obs[idx], deterministic=True)
            loss = torch.mean(((pred - target[idx]) * weights) ** 2)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.policy.actor.parameters(), 5.0)
            opt.step()
            losses.append(float(loss.detach().cpu().item()))
    with torch.no_grad():
        pred = model.policy.actor(obs, deterministic=True)
        pred_action = act_low + 0.5 * (pred + 1.0) * (act_high - act_low)
        mse = torch.mean((pred_action - target_action) ** 2, dim=0).detach().cpu().numpy()
    return {
        "final_loss": float(losses[-1]) if losses else float("nan"),
        "mean_loss_tail": float(np.mean(losses[-min(50, len(losses)) :])) if losses else float("nan"),
        "action_mse": [float(v) for v in mse],
        "samples": int(n),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--curriculum",
        choices=["all", "steady_step4", "topology2_fault", "switch_fault_transition", "expanded_fault_transition"],
        default="steady_step4",
    )
    parser.add_argument("--teacher-source", choices=["table", "execution_guard"], default="table")
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--episodes-per-scenario", type=int, default=24)
    parser.add_argument("--noise-std", type=float, default=0.08)
    parser.add_argument("--feedback-gain-topology1", type=float, default=1.2)
    parser.add_argument("--feedback-gain-topology2", type=float, default=0.0)
    parser.add_argument("--feedforward-scale-topology1", type=float, default=1.0)
    parser.add_argument("--feedforward-scale-topology2", type=float, default=1.0)
    parser.add_argument("--step4-correction-csv", type=Path, default=None)
    parser.add_argument("--step4-correction-repeat", type=int, default=512)
    parser.add_argument("--switch-trace-csv", type=Path, default=None)
    parser.add_argument("--switch-trace-repeat", type=int, default=4)
    parser.add_argument("--switch-trace-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--switch-trace-topologies", default="all")
    parser.add_argument("--switch-trace-condition-classes", default="all")
    parser.add_argument("--switch-trace-case-contains", default="all")
    parser.add_argument("--switch-trace-topology2-phase-equivalent", action="store_true")
    parser.add_argument("--switch-trace-phase-shift-rad", type=float, default=0.55)
    parser.add_argument("--raw-smoke-correction-csv", type=Path, default=None)
    parser.add_argument("--raw-smoke-correction-repeat", type=int, default=512)
    parser.add_argument("--raw-smoke-correction-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--energy-teacher-trace-csv", type=Path, default=None)
    parser.add_argument("--energy-teacher-trace-repeat", type=int, default=16)
    parser.add_argument("--energy-teacher-trace-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--energy-teacher-min-time", type=float, default=0.0)
    parser.add_argument("--epochs", type=int, default=240)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument("--teacher-prior-weight", type=float, default=30.0)
    parser.add_argument("--init-model", type=Path, default=None)
    parser.add_argument("--model-out", type=Path, default=MODELS / "hpt_voltage_sac_bc_warmstart.zip")
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_sac_bc_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)

    scenarios = select_scenarios(args.curriculum)
    config = make_env_config(args)
    X, Y = collect_teacher_samples(
        scenarios,
        config,
        episodes_per_scenario=args.episodes_per_scenario,
        noise_std=args.noise_std,
        feedback_gain_topology1=args.feedback_gain_topology1,
        feedback_gain_topology2=args.feedback_gain_topology2,
        feedforward_scale_topology1=args.feedforward_scale_topology1,
        feedforward_scale_topology2=args.feedforward_scale_topology2,
        teacher_source=args.teacher_source,
        seed=args.seed,
    )
    X, Y = append_step4_corrections(
        X,
        Y,
        args.step4_correction_csv,
        repeat=args.step4_correction_repeat,
        reg_limit=args.reg_limit,
    )
    X, Y, switch_trace_samples = append_switch_trace_samples(
        X,
        Y,
        args.switch_trace_csv,
        repeat=args.switch_trace_repeat,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.switch_trace_scenario_types,
        topologies=args.switch_trace_topologies,
        condition_classes=args.switch_trace_condition_classes,
        case_contains=args.switch_trace_case_contains,
    )
    X, Y, raw_smoke_samples = append_raw_smoke_corrections(
        X,
        Y,
        args.raw_smoke_correction_csv,
        repeat=args.raw_smoke_correction_repeat,
        energy_limit=args.energy_limit,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.raw_smoke_correction_scenario_types,
    )
    X, Y, energy_teacher_samples = append_energy_teacher_trace_samples(
        X,
        Y,
        args.energy_teacher_trace_csv,
        repeat=args.energy_teacher_trace_repeat,
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        dynamic_reg_limit_topology1=config.dynamic_reg_limit_topology1,
        dynamic_reg_limit_topology2=config.dynamic_reg_limit_topology2,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.energy_teacher_trace_scenario_types,
        min_time=args.energy_teacher_min_time,
    )
    model = build_or_load_model(args, scenarios, config)
    metrics = train_actor_bc(
        model,
        X,
        Y,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
    )
    model.save(str(args.model_out))

    sidecar = {
        "run_id": run_id,
        "controller": "hpt-voltage-sac-bc-warmstart",
        "observation_dim": OBS_DIM_HPT,
        "action_dim": ACT_DIM_HPT,
        "curriculum": args.curriculum,
        "scenario_summary": scenario_summary(scenarios),
        "init_model": str(args.init_model) if args.init_model else None,
        "model_path": str(args.model_out),
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "metrics": {
            **metrics,
            "switch_trace_augmented_samples": int(switch_trace_samples),
            "raw_smoke_correction_samples": int(raw_smoke_samples),
            "energy_teacher_trace_samples": int(energy_teacher_samples),
        },
    }
    args.model_out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_actor_bc_warmstart",
        config=sidecar["config"],
        topology_models=TOPOLOGY_MODELS,
        policy_checkpoint=args.model_out,
        extra={"summary_path": str(run_dir / "summary.json")},
    )
    print(json.dumps(sidecar, indent=2), flush=True)


if __name__ == "__main__":
    main()
