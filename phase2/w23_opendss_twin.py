"""w23_opendss_twin.py — phasor twin of the phase-1 EMT divider (source Z @SCR=3, fault r at MV,
10kV/0.4kV transformer, LV load). Compares LV fault residuals vs w23_emt_residuals.csv (EMT).
Agreement bound = phasor-approximation credibility for sag-propagation studies (W2.3 deliverable).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from pathlib import Path
import opendssdirect as dss

HERE = Path(__file__).resolve().parent
RG, LG = 11.785, 0.2626          # phase-1 weak grid SCR=3 (10 kV side)
XG = 2 * np.pi * 50 * LG
EMF_PU = 11281.3 / (10e3 * np.sqrt(3) / np.sqrt(3))   # EMT-calibrated EMF (LL kV base 10)


def solve(r_fault):
    dss.Text.Command('clear')
    dss.Text.Command(f'New Circuit.twin basekv=10 pu={11281.3/10000:.4f} phases=3 bus1=src '
                     'MVAsc3=500000 MVAsc1=500000')
    dss.Text.Command(f'New Line.zg bus1=src bus2=mv r1={RG} x1={XG} r0={RG} x0={XG} c1=0 c0=0 length=1')
    dss.Text.Command('New Transformer.t1 phases=3 windings=2 xhl=4 '
                     'wdg=1 bus=mv conn=delta kv=10 kva=400 %r=0.5 '
                     'wdg=2 bus=lv conn=wye kv=0.4 kva=400 %r=0.5')
    dss.Text.Command('New Load.l1 bus1=lv phases=3 kv=0.4 kw=320 kvar=155 model=1 vminpu=0.3 vmaxpu=1.5')
    dss.Text.Command(f'New Fault.f1 bus1=mv phases=3 r={r_fault}')
    dss.Text.Command('Set VoltageBases=[10 0.4]')
    dss.Text.Command('CalcVoltageBases')
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    assert dss.Solution.Converged()
    dss.Circuit.SetActiveBus('lv')
    return float(np.mean(dss.Bus.puVmagAngle()[::2]))


emt = np.loadtxt(HERE / 'w23_emt_residuals.csv', delimiter=',')
print(f'{"r_fault":>8} | {"EMT":>8} | {"OpenDSS":>8} | {"diff":>7}')
errs = []
for r, v_emt in emt:
    v_dss = solve(r)
    errs.append(abs(v_dss - v_emt))
    print(f'{r:8.1f} | {v_emt:8.4f} | {v_dss:8.4f} | {v_dss-v_emt:+7.4f}')
print(f'\nmax |diff| = {max(errs):.4f} pu, mean = {np.mean(errs):.4f} pu')
print('W2.3 CROSS-CHECK DONE')
