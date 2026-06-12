"""w6_dcpool.py — Phase-2 W6: DC-interlinked HPT clusters — quantify the energy-routing lever.

Physics (phase-1-calibrated): per-device sustainable series budget se_i ≤ (0.18 − sag_iq_i)/1.9
(the 1.9 constant lumps series DC drain vs local import capability; Vdc margin 0.82). With DC
interlinks, a CLUSTER pools budgets:  Σ se_i ≤ Σ (0.18 − sag_iq_i)/1.9  (+ per-device rating 0.2,
+ link transfer cap). Healthy members (V≈1, iq=0) contribute 0.095 each → a sagged member can run
series at FULL rating 0.2 (boost 9.4% vs solo ~4.5%).

Quantified here (no learner yet — discipline of lever-first):
  (a) load ride-through (400 scenarios, exact OpenDSS voltages, droop_full Q):
      solo vs pool-greedy allocation;
  (b) motor stall/trip/FIDVR (w5 model) solo vs pool;
  (c) how often the pool is CONTESTED (Σ demand > pool) -> the allocation decision space for RL.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
from w3_scenarios import gen_scenarios, build_network, HPT_BUSES, duration_rule

HERE = Path(__file__).resolve().parent
CLUSTERS = [[4, 7, 10], [14, 17, 21], [24, 28, 31, 33]]
IDX = {b: i for i, b in enumerate(HPT_BUSES)}
SE_GAIN, SE_RATE, IQ_CAP, HPT_KVA = 0.47, 0.20, 0.27, 400.0
LINK_CAP = None           # None = uncapped intra-cluster transfer (sensitivity later)


def budgets(vh, iq):
    """Per-device sustainable se budget (solo)."""
    sag_iq = 0.08 * np.abs(iq) / np.maximum(0.3, vh)
    return np.maximum(0.0, (1.0 - 0.82 - sag_iq) / 1.9)


def se_alloc(vh, iq, mode):
    """Series allocation.
    solo       : own budget only;
    pool       : cluster-pooled, greedy DEEPEST-first (naive — wastes pool on unsavable members);
    pool_smart : cluster-pooled, FLIP-aware — fund strict-flippable members (vh>=0.806) cheapest
                 first, then tol-flippable (vh>=0.606), then leftovers deepest-first."""
    B = budgets(vh, iq)
    se = np.zeros(len(HPT_BUSES))
    if mode == 'solo':
        for i in range(len(HPT_BUSES)):
            need = max(0.0, (0.90 - vh[i]) / SE_GAIN) if vh[i] < 0.9 else 0.0
            se[i] = min(SE_RATE, B[i], need if need > 0 else 0.0)
        return se, 0
    contested = 0
    for cl in CLUSTERS:
        ids = [IDX[b] for b in cl]
        pool = float(np.sum(B[ids]))
        needs = {i: min(SE_RATE, max(0.0, (0.90 - vh[i]) / SE_GAIN)) for i in ids if vh[i] < 0.9}
        if sum(needs.values()) > pool + 1e-9:
            contested = 1
        if mode == 'pool':
            order = sorted(needs, key=lambda i: vh[i])                    # deepest first
        else:  # pool_smart
            strict_flip = [i for i in needs if vh[i] >= 0.90 - SE_GAIN * SE_RATE]
            tol_flip = [i for i in needs if 0.70 - SE_GAIN * SE_RATE <= vh[i] < 0.70]
            rest = [i for i in needs if i not in strict_flip and i not in tol_flip]
            order = sorted(strict_flip, key=lambda i: needs[i]) + \
                    sorted(tol_flip, key=lambda i: max(0.0, (0.70 - vh[i]) / SE_GAIN)) + \
                    sorted(rest, key=lambda i: vh[i])
        for i in order:
            need = needs[i]
            if mode == 'pool_smart' and i in [j for j in needs if 0.70 - SE_GAIN * SE_RATE <= vh[j] < 0.70]:
                need = min(SE_RATE, max(0.0, (0.70 - vh[i]) / SE_GAIN) + 1e-3)   # fund to tol only
            give = min(need, pool)
            se[i] = give; pool -= give
            if pool <= 1e-9:
                break
    return se, contested


def eval_load(n=400):
    scen = gen_scenarios(n)
    agg = {m: {'strict': [], 'tol': []} for m in ['solo', 'pool', 'pool_smart']}
    contested_n, total = 0, 0
    for sc in scen:
        # droop_full Q fixed point (2 iters enough per W3)
        q = np.zeros(len(HPT_BUSES))
        v = None
        for _ in range(3):
            v = build_network(sc, list(q))
            if v is None:
                break
            vh = np.array([v[str(b)] for b in HPT_BUSES])
            q = np.clip(1.5 * (0.9 - vh), 0, IQ_CAP) * HPT_KVA
        if v is None:
            continue
        vh = np.array([v[str(b)] for b in HPT_BUSES])
        iq = q / HPT_KVA
        total += 1
        for mode in ['solo', 'pool', 'pool_smart']:
            se, cont = se_alloc(vh, iq, mode)
            if mode == 'pool':
                contested_n += cont
            vl = np.where(vh < 0.9, np.minimum(1.0, vh + SE_GAIN * se), vh)
            agg[mode]['strict'] += list(vl >= 0.90)
            agg[mode]['tol'] += list(vl >= 0.70)
    out = {}
    for m in agg:
        out[m] = {k: 100 * float(np.mean(v)) for k, v in agg[m].items()}
    out['contested_%'] = 100 * contested_n / max(1, total)
    return out


def eval_motor():
    """Motor stall/trip with solo vs pooled series (w5 model, se applied at HPT buses)."""
    import w5_motor as W5
    res = {}
    for fb, rf in [(6, 1.0), (12, 1.0), (25, 1.0), (30, 2.0), (12, 5.0), (30, 5.0)]:
        for mode in ['solo', 'pool']:
            r = run_motor_episode(W5, fb, rf, mode)
            res[f'{fb}_{rf}_{mode}'] = r
    return res


def run_motor_episode(W5, fault_bus, r_fault, mode, fault_dur=0.3):
    state = {b: {'ind': 'run', 'comp': 'run'} for b in W5.LOAD_BUSES}
    stall_t = {b: {'ind': 0.0, 'comp': 0.0} for b in W5.LOAD_BUSES}
    q = np.zeros(len(HPT_BUSES))
    v = W5.solve(fault_bus, r_fault, q, state)
    if v is None: return None
    for _ in range(3):
        vh = np.array([v[str(b)] for b in HPT_BUSES])
        q = np.clip(1.5 * (0.9 - vh), 0, IQ_CAP) * HPT_KVA
        v = W5.solve(fault_bus, r_fault, q, state)
        if v is None: return None
    vh = np.array([v[str(b)] for b in HPT_BUSES])
    se, _ = se_alloc(vh, q / HPT_KVA, mode)
    boost = {HPT_BUSES[i]: SE_GAIN * se[i] for i in range(len(HPT_BUSES))}
    for b in W5.LOAD_BUSES:
        if v[str(b)] + boost.get(b, 0.0) < W5.V_STALL:
            for t in ('ind', 'comp'):
                state[b][t] = 'stall'; stall_t[b][t] = fault_dur
    fidvr = 0.0
    for k in range(W5.N_REC):
        vh = np.array([v[str(b)] for b in HPT_BUSES]) if v else None
        q = np.full(len(HPT_BUSES), IQ_CAP * HPT_KVA)      # recovery: keep Q on (W5.1 lesson)
        v = W5.solve(None, None, q, state)
        if v is None: return None
        if min(v[str(b)] for b in W5.LOAD_BUSES) < 0.90:
            fidvr += W5.T_STEP
        vh = np.array([v[str(b)] for b in HPT_BUSES])
        se, _ = se_alloc(vh, q / HPT_KVA, mode)
        boost = {HPT_BUSES[i]: SE_GAIN * se[i] for i in range(len(HPT_BUSES))}
        for b in W5.LOAD_BUSES:
            if state[b]['ind'] == 'stall':
                if v[str(b)] + boost.get(b, 0.0) >= W5.V_REACC:
                    state[b]['ind'] = 'run'
                else:
                    stall_t[b]['ind'] += W5.T_STEP
                    if stall_t[b]['ind'] >= W5.T_TRIP: state[b]['ind'] = 'trip'
            if state[b]['comp'] == 'stall':
                stall_t[b]['comp'] += W5.T_STEP
                if stall_t[b]['comp'] >= W5.T_TRIP: state[b]['comp'] = 'trip'
    kw_i = {b: W5.BASE[b][0] * W5.MOTOR_FRAC * (1 - W5.COMP_FRAC) for b in W5.LOAD_BUSES}
    kw_c = {b: W5.BASE[b][0] * W5.MOTOR_FRAC * W5.COMP_FRAC for b in W5.LOAD_BUSES}
    tot = sum(kw_i.values()) + sum(kw_c.values())
    trip = sum(kw_i[b] for b in W5.LOAD_BUSES if state[b]['ind'] == 'trip') + \
           sum(kw_c[b] for b in W5.LOAD_BUSES if state[b]['comp'] == 'trip')
    nstall = sum(1 for b in W5.LOAD_BUSES if stall_t[b]['comp'] > 0)
    return {'trip_%': round(100 * trip / tot, 1), 'fidvr_s': round(fidvr, 1), 'n_stall': nstall}


def main():
    print('=== W6: DC-pool lever quantification ===')
    load = eval_load()
    print(f"strict: solo {load['solo']['strict']:.1f}  pool(naive) {load['pool']['strict']:.1f}  "
          f"pool_SMART {load['pool_smart']['strict']:.1f}   "
          f"(DC-link gain {load['pool']['strict']-load['solo']['strict']:+.1f}pp, "
          f"intelligence premium {load['pool_smart']['strict']-load['pool']['strict']:+.1f}pp)")
    print(f"tol   : solo {load['solo']['tol']:.1f}  pool {load['pool']['tol']:.1f}  "
          f"pool_smart {load['pool_smart']['tol']:.1f}")
    print(f"pool CONTESTED in {load['contested_%']:.1f}% of scenarios  <- allocation decision space")
    print('\nmotor cases (trip% / FIDVR s / initially stalled):')
    mot = eval_motor()
    for k, r in mot.items():
        print(f'  {k:14s}: {r}')
    json.dump({'load': load, 'motor': mot}, open(HERE / 'w6_dcpool.json', 'w'), indent=1)
    print('\nW6 DC-POOL LEVER QUANTIFIED')


if __name__ == '__main__':
    main()
