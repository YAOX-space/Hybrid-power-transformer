"""w5_motor.py — Phase-2 W5.1: recovery-window physics with induction-motor loads (FIDVR).

Why: W5.0 analytic check killed DC-recharge scheduling (704 J caps recharge in ~3 ms — invisible
at feeder scale). The real recovery-window physics is motor stall/reacceleration:
  - during fault: motor stalls if its bus voltage < V_STALL;
  - stalled motor = locked-rotor impedance (≈6× current, pf 0.3) → keeps voltage depressed
    after the fault clears (FIDVR) → neighbors can't reaccelerate → bistable cascade;
  - thermal trip after T_TRIP stalled → load lost.
Quasi-static multi-step simulation: fault step + recovery steps with OpenDSS network solves,
motor states evolving between steps. HPT actions per step: reactive q (network support) +
series boost (protects own bus's motors via compensated voltage).

W5.1 deliverable: quantify the coordination lever — stall/trip outcomes under
  (a) no HPT support, (b) local droop, (c) all-max Q —
across severe scenarios. If (c)-(b) gap is real, the multi-step coordinator (W5.2) has teeth.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
import opendssdirect as dss

HERE = Path(__file__).resolve().parent
HPT_BUSES = [4, 7, 10, 14, 17, 21, 24, 28, 31, 33]
HPT_KVA, IQ_CAP, SE_GAIN = 400.0, 0.27, 0.47
LOAD_BUSES = list(range(2, 34))
MOTOR_FRAC = 0.5          # fraction of each load that is induction motor
COMP_FRAC = 0.4           # of the motor part: single-phase compressor type (CANNOT reaccelerate
                          # against head pressure — stays locked-rotor until thermal trip; the
                          # real-world FIDVR driver per NERC)
V_STALL = 0.55            # stalls below this during any step
V_REACC = 0.78            # industrial 3-phase motors reaccelerate above this
LR_I, LR_PF = 6.0, 0.30   # locked-rotor: 6x current at pf 0.3
T_STEP, T_TRIP = 0.2, 4.0 # step (s); compressor thermal trip after stalled this long
N_REC = 25                # recovery steps (5 s)

# base loads (kW,kvar) from ieee33
BASE = {2:(100,60),3:(90,40),4:(120,80),5:(60,30),6:(60,20),7:(200,100),8:(200,100),9:(60,20),
        10:(60,20),11:(45,30),12:(60,35),13:(60,35),14:(120,80),15:(60,10),16:(60,20),17:(60,20),
        18:(90,40),19:(90,40),20:(90,40),21:(90,40),22:(90,40),23:(90,50),24:(420,200),25:(420,200),
        26:(60,25),27:(60,25),28:(60,20),29:(120,70),30:(200,600),31:(150,70),32:(210,100),33:(60,40)}


def add_motor(name, bus, mkw, st):
    if st == 'run':
        dss.Text.Command(f'New Load.{name} bus1={bus} phases=3 kv=12.66 kw={mkw:.1f} '
                         f'kvar={mkw*0.45:.1f} model=1 vminpu=0.4 vmaxpu=1.4')
    elif st == 'stall':
        s_lr = LR_I * mkw / 0.85                           # locked-rotor apparent power at 1 pu
        dss.Text.Command(f'New Load.{name} bus1={bus} phases=3 kv=12.66 kw={s_lr*LR_PF:.1f} '
                         f'kvar={s_lr*np.sqrt(1-LR_PF**2):.1f} model=2 vminpu=0.2 vmaxpu=1.4')
    # 'trip': removed


def solve(fault_bus, r_fault, q_kvar, motor_state):
    """One quasi-static step. motor_state[b] = {'ind': st, 'comp': st}, st in {'run','stall','trip'}.
    ind = 3-phase industrial (can reaccelerate); comp = 1-phase compressor (cannot)."""
    dss.Text.Command(f'compile "{HERE / "ieee33.dss"}"')
    dss.Text.Command('set algorithm=newton')
    for b in LOAD_BUSES:
        kw, kvar = BASE[b]
        mkw = kw * MOTOR_FRAC
        skw, skvar = kw - mkw, kvar * (1 - MOTOR_FRAC)
        dss.Text.Command(f'Load.S{b}.kw={skw:.1f}')
        dss.Text.Command(f'Load.S{b}.kvar={skvar:.1f}')
        add_motor(f'MI{b}', b, mkw * (1 - COMP_FRAC), motor_state[b]['ind'])
        add_motor(f'MC{b}', b, mkw * COMP_FRAC, motor_state[b]['comp'])
    for i, b in enumerate(HPT_BUSES):
        dss.Text.Command(f'New Generator.hpt{b} bus1={b} phases=3 kv=12.66 kw=0.001 '
                         f'kvar={q_kvar[i]:.2f} model=1 vminpu=0.05 vmaxpu=1.5')
    if fault_bus is not None:
        dss.Text.Command(f'New Fault.f1 bus1={fault_bus} phases=3 r={r_fault}')
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


def hpt_q(policy, v):
    vh = np.array([v[str(b)] for b in HPT_BUSES])
    if policy == 'none':
        return np.zeros(len(HPT_BUSES))
    if policy == 'droop':
        return np.clip(1.5 * (0.9 - vh), 0, IQ_CAP) * HPT_KVA
    if policy == 'allmax':
        return np.full(len(HPT_BUSES), IQ_CAP * HPT_KVA)
    raise ValueError(policy)


def episode(fault_bus, r_fault, policy, fault_dur=0.3):
    """Fault window (stall decisions) + N_REC recovery steps.
    ind motors reaccelerate at V>=V_REACC; comp motors NEVER reaccelerate (thermal trip at T_TRIP)."""
    state = {b: {'ind': 'run', 'comp': 'run'} for b in LOAD_BUSES}
    stall_t = {b: {'ind': 0.0, 'comp': 0.0} for b in LOAD_BUSES}
    se_boost = {b: 0.0 for b in LOAD_BUSES}
    # --- fault window ---
    q = np.zeros(len(HPT_BUSES))
    v = solve(fault_bus, r_fault, q, state)
    if v is None: return None
    for _ in range(3):
        q = hpt_q(policy, v)
        v = solve(fault_bus, r_fault, q, state)
        if v is None: return None
    for i, b in enumerate(HPT_BUSES):
        iq = q[i] / HPT_KVA
        se = min(0.2, max(0, (1 - 0.82 - 0.08 * iq / max(0.3, v[str(b)])) / 1.9))
        se_boost[b] = SE_GAIN * se
    for b in LOAD_BUSES:
        v_eff = v[str(b)] + se_boost.get(b, 0.0)
        if v_eff < V_STALL:
            for t in ('ind', 'comp'):
                state[b][t] = 'stall'; stall_t[b][t] = fault_dur
    # --- recovery window ---
    fidvr_t, reacc_delay = 0.0, {}
    for k in range(N_REC):
        q = hpt_q(policy, v)
        v = solve(None, None, q, state)
        if v is None: return None
        if min(v[str(b)] for b in LOAD_BUSES) < 0.90:
            fidvr_t += T_STEP
        for i, b in enumerate(HPT_BUSES):
            iq = q[i] / HPT_KVA
            se = min(0.2, max(0, (1 - 0.82 - 0.08 * iq / max(0.3, v[str(b)])) / 1.9))
            se_boost[b] = SE_GAIN * se
        for b in LOAD_BUSES:
            if state[b]['ind'] == 'stall':
                v_eff = v[str(b)] + se_boost.get(b, 0.0)
                if v_eff >= V_REACC:
                    state[b]['ind'] = 'run'
                    reacc_delay[b] = (k + 1) * T_STEP
                else:
                    stall_t[b]['ind'] += T_STEP
                    if stall_t[b]['ind'] >= T_TRIP:
                        state[b]['ind'] = 'trip'
            if state[b]['comp'] == 'stall':
                stall_t[b]['comp'] += T_STEP
                if stall_t[b]['comp'] >= T_TRIP:
                    state[b]['comp'] = 'trip'
    kw_ind = {b: BASE[b][0] * MOTOR_FRAC * (1 - COMP_FRAC) for b in LOAD_BUSES}
    kw_comp = {b: BASE[b][0] * MOTOR_FRAC * COMP_FRAC for b in LOAD_BUSES}
    kw_tot = sum(kw_ind.values()) + sum(kw_comp.values())
    kw_trip = sum(kw_ind[b] for b in LOAD_BUSES if state[b]['ind'] == 'trip') + \
              sum(kw_comp[b] for b in LOAD_BUSES if state[b]['comp'] == 'trip')
    kw_stuck = sum(kw_ind[b] for b in LOAD_BUSES if state[b]['ind'] == 'stall') + \
               sum(kw_comp[b] for b in LOAD_BUSES if state[b]['comp'] == 'stall')
    n_init = sum(1 for b in LOAD_BUSES if stall_t[b]['ind'] > 0)
    mean_reacc = float(np.mean(list(reacc_delay.values()))) if reacc_delay else 0.0
    return {'trip_%': 100 * kw_trip / kw_tot, 'stuck_%': 100 * kw_stuck / kw_tot,
            'fidvr_s': fidvr_t, 'n_stalled_init': n_init, 'mean_reacc_s': mean_reacc}


def main():
    cases = [(6, 1.0), (6, 3.0), (12, 1.0), (25, 1.0), (30, 2.0), (3, 3.0)]
    print(f'motor fraction {MOTOR_FRAC} (comp {COMP_FRAC} of it, no-reacc), '
          f'V_stall {V_STALL}, V_reacc {V_REACC}, trip {T_TRIP}s')
    print(f'{"fault":>10} | {"policy":>7} | {"init stalled":>12} | {"tripped kW%":>11} | '
          f'{"FIDVR s":>7} | {"mean reacc s":>12}')
    res = {}
    for fb, rf in cases:
        for pol in ['none', 'droop', 'allmax']:
            r = episode(fb, rf, pol)
            if r is None:
                print(f'{fb}/{rf:>5} | {pol:>7} | nonconverged'); continue
            res[f'{fb}_{rf}_{pol}'] = r
            print(f'{fb}@{rf:>4.1f}R | {pol:>7} | {r["n_stalled_init"]:>12} | '
                  f'{r["trip_%"]:>11.1f} | {r["fidvr_s"]:>7.1f} | {r["mean_reacc_s"]:>12.1f}')
        print()
    (HERE / 'w5_motor_lever.json').write_text(json.dumps(res, indent=1))
    print('W5.1 MOTOR LEVER QUANTIFIED')


if __name__ == '__main__':
    main()
