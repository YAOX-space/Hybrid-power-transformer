"""w4_eval.py — W4 final evaluation: 4 policies × scenarios, voltages from EXACT OpenDSS
(L3 authority, surrogate only used inside the coordinator's training).
Policies: droop_full / se_first / all_max / SAC coordinator (w4_coordinator_best.zip).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
from stable_baselines3 import SAC
from w3_scenarios import gen_scenarios, build_network, HPT_BUSES
from w4_train import device_outcome, floors, policy_uniform, IQ_CAP, HPT_KVA

HERE = Path(__file__).resolve().parent


def eval_policy(name, model=None, n=400):
    scen = gen_scenarios(n)
    data = np.load(HERE / 'w4_dataset.npz')
    v0s, metas = data['v0'], data['meta']
    # map scenario id -> dataset row (dataset kept converged ones in order)
    agg = {'strict': [], 'tol': [], 'survive': []}
    di = 0
    for sc in scen:
        # recompute no-support to check convergence (skip the 13 nonconverged like dataset did)
        if di >= len(v0s):
            break
        v0 = v0s[di]; meta = metas[di]
        if int(meta[0]) != sc['fault_bus']:
            continue  # this scenario was dropped in dataset (nonconverged)
        di += 1
        dur = meta[5]
        if name == 'coord':
            obs = np.concatenate([v0, [v0.min(), meta[3], meta[4]]]).astype(np.float32)
            a, _ = model.predict(obs, deterministic=True)
            f = floors(v0)
            q = f + (a * 0.5 + 0.5) * (IQ_CAP - f)
        else:
            q = policy_uniform(v0, name)
        v = build_network(sc, list(q * HPT_KVA))
        if v is None:
            continue
        for h, b in enumerate(HPT_BUSES):
            v_load, surv = device_outcome(max(0.01, v[str(b)]), q[h], dur)
            agg['strict'].append(v_load >= 0.90)
            agg['tol'].append(v_load >= 0.70)
            agg['survive'].append(surv)
    out = {k: 100 * float(np.mean(v)) for k, v in agg.items()}
    out['n'] = len(agg['strict'])
    return out


def main():
    res = {}
    for name in ['droop_full', 'se_first', 'all_max']:
        res[name] = eval_policy(name)
        print(f'{name:11s}: ' + '  '.join(f'{k}={v:.1f}' for k, v in res[name].items()))
    model = SAC.load(str(HERE / 'w4_coordinator_best.zip'), device='cpu')
    res['coord'] = eval_policy('coord', model)
    print(f'{"coord":11s}: ' + '  '.join(f'{k}={v:.1f}' for k, v in res['coord'].items()))
    (HERE / 'w4_eval.json').write_text(json.dumps(res, indent=1))
    gain = res['coord']['strict'] - res['droop_full']['strict']
    print(f'\nCOORDINATION GAIN (strict load ride-through, exact OpenDSS): {gain:+.1f} pp')
    print('W4 EVAL DONE')


if __name__ == '__main__':
    main()
