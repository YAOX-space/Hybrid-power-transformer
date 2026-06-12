"""train_ab.py — SAC-variant A/B on the two improvable experts (sym, hvrt_sym).

Variants (same env, same reward, same net 256^3, same gs=2 as production for fairness):
  sac_reset : SAC + periodic full-network resets @100k/200k (primacy-bias fix, Nikishin'22)
  tqc_reset : TQC (truncated quantile critics, sb3-contrib) + same resets

Experts: sym (LVRT sym3ph; prod Simulink 81.7%), hvrt_sym (swell_3ph; absorb-depth weakness).
Saves data/models/ab_{variant}_{expert}_best.zip. Winner selection happens in Simulink, not ODE
(ODE bests are saturated ~100; ODE eval here is only a sanity/selection proxy).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import torch as th
from torch import nn
from stable_baselines3 import SAC
from sb3_contrib import TQC
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
from frt_env import HPTFRTEnv, load_frt_scenarios
from frt_metrics import evaluate_frt

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parent / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)

EXPERTS = {
    'sym':      lambda s: s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph',
    'hvrt_sym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph',
}
RESET_AT = [100_000, 200_000]


class ResetCallback(BaseCallback):
    """Full network re-init (actor+critic, keep buffer & alpha) at given timesteps."""
    def __init__(self, reset_steps):
        super().__init__()
        self.todo = sorted(reset_steps)

    def _on_step(self) -> bool:
        if self.todo and self.num_timesteps >= self.todo[0]:
            self.todo.pop(0)
            pol = self.model.policy
            for net in (pol.actor, pol.critic):
                for m in net.modules():
                    if isinstance(m, nn.Linear):
                        m.reset_parameters()
            pol.critic_target.load_state_dict(pol.critic.state_dict())
            for opt in (pol.actor.optimizer, pol.critic.optimizer):
                opt.state = defaultdict(dict)
            print(f'  [reset] networks re-initialized at step {self.num_timesteps:,}', flush=True)
        return True


def make_model(variant, vec):
    common = dict(learning_rate=3e-4, buffer_size=100_000, batch_size=512, tau=0.005,
                  gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
                  device='cpu', verbose=0, seed=42)
    if variant == 'tqc_reset':
        return TQC('MlpPolicy', vec, top_quantiles_to_drop_per_net=2,
                   policy_kwargs=dict(net_arch=[256, 256, 256]), **common)
    return SAC('MlpPolicy', vec, policy_kwargs=dict(net_arch=[256, 256, 256]), **common)


def train_one(variant, name, filt, total_steps=300_000, n_envs=8, eval_freq=25_000):
    scen = [s for s in load_frt_scenarios(ROOT / 'frt_scenarios.csv') if filt(s)]
    print(f'\n=== {variant} / expert "{name}": {len(scen)} scenarios ===', flush=True)
    vec = DummyVecEnv([lambda: HPTFRTEnv(scen, seed=int(np.random.randint(99999)), train_mode=True)
                       for _ in range(n_envs)])
    model = make_model(variant, vec)
    # sanity: actor keys must match the Simulink exporter
    keys = list(model.policy.actor.state_dict().keys())
    assert any('latent_pi.0.weight' in k for k in keys) and any(k.startswith('mu.') for k in keys), keys
    cb = ResetCallback(RESET_AT)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=cb)
        step += chunk
        m = evaluate_frt(model, scen, HPTFRTEnv, n_eval=min(80, len(scen)))
        if m['frt_pass'] > best:
            best = m['frt_pass']; model.save(str(MODELS / f'ab_{variant}_{name}_best.zip'))
        print(f"  [{variant}/{name}] step={step:7,} FRT={m['frt_pass']:.0f}% "
              f"(rea={m['reactive']:.0f} sur={m['survive']:.0f}) best={best:.0f}% "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    return best


if __name__ == '__main__':
    res = {}
    for variant in ['sac_reset', 'tqc_reset']:
        for nm, fl in EXPERTS.items():
            res[f'{variant}/{nm}'] = train_one(variant, nm, fl)
    (ROOT / 'results' / 'ab_train.json').write_text(json.dumps(res, indent=2))
    print('\nA/B DONE:', res, flush=True)
