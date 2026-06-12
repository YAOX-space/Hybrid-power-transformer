"""w4_train.py — system-level coordinator SAC on the audited linear surrogate (zero OpenDSS calls).

Decision: one allocation per fault event (single-step episode / contextual bandit).
  obs  (13): no-support fault voltages at the 10 HPT buses + [global min v0, pv_pen, load_lvl]
  act  (10): per-HPT reactive quota, mapped to [floor(v), 0.27] pu where
             floor = max(0, iqref(v) − 0.10) keeps the GB/T reactive criterion satisfied.
  reward    : load-weighted ride-through (strict 1.0 / tolerant 0.3) − survive violations,
              computed through the surrogate v = v0 + S·q and the phase-1 device model.

The non-trivial allocation: borderline HPTs prefer LOW iq (DC budget → own series boost);
helper HPTs (v≥0.9 or far) prefer HIGH iq (lift neighbors). Uniform policies are suboptimal.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json, time
from pathlib import Path
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import SAC

HERE = Path(__file__).resolve().parent
HPT_KVA, IQ_CAP, SE_GAIN, SE_MAX = 400.0, 0.27, 0.47, 0.20
DC_TAU = 0.0035 / 0.195


def device_outcome(v_final, iq, dur):
    """Phase-1-calibrated device model: series from leftover DC budget, Vdc state, load voltage."""
    se = min(SE_MAX, max(0.0, (1.0 - 0.82 - 0.08 * iq / max(0.3, v_final)) / 1.9))
    veq = 1.0 - 0.08 * abs(iq) / max(0.3, v_final) - 1.9 * se
    vdc_end = veq + (1.0 - veq) * np.exp(-dur / DC_TAU)
    survive = vdc_end >= 0.75 or (v_final < 0.05 and dur <= 0.15)
    v_load = min(1.0, v_final + SE_GAIN * se) if v_final < 0.9 else v_final
    return v_load, survive


def floors(v0):
    iqref = np.clip(1.5 * (0.9 - v0), 0, 0.30)
    return np.where(v0 < 0.9, np.maximum(0.0, iqref - 0.10), 0.0)


def rollout_reward(v0, S, dur, q_pu):
    v = v0 + S @ (q_pu * HPT_KVA)
    r = 0.0
    for h in range(len(v0)):
        v_load, surv = device_outcome(max(0.01, v[h]), q_pu[h], dur)
        r += (1.0 if v_load >= 0.90 else (0.3 if v_load >= 0.70 else 0.0))
        if not surv:
            r -= 0.5
    return r / len(v0), v


class CoordEnv(gym.Env):
    def __init__(self, data, seed=0):
        super().__init__()
        self.v0s, self.Ss, self.meta = data['v0'], data['S'], data['meta']
        self.n = len(self.v0s)
        self.rng = np.random.default_rng(seed)
        self.observation_space = spaces.Box(-5, 5, shape=(13,), dtype=np.float32)
        self.action_space = spaces.Box(-1, 1, shape=(10,), dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        self.i = int(self.rng.integers(self.n))
        v0 = self.v0s[self.i]; m = self.meta[self.i]
        self.obs = np.concatenate([v0, [v0.min(), m[3], m[4]]]).astype(np.float32)
        return self.obs, {}

    def step(self, action):
        v0, S, dur = self.v0s[self.i], self.Ss[self.i], self.meta[self.i][5]
        f = floors(v0)
        q = f + (np.asarray(action) * 0.5 + 0.5) * (IQ_CAP - f)     # [-1,1] -> [floor, cap]
        r, _ = rollout_reward(v0, S, dur, q)
        return self.obs, float(r), True, False, {}


def policy_uniform(v0, mode):
    f = floors(v0)
    iqref = np.clip(1.5 * (0.9 - v0), 0, 0.30)
    if mode == 'droop_full':
        return np.where(v0 < 0.9, np.minimum(IQ_CAP, iqref), 0.0)
    if mode == 'se_first':
        return f
    if mode == 'all_max':
        return np.full(10, IQ_CAP)
    raise ValueError(mode)


def main(steps=120_000):
    data = np.load(HERE / 'w4_dataset.npz')
    n = len(data['v0'])
    print(f'dataset: {n} scenarios')
    # --- analytic baselines on the surrogate (same reward) ---
    base = {}
    for mode in ['droop_full', 'se_first', 'all_max']:
        rs = [rollout_reward(data['v0'][i], data['S'][i], data['meta'][i][5],
                             policy_uniform(data['v0'][i], mode))[0] for i in range(n)]
        base[mode] = float(np.mean(rs))
        print(f'  baseline {mode:11s}: mean reward {base[mode]:.4f}')
    # --- SAC coordinator ---
    env = CoordEnv(data)
    sac = SAC('MlpPolicy', env, learning_rate=lambda p: 3e-5 + (3e-4 - 3e-5) * p,
              buffer_size=120_000, batch_size=512, gamma=0.0, train_freq=1, gradient_steps=2,
              ent_coef='auto', policy_kwargs=dict(net_arch=[256, 256]), device='cpu',
              verbose=0, seed=42)
    best, t0 = -9, time.time()
    for k in range(steps // 10_000):
        sac.learn(10_000, reset_num_timesteps=False)
        rs = []
        for i in range(n):
            v0 = data['v0'][i]; m = data['meta'][i]
            obs = np.concatenate([v0, [v0.min(), m[3], m[4]]]).astype(np.float32)
            a, _ = sac.predict(obs, deterministic=True)
            f = floors(v0)
            q = f + (a * 0.5 + 0.5) * (IQ_CAP - f)
            rs.append(rollout_reward(v0, data['S'][i], m[5], q)[0])
        mr = float(np.mean(rs))
        if mr > best:
            best = mr; sac.save(str(HERE / 'w4_coordinator_best.zip'))
        print(f'  [coord] {(k+1)*10}k: reward {mr:.4f} best {best:.4f} '
              f'({(time.time()-t0)/60:.0f}min)', flush=True)
    (HERE / 'w4_train.json').write_text(json.dumps({'baselines': base, 'coord_best': best}, indent=1))
    print(f'W4 TRAIN DONE coord={best:.4f} vs droop_full={base["droop_full"]:.4f}')


if __name__ == '__main__':
    main()
