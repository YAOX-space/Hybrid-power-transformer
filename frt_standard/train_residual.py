"""train_residual.py — Residual-SAC on the MPC prior, ONE policy for ALL 320 scenarios.

Stability suite (lit-grounded): linear LR annealing 3e-4→3e-5 + actor-weight EMA (deploy the
averaged actor; evaluated alongside the raw actor, best of both checkpointed).
Saves: data/models/sac_residual_best.zip (raw) / sac_residual_ema_best.zip (EMA snapshot).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json, copy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import torch as th
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
from residual_env import HPTFRTResidualEnv
from frt_env import load_frt_scenarios
from frt_metrics import evaluate_frt

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parent / 'data' / 'models'


class EMACallback(BaseCallback):
    """Exponential moving average of actor weights (updated every 250 env steps, beta=0.99)."""
    def __init__(self, every=250, beta=0.99):
        super().__init__(); self.every = every; self.beta = beta; self.ema = None; self.k = 0

    def _on_step(self):
        self.k += 1
        if self.k % self.every == 0:
            sd = self.model.policy.actor.state_dict()
            if self.ema is None:
                self.ema = copy.deepcopy(sd)
            else:
                for key in self.ema:
                    if self.ema[key].dtype.is_floating_point:
                        self.ema[key].mul_(self.beta).add_(sd[key], alpha=1 - self.beta)
        return True

    def load_into(self, model):
        """Swap EMA weights into the actor (returns backup for restoring)."""
        bak = copy.deepcopy(model.policy.actor.state_dict())
        model.policy.actor.load_state_dict(self.ema)
        return bak


def main(total_steps=300_000, n_envs=8, eval_freq=25_000):
    scen = load_frt_scenarios(ROOT / 'frt_scenarios.csv')
    print(f'=== residual-SAC: {len(scen)} scenarios (ALL), MPC prior inside env ===', flush=True)
    vec = DummyVecEnv([lambda: HPTFRTResidualEnv(scen, seed=int(np.random.randint(99999)))
                       for _ in range(n_envs)])
    lr = lambda p: 3e-5 + (3e-4 - 3e-5) * p          # linear anneal (p: 1→0)
    sac = SAC('MlpPolicy', vec, learning_rate=lr, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device='cpu', verbose=0, seed=42)
    ema = EMACallback()
    best, best_ema, t0, step = 0.0, 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=ema)
        step += chunk
        m = evaluate_frt(sac, scen, HPTFRTResidualEnv, n_eval=80)
        if m['frt_pass'] > best:
            best = m['frt_pass']; sac.save(str(MODELS / 'sac_residual_best.zip'))
        me = {'frt_pass': -1}
        if ema.ema is not None:
            bak = ema.load_into(sac)
            me = evaluate_frt(sac, scen, HPTFRTResidualEnv, n_eval=80)
            if me['frt_pass'] > best_ema:
                best_ema = me['frt_pass']; sac.save(str(MODELS / 'sac_residual_ema_best.zip'))
            sac.policy.actor.load_state_dict(bak)
        print(f"  [res] step={step:7,} FRT={m['frt_pass']:.0f}% (sur={m['survive']:.0f} "
              f"rea={m['reactive']:.0f}) EMA={me['frt_pass']:.0f}% best={best:.0f}/{best_ema:.0f}% "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    (ROOT / 'results' / 'residual_train.json').write_text(
        json.dumps({'best': best, 'best_ema': best_ema}, indent=2))
    print(f'RESIDUAL DONE best={best} ema={best_ema}', flush=True)


if __name__ == '__main__':
    main()
