"""Validate emt_core against analytical solutions and known rectifier behaviour."""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from emt_core import Circuit

def test_RC():
    E, R, C = 10.0, 1.0, 1e-3   # tau = RC = 1e-3
    dt = 1e-6
    ck = Circuit(dt)
    ck.add_vsource_th('A', 'gnd', lambda t: E, R)   # EMF E (+ at A) behind R
    ck.add_C('A', 'gnd', C)
    err = 0.0
    for _ in range(5000):
        ck.step()
        ana = E*(1 - math.exp(-ck.t/(R*C)))
        err = max(err, abs(ck.v('A') - ana))
    print(f"RC charge: max|num-analytical| = {err:.4e} V  (E={E})  -> {'OK' if err<2e-2 else 'FAIL'}")
    return err < 2e-2

def test_RL():
    E, R, L = 10.0, 2.0, 1e-3   # tau = L/R = 5e-4, i_inf = 5
    dt = 1e-6
    ck = Circuit(dt)
    src = ck.add_vsource_th('A', 'gnd', lambda t: E, R)
    Lc = ck.add_L('A', 'gnd', L)
    err = 0.0
    for _ in range(3000):
        ck.step()
        ana = (E/R)*(1 - math.exp(-R*ck.t/L))
        err = max(err, abs(Lc.iL - ana))
    print(f"RL current: max|num-analytical| = {err:.4e} A  (i_inf={E/R})  -> {'OK' if err<2e-2 else 'FAIL'}")
    return err < 2e-2

def test_rectifier():
    # Half-wave: EMF sine behind R -> diode(src->out) -> C||Rload
    Vm, f, R = 100.0, 50.0, 0.5
    C, Rload = 1e-3, 50.0
    dt = 1e-6
    ck = Circuit(dt)
    ck.add_vsource_th('S', 'gnd', lambda t: Vm*math.sin(2*math.pi*f*t), R)
    d = ck.add_switch('OUT', 'S')      # diode conducts S->OUT (k=S,a=OUT) when V_S>V_OUT
    d.gate = 0
    ck.add_C('OUT', 'gnd', C)
    ck.add_R('OUT', 'gnd', Rload)
    vout = []
    for _ in range(int(0.1/dt)):       # 100 ms (5 cycles)
        ck.step({d: 0})
        vout.append(ck.v('OUT'))
    vout = np.array(vout)
    vtail = vout[int(0.06/dt):]        # after settling
    print(f"Half-wave rectifier: Vout mean={vtail.mean():.1f} V, ripple={vtail.max()-vtail.min():.1f} V "
          f"(peak~{Vm:.0f}) -> {'OK' if 70 < vtail.mean() < Vm and vtail.min()>0 else 'FAIL'}")
    return 70 < vtail.mean() < Vm and vtail.min() > 0

if __name__ == '__main__':
    ok = [test_RC(), test_RL(), test_rectifier()]
    print(f"\n{sum(ok)}/{len(ok)} core tests passed")
