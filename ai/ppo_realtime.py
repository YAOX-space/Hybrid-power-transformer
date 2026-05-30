"""
ppo_realtime.py — 改进版 PPO，使用实时信号作为状态观测
==========================================================
与旧版 ppo_hpt_v2.py 的核心区别：

  旧版：obs = 8维场景参数（P_load, t_fault, R_f...）→ 故障前就固定，无法感知Vdc变化
  新版：obs = 实时电气量（Vdc_pu, dVdc/dt, V2_rms, I2_rms, t_since_fault, fault_class）

新状态观测（10维）：
  [0] Vdc_pu            — 当前DC母线电压（标幺值）
  [1] dVdc_dt           — Vdc变化速率（pu/s）
  [2] V2_rms_pu         — 二次侧电压有效值
  [3] I2_rms_pu         — 二次侧电流有效值
  [4] t_since_fault_ms  — 故障后经过时间（ms，归一化到[0,1]，500ms为1）
  [5] fault_class/6     — MSFFN预测的故障类别（归一化）
  [6] Vdc_ref/800       — 当前Vdc参考值（反映当前策略）
  [7] I_lim/3.0         — 当前电流限制
  [8] P_load/400e3      — 负荷（场景级）
  [9] sc_id/6           — 真实故障类别（场景级，训练时已知）

动作（3维，不变）：
  [0] ΔVdc_ref ∈ [-80, +40] V
  [1] ΔV2_ref  ∈ [-40, +20] V
  [2] ΔI_lim   ∈ [-0.5, +0.5] pu

Simulink交互（ControllerMode=8）：
  - Python每隔 DECISION_INTERVAL_MS 写一次动作到 hpt_ppo_action.mat
  - Simulink读取并应用，每步结束后将状态写到 hpt_ppo_state.mat
  - Python读取状态，计算奖励，更新策略

使用方式：
  # 训练
  python ai/ppo_realtime.py --train --episodes 500 --matlab-cd /path/to/data_collection

  # 评估
  python ai/ppo_realtime.py --eval --checkpoint data/models/ppo_realtime_best.pt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio
import torch
import torch.nn as nn
from torch.distributions import Normal
from torch.optim import Adam

PROJECT_ROOT   = Path(__file__).resolve().parent.parent
SCENARIO_TABLE = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
RESULTS_DIR    = PROJECT_ROOT / 'results'
MODEL_DIR      = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# ── 物理常数 ──────────────────────────────────────────────────────────────────
VDC_NOM  = 800.0
V2_NOM   = 400.0
I2_NOM   = 816.5   # A，额定电流 = S/(√3·V2) = 400e3/(√3·400)
C_DC     = 2200e-6
F_SAMPLE = 20000   # Hz

DECISION_INTERVAL_MS = 5   # 每5ms决策一次（对应MSFFN检测窗口）

# 动作边界（与旧版保持一致）
VDC_REF_DMIN = -80.0;  VDC_REF_DMAX = +40.0
V2_REF_DMIN  = -40.0;  V2_REF_DMAX  = +20.0
ILIM_DMIN    = -0.5;   ILIM_DMAX    = +0.5

OBS_DIM    = 10
ACTION_DIM = 3


# ── 状态观测提取 ───────────────────────────────────────────────────────────────

def obs_from_timeseries(
    t: np.ndarray,
    Vdc: np.ndarray,
    V2_abc: np.ndarray,
    I2_abc: np.ndarray,
    t_fault: float,
    fault_class: int,
    vdc_ref: float,
    i_lim: float,
    p_load: float,
    sc_id: int,
    window_end_idx: int,
) -> np.ndarray:
    """当前时间窗口末尾的10维状态向量。

    window_end_idx: 当前决策时刻的样本索引（Vdc窗口的最后一个样本）
    """
    w = min(window_end_idx, 100)   # 5ms = 100个样本
    i_end  = window_end_idx
    i_start = max(0, i_end - w)

    vdc_win = Vdc[i_start:i_end]
    vdc_now = float(vdc_win[-1]) / VDC_NOM if len(vdc_win) > 0 else 1.0

    # dVdc/dt（pu/s）
    if len(vdc_win) >= 2:
        dt_s    = (t[i_end-1] - t[max(0, i_end-10)]) if i_end > 10 else 1/F_SAMPLE*w
        dvdc_dt = (float(vdc_win[-1]) - float(vdc_win[0])) / (dt_s * VDC_NOM + 1e-9)
    else:
        dvdc_dt = 0.0

    # V2_rms（标幺值）
    v2_win = V2_abc[i_start:i_end]
    v2_rms = float(np.sqrt(np.mean(v2_win**2))) / (V2_NOM / np.sqrt(2)) if len(v2_win) > 0 else 1.0

    # I2_rms（标幺值）
    i2_win = I2_abc[i_start:i_end]
    i2_rms = float(np.sqrt(np.mean(i2_win**2))) / (I2_NOM / np.sqrt(2)) if len(i2_win) > 0 else 0.0

    # 故障后时间（归一化，500ms=1）
    t_now = float(t[i_end-1]) if i_end > 0 else 0.0
    t_since = max(0.0, (t_now - t_fault) * 1000) / 500.0

    return np.array([
        np.clip(vdc_now,     0.0, 1.5),
        np.clip(dvdc_dt,    -5.0, 5.0) / 5.0,   # 归一化到[-1,1]
        np.clip(v2_rms,      0.0, 1.5),
        np.clip(i2_rms,      0.0, 5.0) / 5.0,
        np.clip(t_since,     0.0, 1.0),
        fault_class / 6.0,
        vdc_ref / VDC_NOM,
        i_lim / 3.0,
        p_load / 400e3,
        sc_id / 6.0,
    ], dtype=np.float32)


def decode_action(action: np.ndarray):
    """归一化动作[-1,+1]³ → 物理量偏置"""
    dvdc  = VDC_REF_DMIN + (action[0]+1)/2 * (VDC_REF_DMAX - VDC_REF_DMIN)
    dv2   = V2_REF_DMIN  + (action[1]+1)/2 * (V2_REF_DMAX  - V2_REF_DMIN)
    dilim = ILIM_DMIN    + (action[2]+1)/2 * (ILIM_DMAX    - ILIM_DMIN)
    return float(dvdc), float(dv2), float(dilim)


def encode_action(dvdc, dv2, dilim) -> np.ndarray:
    a0 = 2*(dvdc  - VDC_REF_DMIN)/(VDC_REF_DMAX - VDC_REF_DMIN) - 1
    a1 = 2*(dv2   - V2_REF_DMIN )/(V2_REF_DMAX  - V2_REF_DMIN ) - 1
    a2 = 2*(dilim - ILIM_DMIN   )/(ILIM_DMAX    - ILIM_DMIN   ) - 1
    return np.clip(np.array([a0, a1, a2], dtype=np.float32), -1, 1)


# ── Actor-Critic 网络（扩展到10维输入）──────────────────────────────────────

class ActorCritic(nn.Module):
    """实时状态版 Actor-Critic，obs_dim=10。"""

    def __init__(self, obs_dim: int = OBS_DIM, action_dim: int = ACTION_DIM,
                 hidden: int = 256):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.LayerNorm(hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.LayerNorm(hidden), nn.Tanh(),
            nn.Linear(hidden, 128),    nn.Tanh(),
        )
        self.mu      = nn.Linear(128, action_dim)
        self.log_std = nn.Parameter(torch.full((action_dim,), -0.5))
        self.value   = nn.Linear(128, 1)

    def forward(self, obs):
        h   = self.backbone(obs)
        mu  = torch.tanh(self.mu(h))
        std = torch.exp(self.log_std.clamp(-3, 1)).expand_as(mu)
        return mu, std, self.value(h).squeeze(-1)

    def act(self, obs):
        mu, std, val = self(obs)
        dist   = Normal(mu, std)
        action = dist.sample().clamp(-1, 1)
        logp   = dist.log_prob(action).sum(-1)
        return action, logp, val


# ── 奖励函数（与旧版相同，基于物理判据）─────────────────────────────────────

def reward_from_metrics(vdc_min, vdc_max, i2_max, v2_min, recovery_ms, lvrt_pass):
    r  = 4.0 * float(lvrt_pass)
    r += 2.0 * min(1.0, max(0.0, v2_min / 0.90))
    r += 2.0 * min(1.0, max(0.0, vdc_min / 0.75))
    r += 1.5 * min(1.0, max(0.0, (1.25 - vdc_max) / 0.25))
    r += 2.0 * min(1.0, max(0.0, (3.0 - i2_max) / 2.0))
    r -= 10.0 * max(0.0, 0.75 - vdc_min)
    r -= 8.0  * max(0.0, vdc_max - 1.25)
    r -= 6.0  * max(0.0, i2_max - 3.0)
    r -= 0.01 * min(max(recovery_ms, 0.0), 500.0)
    return float(r)


# ── 离线训练（使用已有 .mat 数据模拟多步决策）────────────────────────────────

class OfflineEnv:
    """用已有仿真数据模拟多步环境，无需 Simulink。

    每个 episode = 一个 .mat 文件
    每步 = DECISION_INTERVAL_MS 对应的时间窗口
    动作影响当前步的"虚拟奖励"（Vdc margin 相对奖励）

    注意：这是离线近似，不能替代在线 Simulink 验证，
         但可以快速训练出一个合理的初始策略。
    """

    def __init__(self, mat_dir: Path, msffn_model=None):
        from data_loader import FAULT_CLASSES
        self.files = sorted(mat_dir.glob('*.mat'))
        if not self.files:
            raise FileNotFoundError(f'No .mat files in {mat_dir}')
        self.msffn  = msffn_model
        self.FAULT_CLASSES = FAULT_CLASSES
        self._reset_state()

    def _reset_state(self):
        self._file_idx  = 0
        self._step_idx  = 0
        self._vdc_ref   = VDC_NOM
        self._v2_ref    = V2_NOM
        self._i_lim     = 3.0
        self._mat_data  = None

    def _load_mat(self, path):
        try:
            mat = sio.loadmat(str(path))
        except Exception:
            import mat73
            mat = mat73.loadmat(str(path))
        return mat

    def reset(self):
        if self._file_idx >= len(self.files):
            self._file_idx = 0
        mat = self._load_mat(self.files[self._file_idx])
        self._file_idx += 1

        self._t       = mat['t_uniform'].squeeze()
        self._Vdc     = mat['V_dc'].squeeze()
        self._V2      = mat['V2_abc']
        self._I2      = mat['I2_abc']
        self._t_fault = float(mat['t_fault'].flat[0])
        self._sc_id   = int(mat['sc_id'].flat[0])
        self._p_load  = float(mat.get('P_load', np.array([[0.0]]).flat[0]))

        # 故障时刻索引
        self._i_fault = max(0, np.searchsorted(self._t, self._t_fault))
        # 决策点：故障后每5ms一次
        step_samples  = int(DECISION_INTERVAL_MS / 1000 * F_SAMPLE)
        self._decision_pts = list(range(
            self._i_fault,
            min(len(self._t), self._i_fault + step_samples * 40),  # 最多40步=200ms
            step_samples
        ))
        self._step_idx = 0
        self._vdc_ref  = VDC_NOM
        self._v2_ref   = V2_NOM
        self._i_lim    = 3.0

        # 用 MSFFN 预测故障类别（若有模型）
        self._fault_class = self._sc_id  # 默认用真实类别

        obs = self._get_obs()
        return obs

    def _get_obs(self):
        if self._step_idx >= len(self._decision_pts):
            i_end = len(self._t)
        else:
            i_end = self._decision_pts[self._step_idx]
        return obs_from_timeseries(
            self._t, self._Vdc, self._V2, self._I2,
            self._t_fault, self._fault_class,
            self._vdc_ref, self._i_lim,
            self._p_load, self._sc_id,
            max(1, i_end),
        )

    def step(self, action: np.ndarray):
        dvdc, dv2, dilim = decode_action(action)
        self._vdc_ref = np.clip(self._vdc_ref + dvdc, 720, 840)
        self._v2_ref  = np.clip(self._v2_ref  + dv2,  360, 420)
        self._i_lim   = np.clip(self._i_lim   + dilim, 2.5, 3.5)

        self._step_idx += 1
        done = self._step_idx >= len(self._decision_pts)

        # 当前窗口的Vdc_min作为即时奖励信号
        if self._step_idx < len(self._decision_pts):
            i_end = self._decision_pts[self._step_idx]
        else:
            i_end = len(self._t)

        step_samples = int(DECISION_INTERVAL_MS / 1000 * F_SAMPLE)
        i_start = max(0, i_end - step_samples)
        vdc_slice = self._Vdc[i_start:i_end] / VDC_NOM

        vdc_min = float(np.min(vdc_slice)) if len(vdc_slice) > 0 else 1.0
        vdc_max = float(np.max(vdc_slice)) if len(vdc_slice) > 0 else 1.0

        v2_slice = self._V2[i_start:i_end]
        v2_min   = float(np.sqrt(np.mean(v2_slice**2))) / (V2_NOM/np.sqrt(2)) if len(v2_slice) > 0 else 1.0
        i2_slice = self._I2[i_start:i_end]
        i2_max   = float(np.sqrt(np.mean(i2_slice**2))) / (I2_NOM/np.sqrt(2)) if len(i2_slice) > 0 else 0.0

        lvrt = float(vdc_min >= 0.75 and vdc_max <= 1.25 and i2_max <= 3.0)
        reward = reward_from_metrics(vdc_min, vdc_max, i2_max, v2_min, 0.0, lvrt if done else 0.0)

        # 连续罚：控制器调节越激进则给予小的动作代价
        action_cost = 0.01 * float(np.sum(np.abs(np.array([dvdc/80, dv2/40, dilim/0.5]))))
        reward -= action_cost

        obs = self._get_obs()
        return obs, reward, done, {'vdc_min': vdc_min, 'i2_max': i2_max}


# ── PPO 更新 ──────────────────────────────────────────────────────────────────

class PPOTrainer:
    def __init__(self, model: ActorCritic, lr: float = 3e-4,
                 clip_eps: float = 0.2, gamma: float = 0.97,
                 gae_lambda: float = 0.95, n_epochs: int = 6,
                 batch_size: int = 256):
        self.model     = model
        self.opt       = Adam(model.parameters(), lr=lr, eps=1e-5)
        self.clip_eps  = clip_eps
        self.gamma     = gamma
        self.gae_lambda = gae_lambda
        self.n_epochs  = n_epochs
        self.batch_size = batch_size

    def update(self, buf: dict) -> dict:
        obs    = torch.tensor(buf['obs'],    dtype=torch.float32)
        acts   = torch.tensor(buf['acts'],   dtype=torch.float32)
        logps  = torch.tensor(buf['logps'],  dtype=torch.float32)
        rets   = torch.tensor(buf['rets'],   dtype=torch.float32)
        advs   = torch.tensor(buf['advs'],   dtype=torch.float32)
        advs   = (advs - advs.mean()) / (advs.std() + 1e-8)

        N = len(obs)
        pi_losses, v_losses, entropies = [], [], []

        for _ in range(self.n_epochs):
            idx = torch.randperm(N)
            for start in range(0, N, self.batch_size):
                b = idx[start:start+self.batch_size]
                mu, std, vals = self.model(obs[b])
                dist     = Normal(mu, std)
                new_logp = dist.log_prob(acts[b]).sum(-1)
                entropy  = dist.entropy().sum(-1).mean()
                ratio    = (new_logp - logps[b]).exp()
                pi_loss  = -torch.min(
                    ratio * advs[b],
                    ratio.clamp(1-self.clip_eps, 1+self.clip_eps) * advs[b]
                ).mean()
                v_loss   = (vals - rets[b]).pow(2).mean()
                loss     = pi_loss + 0.5*v_loss - 0.01*entropy
                self.opt.zero_grad(); loss.backward();
                nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
                self.opt.step()
                pi_losses.append(pi_loss.item())
                v_losses.append(v_loss.item())
                entropies.append(entropy.item())

        return {'pi_loss': np.mean(pi_losses), 'v_loss': np.mean(v_losses),
                'entropy': np.mean(entropies)}


def compute_gae(rewards, values, dones, gamma, lam):
    T = len(rewards)
    adv = np.zeros(T, dtype=np.float32)
    last_gae = 0.0
    for t in reversed(range(T)):
        next_val = 0.0 if dones[t] else (values[t+1] if t+1 < T else 0.0)
        delta    = rewards[t] + gamma * next_val - values[t]
        adv[t]   = last_gae = delta + gamma * lam * (0.0 if dones[t] else last_gae)
    rets = adv + np.array(values[:T])
    return adv, rets


# ── 离线训练主循环 ─────────────────────────────────────────────────────────────

def train_offline(mat_dir: Path, episodes: int = 1000, steps_per_update: int = 2048,
                  save_every: int = 50) -> Path:
    env   = OfflineEnv(mat_dir)
    model = ActorCritic()
    ppo   = PPOTrainer(model)

    ckpt_best = MODEL_DIR / 'ppo_realtime_best.pt'
    ckpt_last = MODEL_DIR / 'ppo_realtime_last.pt'

    buf = {'obs':[], 'acts':[], 'logps':[], 'rews':[], 'vals':[], 'dones':[]}
    ep_rewards, ep_lengths = [], []
    best_mean_reward = -float('inf')

    print(f'离线训练 PPO（实时观测版）: {episodes} episodes, mat_dir={mat_dir}')
    print(f'观测维度: {OBS_DIM}, 动作维度: {ACTION_DIM}')

    total_steps = 0
    for ep in range(1, episodes+1):
        obs   = env.reset()
        ep_r  = 0.0
        ep_t  = 0

        while True:
            obs_t  = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                act, logp, val = model.act(obs_t)
            act_np = act.squeeze(0).numpy()
            val_np = float(val.item())

            next_obs, rew, done, _ = env.step(act_np)
            buf['obs'].append(obs)
            buf['acts'].append(act_np)
            buf['logps'].append(float(logp.item()))
            buf['rews'].append(rew)
            buf['vals'].append(val_np)
            buf['dones'].append(done)

            obs    = next_obs
            ep_r  += rew
            ep_t  += 1
            total_steps += 1

            if done or total_steps % steps_per_update == 0:
                if done:
                    ep_rewards.append(ep_r)
                    ep_lengths.append(ep_t)
                    ep_r = ep_t = 0.0
                    if ep < episodes:
                        obs = env.reset()

                # GAE
                T    = len(buf['rews'])
                adv, rets = compute_gae(
                    buf['rews'], buf['vals'], buf['dones'],
                    ppo.gamma, ppo.gae_lambda
                )
                stats = ppo.update({
                    'obs':  np.array(buf['obs']),
                    'acts': np.array(buf['acts']),
                    'logps':np.array(buf['logps']),
                    'rets': rets, 'advs': adv,
                })
                buf = {k: [] for k in buf}

                if done:
                    break

        if ep % 20 == 0 or ep == episodes:
            mean_r = float(np.mean(ep_rewards[-20:])) if ep_rewards else 0.0
            print(f'ep={ep:5d}  mean_r={mean_r:6.2f}  '
                  f'pi={stats["pi_loss"]:.4f}  v={stats["v_loss"]:.4f}  '
                  f'ent={stats["entropy"]:.3f}  steps={total_steps}')
            if mean_r > best_mean_reward:
                best_mean_reward = mean_r
                torch.save({'model_state': model.state_dict(),
                            'episode': ep, 'mean_reward': mean_r,
                            'obs_dim': OBS_DIM}, ckpt_best)

        if ep % save_every == 0:
            torch.save({'model_state': model.state_dict(), 'episode': ep}, ckpt_last)

    print(f'\n最优平均奖励: {best_mean_reward:.3f}')
    print(f'检查点: {ckpt_best}')
    return ckpt_best


# ── 离线评估（用已有 .mat 文件跑策略，统计 Vdc_min 分布）─────────────────────

def evaluate_offline(mat_dir: Path, ckpt_path: Path) -> dict:
    """在已有 .mat 文件上跑策略，统计逐类 Vdc_min 和 I2_max。"""
    ckpt  = torch.load(str(ckpt_path), map_location='cpu')
    model = ActorCritic()
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    env    = OfflineEnv(mat_dir)
    n_ep   = len(env.files)
    by_sc  = {}

    for _ in range(n_ep):
        obs  = env.reset()
        sc   = env._sc_id
        done = False
        vdc_mins = []; i2_maxs = []

        while not done:
            with torch.no_grad():
                act, _, _ = model.act(torch.tensor(obs, dtype=torch.float32).unsqueeze(0))
            obs, _, done, info = env.step(act.squeeze(0).numpy())
            vdc_mins.append(info['vdc_min'])
            i2_maxs.append(info['i2_max'])

        rec = by_sc.setdefault(sc, {'vdc_min':[], 'i2_max':[]})
        rec['vdc_min'].append(min(vdc_mins) if vdc_mins else 1.0)
        rec['i2_max'].append(max(i2_maxs) if i2_maxs else 0.0)

    SC_NAMES = {0:'normal',3:'igbt_oc_sh',4:'igbt_oc_se',5:'cap_fault',
                6:'sc_1ph',7:'sc_3ph',8:'cascade'}
    print('\n=== 离线 PPO 评估（Vdc_min 均值）===')
    for sc_id in sorted(by_sc):
        d = by_sc[sc_id]
        pass_rate = sum(1 for v in d['vdc_min'] if v >= 0.75) / len(d['vdc_min']) * 100
        print(f'  {SC_NAMES.get(sc_id,str(sc_id)):15s}  '
              f'Vdc_min={np.mean(d["vdc_min"]):.3f}±{np.std(d["vdc_min"]):.3f}  '
              f'I2_max={np.mean(d["i2_max"]):.3f}  pass≈{pass_rate:.0f}%')
    return by_sc


# ── 在线 MATLAB 训练（接入 Simulink Mode 8）──────────────────────────────────

def train_online_matlab(matlab_cd: str, episodes: int = 200,
                        scenario_table: Path = SCENARIO_TABLE) -> Path:
    """在线训练：Python ↔ MATLAB/Simulink 交互（ControllerMode=8）。

    Mode 8 协议：
      Python → 写 data/ppo_state_exchange/ppo_action.mat（动作）
      Simulink → 每 DECISION_INTERVAL_MS 读一次动作，执行并写 ppo_state.mat（状态）
      Python → 读 ppo_state.mat，计算奖励，更新策略
    """
    exchange_dir = PROJECT_ROOT / 'data' / 'ppo_state_exchange'
    exchange_dir.mkdir(parents=True, exist_ok=True)
    action_file = exchange_dir / 'ppo_action.mat'
    state_file  = exchange_dir / 'ppo_state.mat'

    model = ActorCritic()
    # 先加载离线训练的初始权重（若有）
    offline_ckpt = MODEL_DIR / 'ppo_realtime_best.pt'
    if offline_ckpt.exists():
        model.load_state_dict(torch.load(str(offline_ckpt), map_location='cpu')['model_state'])
        print(f'从离线检查点初始化: {offline_ckpt}')

    ppo  = PPOTrainer(model, lr=1e-4)   # 在线阶段用更小学习率
    table = pd.read_csv(scenario_table)
    ckpt_best = MODEL_DIR / 'ppo_realtime_online_best.pt'
    best_pass = 0.0

    buf = {'obs':[], 'acts':[], 'logps':[], 'rews':[], 'vals':[], 'dones':[]}

    for ep in range(1, episodes+1):
        row = table.iloc[ep % len(table)]

        # 初始动作写出（Vdc_ref=800, V2_ref=400, I_lim=3.0）
        init_action = np.zeros(3, dtype=np.float32)
        sio.savemat(str(action_file), {
            'dvdc_ref': float(decode_action(init_action)[0]),
            'dv2_ref':  float(decode_action(init_action)[1]),
            'dilim':    float(decode_action(init_action)[2]),
        })

        env_vars = os.environ.copy()
        env_vars.update({
            'HPT_SCENARIO_TABLE':    'scenario_table_hpt_v2.csv',
            'HPT_SCENARIO_ROW':      str(int(row.name) + 1),
            'HPT_SWITCHING_OUT_DIR': str(exchange_dir).replace('\\', '/'),
            'HPT_CONTROLLER_MODE':   '8',
            'HPT_PPO_EXCHANGE_DIR':  str(exchange_dir).replace('\\', '/'),
        })

        cmd = ['matlab', '-batch',
               f"cd('{matlab_cd}'); run('run_switching_scenarios.m');"]
        proc = subprocess.Popen(cmd, env=env_vars, cwd=str(PROJECT_ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 实时状态交换循环
        ep_obs = []; ep_acts = []; ep_logps = []
        ep_rews = []; ep_vals = []; ep_dones = []
        prev_vdc_pu = 1.0
        vdc_ref = VDC_NOM

        while proc.poll() is None:
            if not state_file.exists():
                time.sleep(0.001)
                continue

            try:
                state = sio.loadmat(str(state_file))
                os.remove(str(state_file))
            except Exception:
                time.sleep(0.001)
                continue

            # 解析状态
            vdc_now = float(state.get('vdc', np.array([[VDC_NOM]])).flat[0]) / VDC_NOM
            v2_now  = float(state.get('v2_rms', np.array([[V2_NOM]])).flat[0]) / (V2_NOM/np.sqrt(2))
            i2_now  = float(state.get('i2_rms', np.array([[0.0]])).flat[0]) / (I2_NOM/np.sqrt(2))
            t_since = float(state.get('t_since_fault_ms', np.array([[0.0]])).flat[0]) / 500.0
            done    = bool(state.get('done', np.array([[0]])).flat[0])
            fault_cls = int(state.get('fault_class', np.array([[0]])).flat[0])

            dvdc_dt = (vdc_now - prev_vdc_pu) / (DECISION_INTERVAL_MS/1000) / VDC_NOM
            prev_vdc_pu = vdc_now

            obs = np.array([
                vdc_now, np.clip(dvdc_dt,-5,5)/5,
                v2_now, np.clip(i2_now,0,5)/5,
                np.clip(t_since,0,1), fault_cls/6,
                vdc_ref/VDC_NOM, 3.0/3.0,
                float(row.get('P_load', 400e3))/400e3,
                float(row.sc_id)/6.0,
            ], dtype=np.float32)

            obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                act, logp, val = model.act(obs_t)
            act_np = act.squeeze(0).numpy()
            dvdc, dv2, dilim = decode_action(act_np)
            vdc_ref = np.clip(vdc_ref + dvdc, 720, 840)

            sio.savemat(str(action_file), {
                'dvdc_ref': dvdc, 'dv2_ref': dv2, 'dilim': dilim,
            })

            vdc_min_now = vdc_now
            lvrt = float(vdc_now >= 0.75 and i2_now <= 3.0)
            rew = reward_from_metrics(vdc_min_now, vdc_now+0.01, i2_now, v2_now,
                                      0.0, lvrt if done else 0.0)

            ep_obs.append(obs); ep_acts.append(act_np)
            ep_logps.append(float(logp.item())); ep_rews.append(rew)
            ep_vals.append(float(val.item())); ep_dones.append(done)

            if done:
                break

        proc.wait(timeout=120)
        if not ep_obs:
            continue

        adv, rets = compute_gae(ep_rews, ep_vals, ep_dones, ppo.gamma, ppo.gae_lambda)
        buf['obs'].extend(ep_obs); buf['acts'].extend(ep_acts)
        buf['logps'].extend(ep_logps); buf['rews'].extend(ep_rews)
        buf['vals'].extend(ep_vals); buf['dones'].extend(ep_dones)

        if len(buf['obs']) >= 512 or ep == episodes:
            stats = ppo.update({
                'obs':  np.array(buf['obs']), 'acts': np.array(buf['acts']),
                'logps':np.array(buf['logps']), 'rets': rets, 'advs': adv,
            })
            buf = {k: [] for k in buf}
            total_pass = sum(ep_dones) / len(ep_dones) * 100 if ep_dones else 0
            if total_pass > best_pass:
                best_pass = total_pass
                torch.save({'model_state': model.state_dict(), 'episode': ep}, ckpt_best)
            if ep % 20 == 0:
                print(f'ep={ep:4d}  pi={stats["pi_loss"]:.4f}  v={stats["v_loss"]:.4f}')

    return ckpt_best


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--train-offline', action='store_true', help='离线训练（无需Simulink）')
    parser.add_argument('--train-online',  action='store_true', help='在线训练（需要MATLAB）')
    parser.add_argument('--eval',          action='store_true', help='离线评估')
    parser.add_argument('--mat-dir',  type=str, default=str(PROJECT_ROOT/'data'/'raw'))
    parser.add_argument('--matlab-cd',type=str, default='',
                        help='MATLAB cd路径（data_collection目录绝对路径）')
    parser.add_argument('--checkpoint', type=str, default=str(MODEL_DIR/'ppo_realtime_best.pt'))
    parser.add_argument('--episodes',   type=int, default=500)
    args = parser.parse_args()

    if args.train_offline:
        train_offline(Path(args.mat_dir), episodes=args.episodes)

    if args.train_online:
        if not args.matlab_cd:
            print('请提供 --matlab-cd 参数（data_collection目录路径）')
        else:
            train_online_matlab(args.matlab_cd, episodes=args.episodes)

    if args.eval:
        evaluate_offline(Path(args.mat_dir), Path(args.checkpoint))
