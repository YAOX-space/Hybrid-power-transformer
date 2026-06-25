"""
gen_frt_scenarios.py — generate the standardized FRT scenario table per FRT_SPEC.md.

Matrix (FRT_SPEC §3): 32 families × 10 = 320 scenarios.
  LVRT (24 families) = type{sym3ph, 1ph_g, 2ph, 2ph_g} × residual{0.2,0.5,0.75} × grid{strong,weak}
  HVRT  (8 families) = type{swell_3ph, swell_1ph}        × level{1.2,1.3}        × grid{strong,weak}

Each scenario randomizes (fixed seed): load, power factor, fault instant, clearing time,
transition resistance. Voltage-time envelope per GB/T (residual held 625 ms, recover to
0.9 pu by 2 s; HVRT 1.3 pu/500 ms, 1.2 pu/1 s). SCR↔Z_grid: |Z|=V_LL²/(SCR·S_rated), X/R≈3.
"""
from __future__ import annotations
import csv, math
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parents[3] / 'lab' / 'frt_scenarios.csv'
VLL = 10e3            # MV line-line
S_RATED = 400e3
W = 2 * math.pi * 50

LVRT_TYPES = ['sym3ph', '1ph_g', '2ph', '2ph_g']
HVRT_TYPES = ['swell_3ph', 'swell_1ph']
LVRT_RESIDUAL = [0.2, 0.5, 0.75]      # pu residual voltage during dip [GB/T]
HVRT_LEVEL = [1.20, 1.30]             # pu swell level [GB/T 19963-2021]
GRID = {'strong': 10.0, 'weak': 3.0}  # SCR

REACH_09_S = 2.0                       # recover to 0.9 pu by 2 s [GB/T]


def z_grid(scr):
    zmag = VLL**2 / (scr * S_RATED)    # |Z| from short-circuit ratio
    R = zmag / math.sqrt(1 + 3**2)     # X/R = 3
    X = 3 * R
    return round(R, 4), round(X / W, 6)  # R(ohm), L(H)


def build(runs=10, seed=20260609):
    rng = np.random.default_rng(seed)
    rows, sid, fid = [], 0, 0
    families = []
    # LVRT families
    for ft in LVRT_TYPES:
        for vr in LVRT_RESIDUAL:
            for gname, scr in GRID.items():
                families.append(('LVRT', ft, vr, gname, scr))
    # HVRT families
    for ft in HVRT_TYPES:
        for lvl in HVRT_LEVEL:
            for gname, scr in GRID.items():
                families.append(('HVRT', ft, lvl, gname, scr))

    for (cat, ft, targetV, gname, scr) in families:
        fid += 1
        Rg, Lg = z_grid(scr)
        for _ in range(runs):
            sid += 1
            P = float(S_RATED * rng.uniform(0.70, 0.90))
            pf = float(rng.uniform(0.85, 0.95))
            Q = float(P * math.tan(math.acos(pf)))
            t_fault = float(rng.uniform(0.012, 0.030))
            if cat == 'LVRT':
                fault_dur = float(rng.uniform(0.15, 0.625))   # clearing time (≤625 ms ride window)
            else:  # HVRT swell duration per level
                fault_dur = 0.5 if targetV >= 1.30 else 1.0
            T_sim = round(t_fault + fault_dur + 1.5, 4)        # +1.5 s recovery window
            r_trans = float(rng.uniform(0.05, 0.8))           # transition resistance
            rows.append({
                'scenario_id': sid, 'family_id': fid, 'category': cat,
                'fault_type': ft, 'target_V_pu': round(targetV, 3),
                'grid': gname, 'scr': scr, 'Rg_ohm': Rg, 'Lg_H': Lg,
                'P_load': round(P, 1), 'Q_load': round(Q, 1), 'power_factor': round(pf, 4),
                't_fault': round(t_fault, 6), 'fault_dur': round(fault_dur, 4),
                'recover_to_0p9_s': REACH_09_S, 'T_sim': T_sim,
                'trans_resistance': round(r_trans, 4), 'random_seed': seed,
            })
    return rows


def main():
    rows = build()
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    # summary
    import collections
    bycat = collections.Counter(r['category'] for r in rows)
    bytype = collections.Counter(r['fault_type'] for r in rows)
    print(f'Wrote {len(rows)} FRT scenarios -> {OUT}')
    print(f'  by category: {dict(bycat)}')
    print(f'  by type:     {dict(bytype)}')
    print(f'  families: {max(r["family_id"] for r in rows)}  (expect 32)')
    print(f'  T_sim range: {min(r["T_sim"] for r in rows):.2f}–{max(r["T_sim"] for r in rows):.2f} s')


if __name__ == '__main__':
    main()
