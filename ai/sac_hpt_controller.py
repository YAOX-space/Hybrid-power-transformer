"""
sac_hpt_controller.py  —  SAC continuous controller for HPT direct control.

Architecture:
  - SAC (Soft Actor-Critic) with continuous 3D action space
  - State: 17D physically observable vector
  - Action: [m_sh, m_se_d, m_se_q] — SPWM modulation indices
  - Reward: multi-objective physics-grounded (W_vdc=10, W_v2=5, W_i2=8, ...)

Training phases:
  1. ODE fast training (~1 hour on CPU)  ← this file
  2. Simulink validation via Mode 5 interface (separate script)

Honest limitations:
  - ODE accuracy: VdcMin RMSE ≈ 0.17 pu vs Simulink for sc_3ph/sc_1ph
  - cap_fault (sc_id=5): C_dc=680µF but trigger mechanism unknown
  - igbt faults (sc_id=3,4,8): switching ripple not modelled in ODE
  → Simulink validation is mandatory for deployment
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from stable_baselines3 import SAC
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import BaseCallback

from hpt_direct_env import HPTDirectEnv, load_scenarios, MSFFNSimulator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCEN_CSV     = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
MODEL_DIR    = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR  = PROJECT_ROOT / 'results'
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Evaluation helper ──────────────────────────────────────────────────────────

def evaluate_sac(
    model: SAC,
    scenarios: list[dict],
    n_eval: int = 100,
) -> dict:
    """Evaluate SAC on a random subset of scenarios.  Returns metrics dict."""
    rng  = np.random.default_rng(0)
    idxs = rng.choice(len(scenarios), size=min(n_eval, len(scenarios)), replace=False)
    msffn = MSFFNSimulator()

    vdc_mins  = []
    lvrt_pass = []
    rewards   = []

    for idx in idxs:
        sc  = scenarios[idx]
        # train_mode=False: 50ms episode, no DR, no MSFFN noise → matches Simulink conditions
        env = HPTDirectEnv([sc], msffn=msffn, seed=42, train_mode=False)
        obs, _ = env.reset()
        total_r = 0.0
        done    = False
        vdc_min = 1.5
        vdc_max = 0.0
        i2_max  = 0.0
        in_post_fault = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            if info['t'] >= sc['t_fault']:
                in_post_fault = True
            if in_post_fault:
                vdc_min = min(vdc_min, info['V_dc_pu'])
                vdc_max = max(vdc_max, info['V_dc_pu'])
                i2_max  = max(i2_max,  info['I2_pu'])
            done = term or trunc
        lvrt_ok = (vdc_min >= 0.75 and vdc_max <= 1.25 and i2_max <= 3.0)
        vdc_mins.append(vdc_min)
        lvrt_pass.append(int(lvrt_ok))
        rewards.append(total_r)

    return {
        'lvrt_pass_pct': round(100.0 * np.mean(lvrt_pass), 2),
        'vdc_min_mean':  round(float(np.mean(vdc_mins)),    4),
        'vdc_min_min':   round(float(np.min(vdc_mins)),     4),
        'mean_reward':   round(float(np.mean(rewards)),     2),
    }
    # Note: evaluation uses train_mode=False (50ms, no DR, no noise) to match
    # Simulink validation conditions for comparable LVRT % metrics.


# ── Progress callback ──────────────────────────────────────────────────────────

class SACProgressCallback(BaseCallback):
    def __init__(self, scenarios, eval_freq=10_000, verbose=1):
        super().__init__(verbose)
        self._scenarios = scenarios
        self._freq      = eval_freq
        self._best_lvrt = 0.0
        self._start_t   = time.time()

    def _on_step(self) -> bool:
        if self.num_timesteps % self._freq == 0:
            metrics = evaluate_sac(self.model, self._scenarios, n_eval=70)
            lvrt = metrics['lvrt_pass_pct']
            if lvrt > self._best_lvrt:
                self._best_lvrt = lvrt
                self.model.save(str(MODEL_DIR / 'sac_hpt_direct_best.zip'))
            elapsed = (time.time() - self._start_t) / 60
            if self.verbose:
                print(f'  step={self.num_timesteps:8d}  LVRT={lvrt:.1f}%  '
                      f'VdcMin={metrics["vdc_min_mean"]:.3f}  '
                      f'reward={metrics["mean_reward"]:.1f}  '
                      f'best={self._best_lvrt:.1f}%  '
                      f'elapsed={elapsed:.0f}min')
        return True


# ── Main training function ─────────────────────────────────────────────────────

def train(
    total_steps: int  = 500_000,
    n_envs:      int  = 8,
    eval_freq:   int  = 10_000,
    learning_rate: float = 3e-4,
    batch_size:  int  = 256,
    buffer_size: int  = 100_000,
):
    print('=' * 62)
    print('SAC Direct HPT Control Training')
    print('Action: [m_sh, m_se_d, m_se_q]  (SPWM modulation indices)')
    print('State:  17D  (physics + MSFFN + context + last_action)')
    print('Reward: multi-objective physics-grounded')
    print('=' * 62)

    scenarios = load_scenarios(SCEN_CSV)
    print(f'\nLoaded {len(scenarios)} scenarios from scenario table.')

    # Dq baseline reference (from existing results)
    print(f'dq baseline LVRT: 64.00%  (dq双环PI, from existing data)')
    print(f'Oracle upper:     66.86%  (best strategy per scenario, real Simulink)\n')

    # Build vectorised environment
    def _make():
        sc = load_scenarios(SCEN_CSV)
        return HPTDirectEnv(sc, seed=int(np.random.randint(99999)))

    # DummyVecEnv: same process, no subprocess overhead (prevents hangs)
    from stable_baselines3.common.vec_env import DummyVecEnv
    vec_env = DummyVecEnv([_make for _ in range(n_envs)])

    # SAC configuration (optimised for this problem)
    sac = SAC(
        policy          = 'MlpPolicy',
        env             = vec_env,
        learning_rate   = learning_rate,
        buffer_size     = buffer_size,
        batch_size      = batch_size,
        tau             = 0.005,         # soft update coefficient
        gamma           = 0.99,          # discount for multi-step episodes
        train_freq      = 1,
        gradient_steps  = 1,
        ent_coef        = 'auto',        # auto-tune entropy (SAC hallmark)
        target_update_interval = 1,
        policy_kwargs   = dict(
            net_arch = [256, 256, 256],  # deeper network for 17D state
        ),
        verbose         = 0,
        seed            = 42,
    )
    print(f'SAC actor/critic: MLP 256×256×256')
    print(f'Auto entropy tuning: yes')
    print(f'Training steps: {total_steps:,}')
    print(f'Parallel envs:  {n_envs}\n')

    cb = SACProgressCallback(scenarios, eval_freq=eval_freq, verbose=1)

    t_start = time.time()
    sac.learn(total_timesteps=total_steps, callback=cb, progress_bar=False)
    t_train = (time.time() - t_start) / 60

    sac.save(str(MODEL_DIR / 'sac_hpt_direct_final.zip'))

    # Final evaluation
    print('\n── Final Evaluation ──')
    best_path = MODEL_DIR / 'sac_hpt_direct_best.zip'
    if best_path.exists():
        best_sac = SAC.load(str(best_path))
        final_metrics = evaluate_sac(best_sac, scenarios, n_eval=350)
    else:
        final_metrics = evaluate_sac(sac, scenarios, n_eval=350)

    print(f'\n{"="*62}')
    print('SAC Direct Control — Final Results (ODE physics)')
    print(f'{"="*62}')
    print(f'  LVRT pass rate:  {final_metrics["lvrt_pass_pct"]:.2f}%')
    print(f'  VdcMin mean:     {final_metrics["vdc_min_mean"]:.3f} pu')
    print(f'  VdcMin worst:    {final_metrics["vdc_min_min"]:.3f} pu')
    print(f'  Mean reward:     {final_metrics["mean_reward"]:.1f}')
    print(f'  Training time:   {t_train:.0f} min')
    print()
    print('  ⚠ These results are from the ODE model (averaged, no switching).')
    print('  ⚠ Simulink validation required for final confirmation.')

    result = {
        'model': 'SAC direct control [m_sh, m_se_d, m_se_q]',
        'env':   'HPT ODE averaged model',
        **final_metrics,
        'training_steps': total_steps,
        'training_min':   round(t_train, 1),
    }
    out = RESULTS_DIR / 'sac_hpt_direct_result.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'\nSaved → {out}')
    return sac, final_metrics


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--steps',      type=int,   default=500_000)
    p.add_argument('--n-envs',     type=int,   default=8)
    p.add_argument('--eval-freq',  type=int,   default=10_000)
    p.add_argument('--lr',         type=float, default=3e-4)
    args = p.parse_args()
    train(
        total_steps  = args.steps,
        n_envs       = args.n_envs,
        eval_freq    = args.eval_freq,
        learning_rate= args.lr,
    )
