"""w4_dataset.py — precompute per-scenario (v0, S) from OpenDSS for coordinator training.
v0 = no-support fault voltages at HPT buses; S = dV/dQ sensitivity (audited linear surrogate).
~400 scenarios x 11 solves. Output: w4_dataset.npz
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from pathlib import Path
from w3_scenarios import gen_scenarios, build_network, HPT_BUSES, duration_rule

HERE = Path(__file__).resolve().parent
DQ = 60.0  # kvar finite difference


def main(n=400):
    scen = gen_scenarios(n)
    V0, S, META = [], [], []
    kept = 0
    for sc in scen:
        v = build_network(sc, [0.0] * len(HPT_BUSES))
        if v is None:
            continue
        v0 = np.array([v[str(b)] for b in HPT_BUSES])
        Smat = np.zeros((len(HPT_BUSES), len(HPT_BUSES)))
        ok = True
        for j in range(len(HPT_BUSES)):
            q = [0.0] * len(HPT_BUSES); q[j] = DQ
            vj = build_network(sc, q)
            if vj is None:
                ok = False; break
            Smat[:, j] = (np.array([vj[str(b)] for b in HPT_BUSES]) - v0) / DQ
        if not ok:
            continue
        V0.append(v0); S.append(Smat)
        META.append([sc['fault_bus'], sc['phases'], sc['r_fault'], sc['pv_pen'],
                     sc['load_lvl'], duration_rule(min(v.values()))])
        kept += 1
        if kept % 50 == 0:
            print(f'{kept} scenarios done', flush=True)
    np.savez(HERE / 'w4_dataset.npz', v0=np.array(V0), S=np.array(S), meta=np.array(META))
    print(f'DATASET DONE: {kept} scenarios -> w4_dataset.npz')


if __name__ == '__main__':
    main()
