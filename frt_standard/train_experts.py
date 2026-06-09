"""
train_experts.py — train 3 specialist SAC policies on disjoint fault sub-categories,
for a hierarchical "classify → specialist" controller gated by (V, V2n):

  sym  : LVRT, fault_type == sym3ph            (symmetric undervoltage)
  asym : LVRT, fault_type in {1ph_g,2ph,2ph_g} (asymmetric, negative-seq / 2ω)
  hvrt : HVRT  (swell, overvoltage → absorb reactive)

Each specialist trains on the SAME upgraded ODE env (frt_env.py, v1 baseline gains),
only the scenario subset differs.  Saves data/models/sac_{name}_best.zip.
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
MODELS = ROOT.parent / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)

EXPERTS = {
    'sym':  lambda s: s['category']=='LVRT' and s['fault_type']=='sym3ph',
    'asym': lambda s: s['category']=='LVRT' and s['fault_type'] in ('1ph_g','2ph','2ph_g'),
    'hvrt': lambda s: s['category']=='HVRT',
}

def train_one(name, filt, total_steps=300_000, n_envs=8, eval_freq=25_000):
    allscn = load_frt_scenarios(SCEN)
    scen = [s for s in allscn if filt(s)]
    print(f'\n=== expert "{name}": {len(scen)} scenarios ===', flush=True)
    vec = DummyVecEnv([lambda: HPTFRTEnv(scen, seed=int(np.random.randint(99999)), train_mode=True)
                       for _ in range(n_envs)])
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256,256,256]), device=dev, verbose=0, seed=42)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps-step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, scen, HPTFRTEnv, n_eval=min(80,len(scen)))
        if m['frt_pass'] > best:
            best = m['frt_pass']; sac.save(str(MODELS / f'sac_{name}_best.zip'))
        print(f"  [{name}] step={step:7,} FRT={m['frt_pass']:.0f}% "
              f"(con={m['connect']:.0f} rea={m['reactive']:.0f} lim={m['limit']:.0f} "
              f"rec={m['recover']:.0f} sur={m['survive']:.0f}) best={best:.0f}% "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    sac.save(str(MODELS / f'sac_{name}_final.zip'))
    return best

if __name__ == '__main__':
    res = {}
    for nm, fl in EXPERTS.items():
        res[nm] = train_one(nm, fl, total_steps=300_000)
    (ROOT / 'results' / 'experts_train.json').write_text(json.dumps(res, indent=2))
    print('\nALL EXPERTS DONE:', res, flush=True)
