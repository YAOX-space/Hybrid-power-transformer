"""
hpt_emt_model.py — switching-level EMT model of the HPT, assembled on emt_core.

Incremental build. Phase A (this commit): 3-phase 10 kV grid (EMF behind Z_grid)
→ main Δ-Yg transformer (per-phase coupled inductors) → LV Y load.
Subsequent phases add: DC link + Tsh + shunt bridge, series H-bridges + Tse, faults.

Transformer model (per phase, matches SimPowerSystems linear-transformer family):
  coupled inductor with L1 = Lmag + Lleak1, L2 = Lmag/n² + Lleak2, M = Lmag/n
  (leakage folded into the inductance matrix), series winding R1/R2, magnetizing Rm.
"""
from __future__ import annotations
import math
import numpy as np
from emt_core import Circuit

# ── HPT parameters (from simulink/parameters.m) ─────────────────────────────────
F = 50.0
W = 2*math.pi*F
VLL_MV = 10e3
VLL_LV = 400.0
S_RATED = 400e3
RG, LG = 0.1, 0.3/W           # Z_grid = 0.1 + j0.3 Ω

def _xfmr_params(VLLp, VLLs, S, Lleak_pu=0.01, R_pu=0.002, Lmag=50.0,
                 prim_delta=True, sec_wye=True):
    """Per-winding coupled-inductor params for a 3-phase transformer.
    Delta winding sees line voltage; wye winding sees phase voltage."""
    Vw_p = VLLp if prim_delta else VLLp/math.sqrt(3)      # primary winding voltage
    Vw_s = VLLs/math.sqrt(3) if sec_wye else VLLs         # secondary winding voltage
    n = Vw_p/Vw_s
    Sw = S/3.0
    Zb_p = Vw_p**2/Sw; Zb_s = Vw_s**2/Sw
    Lleak1 = Lleak_pu*Zb_p/W; Lleak2 = Lleak_pu*Zb_s/W
    R1 = R_pu*Zb_p; R2 = R_pu*Zb_s
    L1 = Lmag + Lleak1; L2 = Lmag/n**2 + Lleak2; M = Lmag/n
    Rm = 500.0*Zb_p
    return dict(n=n, L1=L1, L2=L2, M=M, R1=R1, R2=R2, Rm=Rm)


def _tse_params(Lmag=2.0):
    """Single-phase series-injection transformer Tse: winding1 400V (H-bridge),
    winding2 46.2V (series in LV line). n=8.66, per-phase 40 kVA."""
    Vw1, Vw2, Sw = 400.0, 46.2, 120e3/3
    n = Vw1/Vw2
    Zb1, Zb2 = Vw1**2/Sw, Vw2**2/Sw
    Ll1, Ll2 = 0.001*Zb1/W, 0.001*Zb2/W
    R1 = 0.001*Zb1
    L1 = Lmag + Ll1; L2 = Lmag/n**2 + Ll2; M = Lmag/n
    return dict(n=n, L1=L1, L2=L2, M=M, R1=R1, Rm=1000.0)


def _add_grid_main_load(ck, P_load, Q_load, Lmag_main=50.0, sec_prefix='L', load_prefix='L'):
    # ── 3-phase grid: EMF (phase-neutral) behind R then L to grid bus G{a,b,c} ──
    Vm = VLL_MV/math.sqrt(3)*math.sqrt(2)        # phase-neutral peak = 8165 V
    ph = {'a': 0.0, 'b': -2*math.pi/3, 'c': 2*math.pi/3}
    for p, a in ph.items():
        ck.add_vsource_th(f'X{p}', 'gnd', (lambda a: (lambda t: Vm*math.sin(W*t+a)))(a), RG)
        ck.add_L(f'X{p}', f'G{p}', LG)
    # ── Main transformer Δ(MV)-Yg(LV); secondary output node = sec_prefix{p} ─────
    tp = _xfmr_params(VLL_MV, VLL_LV, S_RATED, Lmag=Lmag_main)
    delta = {'a': ('Ga', 'Gb'), 'b': ('Gb', 'Gc'), 'c': ('Gc', 'Ga')}
    for p, (hp, lp) in delta.items():
        wp, ws = f'Wp_{p}', f'Ls_{p}'
        ck.add_R(hp, wp, tp['R1']); ck.add_R(f'{sec_prefix}{p}', ws, tp['R2'])
        ck.add_coupledL([(wp, lp), (ws, 'gnd')], [[tp['L1'], tp['M']], [tp['M'], tp['L2']]])
        ck.add_R(wp, lp, tp['Rm'])
    # ── LV Y load on load_prefix{p} ─────────────────────────────────────────────
    Vph = VLL_LV/math.sqrt(3)
    ck._Rph = 3*Vph**2/P_load if P_load > 0 else 1e9
    for p in 'abc':
        ck.add_R(f'{load_prefix}{p}', 'gnd', ck._Rph)
    if Q_load > 0:
        Lph = (3*Vph**2/Q_load)/W
        for p in 'abc':
            ck.add_L(f'{load_prefix}{p}', 'gnd', Lph)


def _add_tsh_shunt(ck, Lmag_tsh=20.0, C_dc=2200e-6, R_damp=8.2, Vdc0=800.0):
    """Tsh(MV→400V) + shunt 3-phase bridge + DC link. Returns shunt switch dict."""
    tsp = _xfmr_params(VLL_MV, VLL_LV, 120e3, Lleak_pu=0.02, Lmag=Lmag_tsh)
    delta = {'a': ('Ga', 'Gb'), 'b': ('Gb', 'Gc'), 'c': ('Gc', 'Ga')}
    for p, (hp, lp) in delta.items():
        wp, ws = f'Tp_{p}', f'Ts_{p}'
        ck.add_R(hp, wp, tsp['R1']); ck.add_R(f'S{p}', ws, tsp['R2'])
        ck.add_coupledL([(wp, lp), (ws, 'gnd')], [[tsp['L1'], tsp['M']], [tsp['M'], tsp['L2']]])
        ck.add_R(wp, lp, tsp['Rm'])
    R_SH, L_SH = 0.05, 3e-3
    sw = {}
    for p in 'abc':
        ck.add_R(f'S{p}', f'Rf_{p}', R_SH)
        ck.add_L(f'Rf_{p}', f'B{p}', L_SH)
        sw[f'top_{p}'] = ck.add_switch('dcp', f'B{p}')
        sw[f'bot_{p}'] = ck.add_switch(f'B{p}', 'dcn')
    cap = ck.add_C('dcp', 'dcn', C_dc, v0=Vdc0)
    ck.add_R('dcp', 'dcn', R_damp)
    ck.add_R('dcn', 'gnd', 1e5)            # numerical common-mode reference
    return sw, cap


def _add_series(ck, Lmag_tse=2.0):
    """3× single-phase H-bridges + Tse: winding2 in series P{p}→L{p}, DC on dcp/dcn.
    Returns series switch dict (bipolar gating per phase)."""
    tse = _tse_params(Lmag_tse)
    sw = {}
    for p in 'abc':
        HA, HB = f'HA_{p}', f'HB_{p}'
        # Tse: winding1 (HA,HB) coupled to series winding2 (P{p}→L{p})
        ck.add_coupledL([(HA, HB), (f'P{p}', f'L{p}')],
                        [[tse['L1'], tse['M']], [tse['M'], tse['L2']]])
        ck.add_R(HA, HB, tse['Rm'])                 # magnetizing (approx)
        # single-phase full bridge (2 legs) on shared DC link
        sw[f'se_t1_{p}'] = ck.add_switch('dcp', HA)
        sw[f'se_b1_{p}'] = ck.add_switch(HA, 'dcn')
        sw[f'se_t2_{p}'] = ck.add_switch('dcp', HB)
        sw[f'se_b2_{p}'] = ck.add_switch(HB, 'dcn')
    return sw


def build_main_path(P_load, Q_load, dt=1e-6, Lmag_main=50.0):
    ck = Circuit(dt); _add_grid_main_load(ck, P_load, Q_load, Lmag_main); return ck


def build_shunt_model(P_load, Q_load, dt=2e-6, Lmag_main=50.0, Lmag_tsh=20.0,
                      C_dc=2200e-6, R_damp=8.2, Vdc0=800.0):
    """Main path + Tsh + shunt bridge + DC link. Returns (ck, h)."""
    ck = Circuit(dt)
    _add_grid_main_load(ck, P_load, Q_load, Lmag_main)
    sw, cap = _add_tsh_shunt(ck, Lmag_tsh, C_dc, R_damp, Vdc0)
    return ck, dict(sw=sw, cap=cap, Rph=ck._Rph)


def build_full_model(P_load, Q_load, dt=2e-6, Lmag_main=50.0, Lmag_tsh=20.0,
                     Lmag_tse=2.0, C_dc=2200e-6, R_damp=8.2, Vdc0=800.0, r_fault=0.3):
    """Full HPT: main path (secondary→P) + Tsh/shunt + series H-bridges (Tse: P→L)
    + per-phase LV fault branches. Both converters share the DC link. Returns (ck, h)."""
    ck = Circuit(dt)
    _add_grid_main_load(ck, P_load, Q_load, Lmag_main, sec_prefix='P', load_prefix='L')
    sw_sh, cap = _add_tsh_shunt(ck, Lmag_tsh, C_dc, R_damp, Vdc0)
    sw_se = _add_series(ck, Lmag_tse)
    # per-phase gated fault branches L{p}->gnd (gated off by default)
    flt = {p: ck.add_fault(f'L{p}', 'gnd', r_fault) for p in 'abc'}
    return ck, dict(sw_sh=sw_sh, sw_se=sw_se, cap=cap, Rph=ck._Rph, flt=flt, r_fault=r_fault)


def v2_ll_rms(ck, samples):
    """compute LV line-line RMS from collected [Va,Vb,Vc] samples."""
    a = np.array(samples)
    vab = a[:, 0]-a[:, 1]; vbc = a[:, 1]-a[:, 2]; vca = a[:, 2]-a[:, 0]
    return math.sqrt((np.mean(vab**2)+np.mean(vbc**2)+np.mean(vca**2))/3)


if __name__ == '__main__':
    # validate: rated load, expect V2_LL ≈ 400 V (minus leakage/regulation)
    P, Q = 320e3, 80e3
    dt = 1e-6
    ck = build_main_path(P, Q, dt)
    samp = []
    nstep = int(0.1/dt)
    for k in range(nstep):
        ck.step()
        if k > int(0.06/dt):
            samp.append([ck.v('La'), ck.v('Lb'), ck.v('Lc')])
    v2 = v2_ll_rms(ck, samp)
    print(f"main-path LV V2_LL_rms = {v2:.1f} V (expect ~360-400 under load)  "
          f"-> {'OK' if 330 < v2 < 410 else 'CHECK'}")
