"""
generate_synthetic_mat.py
Generates synthetic .mat files that mimic run_scenarios.m output.
Used for testing AI methods without running the full Simulink simulation.
Physics-based signal generation for realistic fault signatures.
"""

import numpy as np
import scipy.io as sio
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / 'data' / 'raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)

F_S     = 20_000   # 20 kHz sample rate
F_GRID  = 50       # Hz
V_GRID  = 10_000 / np.sqrt(3)   # phase voltage (V)
V_SEC   = 400 / np.sqrt(3)      # secondary phase voltage (V)
V_DC    = 800.0
S_RATED = 400e3

SCENARIO_SPECS = [
    (0, 'normal',       2.0, 200),
    (1, 'pv_disturbance',2.0, 80),
    (2, 'load_step',    2.0, 80),
    (3, 'igbt_oc_sh',   2.0, 80),
    (4, 'igbt_oc_se',   2.0, 80),
    (5, 'cap_fault',    2.0, 80),
    (6, 'sc_1ph',       2.0, 80),
    (7, 'sc_3ph',       2.0, 80),
    (8, 'cascade',      2.5, 80),
]

# fault class mapping: sc_id → fault_label (after onset)
FAULT_LABEL = {0:0, 1:0, 2:0, 3:1, 4:2, 5:3, 6:4, 7:5, 8:6}


def make_3phase(N, t, V_amp, offset_rad=0.0, noise=0.02):
    rng = np.random.default_rng()
    ph = offset_rad
    V = np.column_stack([
        V_amp * np.sin(2*np.pi*F_GRID*t + ph + 0)       + rng.normal(0, noise*V_amp, N),
        V_amp * np.sin(2*np.pi*F_GRID*t + ph + 2*np.pi/3) + rng.normal(0, noise*V_amp, N),
        V_amp * np.sin(2*np.pi*F_GRID*t + ph + 4*np.pi/3) + rng.normal(0, noise*V_amp, N),
    ])
    return V.astype(np.float32)


def make_scenario(sc_id, sc_label, T_sim, rng):
    N     = int(T_sim * F_S)
    t     = np.linspace(0, T_sim, N, dtype=np.float32)
    P_pct = 0.3 + 0.7 * rng.random()
    Q_pct = 0.0 + 0.4 * rng.random()
    P_load = S_RATED * P_pct
    Q_load = S_RATED * Q_pct

    t_fault = 0.8 + 0.4 * rng.random()
    fault_idx = int(t_fault * F_S)

    # Base signals (normal operation)
    V1_amp = V_GRID * (0.97 + 0.06 * rng.random())
    V2_amp = V_SEC  * (0.97 + 0.06 * rng.random())
    I1_amp = P_load / (3 * V1_amp) * (0.95 + 0.1 * rng.random())
    I2_amp = P_load / (3 * V2_amp) * (0.95 + 0.1 * rng.random())

    V1_abc = make_3phase(N, t, V1_amp, noise=0.01)
    I1_abc = make_3phase(N, t, I1_amp, offset_rad=-0.3, noise=0.02)
    V2_abc = make_3phase(N, t, V2_amp, noise=0.01)
    I2_abc = make_3phase(N, t, I2_amp, offset_rad=-0.35, noise=0.02)
    V_dc   = np.full(N, V_DC, dtype=np.float32) + rng.normal(0, 5, N).astype(np.float32)

    # dq currents (simplified: d=active, q=reactive)
    Ish_d  = np.full(N, I2_amp * 0.3, dtype=np.float32)
    Ish_q  = np.full(N, I2_amp * 0.1, dtype=np.float32)
    Ise_d  = np.full(N, I1_amp * 0.15, dtype=np.float32)
    Ise_q  = np.full(N, I1_amp * 0.05, dtype=np.float32)

    P1 = np.full(N, P_load, dtype=np.float32)
    Q1 = np.full(N, Q_load, dtype=np.float32)
    P2 = np.full(N, P_load * 0.97, dtype=np.float32)  # losses
    Q2 = np.full(N, Q_load * 0.95, dtype=np.float32)
    mode = np.ones(N, dtype=np.float32)

    fault_labels = np.zeros(N, dtype=np.int32)

    # Inject fault signatures
    if sc_id == 1:   # PV disturbance — voltage swell after t_fault
        if fault_idx < N:
            V2_abc[fault_idx:] *= 1.15
            P1[fault_idx:] *= 1.2

    elif sc_id == 2:  # Load step
        if fault_idx < N:
            P2[fault_idx:] *= 1.5
            I2_abc[fault_idx:] *= 1.5

    elif sc_id == 3:  # IGBT OC in VSC_sh — one phase current collapses
        if fault_idx < N:
            fault_phase = rng.integers(0, 3)
            I2_abc[fault_idx:, fault_phase] *= 0.1   # near zero for upper switch
            V_dc[fault_idx:] += 30 * np.exp(-np.arange(N-fault_idx)/500).astype(np.float32)
            Ish_d[fault_idx:] *= 0.1
            fault_labels[fault_idx:] = 1

    elif sc_id == 4:  # IGBT OC in VSC_se — series voltage distortion
        if fault_idx < N:
            fault_phase = rng.integers(0, 3)
            I1_abc[fault_idx:, fault_phase] *= 0.15
            V1_abc[fault_idx:, fault_phase] *= 0.85
            Ise_d[fault_idx:] *= 0.1
            fault_labels[fault_idx:] = 2

    elif sc_id == 5:  # DC cap fault — V_dc drops then oscillates
        if fault_idx < N:
            decay = np.exp(-np.arange(N-fault_idx) / 2000).astype(np.float32)
            oscillation = 60 * np.sin(2*np.pi*300*t[fault_idx:])
            V_dc[fault_idx:] -= 80 * decay
            V_dc[fault_idx:] += oscillation.astype(np.float32)
            fault_labels[fault_idx:] = 3

    elif sc_id == 6:  # Single-phase short — one phase collapses
        t_clear = t_fault + 0.1 + 0.05 * rng.random()
        clear_idx = int(t_clear * F_S)
        if fault_idx < N:
            end = min(clear_idx, N)
            V2_abc[fault_idx:end, 0] *= 0.05
            I1_abc[fault_idx:end, 0] *= 5.0
            I2_abc[fault_idx:end, 0] *= 4.0
            fault_labels[fault_idx:min(end, N)] = 4

    elif sc_id == 7:  # Three-phase short
        t_clear = t_fault + 0.1 + 0.05 * rng.random()
        clear_idx = int(t_clear * F_S)
        if fault_idx < N:
            end = min(clear_idx, N)
            V2_abc[fault_idx:end] *= 0.05
            I1_abc[fault_idx:end] *= 4.0
            I2_abc[fault_idx:end] *= 4.0
            fault_labels[fault_idx:min(end, N)] = 5

    elif sc_id == 8:  # Cascade: IGBT fault → DC overvoltage
        if fault_idx < N:
            fault_phase = rng.integers(0, 3)
            I2_abc[fault_idx:, fault_phase] *= 0.1
            dc_rise = np.minimum(np.arange(N-fault_idx)*0.05, 120).astype(np.float32)
            V_dc[fault_idx:] += dc_rise
            Ish_d[fault_idx:] *= 0.1
            fault_labels[fault_idx:] = 6

    return {
        't_uniform':   t.reshape(-1, 1),
        'V1_abc':      V1_abc,
        'I1_abc':      I1_abc,
        'V2_abc':      V2_abc,
        'I2_abc':      I2_abc,
        'V_dc':        V_dc.reshape(-1, 1),
        'Ish_dq':      np.column_stack([Ish_d, Ish_q]).astype(np.float32),
        'Ise_dq':      np.column_stack([Ise_d, Ise_q]).astype(np.float32),
        'P1':          P1.reshape(-1, 1),
        'Q1':          Q1.reshape(-1, 1),
        'P2':          P2.reshape(-1, 1),
        'Q2':          Q2.reshape(-1, 1),
        'mode':        mode.reshape(-1, 1),
        'fault_labels':fault_labels.reshape(-1, 1),
        'sc_id':       np.array([[sc_id]]),
        'sc_label':    np.array([[sc_label]]),
        'P_load':      np.array([[P_load]]),
        'Q_load':      np.array([[Q_load]]),
        't_fault':     np.array([[t_fault]]),
    }


def generate_all(seed=42):
    rng = np.random.default_rng(seed)
    total = sum(n for _, _, _, n in SCENARIO_SPECS)
    count = 0

    print(f'Generating {total} synthetic .mat files → {RAW_DIR}')
    for sc_id, sc_label, T_sim, N_runs in SCENARIO_SPECS:
        for run in range(1, N_runs + 1):
            count += 1
            data = make_scenario(sc_id, sc_label, T_sim, rng)
            fname = RAW_DIR / f'scenario_{sc_id}_{sc_label}_run{run:03d}.mat'
            sio.savemat(str(fname), data)
            if run % 40 == 0 or run == N_runs:
                print(f'  [{count}/{total}] sc={sc_id} {sc_label:15s} run {run}/{N_runs}')

    print(f'\nDone. {count} files in {RAW_DIR}')


if __name__ == '__main__':
    generate_all()
