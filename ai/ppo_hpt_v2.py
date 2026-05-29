"""PPO/DRL scaffold for HPT v2 ride-through control.

This file defines the reward, policy network, PPO update loop, and a
Simulink-facing environment interface. Full training requires a MATLAB Engine
or a faster compiled simulation wrapper; use --dry-run to validate the reward
and scenario-table plumbing without launching long Simulink jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.distributions import Normal
from torch.optim import Adam

from lvrt_metrics import metrics_for_file


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_TABLE = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
RESULTS_DIR = PROJECT_ROOT / 'results'
MODEL_DIR = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)


@dataclass
class HPTMetrics:
    lvrt_pass: float
    v2_min: float
    vdc_min: float
    vdc_max: float
    i2_max: float
    recovery_ms: float
    v2_error_integral: float


def reward_from_metrics(m: HPTMetrics) -> float:
    """Dense physical reward aligned with HPT v2 LVRT/FRT metrics.

    The pass bit is retained, but most of the signal is continuous so failed
    ride-through cases still tell PPO which physical constraint improved.
    """
    reward = 4.0 * float(m.lvrt_pass)
    reward += 2.0 * min(1.0, max(0.0, m.v2_min / 0.90))
    reward += 2.0 * min(1.0, max(0.0, m.vdc_min / 0.75))
    reward += 1.5 * min(1.0, max(0.0, (1.25 - m.vdc_max) / 0.25))
    reward += 2.0 * min(1.0, max(0.0, (3.0 - m.i2_max) / 2.0))
    reward -= 10.0 * max(0.0, 0.75 - m.vdc_min)
    reward -= 8.0 * max(0.0, m.vdc_max - 1.25)
    reward -= 6.0 * max(0.0, m.i2_max - 3.0)
    reward -= 0.01 * min(max(m.recovery_ms, 0.0), 500.0)
    reward -= 2.0 * max(0.0, m.v2_error_integral)
    return float(reward)


class ActorCritic(nn.Module):
    """Small continuous-action actor-critic.

    Actions are normalized setpoint modifiers:
      a0: energy-extraction modulation bias
      a1: regulation modulation bias
      a2: current-limit aggressiveness
    """

    def __init__(self, obs_dim: int = 8, action_dim: int = 3):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(obs_dim, 128),
            nn.Tanh(),
            nn.Linear(128, 128),
            nn.Tanh(),
        )
        self.mu = nn.Linear(128, action_dim)
        self.log_std = nn.Parameter(torch.full((action_dim,), -0.7))
        self.value = nn.Linear(128, 1)

    def forward(self, obs):
        h = self.backbone(obs)
        mu = torch.tanh(self.mu(h))
        std = torch.exp(self.log_std).expand_as(mu)
        return mu, std, self.value(h).squeeze(-1)

    def act(self, obs):
        mu, std, value = self(obs)
        dist = Normal(mu, std)
        action = dist.sample()
        logp = dist.log_prob(action).sum(-1)
        return torch.clamp(action, -1.0, 1.0), logp, value


class ScenarioTableEnv:
    """Scenario iterator and reward adapter for HPT v2.

    The dry-run path uses a deterministic surrogate only to validate PPO code.
    Real training should replace simulate() with MATLAB Engine or a compiled
    Simulink runner and must write metrics using the same LVRT definitions as
    ai/lvrt_metrics.py.
    """

    def __init__(self, table_path: Path = SCENARIO_TABLE, dry_run: bool = False,
                 real_out_dir: Path | None = None, start_row: int = 0):
        self.table = pd.read_csv(table_path)
        self.dry_run = dry_run
        self.idx = max(0, min(len(self.table) - 1, start_row))
        self.real_out_dir = real_out_dir or (PROJECT_ROOT / 'data' / 'ppo_hpt_v2_rollouts')
        self.real_out_dir.mkdir(parents=True, exist_ok=True)

    def reset(self):
        if self.idx >= len(self.table):
            self.idx = 0
        row = self.table.iloc[self.idx]
        self.idx += 1
        obs = self._obs_from_row(row)
        return obs, row

    def step(self, row, action: np.ndarray):
        metrics = self.simulate(row, action)
        reward = reward_from_metrics(metrics)
        obs = self._obs_from_row(row)
        done = True
        info = metrics.__dict__
        return obs, reward, done, info

    def simulate(self, row, action: np.ndarray) -> HPTMetrics:
        if not self.dry_run:
            return self._simulate_matlab(row, action)
        sc_id = int(row.sc_id)
        severity = 1.0 if sc_id in (6, 7) else 0.35
        if sc_id == 0:
            severity = 0.0
        control_gain = float(np.clip(0.35 + 0.25 * action[1] - 0.15 * abs(action[2]), 0, 0.8))
        v2_drop = max(0.0, severity - control_gain)
        vdc_min = 0.92 - 0.55 * max(0.0, action[1]) * severity
        vdc_max = 1.02 + 0.18 * max(0.0, action[0]) + 0.04 * severity
        i2_max = 1.4 + 1.9 * severity - 0.45 * max(0.0, action[2])
        recovery = 20.0 + 160.0 * v2_drop
        v2_min_val = float(max(0.0, 1.0 - v2_drop))
        passed = float(v2_min_val >= 0.20 and vdc_min >= 0.75 and vdc_max <= 1.25
                       and i2_max <= 3.0 and recovery <= 100.0)
        return HPTMetrics(
            lvrt_pass=passed,
            v2_min=v2_min_val,
            vdc_min=float(vdc_min),
            vdc_max=float(vdc_max),
            i2_max=float(i2_max),
            recovery_ms=float(recovery),
            v2_error_integral=float(v2_drop),
        )

    def simulate_batch(self, rows: list[pd.Series], actions: np.ndarray) -> list[HPTMetrics]:
        if self.dry_run:
            return [self.simulate(row, action) for row, action in zip(rows, actions)]

        actions = np.clip(np.asarray(actions, dtype=float), -1.0, 1.0)
        run_id = f"ppo_batch_{int(time.time() * 1000)}"
        out_dir = self.real_out_dir / run_id
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)

        action_table = out_dir / 'actions.csv'
        pd.DataFrame({
            'rollout_id': np.arange(1, len(rows) + 1),
            'scenario_row': [int(row.name) + 1 for row in rows],
            'energy_bias': actions[:, 0],
            'reg_bias': actions[:, 1],
            'current_bias': actions[:, 2],
        }).to_csv(action_table, index=False)

        env = os.environ.copy()
        env['HPT_SCENARIO_TABLE'] = 'scenario_table_hpt_v2.csv'
        env['HPT_PPO_ACTION_TABLE'] = str(action_table).replace('\\', '/')
        env['HPT_SWITCHING_OUT_DIR'] = str(out_dir).replace('\\', '/')
        env['HPT_CONTROLLER_MODE'] = '5'
        env.pop('HPT_SCENARIO_ROW', None)
        env.pop('HPT_RL_ACTION', None)

        cmd = [
            'matlab',
            '-batch',
            "cd('E:/research_space/Hybrid-power-transformer/data_collection'); run('run_switching_scenarios.m');",
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(180, 90 * len(rows)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                'MATLAB Simulink PPO batch failed:\n'
                f'STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}'
            )

        files = sorted(out_dir.glob('*.mat'))
        if len(files) != len(rows):
            raise FileNotFoundError(
                f'Expected {len(rows)} PPO rollout files in {out_dir}, found {len(files)}'
            )
        return [self._metrics_from_file(path) for path in files]

    def _simulate_matlab(self, row, action: np.ndarray) -> HPTMetrics:
        action = np.clip(np.asarray(action, dtype=float), -1.0, 1.0)
        run_id = f"ppo_row{int(row.name) + 1:04d}_{int(time.time() * 1000)}"
        out_dir = self.real_out_dir / run_id
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)

        env = os.environ.copy()
        env['HPT_SCENARIO_TABLE'] = 'scenario_table_hpt_v2.csv'
        env['HPT_SCENARIO_ROW'] = str(int(row.name) + 1)
        env['HPT_SWITCHING_OUT_DIR'] = str(Path('../data/ppo_hpt_v2_rollouts') / run_id)
        env['HPT_CONTROLLER_MODE'] = '5'
        env['HPT_RL_ACTION'] = ','.join(f'{v:.6f}' for v in action)
        env.pop('HPT_PPO_ACTION_TABLE', None)

        cmd = [
            'matlab',
            '-batch',
            "cd('E:/research_space/Hybrid-power-transformer/data_collection'); run('run_switching_scenarios.m');",
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                'MATLAB Simulink PPO step failed:\n'
                f'STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}'
            )

        files = sorted(out_dir.glob('*.mat'))
        if not files:
            raise FileNotFoundError(f'No PPO rollout .mat produced in {out_dir}')
        return self._metrics_from_file(files[0])

    @staticmethod
    def _metrics_from_file(path: Path) -> HPTMetrics:
        row_metrics = metrics_for_file(path)
        recovery = row_metrics['v2_recovery_ms_to_0p90']
        recovery_ms = 500.0 if recovery is None else float(recovery)
        v2_error = max(0.0, 0.9 - float(row_metrics['v2_mean_pu_fault']))
        return HPTMetrics(
            lvrt_pass=float(row_metrics['lvrt_pass_basic']),
            v2_min=float(row_metrics['v2_min_pu_fault']),
            vdc_min=float(row_metrics['vdc_min_pu_post_fault']),
            vdc_max=float(row_metrics['vdc_peak_pu_post_fault']),
            i2_max=float(row_metrics['i2_peak_pu_post_fault']),
            recovery_ms=recovery_ms,
            v2_error_integral=v2_error,
        )

    @staticmethod
    def _obs_from_row(row) -> np.ndarray:
        return np.array([
            row.sc_id / 6.0,
            row.P_load / 400e3,
            row.Q_load / 250e3,
            row.t_fault / 0.05,
            row.fault_variant / 6.0,
            row.fault_mag,
            row.fault_resistance,
            row.ground_resistance,
        ], dtype=np.float32)


def train_dry_run(epochs: int, steps_per_epoch: int, device: str):
    env = ScenarioTableEnv(dry_run=True)
    model = ActorCritic().to(device)
    opt = Adam(model.parameters(), lr=3e-4)
    gamma = 0.99

    history = []
    for epoch in range(1, epochs + 1):
        obs_buf, act_buf, logp_buf, ret_buf, val_buf = [], [], [], [], []
        rewards = []
        for _ in range(steps_per_epoch):
            obs_np, row = env.reset()
            obs = torch.tensor(obs_np, dtype=torch.float32, device=device).unsqueeze(0)
            action, logp, value = model.act(obs)
            _, reward, _, _ = env.step(row, action.squeeze(0).detach().cpu().numpy())
            obs_buf.append(obs.squeeze(0))
            act_buf.append(action.squeeze(0).detach())
            logp_buf.append(logp.squeeze(0).detach())
            val_buf.append(value.squeeze(0))
            ret_buf.append(torch.tensor(reward, dtype=torch.float32, device=device))
            rewards.append(reward)

        obs_t = torch.stack(obs_buf)
        act_t = torch.stack(act_buf)
        old_logp = torch.stack(logp_buf)
        ret_t = torch.stack(ret_buf)
        val_t = torch.stack(val_buf).detach()
        adv_t = ret_t + gamma * 0.0 - val_t
        adv_t = (adv_t - adv_t.mean()) / (adv_t.std() + 1e-6)

        for _ in range(4):
            mu, std, value = model(obs_t)
            dist = Normal(mu, std)
            logp = dist.log_prob(act_t).sum(-1)
            ratio = torch.exp(logp - old_logp)
            clipped = torch.clamp(ratio, 0.8, 1.2) * adv_t
            policy_loss = -torch.min(ratio * adv_t, clipped).mean()
            value_loss = nn.functional.mse_loss(value, ret_t)
            entropy = dist.entropy().sum(-1).mean()
            loss = policy_loss + 0.5 * value_loss - 0.01 * entropy
            opt.zero_grad()
            loss.backward()
            opt.step()

        rec = {'epoch': epoch, 'mean_reward': float(np.mean(rewards))}
        history.append(rec)
        print(f"epoch={epoch:03d} mean_reward={rec['mean_reward']:.3f}")

    ckpt = MODEL_DIR / 'ppo_hpt_v2_dry_run.pt'
    torch.save({'model_state': model.state_dict(), 'history': history}, ckpt)
    report = RESULTS_DIR / 'ppo_hpt_v2_dry_run.json'
    report.write_text(json.dumps({'history': history, 'checkpoint': str(ckpt)}, indent=2), encoding='utf-8')
    print(f'Saved {ckpt}')
    print(f'Saved {report}')


def train_real(epochs: int, steps_per_epoch: int, device: str, start_row: int,
               tag: str, resume_checkpoint: str | None = None):
    env = ScenarioTableEnv(dry_run=False, start_row=start_row)
    model = ActorCritic().to(device)
    if resume_checkpoint:
        ckpt = torch.load(resume_checkpoint, map_location=device)
        model.load_state_dict(ckpt['model_state'])
    opt = Adam(model.parameters(), lr=2e-4)
    history = []
    best_reward = -float('inf')

    for epoch in range(1, epochs + 1):
        obs_buf, act_buf, logp_buf, ret_buf, val_buf = [], [], [], [], []
        rows = []
        for _ in range(steps_per_epoch):
            obs_np, row = env.reset()
            obs = torch.tensor(obs_np, dtype=torch.float32, device=device).unsqueeze(0)
            action, logp, value = model.act(obs)
            obs_buf.append(obs.squeeze(0))
            act_buf.append(action.squeeze(0).detach())
            logp_buf.append(logp.squeeze(0).detach())
            val_buf.append(value.squeeze(0))
            rows.append(row)

        action_np = torch.stack(act_buf).detach().cpu().numpy()
        metrics = env.simulate_batch(rows, action_np)
        rewards = [reward_from_metrics(m) for m in metrics]
        infos = [m.__dict__ for m in metrics]
        for reward in rewards:
            ret_buf.append(torch.tensor(reward, dtype=torch.float32, device=device))

        obs_t = torch.stack(obs_buf)
        act_t = torch.stack(act_buf)
        old_logp = torch.stack(logp_buf)
        ret_t = torch.stack(ret_buf)
        val_t = torch.stack(val_buf).detach()
        adv_t = ret_t - val_t
        adv_t = (adv_t - adv_t.mean()) / (adv_t.std() + 1e-6)

        for _ in range(4):
            mu, std, value = model(obs_t)
            dist = Normal(mu, std)
            logp = dist.log_prob(act_t).sum(-1)
            ratio = torch.exp(logp - old_logp)
            clipped = torch.clamp(ratio, 0.8, 1.2) * adv_t
            policy_loss = -torch.min(ratio * adv_t, clipped).mean()
            value_loss = nn.functional.mse_loss(value, ret_t)
            entropy = dist.entropy().sum(-1).mean()
            loss = policy_loss + 0.5 * value_loss - 0.01 * entropy
            opt.zero_grad()
            loss.backward()
            opt.step()

        rec = {
            'epoch': epoch,
            'mean_reward': float(np.mean(rewards)),
            'mean_lvrt_pass': float(np.mean([i['lvrt_pass'] for i in infos])),
            'mean_v2_min': float(np.mean([i['v2_min'] for i in infos])),
            'mean_vdc_min': float(np.mean([i['vdc_min'] for i in infos])),
            'mean_vdc_max': float(np.mean([i['vdc_max'] for i in infos])),
            'mean_i2_max': float(np.mean([i['i2_max'] for i in infos])),
        }
        history.append(rec)
        suffix = '' if tag == 'real' else f'_{tag}'
        if rec['mean_reward'] > best_reward:
            best_reward = rec['mean_reward']
            best_ckpt = MODEL_DIR / f'ppo_hpt_v2_real{suffix}_best.pt'
            torch.save({
                'model_state': model.state_dict(),
                'history': history,
                'best_epoch': epoch,
                'best_reward': best_reward,
            }, best_ckpt)
        print(
            f"epoch={epoch:03d} reward={rec['mean_reward']:.3f} "
            f"pass={100*rec['mean_lvrt_pass']:.1f}% "
            f"V2min={rec['mean_v2_min']:.3f} "
            f"Vdc=[{rec['mean_vdc_min']:.3f},{rec['mean_vdc_max']:.3f}] "
            f"I2={rec['mean_i2_max']:.3f}"
        )

    suffix = '' if tag == 'real' else f'_{tag}'
    ckpt = MODEL_DIR / f'ppo_hpt_v2_real{suffix}.pt'
    torch.save({'model_state': model.state_dict(), 'history': history}, ckpt)
    report = RESULTS_DIR / f'ppo_hpt_v2_real{suffix}.json'
    report.write_text(json.dumps({'history': history, 'checkpoint': str(ckpt)}, indent=2), encoding='utf-8')
    print(f'Saved {ckpt}')
    print(f'Saved {report}')


def evaluate_real_policy(checkpoint: str, tag: str, device: str):
    env = ScenarioTableEnv(dry_run=False, start_row=0)
    model = ActorCritic().to(device)
    ckpt = torch.load(checkpoint, map_location=device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    rows = [env.table.iloc[i] for i in range(len(env.table))]
    obs = np.stack([env._obs_from_row(row) for row in rows], axis=0)
    obs_t = torch.tensor(obs, dtype=torch.float32, device=device)
    with torch.no_grad():
        actions, _, _ = model.forward(obs_t)
    metrics = env.simulate_batch(rows, actions.cpu().numpy())
    rewards = [reward_from_metrics(m) for m in metrics]
    infos = [m.__dict__ for m in metrics]

    by_sc: dict[int, list[dict]] = {}
    for row, info, reward in zip(rows, infos, rewards):
        rec = dict(info)
        rec['reward'] = reward
        by_sc.setdefault(int(row.sc_id), []).append(rec)

    summary = {}
    for sc_id, group in sorted(by_sc.items()):
        summary[str(sc_id)] = {
            'n': len(group),
            'pass_rate_pct': 100.0 * float(np.mean([g['lvrt_pass'] for g in group])),
            'reward_mean': float(np.mean([g['reward'] for g in group])),
            'v2_min_mean': float(np.mean([g['v2_min'] for g in group])),
            'vdc_min_mean': float(np.mean([g['vdc_min'] for g in group])),
            'vdc_max_mean': float(np.mean([g['vdc_max'] for g in group])),
            'i2_max_mean': float(np.mean([g['i2_max'] for g in group])),
        }

    report = {
        'checkpoint': str(checkpoint),
        'n': len(metrics),
        'mean_reward': float(np.mean(rewards)),
        'pass_rate_pct': 100.0 * float(np.mean([m.lvrt_pass for m in metrics])),
        'v2_min_mean': float(np.mean([m.v2_min for m in metrics])),
        'vdc_min_mean': float(np.mean([m.vdc_min for m in metrics])),
        'vdc_max_mean': float(np.mean([m.vdc_max for m in metrics])),
        'i2_max_mean': float(np.mean([m.i2_max for m in metrics])),
        'summary_by_sc_id': summary,
    }
    out = RESULTS_DIR / f'ppo_hpt_v2_eval_{tag}.json'
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Evaluated {len(metrics)} scenarios: pass={report['pass_rate_pct']:.2f}% "
          f"reward={report['mean_reward']:.3f} V2min={report['v2_min_mean']:.3f} "
          f"VdcMin={report['vdc_min_mean']:.3f} I2Max={report['i2_max_mean']:.3f}")
    print(f'Saved {out}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--steps-per-epoch', type=int, default=64)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--start-row', type=int, default=0,
                        help='Zero-based scenario-table row for real Simulink PPO. Default 0 = full scenario table.')
    parser.add_argument('--tag', default='real',
                        help='Output suffix for real PPO checkpoint/report.')
    parser.add_argument('--resume-checkpoint', default=None)
    parser.add_argument('--eval-checkpoint', default=None)
    parser.add_argument('--eval-tag', default='real')
    args = parser.parse_args()
    if args.eval_checkpoint:
        evaluate_real_policy(args.eval_checkpoint, args.eval_tag, args.device)
    elif args.dry_run:
        train_dry_run(args.epochs, args.steps_per_epoch, args.device)
    else:
        train_real(args.epochs, args.steps_per_epoch, args.device, args.start_row,
                   args.tag, args.resume_checkpoint)


if __name__ == '__main__':
    main()
