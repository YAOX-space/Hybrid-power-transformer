"""train_seeds.py — overnight robustness batch:
(a) seed robustness: 4 experts x seeds {7, 123} (production seed=42 already exists) -> ODE best per run
(b) single-SAC ablation: ONE SAC on ALL 320 scenarios (faithful ODE), seed 42 -> is the 4-expert split needed?
Saves seed-tagged zips (sd_{seed}_{name}_best.zip / ablation_single_best.zip) — production untouched.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from frt_env import HPTFRTEnv, load_frt_scenarios
from frt_metrics import evaluate_frt

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parent / 'data' / 'models'

EXPERTS = {
    'sym':       lambda s: s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph',
    'asym':      lambda s: s['category'] == 'LVRT' and s['fault_type'] in ('1ph_g', '2ph', '2ph_g'),
    'hvrt_sym':  lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph',
    'hvrt_asym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph',
}


def train_one(tag, filt, seed, total_steps=300_000, n_envs=8, eval_freq=25_000):
    scen = [s for s in load_frt_scenarios(ROOT / 'frt_scenarios.csv') if filt(s)]
    print(f'\n=== {tag} (seed {seed}): {len(scen)} scenarios ===', flush=True)
    vec = DummyVecEnv([lambda: HPTFRTEnv(scen, seed=int(np.random.randint(99999)), train_mode=True)
                       for _ in range(n_envs)])
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device='cpu', verbose=0, seed=seed)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, scen, HPTFRTEnv, n_eval=min(80, len(scen)))
        if m['frt_pass'] > best:
            best = m['frt_pass']; sac.save(str(MODELS / f'{tag}_best.zip'))
        print(f"  [{tag}] step={step:7,} FRT={m['frt_pass']:.0f}% best={best:.0f}% "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    return best


if __name__ == '__main__':
    res = {}
    # (a) seed robustness
    for seed in [7, 123]:
        for nm, fl in EXPERTS.items():
            res[f'sd{seed}/{nm}'] = train_one(f'sd_{seed}_{nm}', fl, seed)
            (ROOT / 'results' / 'seeds_train.json').write_text(json.dumps(res, indent=2))
    # (b) single-SAC ablation on all 320
    res['ablation_single'] = train_one('ablation_single', lambda s: True, 42)
    (ROOT / 'results' / 'seeds_train.json').write_text(json.dumps(res, indent=2))
    print('\nSEEDS+ABLATION DONE:', res, flush=True)
