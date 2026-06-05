"""Standalone SAC training - avoids argparse and subprocess issues."""
import sys, time, json
sys.path.insert(0, 'ai')
import numpy as np
from pathlib import Path
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from hpt_direct_env import HPTDirectEnv, load_scenarios
from sac_hpt_controller import evaluate_sac

PROJECT_ROOT = Path('.')
SCEN_CSV     = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
MODEL_DIR    = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR  = PROJECT_ROOT / 'results'
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TOTAL_STEPS = 500_000   # more steps with GPU acceleration
N_ENVS      = 8          # more parallel envs
EVAL_FREQ   = 25_000
BATCH_SIZE  = 512

import io

class _Tee:
    """Write to stdout AND log file simultaneously."""
    def __init__(self, log_path):
        self._log = open(log_path, 'w', encoding='utf-8', buffering=1)
    def write(self, msg):
        sys.__stdout__.write(msg)
        sys.__stdout__.flush()
        self._log.write(msg)
        self._log.flush()
    def flush(self):
        sys.__stdout__.flush()
        self._log.flush()

import sys as _sys
_sys.stdout = _Tee(str(RESULTS_DIR / 'sac_training_log.txt'))

print('=' * 60)
print('SAC Direct Control Training')
print(f'Steps: {TOTAL_STEPS:,}  n_envs: {N_ENVS}  eval_freq: {EVAL_FREQ}')
print('=' * 60)

print('Loading scenarios...')
scenarios = load_scenarios(SCEN_CSV)
print(f'Loaded {len(scenarios)} scenarios')

def _make():
    sc = load_scenarios(SCEN_CSV)
    # train_mode=True: 150ms episode + domain randomisation + MSFFN noise
    return HPTDirectEnv(sc, seed=int(np.random.randint(99999)), train_mode=True)

print(f'Building {N_ENVS}x DummyVecEnv...')
vec_env = DummyVecEnv([_make for _ in range(N_ENVS)])
print('Done.')

import torch as _torch
_device = 'cuda' if _torch.cuda.is_available() else 'cpu'
print(f'Using device: {_device}  ({_torch.cuda.get_device_name(0) if _device=="cuda" else "CPU"})')

sac = SAC('MlpPolicy', vec_env,
    learning_rate   = 3e-4,
    buffer_size     = 100_000,   # larger buffer for GPU
    batch_size      = 512,        # larger batch — GPU handles it easily
    tau             = 0.005,
    gamma           = 0.99,
    train_freq      = 1,
    gradient_steps  = 2,          # 2 gradient steps per env step (GPU allows this)
    ent_coef        = 'auto',
    policy_kwargs   = dict(net_arch=[256, 256, 256]),
    device          = _device,
    verbose         = 0,
    seed            = 42)

best_lvrt = 0.0
t_start   = time.time()
step_done = 0

print(f'\nStarting training...\n')
while step_done < TOTAL_STEPS:
    chunk = min(EVAL_FREQ, TOTAL_STEPS - step_done)
    sac.learn(total_timesteps=chunk, reset_num_timesteps=False)
    step_done += chunk

    # Evaluate
    m = evaluate_sac(sac, scenarios, n_eval=70)
    lvrt = m['lvrt_pass_pct']
    if lvrt > best_lvrt:
        best_lvrt = lvrt
        sac.save(str(MODEL_DIR / 'sac_hpt_direct_best.zip'))

    el = (time.time() - t_start) / 60
    print(f'  step={step_done:8,}  LVRT={lvrt:.1f}%  VdcMin={m["vdc_min_mean"]:.3f}'
          f'  best={best_lvrt:.1f}%  {el:.0f}min')

sac.save(str(MODEL_DIR / 'sac_hpt_direct_final.zip'))

# Final
print('\n' + '='*60)
print('FINAL RESULTS')
from stable_baselines3 import SAC as SAC2
best = SAC2.load(str(MODEL_DIR / 'sac_hpt_direct_best.zip'))
final = evaluate_sac(best, scenarios, n_eval=350)
print(f'LVRT pass: {final["lvrt_pass_pct"]:.2f}%')
print(f'VdcMin:    {final["vdc_min_mean"]:.3f} pu (mean)')
print(f'VdcMin:    {final["vdc_min_min"]:.3f} pu (worst)')
print(f'Reward:    {final["mean_reward"]:.1f}')
print(f'Training:  {(time.time()-t_start)/60:.0f} min')

result = {**final, 'model': 'SAC direct [m_sh,m_se_d,m_se_q]',
          'env': 'ODE Euler 1ms', 'steps': TOTAL_STEPS}
(RESULTS_DIR / 'sac_hpt_direct_result.json').write_text(
    json.dumps(result, indent=2), encoding='utf-8')
print(f'\nSaved -> results/sac_hpt_direct_result.json')
