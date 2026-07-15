"""Train the HPT voltage-regulation/FRT-transition SAC actor.

This runner is intentionally separate from the FRT SAC runners.  It trains on
the averaged HPT surrogate and exports an actor that matches the Simulink
deployment contract: 24-D observation, 4-D modulation action.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from .hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    DEFAULT_PROXY_CALIBRATION,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageScenario,
    HPTVoltageSACEnv,
    _neg_seq_for_fault,
    default_hpt_voltage_scenarios,
)
from .export_hpt_sac_actor import export_hpt_actor
from .experiment_metadata import write_experiment_metadata
from hpt_frt.device.train_common import pick_device


RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK_V2 = ROOT / "version_2" / "simulink"
TOPOLOGY_MODELS = {
    "topology1": SIMULINK_V2 / "topoloty1" / "hpt_v2_1to1_switchlevel.slx",
    "topology2": SIMULINK_V2 / "topology2" / "hpt_v2_topology2_paper.slx",
}


def select_scenarios(curriculum: str) -> list[HPTVoltageScenario]:
    scenarios = default_hpt_voltage_scenarios()
    if curriculum == "all":
        return scenarios
    if curriculum == "steady_step4":
        selected = [
            HPTVoltageScenario(
                topology=topology,
                grid_pu=grid_pu,
                duration_s=0.18,
                category="steady",
                fault_type="steady",
            )
            for topology in ("topology1", "topology2")
            for grid_pu in (0.90, 1.00, 1.10)
        ]
    elif curriculum == "topology2_fault":
        selected = [
            s
            for s in scenarios
            if s.topology == "topology2" and (s.category != "steady" or s.grid_pu in (0.90, 1.10))
        ]
    elif curriculum == "switch_fault_transition":
        selected = [
            HPTVoltageScenario(
                topology=topology,
                grid_pu=grid_pu,
                duration_s=0.16,
                category=category,
                fault_type=fault_type,
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
            for topology in ("topology1", "topology2")
            for grid_pu, category, fault_type in (
                (0.90, "LVRT", "sym3ph"),
                (1.10, "HVRT", "swell_3ph"),
            )
        ]
    elif curriculum == "expanded_fault_transition":
        selected = []
        for topology in ("topology1", "topology2"):
            for target in (0.20, 0.50, 0.75, 0.85, 0.90):
                for fault_type in ("sym3ph", "1ph_g", "2ph", "2ph_g"):
                    selected.append(
                        HPTVoltageScenario(
                            topology=topology,
                            grid_pu=target,
                            neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                            duration_s=0.26,
                            category="LVRT",
                            fault_type=fault_type,
                            fault_start_s=0.035,
                            fault_duration_s=0.090,
                            recovery_tau_s=0.035,
                        )
                    )
            for target in (1.10, 1.20, 1.25, 1.30):
                for fault_type in ("swell_3ph", "swell_1ph"):
                    selected.append(
                        HPTVoltageScenario(
                            topology=topology,
                            grid_pu=target,
                            neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                            duration_s=0.26,
                            category="HVRT",
                            fault_type=fault_type,
                            fault_start_s=0.035,
                            fault_duration_s=0.090,
                            recovery_tau_s=0.035,
                        )
                    )
    else:
        raise ValueError(f"Unknown HPT SAC curriculum: {curriculum}")

    if not selected:
        raise ValueError(f"Curriculum {curriculum} produced no scenarios")
    return selected


def scenario_summary(scenarios: list[HPTVoltageScenario]) -> dict:
    out: dict[str, dict[str, int] | int] = {"count": len(scenarios)}
    for attr in ("topology", "category", "fault_type"):
        bucket: dict[str, int] = {}
        for s in scenarios:
            key = str(getattr(s, attr))
            bucket[key] = bucket.get(key, 0) + 1
        out[attr] = dict(sorted(bucket.items()))
    return out


def evaluate_teacher_or_policy(
    model,
    scenarios: list[HPTVoltageScenario],
    n_rollouts: int = 20,
    config: HPTVoltageEnvConfig | None = None,
) -> dict:
    eval_scenarios = scenarios if n_rollouts <= 0 else scenarios[:n_rollouts]
    env = HPTVoltageSACEnv(scenarios, config=config, train_mode=False)
    returns = []
    final_v = []
    final_vdc = []
    vdc_min = []
    v_min = []
    v_max = []
    condition_counts: dict[str, int] = {}
    for _ in range(len(eval_scenarios)):
        obs, _ = env.reset()
        done = False
        ret = 0.0
        info = {}
        episode_vdc_min = float(obs[3])
        episode_v_min = float(obs[0])
        episode_v_max = float(obs[0])
        while not done:
            act, _ = model.predict(obs, deterministic=True)
            obs, rew, terminated, truncated, info = env.step(act)
            episode_vdc_min = min(episode_vdc_min, float(obs[3]))
            episode_v_min = min(episode_v_min, float(obs[0]))
            episode_v_max = max(episode_v_max, float(obs[0]))
            ret += rew
            done = terminated or truncated
        returns.append(ret)
        final_v.append(float(info["v_lv_pu"]))
        final_vdc.append(float(info["vdc_pu"]))
        vdc_min.append(episode_vdc_min)
        v_min.append(episode_v_min)
        v_max.append(episode_v_max)
        condition = str(info.get("condition", "unknown"))
        condition_counts[condition] = condition_counts.get(condition, 0) + 1
    return {
        "rollouts": len(eval_scenarios),
        "mean_return": float(np.mean(returns)),
        "mean_final_v_pu": float(np.mean(final_v)),
        "max_abs_final_v_err": float(np.max(np.abs(np.asarray(final_v) - 1.0))),
        "mean_final_vdc_pu": float(np.mean(final_vdc)),
        "min_vdc_pu": float(np.min(vdc_min)),
        "min_episode_v_pu": float(np.min(v_min)),
        "max_episode_v_pu": float(np.max(v_max)),
        "condition_counts": dict(sorted(condition_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=120_000)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--curriculum",
        choices=["all", "steady_step4", "topology2_fault", "switch_fault_transition", "expanded_fault_transition"],
        default="all",
    )
    parser.add_argument(
        "--model-out",
        type=Path,
        default=MODELS / "hpt_voltage_sac_best.zip",
        help="SAC checkpoint path. Use a candidate path until switch-level validation passes.",
    )
    parser.add_argument(
        "--init-model",
        type=Path,
        default=None,
        help="Optional existing SAC checkpoint to fine-tune instead of training from scratch.",
    )
    parser.add_argument("--eval-rollouts", type=int, default=20)
    parser.add_argument(
        "--safety-classifier",
        type=Path,
        default=None,
        help="Optional classifier.joblib support mask from switch-level data.",
    )
    parser.add_argument("--safety-penalty-weight", type=float, default=8.0)
    parser.add_argument("--safety-unsafe-terminal", action="store_true")
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument(
        "--teacher-prior-weight",
        type=float,
        default=0.0,
        help="Penalty weight for deviating from the switch-sweep table teacher.",
    )
    parser.add_argument("--export", action="store_true")
    parser.add_argument(
        "--export-out",
        type=Path,
        default=SIMULINK_V2 / "hpt_sac_actor_weights.mat",
        help="MAT actor export path used only with --export.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_sac_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    scenarios = select_scenarios(args.curriculum)
    env_config = HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        safety_classifier_path=str(args.safety_classifier) if args.safety_classifier else "",
        safety_penalty_weight=args.safety_penalty_weight,
        safety_unsafe_terminal=bool(args.safety_unsafe_terminal),
        teacher_prior_weight=args.teacher_prior_weight,
    )

    def make_env(idx: int):
        return lambda: HPTVoltageSACEnv(
            scenarios,
            config=env_config,
            seed=args.seed + idx,
            train_mode=True,
        )

    vec = DummyVecEnv([make_env(i) for i in range(args.n_envs)])
    assert vec.observation_space.shape == (OBS_DIM_HPT,)
    assert vec.action_space.shape == (ACT_DIM_HPT,)

    if args.init_model is not None and args.init_model.exists():
        model = SAC.load(str(args.init_model), env=vec, device=pick_device())
        model.verbose = 1
        model.learn(total_timesteps=args.steps, reset_num_timesteps=False)
    else:
        model = SAC(
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
            verbose=1,
        )
        model.learn(total_timesteps=args.steps)

    model_path = args.model_out
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))
    metrics = evaluate_teacher_or_policy(
        model,
        scenarios,
        n_rollouts=args.eval_rollouts,
        config=env_config,
    )
    calibration_meta = {}
    if DEFAULT_PROXY_CALIBRATION.exists():
        cal = json.loads(DEFAULT_PROXY_CALIBRATION.read_text(encoding="utf-8"))
        calibration_meta = {
            "path": str(DEFAULT_PROXY_CALIBRATION),
            "schema": cal.get("schema"),
            "source_csv": cal.get("source_csv"),
            "energy_source_csv": cal.get("energy_source_csv"),
            "energy_bridge_mode": cal.get("energy_bridge_mode"),
            "target_phase_rms": cal.get("target_phase_rms"),
            "topologies": sorted(cal.get("topologies", {}).keys()),
        }
    sidecar = {
        "run_id": run_id,
        "controller": "hpt-voltage-sac",
        "observation_dim": OBS_DIM_HPT,
        "action_dim": ACT_DIM_HPT,
        "steps": args.steps,
        "seed": args.seed,
        "init_model": str(args.init_model) if args.init_model is not None else None,
        "model_path": str(model_path),
        "curriculum": args.curriculum,
        "scenario_summary": scenario_summary(scenarios),
        "proxy_calibration": calibration_meta,
        "metrics": metrics,
        "metadata_path": str(run_dir / "metadata.json"),
    }
    model_path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_voltage_sac_train",
        config={
            "steps": args.steps,
            "n_envs": args.n_envs,
            "seed": args.seed,
            "run_id": run_id,
            "curriculum": args.curriculum,
            "init_model": str(args.init_model) if args.init_model is not None else None,
            "model_out": str(args.model_out),
            "eval_rollouts": args.eval_rollouts,
            "export": bool(args.export),
            "export_out": str(args.export_out),
            "safety_classifier": str(args.safety_classifier) if args.safety_classifier else None,
            "safety_penalty_weight": args.safety_penalty_weight,
            "safety_unsafe_terminal": bool(args.safety_unsafe_terminal),
            "reg_limit": args.reg_limit,
            "energy_limit": args.energy_limit,
            "teacher_prior_weight": args.teacher_prior_weight,
            "observation_dim": OBS_DIM_HPT,
            "action_dim": ACT_DIM_HPT,
        },
        topology_models=TOPOLOGY_MODELS,
        policy_checkpoint=model_path,
        extra={
            "summary_path": str(run_dir / "summary.json"),
            "model_sidecar_path": str(model_path.with_suffix(".json")),
            "proxy_calibration": calibration_meta,
        },
    )

    if args.export:
        export_hpt_actor(model_path, args.export_out)

    print(json.dumps(sidecar, indent=2), flush=True)


if __name__ == "__main__":
    main()
