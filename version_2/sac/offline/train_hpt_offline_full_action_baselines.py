"""Train offline full-action HPT baselines from the boundary action dataset.

The current boundary dataset is a contextual action table, not a per-step
transition replay buffer.  This script therefore implements honest offline
controller baselines:

* ``td3_bc_style``: imitate the best switch-evidence action while staying close
  to the conventional DQ action, matching the spirit of TD3+BC's behavior
  constraint.
* ``awac_style``: advantage-weighted behavior cloning over all candidate
  actions, matching the practical data weighting used by IQL/AWAC-style
  offline policies when only ranked action evidence is available.
* ``success_bc_style``: imitate only nearby switch-evidence actions that pass
  and improve over the conventional baseline, useful when the feasible action
  region is a narrow island.
* ``bc_conventional``: reproduce the conventional DQ action as a sanity check.

Each trained policy maps a fault/topology/time context to the final direct
action ``[m_reg_d, m_reg_q, m_energy_d, m_energy_q]``.  In ``trajectory`` mode
the same actor is queried at every 2-ms control step, so the specialist learns
the action schedule instead of only one fixed action point.
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
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpt_frt.device.train_common import pick_device

from version_2.sac.experiment_metadata import write_experiment_metadata
from version_2.sac.hpt_voltage_sac_env import ACT_DIM_HPT, HPTVoltageEnvConfig, HPTVoltageSACEnv
from version_2.sac.offline.train_hpt_fault_specialists_vs_baseline import (
    BaselineCase,
    EvalMetrics,
    TOPOLOGY_MODELS,
    beats_sac_over_baseline,
    evaluate_proxy_case,
    scenario_from_case,
    score_metrics,
    voltage_survival_pass,
)


RESULTS = ROOT / "lab" / "results"
DATA_ROOT = ROOT / "version_2" / "data" / "hpt_boundary_full_action"
MODELS = ROOT / "data" / "models" / "hpt_offline_full_action"

ACTION_COLUMNS = [
    "action_m_reg_d",
    "action_m_reg_q",
    "action_m_energy_d",
    "action_m_energy_q",
]

CONTEXT_NAMES = [
    "topology1",
    "topology2",
    "is_lvrt",
    "is_hvrt",
    "fault_pu",
    "fault_depth",
    "duration_s",
    "fault_start_s",
    "stop_time_s",
    "is_asymmetric",
    "is_symmetric",
    "t_s",
    "t_norm",
    "in_fault_window",
    "in_recovery_window",
    "time_to_clear_norm",
]


@dataclass(frozen=True)
class TrainingSample:
    context: np.ndarray
    target: np.ndarray
    conventional: np.ndarray
    weight: float
    source_role: str
    case_name: str
    case_row: dict[str, Any] | None = None


@dataclass
class AlgorithmSummary:
    algorithm: str
    model_path: str
    train_elapsed_s: float
    train_loss_last: float
    eval_cases: int
    baseline_pass_n: int
    policy_pass_n: int
    beat_n: int
    improved_n: int
    viable: bool


def read_csv(path: Path) -> list[dict[str, Any]]:
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


def latest_dataset_csv(root: Path = DATA_ROOT) -> Path:
    files = sorted(root.glob("*/dataset.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No boundary full-action dataset.csv found under {root}")
    return files[-1]


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


def finite(value: float, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def category(row: dict[str, Any]) -> str:
    value = s(row, "category")
    if value:
        return value
    return "LVRT" if f(row, "fault_pu", 1.0) < 1.0 else "HVRT"


def severity(row: dict[str, Any]) -> float:
    pu = f(row, "fault_pu", 1.0)
    return 1.0 - pu if pu < 1.0 else pu - 1.0


def action_from_row(row: dict[str, Any]) -> np.ndarray:
    return np.asarray([finite(f(row, key), 0.0) for key in ACTION_COLUMNS], dtype=np.float32)


def context_from_row(row: dict[str, Any], *, t_s: float | None = None) -> np.ndarray:
    topology = s(row, "topology")
    cat = category(row)
    condition = s(row, "condition_class").lower()
    is_asym = any(token in condition for token in ("asym", "1ph", "2ph", "neg"))
    fault_start = finite(f(row, "fault_start_s"), 0.035)
    duration = finite(f(row, "fault_duration_s"), 0.08)
    fault_clear = fault_start + duration
    stop_time = finite(f(row, "stop_time_s"), fault_clear + 0.125)
    if t_s is None:
        t_value = fault_start + 0.5 * duration
    else:
        t_value = float(t_s)
    t_norm = t_value / max(stop_time, 1e-9)
    in_fault = float(fault_start <= t_value <= fault_clear)
    in_recovery = float(t_value > fault_clear)
    time_to_clear = (fault_clear - t_value) / max(duration, 1e-9)
    return np.asarray(
        [
            1.0 if topology == "topology1" else 0.0,
            1.0 if topology == "topology2" else 0.0,
            1.0 if cat == "LVRT" else 0.0,
            1.0 if cat == "HVRT" else 0.0,
            finite(f(row, "fault_pu"), 1.0),
            finite(f(row, "fault_depth"), severity(row)),
            duration,
            fault_start,
            stop_time,
            1.0 if is_asym else 0.0,
            0.0 if is_asym else 1.0,
            t_value,
            t_norm,
            in_fault,
            in_recovery,
            float(np.clip(time_to_clear, -1.0, 1.0)),
        ],
        dtype=np.float32,
    )


def row_score(row: dict[str, Any]) -> float:
    value = f(row, "survival_score", float("nan"))
    if math.isfinite(value):
        return value
    pass_ok = b(row, "voltage_survival_pass")
    score = 0.0 if pass_ok else 100.0
    score += abs(finite(f(row, "lv_fault_rms_mean"), 207.0) - 207.0) / 5.0
    score += abs(finite(f(row, "lv_recovery_rms_mean"), 207.0) - 207.0) / 5.0
    score += max(0.0, finite(f(row, "vdc_max"), 800.0) - 1000.0) / 10.0
    score += max(0.0, 650.0 - finite(f(row, "vdc_min"), 800.0)) / 10.0
    return float(score)


def candidate_rank(row: dict[str, Any]) -> float:
    score = row_score(row)
    if b(row, "voltage_survival_pass"):
        score -= 25.0
    if b(row, "full_frt_pass"):
        score -= 20.0
    score += 0.2 * float(np.max(np.abs(action_from_row(row))))
    return float(score)


def baseline_metric_from_row(row: dict[str, Any]) -> EvalMetrics:
    metrics = EvalMetrics(
        topology=s(row, "topology"),
        category=category(row),
        duration_ms=int(round(1000.0 * finite(f(row, "fault_duration_s"), 0.0))),
        case_name=s(row, "case_name"),
        fault_pu=finite(f(row, "fault_pu"), 1.0),
        pass_flag=b(row, "voltage_survival_pass"),
        reason=s(row, "reason"),
        score=0.0,
        lv_mean=finite(f(row, "lv_fault_rms_mean"), float("nan")),
        lv_recovery_mean=finite(f(row, "lv_recovery_rms_mean"), float("nan")),
        lv_peak=finite(f(row, "lv_peak_rms"), float("nan")),
        lv_min=finite(f(row, "lv_min_rms"), float("nan")),
        vdc_min=finite(f(row, "vdc_min"), float("nan")),
        vdc_max=finite(f(row, "vdc_max"), float("nan")),
        action_max_abs=finite(f(row, "action_max_abs"), 0.0),
        grid_iq_shortfall_max_pu=finite(f(row, "grid_iq_shortfall_max_pu"), 0.0),
        grid_current_peak_pu=finite(f(row, "grid_current_peak_pu"), 0.0),
        grid_iq_wrong_sign=b(row, "grid_iq_wrong_sign"),
        envelope_violation_max_pu=finite(f(row, "envelope_violation_max_pu"), 0.0),
        envelope_violation_duration_s=finite(f(row, "envelope_violation_duration_s"), 0.0),
        recovery_violation_max_pu=finite(f(row, "recovery_violation_max_pu"), 0.0),
        recovery_violation_duration_s=finite(f(row, "recovery_violation_duration_s"), 0.0),
    )
    metrics.score = score_metrics(metrics)
    return metrics


def filter_rows(
    rows: Iterable[dict[str, Any]],
    *,
    topology: str,
    category_filter: str,
    duration_ms: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if topology != "all" and s(row, "topology") != topology:
            continue
        if category_filter != "all" and category(row) != category_filter:
            continue
        if duration_ms is not None:
            row_duration = int(round(1000.0 * finite(f(row, "fault_duration_s"), 0.0)))
            if row_duration != duration_ms:
                continue
        out.append(row)
    return out


def nearest_candidate(conv: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    bucket = [
        row
        for row in candidates
        if s(row, "topology") == s(conv, "topology") and category(row) == category(conv)
    ]
    if not bucket:
        return None
    conv_pu = finite(f(conv, "fault_pu"), 1.0)
    conv_dur = finite(f(conv, "fault_duration_s"), 0.08)

    def key(row: dict[str, Any]) -> tuple[float, float]:
        dist = 30.0 * abs(finite(f(row, "fault_pu"), conv_pu) - conv_pu)
        dist += 4.0 * abs(finite(f(row, "fault_duration_s"), conv_dur) - conv_dur)
        return (dist, candidate_rank(row))

    close = sorted(bucket, key=key)
    nearest_dist = key(close[0])[0]
    near_bucket = [row for row in close if key(row)[0] <= nearest_dist + 0.25]
    return min(near_bucket, key=candidate_rank)


def build_best_pairs(
    conventional_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for conv in conventional_rows:
        cand = nearest_candidate(conv, candidate_rows)
        conv_score = row_score(conv)
        cand_score = row_score(cand) if cand is not None else conv_score
        improvement = conv_score - cand_score
        pairs.append(
            {
                "conventional": conv,
                "candidate": cand,
                "conventional_score": conv_score,
                "candidate_score": cand_score,
                "candidate_rank": candidate_rank(cand) if cand is not None else conv_score,
                "improvement": improvement,
            }
        )
    return pairs


def make_td3_bc_style_samples(pairs: list[dict[str, Any]]) -> list[TrainingSample]:
    samples: list[TrainingSample] = []
    for pair in pairs:
        conv = pair["conventional"]
        cand = pair["candidate"]
        use_candidate = False
        if cand is not None:
            candidate_turns_fail_to_pass = (
                b(cand, "voltage_survival_pass") and not b(conv, "voltage_survival_pass")
            )
            candidate_score_improves = float(pair["candidate_score"]) + 1e-6 < float(
                pair["conventional_score"]
            )
            use_candidate = bool(candidate_turns_fail_to_pass or candidate_score_improves)
        target = action_from_row(cand) if use_candidate and cand is not None else action_from_row(conv)
        conv_action = action_from_row(conv)
        weight = 1.0
        if use_candidate and cand is not None and b(cand, "voltage_survival_pass") and not b(conv, "voltage_survival_pass"):
            weight = 4.0
        elif use_candidate and pair["improvement"] > 0.0:
            weight = 1.5 + min(2.0, pair["improvement"] / 50.0)
        samples.append(
            TrainingSample(
                context=context_from_row(conv),
                target=target,
                conventional=conv_action,
                weight=float(weight),
                source_role=s(cand or conv, "role"),
                case_name=s(conv, "case_name"),
                case_row=conv,
            )
        )
    return samples


def make_success_bc_style_samples(
    conventional_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    top_k: int = 6,
) -> list[TrainingSample]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in candidate_rows:
        grouped.setdefault((s(row, "topology"), category(row)), []).append(row)

    samples: list[TrainingSample] = []
    for conv in conventional_rows:
        conv_action = action_from_row(conv)
        conv_score = row_score(conv)
        conv_pu = finite(f(conv, "fault_pu"), 1.0)
        conv_dur = finite(f(conv, "fault_duration_s"), 0.08)
        bucket = grouped.get((s(conv, "topology"), category(conv)), [])
        nearby: list[tuple[float, dict[str, Any]]] = []
        for row in bucket:
            if not b(row, "voltage_survival_pass"):
                continue
            score = row_score(row)
            if score + 1e-6 >= conv_score:
                continue
            dist = 30.0 * abs(finite(f(row, "fault_pu"), conv_pu) - conv_pu)
            dist += 4.0 * abs(finite(f(row, "fault_duration_s"), conv_dur) - conv_dur)
            if dist > 0.75:
                continue
            nearby.append((score + 0.05 * dist, row))
        if nearby:
            for _, row in sorted(nearby, key=lambda item: item[0])[: max(1, int(top_k))]:
                improvement = max(0.0, conv_score - row_score(row))
                samples.append(
                    TrainingSample(
                        context=context_from_row(conv),
                        target=action_from_row(row),
                        conventional=conv_action,
                        weight=float(4.0 + min(6.0, improvement / 20.0)),
                        source_role=s(row, "role"),
                        case_name=s(conv, "case_name"),
                        case_row=conv,
                    )
                )
        else:
            samples.append(
                TrainingSample(
                    context=context_from_row(conv),
                    target=conv_action,
                    conventional=conv_action,
                    weight=0.25,
                    source_role="conventional_fallback",
                    case_name=s(conv, "case_name"),
                    case_row=conv,
                )
            )
    return samples


def make_bc_conventional_samples(conventional_rows: list[dict[str, Any]]) -> list[TrainingSample]:
    return [
        TrainingSample(
            context=context_from_row(row),
            target=action_from_row(row),
            conventional=action_from_row(row),
            weight=1.0,
            source_role=s(row, "role"),
            case_name=s(row, "case_name"),
            case_row=row,
        )
        for row in conventional_rows
    ]


def make_awac_style_samples(
    conventional_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    temperature: float,
    behavior_weight: float,
) -> list[TrainingSample]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in candidate_rows:
        grouped.setdefault((s(row, "topology"), category(row)), []).append(row)

    samples: list[TrainingSample] = []
    for conv in conventional_rows:
        group = grouped.get((s(conv, "topology"), category(conv)), [])
        if not group:
            continue
        conv_pu = finite(f(conv, "fault_pu"), 1.0)
        near = sorted(
            group,
            key=lambda row: abs(finite(f(row, "fault_pu"), conv_pu) - conv_pu),
        )[:80]
        if not near:
            continue
        best_rank = min(candidate_rank(row) for row in near)
        conv_score = row_score(conv)
        conv_pass = b(conv, "voltage_survival_pass")
        conv_action = action_from_row(conv)
        for row in near:
            if conv_pass and not b(row, "voltage_survival_pass") and row_score(row) > conv_score:
                continue
            if not conv_pass and row_score(row) > conv_score + 25.0:
                continue
            advantage = best_rank - candidate_rank(row)
            weight = float(np.clip(np.exp(advantage / max(temperature, 1e-6)), 0.02, 8.0))
            samples.append(
                TrainingSample(
                    context=context_from_row(conv),
                    target=action_from_row(row),
                    conventional=conv_action,
                    weight=weight,
                    source_role=s(row, "role"),
                    case_name=s(conv, "case_name"),
                    case_row=conv,
                )
            )
        samples.append(
            TrainingSample(
                context=context_from_row(conv),
                target=conv_action,
                conventional=conv_action,
                weight=float(behavior_weight),
                source_role="conventional_anchor",
                case_name=s(conv, "case_name"),
                case_row=conv,
            )
        )
    return samples


def scheduled_action(
    target: np.ndarray,
    conventional: np.ndarray,
    row: dict[str, Any],
    *,
    t_s: float,
    ramp_s: float,
    post_fault_hold_s: float,
) -> np.ndarray:
    """Convert one target action into a smooth fault-window trajectory target."""

    target = np.asarray(target, dtype=np.float32)
    conventional = np.asarray(conventional, dtype=np.float32)
    fault_start = finite(f(row, "fault_start_s"), 0.035)
    duration = finite(f(row, "fault_duration_s"), 0.08)
    fault_clear = fault_start + duration
    ramp = max(float(ramp_s), 1e-6)
    hold_end = fault_clear + max(0.0, float(post_fault_hold_s))
    t = float(t_s)
    base = np.zeros(ACT_DIM_HPT, dtype=np.float32)
    if t < fault_start:
        return base
    if t < fault_start + ramp:
        frac = (t - fault_start) / ramp
        return (base + frac * (target - base)).astype(np.float32)
    if t <= hold_end:
        return target.astype(np.float32)
    if t < hold_end + ramp:
        frac = 1.0 - (t - hold_end) / ramp
        return (base + frac * (target - base)).astype(np.float32)
    # Leave a tiny conventional anchor in the final tail if the original
    # baseline needed nonzero energy/current bias after clearing.
    return (0.10 * conventional).astype(np.float32)


def expand_samples_to_trajectory(
    samples: list[TrainingSample],
    *,
    decision_dt: float,
    ramp_s: float,
    post_fault_hold_s: float,
    max_points_per_case: int,
) -> list[TrainingSample]:
    out: list[TrainingSample] = []
    for sample in samples:
        row = sample.case_row
        if row is None:
            out.append(sample)
            continue
        stop_time = finite(f(row, "stop_time_s"), finite(f(row, "fault_start_s"), 0.035) + finite(f(row, "fault_duration_s"), 0.08) + 0.125)
        n = int(np.floor(stop_time / max(decision_dt, 1e-9))) + 1
        if max_points_per_case > 0:
            n = min(n, int(max_points_per_case))
        for idx in range(n):
            t_value = idx * decision_dt
            out.append(
                TrainingSample(
                    context=context_from_row(row, t_s=t_value),
                    target=scheduled_action(
                        sample.target,
                        sample.conventional,
                        row,
                        t_s=t_value,
                        ramp_s=ramp_s,
                        post_fault_hold_s=post_fault_hold_s,
                    ),
                    conventional=scheduled_action(
                        sample.conventional,
                        sample.conventional,
                        row,
                        t_s=t_value,
                        ramp_s=ramp_s,
                        post_fault_hold_s=post_fault_hold_s,
                    ),
                    weight=sample.weight,
                    source_role=sample.source_role + "_trajectory",
                    case_name=sample.case_name,
                    case_row=row,
                )
            )
    return out


class ContextActor(nn.Module):
    def __init__(
        self,
        obs_dim: int,
        hidden: int,
        action_scale: np.ndarray,
        *,
        controller_heads: str = "split",
    ):
        super().__init__()
        self.controller_heads = str(controller_heads)
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        if self.controller_heads == "shared":
            self.action_head = nn.Sequential(
                nn.Linear(hidden, ACT_DIM_HPT),
                nn.Tanh(),
            )
            self.reg_head = None
            self.energy_head = None
        elif self.controller_heads == "split":
            self.action_head = None
            self.reg_head = nn.Sequential(
                nn.Linear(hidden, hidden // 2 if hidden >= 64 else hidden),
                nn.ReLU(),
                nn.Linear(hidden // 2 if hidden >= 64 else hidden, 2),
                nn.Tanh(),
            )
            self.energy_head = nn.Sequential(
                nn.Linear(hidden, hidden // 2 if hidden >= 64 else hidden),
                nn.ReLU(),
                nn.Linear(hidden // 2 if hidden >= 64 else hidden, 2),
                nn.Tanh(),
            )
        else:
            raise ValueError("controller_heads must be 'split' or 'shared'")
        self.register_buffer("action_scale", torch.as_tensor(action_scale, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.trunk(x)
        if self.controller_heads == "shared":
            raw = self.action_head(z)
        else:
            assert self.reg_head is not None and self.energy_head is not None
            raw = torch.cat([self.reg_head(z), self.energy_head(z)], dim=-1)
        return raw * self.action_scale


class LegacySharedContextActor(nn.Module):
    """Old single-head actor kept only for loading older diagnostic checkpoints."""

    def __init__(self, obs_dim: int, hidden: int, action_scale: np.ndarray):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, ACT_DIM_HPT),
            nn.Tanh(),
        )
        self.register_buffer("action_scale", torch.as_tensor(action_scale, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x) * self.action_scale


class OfflinePolicy:
    def __init__(self, model: ContextActor, x_mean: np.ndarray, x_std: np.ndarray, device: torch.device):
        self.model = model
        self.x_mean = x_mean.astype(np.float32)
        self.x_std = x_std.astype(np.float32)
        self.device = device

    def action_for_context(self, context: np.ndarray) -> np.ndarray:
        x = (context.astype(np.float32) - self.x_mean) / self.x_std
        with torch.no_grad():
            y = self.model(torch.as_tensor(x[None, :], dtype=torch.float32, device=self.device))
        return y.detach().cpu().numpy()[0].astype(np.float32)


class ConstantActionAdapter:
    def __init__(self, action: np.ndarray):
        self.action = np.asarray(action, dtype=np.float32)

    def predict(self, _obs: np.ndarray, deterministic: bool = True) -> tuple[np.ndarray, None]:
        return self.action.copy(), None


def evaluate_context_policy_case(
    policy: OfflinePolicy,
    row: dict[str, Any],
    *,
    env_config: HPTVoltageEnvConfig,
    trajectory: bool,
) -> tuple[EvalMetrics, np.ndarray]:
    """Evaluate an offline context policy as constant or per-step trajectory."""

    case = BaselineCase(row)
    scenario = scenario_from_case(case)
    env = HPTVoltageSACEnv([scenario], config=env_config, seed=0, train_mode=False)
    obs, _ = env.reset()
    done = False
    rows: list[dict[str, Any]] = []
    first_action: np.ndarray | None = None
    constant_action = policy.action_for_context(context_from_row(row))
    while not done:
        action = (
            policy.action_for_context(context_from_row(row, t_s=env.t))
            if trajectory
            else constant_action
        )
        if first_action is None:
            first_action = np.asarray(action, dtype=np.float32).copy()
        obs, _reward, terminated, truncated, info = env.step(action)
        rows.append(
            {
                "t": float(env.t),
                "v_lv": float(info["v_lv_pu"]) * env_config.v_ref_phase_rms,
                "vdc": float(info["vdc_pu"]) * env_config.vdc_ref,
                "action": np.asarray(info["action"], dtype=float),
                "grid_iq_shortfall": float(info["grid_iq_shortfall_pu"]),
                "grid_current_peak": float(info["grid_current_peak_pu"]),
                "grid_wrong_sign": bool(info["grid_reactive_wrong_sign"]),
                "support_violation": float(info.get("calibration_support_violation", 0.0)),
                "survival_violation": float(info.get("calibrated_survival_violation", 0.0)),
                "envelope_violation": float(info.get("envelope_violation_max_pu", 0.0)),
                "envelope_duration": float(info.get("envelope_violation_duration_s", 0.0)),
                "recovery_violation": float(info.get("recovery_violation_max_pu", 0.0)),
                "recovery_duration": float(info.get("recovery_violation_duration_s", 0.0)),
                "teacher_gap": float(info.get("teacher_gap", 0.0)),
            }
        )
        done = bool(terminated or truncated)

    if not rows:
        raise RuntimeError("Empty proxy rollout")
    t = np.asarray([r["t"] for r in rows], dtype=float)
    fault_start = scenario.fault_start_s
    fault_clear = scenario.fault_start_s + float(scenario.fault_duration_s or case.duration_s)
    fault_idx = (t >= fault_start) & (t <= fault_clear)
    recovery_idx = t >= fault_clear
    v_all = np.asarray([r["v_lv"] for r in rows], dtype=float)
    vdc_all = np.asarray([r["vdc"] for r in rows], dtype=float)
    action_all = np.asarray([r["action"] for r in rows], dtype=float)
    fault_values = v_all[fault_idx] if np.any(fault_idx) else v_all
    recovery_values = v_all[recovery_idx] if np.any(recovery_idx) else v_all
    metrics = EvalMetrics(
        topology=case.topology,
        category=case.category,
        duration_ms=case.duration_ms,
        case_name=case.case_name,
        fault_pu=case.fault_pu,
        pass_flag=False,
        reason="",
        score=0.0,
        lv_mean=float(np.mean(fault_values)),
        lv_recovery_mean=float(np.mean(recovery_values)),
        lv_peak=float(np.max(v_all)),
        lv_min=float(np.min(v_all)),
        vdc_min=float(np.min(vdc_all)),
        vdc_max=float(np.max(vdc_all)),
        action_max_abs=float(np.max(np.abs(action_all))),
        grid_iq_shortfall_max_pu=float(np.max([r["grid_iq_shortfall"] for r in rows])),
        grid_current_peak_pu=float(np.max([r["grid_current_peak"] for r in rows])),
        grid_iq_wrong_sign=any(bool(r["grid_wrong_sign"]) for r in rows),
        calibration_support_violation=float(np.max([r["support_violation"] for r in rows])),
        calibrated_survival_violation=float(np.max([r["survival_violation"] for r in rows])),
        action_reg_d_mean=float(np.mean(action_all[:, 0])),
        action_reg_q_mean=float(np.mean(action_all[:, 1])),
        action_energy_d_mean=float(np.mean(action_all[:, 2])),
        action_energy_q_mean=float(np.mean(action_all[:, 3])),
        action_reg_d_abs_max=float(np.max(np.abs(action_all[:, 0]))),
        action_reg_q_abs_max=float(np.max(np.abs(action_all[:, 1]))),
        action_energy_d_abs_max=float(np.max(np.abs(action_all[:, 2]))),
        action_energy_q_abs_max=float(np.max(np.abs(action_all[:, 3]))),
        teacher_gap_mean=float(np.mean([r["teacher_gap"] for r in rows])),
        teacher_gap_max=float(np.max([r["teacher_gap"] for r in rows])),
        envelope_violation_max_pu=float(np.max([r["envelope_violation"] for r in rows])),
        envelope_violation_duration_s=float(np.max([r["envelope_duration"] for r in rows])),
        recovery_violation_max_pu=float(np.max([r["recovery_violation"] for r in rows])),
        recovery_violation_duration_s=float(np.max([r["recovery_duration"] for r in rows])),
    )
    metrics.pass_flag, metrics.reason = voltage_survival_pass(metrics)
    metrics.score = score_metrics(metrics)
    return metrics, (first_action if first_action is not None else constant_action)


def train_policy(
    samples: list[TrainingSample],
    *,
    algorithm: str,
    model_tag: str,
    run_dir: Path,
    epochs: int,
    batch_size: int,
    lr: float,
    behavior_alpha: float,
    seed: int,
    action_scale: np.ndarray,
    hidden: int,
    controller_heads: str,
) -> tuple[OfflinePolicy, Path, float, float]:
    if not samples:
        raise RuntimeError(f"No training samples for {algorithm}")
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    contexts = np.asarray([sample.context for sample in samples], dtype=np.float32)
    targets = np.asarray([sample.target for sample in samples], dtype=np.float32)
    conventional = np.asarray([sample.conventional for sample in samples], dtype=np.float32)
    weights = np.asarray([sample.weight for sample in samples], dtype=np.float32)

    x_mean = contexts.mean(axis=0)
    x_std = contexts.std(axis=0)
    x_std[x_std < 1e-6] = 1.0
    x_norm = (contexts - x_mean) / x_std

    order = rng.permutation(len(x_norm))
    dataset = TensorDataset(
        torch.as_tensor(x_norm[order], dtype=torch.float32),
        torch.as_tensor(targets[order], dtype=torch.float32),
        torch.as_tensor(conventional[order], dtype=torch.float32),
        torch.as_tensor(weights[order], dtype=torch.float32),
    )
    loader = DataLoader(dataset, batch_size=max(1, batch_size), shuffle=True)
    device = torch.device(pick_device())
    action_scale = np.asarray(action_scale, dtype=np.float32)
    if action_scale.shape != (ACT_DIM_HPT,):
        raise RuntimeError(f"Bad action_scale shape: {action_scale.shape}")
    model = ContextActor(
        contexts.shape[1],
        hidden,
        action_scale,
        controller_heads=controller_heads,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    last_loss = float("nan")
    start = time.time()
    for _epoch in range(max(1, epochs)):
        for xb, yb, cb, wb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            cb = cb.to(device)
            wb = wb.to(device).view(-1, 1)
            pred = model(xb)
            imitate = ((pred - yb) ** 2).mean(dim=1, keepdim=True)
            behavior = ((pred - cb) ** 2).mean(dim=1, keepdim=True)
            loss = (wb * imitate).mean() + float(behavior_alpha) * behavior.mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            last_loss = float(loss.detach().cpu().item())
    elapsed = time.time() - start

    model_path = MODELS / f"{run_dir.name}_{model_tag}_{algorithm}.pt"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema": "hpt-offline-context-actor-v2",
            "algorithm": algorithm,
            "controller_heads": controller_heads,
            "context_names": CONTEXT_NAMES,
            "action_columns": ACTION_COLUMNS,
            "x_mean": x_mean,
            "x_std": x_std,
            "action_scale": action_scale,
            "state_dict": model.state_dict(),
            "config": {
                "epochs": epochs,
                "batch_size": batch_size,
                "lr": lr,
                "behavior_alpha": behavior_alpha,
                "hidden": hidden,
                "seed": seed,
                "action_scale": action_scale.tolist(),
                "controller_heads": controller_heads,
            },
        },
        model_path,
    )
    return OfflinePolicy(model, x_mean, x_std, device), model_path, elapsed, last_loss


def evaluate_policy(
    *,
    algorithm: str,
    policy: OfflinePolicy,
    conventional_rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    env_config: HPTVoltageEnvConfig,
    trajectory: bool,
) -> tuple[AlgorithmSummary, list[dict[str, Any]]]:
    pair_by_case = {id(pair["conventional"]): pair for pair in pairs}
    case_rows: list[dict[str, Any]] = []
    baseline_pass_n = 0
    policy_pass_n = 0
    beat_n = 0
    improved_n = 0
    for row in conventional_rows:
        baseline = baseline_metric_from_row(row)
        proxy, first_action = evaluate_context_policy_case(
            policy,
            row,
            env_config=env_config,
            trajectory=trajectory,
        )
        action = policy.action_for_context(context_from_row(row))
        beat = beats_sac_over_baseline(proxy, baseline)
        improved = proxy.score < baseline.score
        baseline_pass_n += int(baseline.pass_flag)
        policy_pass_n += int(proxy.pass_flag)
        beat_n += int(beat)
        improved_n += int(improved)
        pair = pair_by_case.get(id(row), {})
        cand = pair.get("candidate")
        case_rows.append(
            {
                "algorithm": algorithm,
                "topology": s(row, "topology"),
                "category": category(row),
                "duration_ms": int(round(1000.0 * finite(f(row, "fault_duration_s"), 0.0))),
                "case_name": s(row, "case_name"),
                "fault_pu": finite(f(row, "fault_pu"), 1.0),
                "baseline_pass": baseline.pass_flag,
                "baseline_score": baseline.score,
                "baseline_reason": baseline.reason,
                "best_candidate_role": s(cand or {}, "role"),
                "best_candidate_pass": b(cand or {}, "voltage_survival_pass"),
                "best_candidate_score": row_score(cand) if cand is not None else float("nan"),
                "policy_pass": proxy.pass_flag,
                "policy_score": proxy.score,
                "policy_reason": proxy.reason,
                "policy_lv_mean": proxy.lv_mean,
                "policy_lv_recovery_mean": proxy.lv_recovery_mean,
                "policy_vdc_min": proxy.vdc_min,
                "policy_vdc_max": proxy.vdc_max,
                "policy_envelope_violation_max_pu": proxy.envelope_violation_max_pu,
                "policy_envelope_violation_duration_s": proxy.envelope_violation_duration_s,
                "policy_recovery_violation_max_pu": proxy.recovery_violation_max_pu,
                "policy_recovery_violation_duration_s": proxy.recovery_violation_duration_s,
                "policy_grid_iq_shortfall_max_pu": proxy.grid_iq_shortfall_max_pu,
                "policy_grid_current_peak_pu": proxy.grid_current_peak_pu,
                "policy_calibration_support_violation": proxy.calibration_support_violation,
                "policy_calibrated_survival_violation": proxy.calibrated_survival_violation,
                "action_m_reg_d": float(action[0]),
                "action_m_reg_q": float(action[1]),
                "action_m_energy_d": float(action[2]),
                "action_m_energy_q": float(action[3]),
                "first_step_m_reg_d": float(first_action[0]),
                "first_step_m_reg_q": float(first_action[1]),
                "first_step_m_energy_d": float(first_action[2]),
                "first_step_m_energy_q": float(first_action[3]),
                "action_max_abs": float(np.max(np.abs(action))),
                "deployment_mode": "trajectory" if trajectory else "constant",
                "beat": beat,
                "improved": improved,
            }
        )
    summary = AlgorithmSummary(
        algorithm=algorithm,
        model_path="",
        train_elapsed_s=0.0,
        train_loss_last=float("nan"),
        eval_cases=len(conventional_rows),
        baseline_pass_n=baseline_pass_n,
        policy_pass_n=policy_pass_n,
        beat_n=beat_n,
        improved_n=improved_n,
        viable=bool(beat_n > 0 and policy_pass_n >= baseline_pass_n),
    )
    return summary, case_rows


def make_active_sampling_rows(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in case_rows:
        if row.get("policy_pass") in {True, "True", "true", "1"}:
            continue
        reason = str(row.get("policy_reason", ""))
        if not reason:
            reason = "policy_failed_proxy_gate"
        out.append(
            {
                "algorithm": row["algorithm"],
                "topology": row["topology"],
                "category": row["category"],
                "duration_ms": row["duration_ms"],
                "case_name": row["case_name"],
                "fault_pu": row["fault_pu"],
                "action_m_reg_d": row["action_m_reg_d"],
                "action_m_reg_q": row["action_m_reg_q"],
                "action_m_energy_d": row["action_m_energy_d"],
                "action_m_energy_q": row["action_m_energy_q"],
                "reason": reason,
                "priority": float(row["policy_score"]) - float(row["baseline_score"]),
            }
        )
    return sorted(out, key=lambda r: float(r["priority"]), reverse=True)


def write_report(
    run_dir: Path,
    *,
    dataset_csv: Path,
    summaries: list[AlgorithmSummary],
    case_rows: list[dict[str, Any]],
    active_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# HPT Full-Action Offline Baselines",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Dataset: `{dataset_csv}`",
        f"- Algorithms: `{', '.join(summary.algorithm for summary in summaries)}`",
        "",
        "## Summary",
        "",
        "| Algorithm | Cases | Baseline Pass | Policy Pass | Beat | Improved | Viable | Loss | Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            f"| `{summary.algorithm}` | {summary.eval_cases} | {summary.baseline_pass_n} | "
            f"{summary.policy_pass_n} | {summary.beat_n} | {summary.improved_n} | "
            f"{summary.viable} | {summary.train_loss_last:.6f} | {summary.train_elapsed_s:.1f}s |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `td3_bc_style` is the first fallback target: it learns from best switch-evidence actions but keeps an explicit penalty toward conventional DQ behavior.",
            "- `awac_style` is the second fallback: it uses all nearby candidate actions with advantage-like weights, so the model can learn a smoother action surface.",
            "- `success_bc_style` learns only nearby switch-evidence actions that pass and improve over conventional, intended for narrow feasible islands.",
            "- `bc_conventional` is only a sanity check.  It should reproduce the traditional baseline and is not expected to beat it.",
            "- A row is `viable` only when it beats conventional on at least one case and does not reduce the number of passed cases in this proxy gate.",
            "",
            "## Case Details",
            "",
        ]
    )
    for row in case_rows:
        lines.append(
            f"- `{row['algorithm']}` `{row['case_name']}`: conventional "
            f"`{row['baseline_pass']}` score `{float(row['baseline_score']):.3f}` -> "
            f"policy `{row['policy_pass']}` score `{float(row['policy_score']):.3f}`, "
            f"beat `{row['beat']}`, action "
            f"`[{float(row['action_m_reg_d']):.3f}, {float(row['action_m_reg_q']):.3f}, "
            f"{float(row['action_m_energy_d']):.3f}, {float(row['action_m_energy_q']):.3f}]`, "
            f"reason `{row['policy_reason']}`"
        )
    if active_rows:
        lines.extend(
            [
                "",
                "## Active-Sampling Candidates",
                "",
                f"- Failed proxy-evaluation actions exported: `{len(active_rows)}`",
                "- These are the next switch-level cases to simulate if no offline baseline is viable.",
            ]
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def parse_algorithms(value: str) -> list[str]:
    if value.strip().lower() == "auto":
        return ["td3_bc_style", "awac_style", "bc_conventional"]
    allowed = {"td3_bc_style", "awac_style", "success_bc_style", "bc_conventional"}
    out = [item.strip() for item in value.split(",") if item.strip()]
    bad = [item for item in out if item not in allowed]
    if bad:
        raise argparse.ArgumentTypeError(f"Unknown algorithms: {bad}; allowed: {sorted(allowed)}")
    return out


def parse_duration_ms(value: str) -> int | None:
    text = str(value).strip().lower()
    if text in {"all", "none", "*", "-1"}:
        return None
    return int(text)


def fault_token(row: dict[str, Any]) -> str:
    pu = finite(f(row, "fault_pu"), 1.0)
    return f"{pu:.3f}pu".replace(".", "p")


def group_tag(row: dict[str, Any], *, include_fault: bool = False) -> str:
    duration_ms = int(round(1000.0 * finite(f(row, "fault_duration_s"), 0.0)))
    tag = f"{s(row, 'topology')}_{category(row).lower()}_{duration_ms}ms"
    if include_fault:
        tag += f"_{fault_token(row)}"
    return tag


def grouped_conventional_rows(
    conventional_rows: list[dict[str, Any]],
    *,
    include_fault: bool = False,
) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in conventional_rows:
        groups.setdefault(group_tag(row, include_fault=include_fault), []).append(row)
    return [(tag, sorted(items, key=severity)) for tag, items in sorted(groups.items())]


def run_algorithm_sequence(
    *,
    group_label: str,
    conventional_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    run_dir: Path,
    algorithms: list[str],
    auto_requested: bool,
    args: argparse.Namespace,
    env_config: HPTVoltageEnvConfig,
) -> tuple[list[AlgorithmSummary], list[dict[str, Any]], bool]:
    pairs = build_best_pairs(conventional_rows, candidate_rows)
    summaries: list[AlgorithmSummary] = []
    case_rows_out: list[dict[str, Any]] = []
    viable_found = False
    safe_group_label = group_label.replace("/", "_").replace("\\", "_").replace(" ", "_")
    action_scale = np.asarray(
        [
            env_config.reg_d_limit,
            env_config.reg_q_limit,
            env_config.energy_d_limit,
            env_config.energy_q_limit,
        ],
        dtype=np.float32,
    )
    for idx, algorithm in enumerate(algorithms):
        if algorithm == "td3_bc_style":
            samples = make_td3_bc_style_samples(pairs)
            behavior_alpha = args.behavior_alpha
        elif algorithm == "awac_style":
            samples = make_awac_style_samples(
                conventional_rows,
                candidate_rows,
                temperature=args.awac_temperature,
                behavior_weight=args.awac_behavior_weight,
            )
            behavior_alpha = args.behavior_alpha
        elif algorithm == "success_bc_style":
            samples = make_success_bc_style_samples(
                conventional_rows,
                candidate_rows,
                top_k=args.success_top_k,
            )
            behavior_alpha = 0.0
        elif algorithm == "bc_conventional":
            samples = make_bc_conventional_samples(conventional_rows)
            behavior_alpha = 0.0
        else:
            raise RuntimeError(f"Unhandled algorithm: {algorithm}")

        if args.specialist_mode == "trajectory":
            samples = expand_samples_to_trajectory(
                samples,
                decision_dt=args.decision_dt,
                ramp_s=args.trajectory_ramp_s,
                post_fault_hold_s=args.trajectory_post_fault_hold_s,
                max_points_per_case=args.max_trajectory_points_per_case,
            )

        policy, model_path, elapsed, loss = train_policy(
            samples,
            algorithm=algorithm,
            model_tag=safe_group_label,
            run_dir=run_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            behavior_alpha=behavior_alpha,
            seed=args.seed + idx * 1000 + (sum(ord(ch) for ch in group_label) % 1000),
            action_scale=action_scale,
            hidden=args.hidden,
            controller_heads=args.controller_heads,
        )
        summary, case_rows = evaluate_policy(
            algorithm=f"{group_label}/{algorithm}",
            policy=policy,
            conventional_rows=conventional_rows,
            pairs=pairs,
            env_config=env_config,
            trajectory=args.specialist_mode == "trajectory",
        )
        summary.model_path = str(model_path)
        summary.train_elapsed_s = elapsed
        summary.train_loss_last = loss
        summaries.append(summary)
        case_rows_out.extend(case_rows)
        print(json.dumps(asdict(summary), indent=2), flush=True)
        if summary.viable:
            viable_found = True
            if auto_requested:
                break
    return summaries, case_rows_out, viable_found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-csv", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", choices=["all", "topology1", "topology2"], default="topology1")
    parser.add_argument("--category", choices=["all", "LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--duration-ms", type=parse_duration_ms, default=80)
    parser.add_argument("--max-cases", type=int, default=2)
    parser.add_argument("--algorithms", default="auto")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument(
        "--controller-heads",
        choices=["split", "shared"],
        default="split",
        help="Use separate regulating/energy output heads or the old shared output head.",
    )
    parser.add_argument(
        "--specialist-mode",
        choices=["trajectory", "single_point"],
        default="trajectory",
        help="Train/evaluate a per-step trajectory specialist or the old fixed-action specialist.",
    )
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument("--trajectory-ramp-s", type=float, default=0.020)
    parser.add_argument("--trajectory-post-fault-hold-s", type=float, default=0.035)
    parser.add_argument(
        "--max-trajectory-points-per-case",
        type=int,
        default=0,
        help="Optional cap for trajectory-expanded samples per case; 0 keeps all 2-ms points.",
    )
    parser.add_argument("--lr", type=float, default=8e-4)
    parser.add_argument("--behavior-alpha", type=float, default=0.45)
    parser.add_argument("--awac-temperature", type=float, default=25.0)
    parser.add_argument("--awac-behavior-weight", type=float, default=0.60)
    parser.add_argument(
        "--success-top-k",
        type=int,
        default=6,
        help="Number of nearest passing/improving switch-evidence actions imitated by success_bc_style.",
    )
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument("--reg-d-limit", type=float, default=0.80)
    parser.add_argument("--reg-q-limit", type=float, default=0.40)
    parser.add_argument("--energy-d-limit", type=float, default=0.95)
    parser.add_argument("--energy-q-limit", type=float, default=0.95)
    parser.add_argument(
        "--group-specialists",
        action="store_true",
        help="Train a separate offline policy for each topology/category/duration group.",
    )
    parser.add_argument(
        "--group-by-fault",
        action="store_true",
        help="When grouping specialists, split each topology/category/duration group by fault_pu as well.",
    )
    args = parser.parse_args()
    raw_algorithms = str(args.algorithms)
    args.algorithms = parse_algorithms(raw_algorithms)
    auto_requested = raw_algorithms.strip().lower() == "auto"

    dataset_csv = args.dataset_csv or latest_dataset_csv()
    run_id = args.run_id or f"hpt_offline_full_action_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = read_csv(dataset_csv)
    conventional_rows = [
        row
        for row in rows
        if s(row, "row_source") == "conventional_boundary"
        and s(row, "scenario_type") == "fault"
    ]
    candidate_rows = [
        row for row in rows if s(row, "row_source") == "switch_matrix" and s(row, "scenario_type") == "fault"
    ]
    conventional_rows = filter_rows(
        conventional_rows,
        topology=args.topology,
        category_filter=args.category,
        duration_ms=args.duration_ms,
    )
    if args.max_cases > 0:
        conventional_rows = sorted(conventional_rows, key=severity)[: args.max_cases]
    if not conventional_rows:
        raise RuntimeError("No conventional boundary rows selected for evaluation/training")

    env_config = HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        reg_d_limit=args.reg_d_limit,
        reg_q_limit=args.reg_q_limit,
        energy_d_limit=args.energy_d_limit,
        energy_q_limit=args.energy_q_limit,
        action_projection_enable=False,
    )
    summaries: list[AlgorithmSummary] = []
    all_case_rows: list[dict[str, Any]] = []
    viable_found = False
    groups = (
        grouped_conventional_rows(conventional_rows, include_fault=args.group_by_fault)
        if args.group_specialists
        else [("pooled", sorted(conventional_rows, key=severity))]
    )
    for group_label, group_rows in groups:
        group_summaries, group_case_rows, group_viable = run_algorithm_sequence(
            group_label=group_label,
            conventional_rows=group_rows,
            candidate_rows=candidate_rows,
            run_dir=run_dir,
            algorithms=args.algorithms,
            auto_requested=auto_requested,
            args=args,
            env_config=env_config,
        )
        summaries.extend(group_summaries)
        all_case_rows.extend(group_case_rows)
        viable_found = viable_found or group_viable

    active_rows = make_active_sampling_rows(all_case_rows)
    write_csv(run_dir / "case_results.csv", all_case_rows)
    write_csv(run_dir / "active_sampling_candidates.csv", active_rows)
    config = {
        key: (str(value) if isinstance(value, Path) else value)
        for key, value in vars(args).items()
    }
    config["algorithms"] = args.algorithms
    config["algorithms_requested"] = raw_algorithms
    summary_json = {
        "schema": "hpt-offline-full-action-baselines-v1",
        "run_id": run_id,
        "dataset_csv": str(dataset_csv),
        "selected_cases": len(conventional_rows),
        "candidate_rows": len(candidate_rows),
        "algorithms": [asdict(summary) for summary in summaries],
        "viable_found": viable_found,
        "active_sampling_candidates": len(active_rows),
        "config": config,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")
    write_report(
        run_dir,
        dataset_csv=dataset_csv,
        summaries=summaries,
        case_rows=all_case_rows,
        active_rows=active_rows,
    )
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_offline_full_action_baselines",
        config=summary_json["config"],
        topology_models=TOPOLOGY_MODELS,
        dataset_manifest=dataset_csv.with_name("manifest.json"),
        extra=summary_json,
    )
    print(json.dumps(summary_json, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


