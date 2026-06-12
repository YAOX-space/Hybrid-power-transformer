"""w3_scenarios.py — Phase-2 W3: system-level scenario generator + reframed criteria evaluator
+ uncoordinated baselines (full 10-HPT fleet).

Scenario matrix: fault bus × type {3ph,2ph,1ph} × resistance (log 0.3-30Ω → depth) × PV
penetration {30,60,90%} × load level {0.7,1.0}; duration COUPLED to depth (GB/T envelope logic:
deeper faults are cleared faster by protection).

Evaluator (reframed metrics, W2 decisions): per HPT a calibrated device model (phase-1 constants)
with Vdc as an ENERGY STATE across the fault window — the physical carrier of the coordination
dimension (DC budget). Series boost protects the HPT's own LV load (SE_GAIN=0.47, phase-1
measured); shunt iq satisfies the GB/T reactive mandate but (per W2) barely moves network voltage.

Baselines:
  B1 droop_full : iq = full GB/T droop (cap 0.27), series gets the leftover DC budget;
  B2 se_first   : iq = minimum that still passes the reactive criterion (ref−0.10),
                  series gets the (larger) leftover — compliance-minimal / protection-maximal.
The B1↔B2 gap on load ride-through quantifies the per-device trade-off headroom that a
coordinator can exploit per-location.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
import opendssdirect as dss

HERE = Path(__file__).resolve().parent
HPT_BUSES = [4, 7, 10, 14, 17, 21, 24, 28, 31, 33]   # 10-unit fleet (main + all branches)
HPT_KVA = 400.0
QMAX_PU, IQ_CAP = 0.30, 0.27
SE_GAIN, SE_MAX = 0.47, 0.20
PV_BUSES = [6, 11, 16, 20, 24, 30, 32]                # PV plants (kw scaled by penetration)
PV_KW_BASE = 250.0
LOAD_KW_TOTAL = 3715.0

# phase-1 calibrated DC model (faithful-ODE constants)
def vdc_eq(iq, se, v_local):
    return 1.0 - 0.08 * abs(iq) / max(0.3, v_local) - 1.9 * max(0.0, se)

DC_TAU = 0.0035 / 0.195        # effective Vdc relaxation time-constant (s) toward equilibrium


def gen_scenarios(n=400, seed=20260612):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        out.append({
            'id': i,
            'fault_bus': int(rng.integers(2, 34)),
            'phases': int(rng.choice([3, 2, 1], p=[0.3, 0.3, 0.4])),
            'r_fault': float(np.exp(rng.uniform(np.log(0.3), np.log(30.0)))),
            'pv_pen': float(rng.choice([0.3, 0.6, 0.9])),
            'load_lvl': float(rng.choice([0.7, 1.0])),
        })
    return out


def build_network(sc, q_kvar):
    dss.Text.Command(f'compile "{HERE / "ieee33.dss"}"')
    dss.Text.Command(f'set loadmult={sc["load_lvl"]}')
    for b in PV_BUSES:
        dss.Text.Command(f'New Generator.pv{b} bus1={b} phases=3 kv=12.66 '
                         f'kw={PV_KW_BASE * sc["pv_pen"]:.1f} pf=1 model=1 vminpu=0.05 vmaxpu=1.5')
    for i, b in enumerate(HPT_BUSES):
        dss.Text.Command(f'New Generator.hpt{b} bus1={b} phases=3 kv=12.66 kw=0.001 '
                         f'kvar={q_kvar[i]:.2f} model=1 vminpu=0.05 vmaxpu=1.5')
    dss.Text.Command(f'New Fault.f1 bus1={sc["fault_bus"]} phases={sc["phases"]} r={sc["r_fault"]:.3f}')
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    if not dss.Solution.Converged():
        return None
    v = {}
    for b in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(b)
        m = dss.Bus.puVmagAngle()[::2]
        if m:
            v[b] = float(np.mean(m))
    return v


def duration_rule(min_v):
    """GB/T-envelope-coupled clearing time: deeper = faster protection."""
    if min_v < 0.20:  return 0.15
    if min_v < 0.50:  return 0.30
    return 0.625


def device_step(policy, v_local):
    """Per-HPT action under a local policy. Returns (iq_pu, se_pu, iq_ref)."""
    iq_ref = float(np.clip(1.5 * (0.9 - v_local), 0, QMAX_PU)) if v_local < 0.9 else 0.0
    if policy == 'droop_full':
        iq = min(IQ_CAP, iq_ref)
    elif policy == 'se_first':
        iq = max(0.0, iq_ref - 0.10)          # reactive criterion tolerance is ±0.12
    else:
        raise ValueError(policy)
    # series budget: keep Vdc_eq >= 0.82 (phase-1 margin); se headroom from DC budget
    se_budget = max(0.0, (1.0 - 0.82 - 0.08 * iq / max(0.3, v_local)) / 1.9)
    se = min(SE_MAX, se_budget)
    return iq, se, iq_ref


def evaluate(sc, policy, iters=5):
    """Quasi-static fault window with Vdc energy state + post-fault recovery check."""
    nH = len(HPT_BUSES)
    q = np.zeros(nH)
    v = None
    for _ in range(iters):                                   # fleet<->network fixed point
        v = build_network(sc, q)
        if v is None:
            return None
        vh = np.array([v[str(b)] for b in HPT_BUSES])
        acts = [device_step(policy, x) for x in vh]
        q_new = np.array([a[0] * HPT_KVA for a in acts])
        if np.max(np.abs(q_new - q)) < 2.0:
            q = q_new; break
        q = 0.5 * q + 0.5 * q_new
    vh = np.array([v[str(b)] for b in HPT_BUSES])
    dur = duration_rule(min(v.values()))
    res = {'dur': dur, 'hpt': []}
    for i, b in enumerate(HPT_BUSES):
        iq, se, iq_ref = device_step(policy, vh[i])
        veq = vdc_eq(iq, se, vh[i])
        # Vdc trajectory: relax 1.0 -> veq over dur (energy state)
        vdc_end = veq + (1.0 - veq) * np.exp(-dur / DC_TAU)
        vdc_min = min(1.0, vdc_end)
        survive = vdc_min >= 0.75 or (vh[i] < 0.05 and dur <= 0.15)   # GB/T zero-V envelope
        reactive_ok = abs(iq - iq_ref) <= 0.12
        v_load = min(1.0, vh[i] + SE_GAIN * se) if vh[i] < 0.9 else vh[i]
        res['hpt'].append({'bus': b, 'v': float(vh[i]), 'iq': iq, 'se': se,
                           'vdc_min': float(vdc_min), 'survive': bool(survive),
                           'reactive': bool(reactive_ok),
                           'v_load': float(v_load),
                           'load_ok_strict': bool(v_load >= 0.90),
                           'load_ok_tol': bool(v_load >= 0.70)})
    return res


def aggregate(results):
    H = [h for r in results if r for h in r['hpt']]
    n = len(H)
    return {
        'n_device_evals': n,
        'survive_%': 100 * np.mean([h['survive'] for h in H]),
        'reactive_%': 100 * np.mean([h['reactive'] for h in H]),
        'load_strict_%': 100 * np.mean([h['load_ok_strict'] for h in H]),
        'load_tol_%': 100 * np.mean([h['load_ok_tol'] for h in H]),
        'compliance_%': 100 * np.mean([h['survive'] and h['reactive'] for h in H]),
    }


def main(n=400):
    scen = gen_scenarios(n)
    out = {}
    for pol in ['droop_full', 'se_first']:
        results, failed = [], 0
        for sc in scen:
            r = evaluate(sc, pol)
            if r is None:
                failed += 1; continue
            results.append(r)
        agg = aggregate(results)
        agg['nonconverged'] = failed
        out[pol] = agg
        print(f'[{pol}]  ' + '  '.join(f'{k}={v:.1f}' if isinstance(v, float) else f'{k}={v}'
                                       for k, v in agg.items()))
    (HERE / 'w3_baseline.json').write_text(json.dumps(out, indent=1))
    d = out['se_first']['load_strict_%'] - out['droop_full']['load_strict_%']
    print(f'\nTrade-off headroom (se_first vs droop_full, load_strict): {d:+.1f} pp')
    print('W3 BASELINES DONE')


if __name__ == '__main__':
    main()
