"""hpt_interface.py — Phase-2 W2: HPT interface model in OpenDSS + L2 surrogate + calibration audit.

W2.1 Interface: each HPT = controllable reactive source (Generator, kw=0, kvar in [-120,120],
     i.e. 0.3 pu of the 400 kVA device) at its MV bus. Quasi-static coupling loop:
     solve -> read local V -> device law (droop / coordinator command) -> update kvar -> resolve.
W2.2 Surrogate: per fault location, V ≈ V0(fault) + S·q  (sensitivity matrix from OpenDSS finite
     differences). Calibration AUDIT: random q vectors -> surrogate-vs-OpenDSS error stats.
     This is the phase-1 faithful-surrogate methodology lifted to network level.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
import opendssdirect as dss

HERE = Path(__file__).resolve().parent
HPT_BUSES = [6, 14, 25, 30]
QMAX = 120.0                 # kvar per HPT (0.3 pu × 400 kVA)
FAULT_R = 0.5


def build(fault_bus=None, q_kvar=None):
    dss.Text.Command(f'compile "{HERE / "ieee33.dss"}"')
    q = q_kvar if q_kvar is not None else [0.0] * len(HPT_BUSES)
    for i, b in enumerate(HPT_BUSES):
        dss.Text.Command(
            f'New Generator.hpt{b} bus1={b} phases=3 kv=12.66 kw=0.001 kvar={q[i]:.2f} '
            f'model=1 vminpu=0.05 vmaxpu=1.5')
    if fault_bus is not None:
        dss.Text.Command(f'New Fault.f1 bus1={fault_bus} phases=3 r={FAULT_R}')
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    assert dss.Solution.Converged()
    out = {}
    for b in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(b)
        v = dss.Bus.puVmagAngle()[::2]
        if v:
            out[b] = float(np.mean(v))
    return out


def v_at_hpts(p):
    return np.array([p[str(b)] for b in HPT_BUSES])


def droop_fixed_point(fault_bus, kq=1.5, iters=8):
    """Device-local droop (no coordination): q_pu = clip(kq*(0.9-V),0,0.3) each, iterate to fixed point."""
    q = np.zeros(len(HPT_BUSES))
    for _ in range(iters):
        p = build(fault_bus, q)
        v = v_at_hpts(p)
        q_new = np.clip(kq * (0.9 - v), 0, 0.3) * 400.0          # kvar
        q_new = np.minimum(q_new, QMAX)
        if np.max(np.abs(q_new - q)) < 1.0:
            q = q_new; break
        q = 0.5 * q + 0.5 * q_new                                 # damped
    return q, build(fault_bus, q)


def sensitivity(fault_bus, dq=60.0):
    """S[i,j] = dV_i/dQ_j (pu per kvar) at HPT buses, under the given fault."""
    p0 = build(fault_bus)
    v0 = v_at_hpts(p0)
    S = np.zeros((len(HPT_BUSES), len(HPT_BUSES)))
    for j in range(len(HPT_BUSES)):
        q = np.zeros(len(HPT_BUSES)); q[j] = dq
        S[:, j] = (v_at_hpts(build(fault_bus, q)) - v0) / dq
    return v0, S


def audit(fault_bus, v0, S, n=15, seed=0):
    """Surrogate V ≈ v0 + S q  vs exact OpenDSS, random q in [0, QMAX]."""
    rng = np.random.default_rng(seed)
    errs = []
    for _ in range(n):
        q = rng.uniform(0, QMAX, len(HPT_BUSES))
        v_sur = v0 + S @ q
        v_dss = v_at_hpts(build(fault_bus, q))
        errs.append(np.max(np.abs(v_sur - v_dss)))
    return float(np.mean(errs)), float(np.max(errs))


def main():
    res = {}
    print('=== W2: HPT interface + support effectiveness + surrogate audit ===')
    print(f'HPTs at buses {HPT_BUSES}, Qmax={QMAX:.0f} kvar each (0.3 pu of 400 kVA)\n')
    for fb in [12, 25, 30]:
        # (a) no support vs local droop (uncoordinated baseline)
        p_no = build(fb)
        q_droop, p_droop = droop_fixed_point(fb)
        v_no, v_dr = v_at_hpts(p_no), v_at_hpts(p_droop)
        # (b) sensitivity + full-Q upper bound
        v0, S = sensitivity(fb)
        p_full = build(fb, [QMAX] * 4)
        v_full = v_at_hpts(p_full)
        # (c) surrogate audit
        e_mean, e_max = audit(fb, v0, S)
        res[fb] = {'v_nofault_support': list(v_no), 'q_droop_kvar': list(q_droop),
                   'v_droop': list(v_dr), 'v_fullQ': list(v_full),
                   'S_pu_per_kvar': S.tolist(), 'audit_err_mean': e_mean, 'audit_err_max': e_max}
        print(f'fault@{fb}:')
        print(f'  V(HPT buses) no-support : ' + ' '.join(f'{x:.3f}' for x in v_no))
        print(f'  V             local droop: ' + ' '.join(f'{x:.3f}' for x in v_dr) +
              f'   (q={np.round(q_droop,0)})')
        print(f'  V             ALL Q=max  : ' + ' '.join(f'{x:.3f}' for x in v_full))
        print(f'  max self-sens dV/dQ = {np.max(np.diag(S))*1000:.3f} pu/Mvar*1e-3 ; '
              f'surrogate audit err mean/max = {e_mean:.4f}/{e_max:.4f} pu\n')
    (HERE / 'w2_results.json').write_text(json.dumps(res, indent=1))
    print('saved w2_results.json\nW2 INTERFACE+SURROGATE DONE')


if __name__ == '__main__':
    main()
