"""
train_frt_sac.py — train SAC on the standard-FRT env (4-D action, ~22-D state).
Trains on the upgraded averaged ODE (frt_env); Simulink validation is a later phase.
"""
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from frt_env import HPTFRTEnv, load_frt_scenarios
from frt_metrics import evaluate_frt

ROOT   = Path(__file__).resolve().parent
SCEN   = ROOT / 'frt_scenarios.csv'
OUT    = ROOT / 'results'; OUT.mkdir(exist_ok=True)
MODELS = ROOT.parent / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)


def train(total_steps=400_000, n_envs=8, eval_freq=25_000):
    scen = load_frt_scenarios(SCEN)
    print(f'Loaded {len(scen)} FRT scenarios')
    vec = DummyVecEnv([lambda: HPTFRTEnv(load_frt_scenarios(SCEN),
                                         seed=int(np.random.randint(99999)), train_mode=True)
                       for _ in range(n_envs)])
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=dev, verbose=0, seed=42)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, scen, HPTFRTEnv, n_eval=80)
        if m['frt_pass'] > best:
            best = m['frt_pass']; sac.save(str(MODELS / 'sac_frt_best.zip'))
        print(f"  step={step:7,}  FRT={m['frt_pass']:.0f}%  (connect={m['connect']:.0f} "
              f"react={m['reactive']:.0f} recover={m['recover']:.0f} survive={m['survive']:.0f})  "
              f"best={best:.0f}%  {(time.time()-t0)/60:.0f}min")
    sac.save(str(MODELS / 'sac_frt_final.zip'))
    final = evaluate_frt(sac, scen, HPTFRTEnv)
    (OUT / 'frt_train_result.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
    print('FINAL:', final)
    return final


if __name__ == '__main__':
    train(total_steps=400_000)   # v3: calibrated env + balanced reactive reward (-5) + I_Q_MAX 0.25
