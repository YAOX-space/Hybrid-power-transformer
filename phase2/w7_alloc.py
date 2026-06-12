"""w7_alloc.py — Phase-2 W7: allocator showdown for the DC-pool.

Single-step allocation is a small knapsack per cluster (3-4 members) -> EXACT optimum by subset
enumeration = theoretical ceiling for one-shot allocation. Ladder:
  solo < pool-naive(deepest-first) < pool-smart(flip-aware heuristic) <= pool-OPT (exact)
The OPT-vs-smart gap bounds what any smarter single-step allocator (incl. RL) can add;
RL's genuine room is then the TEMPORAL/motor-coupled dimension (tested on FIDVR episodes:
myopic-OPT per step vs heuristics — if insensitive, the honest verdict is that an enumeration
allocator IS the final scheme and learning is unnecessary at this layer).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from itertools import combinations
from pathlib import Path
import numpy as np
from w3_scenarios import gen_scenarios, build_network, HPT_BUSES
from w6_dcpool import budgets, se_alloc, CLUSTERS, IDX, SE_GAIN, SE_RATE, IQ_CAP, HPT_KVA

HERE = Path(__file__).resolve().parent
W_TOL = 0.3      # value of a tolerant flip relative to a strict flip


def opt_alloc(vh, iq):
    """Exact per-cluster optimum (subset enumeration over flip candidates)."""
    B = budgets(vh, iq)
    se = np.zeros(len(HPT_BUSES))
    for cl in CLUSTERS:
        ids = [IDX[b] for b in cl]
        pool = float(np.sum(B[ids]))
        cand = []   # (cost, value, idx)
        for i in ids:
            if vh[i] >= 0.9:
                continue
            need_s = (0.90 - vh[i]) / SE_GAIN
            if need_s <= SE_RATE:
                cand.append((need_s, 1.0, i))
            elif vh[i] < 0.70:
                need_t = (0.70 - vh[i]) / SE_GAIN
                if need_t <= SE_RATE:
                    cand.append((need_t, W_TOL, i))
        best_val, best_set = 0.0, ()
        for r in range(len(cand) + 1):
            for sub in combinations(cand, r):
                cost = sum(c[0] for c in sub)
                if cost <= pool + 1e-9:
                    val = sum(c[1] for c in sub)
                    if val > best_val + 1e-12:
                        best_val, best_set = val, sub
        for cost, _, i in best_set:
            se[i] = min(SE_RATE, cost + 1e-4)
    return se


def eval_load(n=400):
    scen = gen_scenarios(n)
    modes = ['solo', 'pool', 'pool_smart', 'pool_opt']
    agg = {m: {'strict': [], 'tol': []} for m in modes}
    for sc in scen:
        q = np.zeros(len(HPT_BUSES)); v = None
        for _ in range(3):
            v = build_network(sc, list(q))
            if v is None: break
            vh = np.array([v[str(b)] for b in HPT_BUSES])
            q = np.clip(1.5 * (0.9 - vh), 0, IQ_CAP) * HPT_KVA
        if v is None: continue
        vh = np.array([v[str(b)] for b in HPT_BUSES]); iq = q / HPT_KVA
        for m in modes:
            se = opt_alloc(vh, iq) if m == 'pool_opt' else se_alloc(vh, iq, m)[0]
            vl = np.where(vh < 0.9, np.minimum(1.0, vh + SE_GAIN * se), vh)
            agg[m]['strict'] += list(vl >= 0.90)
            agg[m]['tol'] += list(vl >= 0.70)
    return {m: {k: 100 * float(np.mean(x)) for k, x in d.items()} for m, d in agg.items()}


def eval_motor():
    """FIDVR episodes with myopic-OPT vs smart vs naive (temporal dimension test)."""
    import w5_motor as W5
    from w6_dcpool import run_motor_episode
    res = {}
    # monkey-patch a per-mode se chooser into the w6 episode runner via mode string
    for fb, rf in [(25, 1.0), (30, 2.0), (12, 5.0), (6, 8.0), (18, 8.0)]:
        for mode in ['pool', 'pool_smart']:
            r = run_motor_episode(W5, fb, rf, mode)
            res[f'{fb}_{rf}_{mode}'] = r
    return res


def main():
    print('=== W7: allocator showdown (load ride-through, exact OpenDSS, 400 scen) ===')
    L = eval_load()
    for m in L:
        print(f'  {m:11s}: strict {L[m]["strict"]:.1f}%  tol {L[m]["tol"]:.1f}%')
    gap = L['pool_opt']['strict'] - L['pool_smart']['strict']
    print(f'\n  OPT - smart = {gap:+.1f} pp  <- remaining single-step intelligence headroom')
    print('\nmotor episodes (temporal dimension):')
    M = eval_motor()
    for k, r in M.items():
        print(f'  {k:18s}: {r}')
    json.dump({'load': L, 'motor': M}, open(HERE / 'w7_alloc.json', 'w'), indent=1)
    print('W7 SHOWDOWN DONE')


if __name__ == '__main__':
    main()
