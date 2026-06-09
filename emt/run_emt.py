"""run_emt.py — drive the EMT HPT model with SAC直接调制 control; validate vs Simulink."""
import sys, math, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from hpt_emt_model import build_shunt_model
from hpt_emt_control import EnergyCtrl

I2_NOM_PK = (400e3/(math.sqrt(3)*400.0))*math.sqrt(2)   # 816.5 A

def run_shunt(m_sh, P=320e3, Q=80e3, dt=2e-6, t_end=0.06, t_fault=0.02, mode=9):
    ck, h = build_shunt_model(P, Q, dt)
    ck.build()
    ctrl = EnergyCtrl(dt)
    sw = h['sw']; Rph = h['Rph']
    vdc_hist = []
    n = int(t_end/dt)
    for k in range(n):
        vdc = ck.vdiff('dcp', 'dcn')
        v2 = [ck.v('La'), ck.v('Lb'), ck.v('Lc')]
        ipk = max(abs(v2[0]), abs(v2[1]), abs(v2[2]))/Rph     # resistive load current approx
        ipu = ipk/I2_NOM_PK
        gates, m = ctrl.gates(ck.t, vdc, v2, ipu, t_fault, m_sh, mode=mode)
        gd = {}
        for i, p in enumerate('abc'):
            gd[sw[f'top_{p}']] = gates[i]
            gd[sw[f'bot_{p}']] = 1 - gates[i]
        ck.step(gd)
        if k > int(0.04/dt):
            vdc_hist.append(ck.vdiff('dcp', 'dcn'))
    return float(np.mean(vdc_hist[-200:])) if vdc_hist else float('nan')

def run_full(m_sh, m_se_d, m_se_q, P=320e3, Q=80e3, dt=2e-6, t_end=0.06, t_fault=0.02):
    """Full HPT (shunt + series), both controllers. Returns (Vdc_end, V2_ll_rms)."""
    from hpt_emt_model import build_full_model, v2_ll_rms
    from hpt_emt_control import EnergyCtrl, RegulationCtrl
    ck, h = build_full_model(P, Q, dt); ck.build()
    ec, rc = EnergyCtrl(dt), RegulationCtrl(dt)
    sh, se, Rph = h['sw_sh'], h['sw_se'], h['Rph']
    vdc_h, v2samp = [], []
    for k in range(int(t_end/dt)):
        vdc = ck.vdiff('dcp', 'dcn')
        v2 = [ck.v('La'), ck.v('Lb'), ck.v('Lc')]
        ipu = max(abs(x) for x in v2)/Rph/I2_NOM_PK
        g_sh, _ = ec.gates(ck.t, vdc, v2, ipu, t_fault, m_sh)
        g_se, _ = rc.gates(ck.t, vdc, v2, ipu, t_fault, m_se_d, m_se_q)
        gd = {}
        for i, p in enumerate('abc'):
            gd[sh[f'top_{p}']] = g_sh[i]; gd[sh[f'bot_{p}']] = 1-g_sh[i]
            ga = g_se[i]                              # bipolar H-bridge
            gd[se[f'se_t1_{p}']] = ga;   gd[se[f'se_b1_{p}']] = 1-ga
            gd[se[f'se_t2_{p}']] = 1-ga; gd[se[f'se_b2_{p}']] = ga
        ck.step(gd)
        if k > int(0.04/dt):
            vdc_h.append(ck.vdiff('dcp', 'dcn')); v2samp.append(v2)
    return float(np.mean(vdc_h[-200:])), v2_ll_rms(ck, v2samp[-int(0.01/dt):])


def run_scenario(sc_id, m_sh, m_se_d, m_se_q, P=320e3, Q=80e3, t_fault=0.02,
                 r_fault=0.3, fault_dur=0.015, dt=2e-6, T_sim=0.05):
    """Full EMT scenario with fault injection; returns LVRT metrics dict."""
    from hpt_emt_model import build_full_model
    from hpt_emt_control import EnergyCtrl, RegulationCtrl
    C_dc = 680e-6 if sc_id == 5 else 2200e-6
    ck, h = build_full_model(P, Q, dt, C_dc=C_dc, r_fault=r_fault); ck.build()
    ec, rc = EnergyCtrl(dt), RegulationCtrl(dt)
    sh, se, flt, Rph = h['sw_sh'], h['sw_se'], h['flt'], h['Rph']
    fphases = {6: ['a'], 7: ['a', 'b', 'c']}.get(sc_id, [])
    vmin, vmax, i2max = 2.0, 0.0, 0.0
    for k in range(int(T_sim/dt)):
        t = ck.t
        vdc = ck.vdiff('dcp', 'dcn'); v2 = [ck.v('La'), ck.v('Lb'), ck.v('Lc')]
        faulted = (t_fault <= t < t_fault + fault_dur)
        # I2 (secondary line current) = load + fault branch current
        ipk = 0.0
        for i, p in enumerate('abc'):
            ip = abs(v2[i])*(1.0/Rph + (1.0/r_fault if (faulted and p in fphases) else 0.0))
            ipk = max(ipk, ip)
        ipu = ipk/I2_NOM_PK
        g_sh, _ = ec.gates(t, vdc, v2, ipu, t_fault, m_sh)
        g_se, _ = rc.gates(t, vdc, v2, ipu, t_fault, m_se_d, m_se_q)
        gd = {}
        for i, p in enumerate('abc'):
            gd[sh[f'top_{p}']] = g_sh[i]; gd[sh[f'bot_{p}']] = 1-g_sh[i]
            ga = g_se[i]
            gd[se[f'se_t1_{p}']] = ga;   gd[se[f'se_b1_{p}']] = 1-ga
            gd[se[f'se_t2_{p}']] = 1-ga; gd[se[f'se_b2_{p}']] = ga
            gd[flt[p]] = 1 if (faulted and p in fphases) else 0
        # IGBT open-circuit faults: disable one device during fault
        if faulted and sc_id in (3, 8): gd[sh['bot_a']] = 0
        if faulted and sc_id == 4:      gd[se['se_b1_a']] = 0
        ck.step(gd)
        if t >= t_fault:
            vdc2 = ck.vdiff('dcp', 'dcn')/800.0
            vmin = min(vmin, vdc2); vmax = max(vmax, vdc2); i2max = max(i2max, ipu)
    ok = (vmin >= 0.75) and (vmax <= 1.25) and (i2max <= 3.0)
    return dict(vdc_min=round(vmin, 3), vdc_max=round(vmax, 3), i2_max=round(i2max, 2), lvrt=ok)


if __name__ == '__main__':
    if sys.argv[1:2] == ['scen']:
        names = {0: 'normal', 6: 'sc_1ph', 7: 'sc_3ph', 5: 'cap_fault'}
        print("sc_id  name      Vdc_min  Vdc_max  I2_max  LVRT")
        for sc in [0, 6, 7, 5]:
            rf = 0.3 if sc in (6, 7) else 0.3
            m = run_scenario(sc, 0.90, 0.0, 0.0, r_fault=rf)
            print(f"{sc:5d}  {names[sc]:9s} {m['vdc_min']:7.3f}  {m['vdc_max']:7.3f}  {m['i2_max']:6.2f}  {m['lvrt']}")
        sys.exit(0)
    if sys.argv[1:2] == ['full']:
        print("m_sh  m_se_d m_se_q  Vdc    V2_LL   note")
        for (msh, md, mq) in [(0.82, 0.0, 0.0), (0.82, 0.20, 0.0), (0.82, -0.20, 0.0)]:
            v, v2 = run_full(msh, md, mq)
            print(f"{msh:.2f}  {md:+.2f}  {mq:+.2f}  {v:6.1f}  {v2:6.1f}")
        sys.exit(0)
    ref = {0.40: 750, 0.60: 760, 0.82: 876, 0.90: 913}   # Simulink probe
    print("m_sh   EMT_Vdc   Simulink   note")
    t0 = time.time()
    for m in [float(x) for x in (sys.argv[1:] or [0.40, 0.60, 0.82, 0.90])]:
        v = run_shunt(m)
        print(f"{m:.2f}   {v:7.1f}   {ref.get(round(m,2),'-')!s:>8}   ({time.time()-t0:.0f}s)")
