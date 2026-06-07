"""
validate_sac_simulink.py  —  Validate trained SAC on real Simulink Mode 9.

For each of the 350 fixed scenarios, the SAC neural network observes the
scenario features and selects continuous actions [m_sh, m_se_d, m_se_q].
These are applied to Simulink Mode 9 (direct SPWM control).

Two validation modes:
  --scenario-level  : SAC observes initial features → picks one action per scenario.
                      Simulink runs with fixed {m_sh, m_se_d, m_se_q} throughout.
                      Fast (same speed as Mode 9 batch, ~23 min for 350 scenarios).

  --online          : SAC observes state every STEP_MS milliseconds during fault.
                      Simulink steps via MATLAB MCP, SAC re-queries at each step.
                      Slower but truly adaptive (~5× longer).

Comparison output:
  - dq baseline (Mode 4): existing 64.00 %
  - Fixed Mode 9 (m_sh=0.90): existing 96.57 %
  - SAC scenario-level: new result
  - SAC online (if --online): new result
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matlab.engine  # MATLAB Engine API for Python
import numpy as np
import pandas as pd
from stable_baselines3 import SAC

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCEN_CSV     = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
MODEL_DIR    = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR  = PROJECT_ROOT / 'results'

SC_NAMES = {0:'normal',3:'igbt_oc_sh',4:'igbt_oc_se',
            5:'cap_fault',6:'sc_1ph',7:'sc_3ph',8:'cascade'}
SC_IDS   = [0,3,4,5,6,7,8]
SC_ID_TO_IDX = {v:i for i,v in enumerate(SC_IDS)}

# Physical constants (post-fix)
V2_LL   = 400.0
V2_PK   = V2_LL / np.sqrt(3) * np.sqrt(2)    # 326.6 V
VDC_NOM = 800.0
I2_NOM  = 400e3 / (np.sqrt(3) * V2_LL)
I2_NOM_PK = I2_NOM * np.sqrt(2)               # 816.5 A

# SAC action bounds (Mode 9 interface)
M_SH_MAX    = 0.90
M_SE_BOUND  = 0.30

# ── Observation builder ────────────────────────────────────────────────────────

def scenario_obs(row: pd.Series) -> np.ndarray:
    """17-dim observation at fault onset, matching HPTDirectEnv training layout.

    Fix #5 (2026-06-06): the previous version returned a 14-dim vector
    (sc_id one-hot + scenario params), which is INCOMPATIBLE with the SAC trained
    on the 17-dim physics state — feeding it produces meaningless actions.  This now
    mirrors generate_sac_actions.initial_state_obs exactly:
      [V_dc_pu, V2_pu, I2_pu, dVdc_norm, dV2_norm,        (5)
       MSFFN fault_probs × 7,                              (7)
       t_since_fault_norm, in_fault,                       (2)
       last_action × 3]                                    (3)
    """
    sc_id = int(row.sc_id)
    P, Q  = float(row.P_load), float(row.Q_load)
    I_ld    = (2/3) * np.hypot(P, Q) / V2_PK
    I2_pu_0 = float(np.clip(I_ld / I2_NOM_PK, 0, 5))

    fault_probs = np.zeros(7, dtype=np.float32)
    fault_probs[SC_ID_TO_IDX.get(sc_id, 0)] = 0.92
    fault_probs[0] += 0.08                                  # residual normal prob

    m_sh_balance = float(V2_PK / (VDC_NOM / 2.0))           # ≈0.817 active-power balance

    return np.array([
        1.0, 1.0, I2_pu_0, 0.0, 0.0,
        *fault_probs,
        0.0, 1.0,
        m_sh_balance, 0.0, 0.0,
    ], dtype=np.float32)


def state_obs(
    Vdc_pu: float, V2_pu: float, I2_pu: float,
    dVdc_dt: float, dV2_dt: float,
    sc_id: int, t_since_fault_s: float,
    last_action: np.ndarray,
) -> np.ndarray:
    """17-dim runtime observation for online SAC.

    Fix #5: the fault-probability block must mirror the MSFFNSimulator used in
    training (0.92 on the true class, 0.08 residual normal after the 5 ms detection
    delay), not a clean one-hot, so the observation distribution matches.
    """
    fp = np.zeros(7, dtype=np.float32)
    if t_since_fault_s < 5e-3:
        fp[0] = 0.7
        fp[SC_ID_TO_IDX.get(sc_id, 0)] += 0.3
    else:
        fp[SC_ID_TO_IDX.get(sc_id, 0)] = 0.92
        fp[0] += 0.08
    return np.array([
        np.clip(Vdc_pu, 0, 1.5),
        np.clip(V2_pu,  0, 1.5),
        np.clip(I2_pu,  0, 5.0),
        np.clip(dVdc_dt / 10000, -1, 1),
        np.clip(dV2_dt  /  5000, -1, 1),
        *fp,
        np.clip(t_since_fault_s / 0.05, 0, 1),
        float(t_since_fault_s > 0),
        *last_action.tolist(),
    ], dtype=np.float32)


# ── MATLAB/Simulink helpers ────────────────────────────────────────────────────

def configure_scenario(eng, model: str, row: pd.Series, mode: int = 9):
    """Configure Simulink block parameters for one scenario."""
    sc_id = int(row.sc_id)
    eng.set_param(f'{model}/Sc_id',          'Value', str(sc_id),           nargout=0)
    eng.set_param(f'{model}/T_fault',        'Value', str(float(row.t_fault)), nargout=0)
    eng.set_param(f'{model}/FaultVariant',   'Value', str(int(row.fault_variant)), nargout=0)
    eng.set_param(f'{model}/FaultMag',       'Value', str(float(row.fault_mag)), nargout=0)
    eng.set_param(f'{model}/ControllerMode', 'Value', str(mode),            nargout=0)
    eng.set_param(f'{model}/LV_Load',
                  'ActivePower',   str(float(row.P_load)),
                  'InductivePower', str(float(row.Q_load)),
                  'CapacitivePower', '0',                                   nargout=0)
    eng.set_param(f'{model}/DC_Link_Cap_Breaker', 'InitialState', '1',
                  'SwitchingTimes', '[99]',                                 nargout=0)
    cap = '680e-6' if sc_id == 5 else '2200e-6'
    eng.set_param(f'{model}/DC_Link_Capacitor', 'Capacitance', cap,
                  'InitialVoltage', '800',                                  nargout=0)
    eng.set_param(f'{model}/LV_AC_Fault',
                  'FaultA','off','FaultB','off','FaultC','off',
                  'GroundFault','off','SwitchTimes','[99 100]',             nargout=0)
    if sc_id == 6:
        eng.set_param(f'{model}/LV_AC_Fault',
                      'FaultA','on','GroundFault','on',
                      'FaultResistance',str(float(row.fault_resistance)),
                      'GroundResistance',str(float(row.ground_resistance)),
                      'SwitchTimes',
                      f'[{row.t_fault:.6f} {row.t_fault+0.015:.6f}]',     nargout=0)
    elif sc_id == 7:
        eng.set_param(f'{model}/LV_AC_Fault',
                      'FaultA','on','FaultB','on','FaultC','on',
                      'GroundFault','on',
                      'FaultResistance',str(float(row.fault_resistance)),
                      'GroundResistance',str(float(row.ground_resistance)),
                      'SwitchTimes',
                      f'[{row.t_fault:.6f} {row.t_fault+0.015:.6f}]',     nargout=0)
    eng.set_param(model, 'StopTime', str(float(row.T_sim)),                 nargout=0)


def set_mode9_action(eng, model: str, m_sh: float, m_se_d: float, m_se_q: float):
    eng.set_param(f'{model}/RL_Energy_Bias',   'Value', str(np.clip(m_sh,   0, M_SH_MAX)),   nargout=0)
    eng.set_param(f'{model}/RL_Reg_Bias',      'Value', str(np.clip(m_se_d, -M_SE_BOUND, M_SE_BOUND)), nargout=0)
    eng.set_param(f'{model}/RL_Current_Bias',  'Value', str(np.clip(m_se_q, -M_SE_BOUND, M_SE_BOUND)), nargout=0)


def extract_lvrt(eng_out, t_fault: float, f_s: float = 20000) -> dict:
    """Extract LVRT metrics from sim() output object via MATLAB engine."""
    import matlab
    Vdc_raw = np.array(eng_out.get('V_dc')).flatten()
    I2_raw  = np.array(eng_out.get('I2_abc'))
    T_sim   = float(len(Vdc_raw) - 1) / f_s
    t       = np.linspace(0, T_sim, len(Vdc_raw))
    post    = t >= t_fault

    Vdc_pu  = Vdc_raw / VDC_NOM
    I2_pu   = np.max(np.abs(I2_raw[post]), axis=1) / I2_NOM_PK if np.any(post) else np.array([0.0])

    vdc_min = float(np.min(Vdc_pu[post])) if np.any(post) else 1.0
    vdc_max = float(np.max(Vdc_pu[post])) if np.any(post) else 1.0
    i2_max  = float(np.max(I2_pu))
    lvrt    = vdc_min >= 0.75 and vdc_max <= 1.25 and i2_max <= 3.0
    return {'vdc_min': round(vdc_min,4), 'vdc_max': round(vdc_max,4),
            'i2_max': round(i2_max,4), 'lvrt_pass': bool(lvrt)}


# ── Scenario-level validation ──────────────────────────────────────────────────

def validate_scenario_level(sac: SAC, checkpoint_path: str) -> dict:
    """SAC picks one action per scenario using initial features; Simulink runs fixed."""
    print('\n=== Scenario-level SAC validation (Mode 9) ===')
    print('SAC observes scenario features → picks [m_sh, m_se_d, m_se_q] once per scenario')
    print('Simulink runs with those fixed parameters throughout.\n')

    scen = pd.read_csv(SCEN_CSV).reset_index(drop=True)

    # Connect to existing MATLAB session
    print('Connecting to MATLAB...')
    eng = matlab.engine.connect_matlab()
    model = 'hpt_switching_model'

    # Load model and set accelerator
    eng.eval(f"if ~bdIsLoaded('{model}'), load_system('{model}'); end", nargout=0)
    eng.set_param(model, 'SimulationMode', 'accelerator', nargout=0)
    eng.set_param(model, 'FastRestart', 'off', nargout=0)

    results = []
    t_start = time.time()

    for i, (_, row) in enumerate(scen.iterrows()):
        # SAC picks action from scenario features (14-dim obs)
        obs = scenario_obs(row).reshape(1, -1)
        action, _ = sac.predict(obs, deterministic=True)
        m_sh, m_se_d, m_se_q = float(action[0][0]), float(action[0][1]), float(action[0][2])

        # Configure and run Simulink
        eng.set_param(model, 'FastRestart', 'off', nargout=0)
        configure_scenario(eng, model, row, mode=9)
        set_mode9_action(eng, model, m_sh, m_se_d, m_se_q)

        in_obj = eng.Simulink.SimulationInput(model)
        in_obj = eng.setModelParameter(in_obj, 'FastRestart', 'on')
        out = eng.sim(in_obj)

        if eng.isempty(eng.getfield(out, 'ErrorMessage')):
            metrics = extract_lvrt(out, float(row.t_fault))
        else:
            metrics = {'vdc_min':0,'vdc_max':1,'i2_max':0,'lvrt_pass':False}

        results.append({
            'scenario_idx': i+1,
            'sc_id': int(row.sc_id),
            'm_sh':   round(m_sh,3),
            'm_se_d': round(m_se_d,3),
            'm_se_q': round(m_se_q,3),
            **metrics
        })

        if (i+1) % 50 == 0:
            el = time.time() - t_start
            passes = sum(r['lvrt_pass'] for r in results)
            print(f'  [{i+1:3d}/350]  {el:.0f}s  pass={passes}/{i+1}')

    eng.set_param(model, 'FastRestart', 'off', nargout=0)

    # Summarise
    passes = sum(r['lvrt_pass'] for r in results)
    rate   = 100.0 * passes / len(results)
    print(f'\n  SAC scenario-level LVRT: {rate:.2f}%  (dq=64.00%  fixed-Mode9=96.57%)')

    # Per-class
    for sc in sorted(SC_NAMES):
        grp = [r for r in results if r['sc_id']==sc]
        if grp:
            pr = 100*sum(g['lvrt_pass'] for g in grp)/len(grp)
            print(f'    {SC_NAMES[sc]:12s}: {pr:.1f}%')

    out_path = RESULTS_DIR / 'sac_mode9_scenario_level.json'
    out_path.write_text(json.dumps({
        'lvrt_pass_pct': round(rate,2),
        'dq_baseline': 64.00,
        'fixed_mode9': 96.57,
        'results': results,
    }, indent=2), encoding='utf-8')
    print(f'\nSaved → {out_path}')
    return {'pass_rate': rate, 'results': results}


# ── Online step-level validation ───────────────────────────────────────────────

def validate_online(sac: SAC, step_ms: float = 5.0) -> dict:
    """SAC re-queries every step_ms ms during fault for truly adaptive control.

    Uses MATLAB Engine to step through simulation via SimulationInput with
    StopTime advancing step by step.
    NOTE: This approach compiles once (FastRestart) then re-runs short segments.
    """
    print(f'\n=== Online SAC validation (Mode 9, step={step_ms}ms) ===')
    print('SAC re-queries state every 5ms during fault window.\n')

    scen = pd.read_csv(SCEN_CSV).reset_index(drop=True)
    eng  = matlab.engine.connect_matlab()
    model = 'hpt_switching_model'
    eng.eval(f"if ~bdIsLoaded('{model}'), load_system('{model}'); end", nargout=0)
    eng.set_param(model, 'SimulationMode', 'accelerator', nargout=0)

    results = []
    t_start = time.time()
    step_s  = step_ms / 1000.0
    f_s     = 20000   # logging sample rate

    for i, (_, row) in enumerate(scen.iterrows()):
        sc_id  = int(row.sc_id)
        t_f    = float(row.t_fault)
        T_sim  = float(row.T_sim)

        # Initial action: SAC from scenario features
        obs     = scenario_obs(row).reshape(1,-1)
        action, _ = sac.predict(obs, deterministic=True)
        m_sh, m_se_d, m_se_q = float(action[0][0]), float(action[0][1]), float(action[0][2])

        # Run pre-fault segment (0 → t_fault)
        eng.set_param(model, 'FastRestart', 'off', nargout=0)
        configure_scenario(eng, model, row, mode=9)
        set_mode9_action(eng, model, m_sh, m_se_d, m_se_q)
        eng.set_param(model, 'StopTime', str(round(t_f, 6)), nargout=0)

        in_pre = eng.Simulink.SimulationInput(model)
        in_pre = eng.setModelParameter(in_pre, 'FastRestart', 'on')
        out_pre = eng.sim(in_pre)

        Vdc_pre = float(np.array(eng.eval("out.V_dc(end)", nargout=1))) / VDC_NOM
        V2_pre  = float(np.array(eng.eval("sqrt(mean(out.V2_abc(end,:).^2))", nargout=1))) / V2_PK
        last_action = np.array([m_sh, m_se_d, m_se_q], dtype=np.float32)
        dVdc_dt = 0.0; dV2_dt = 0.0

        # Online fault window: query SAC every step_ms
        t_cur   = t_f
        Vdc_all = []; I2_all = []

        while t_cur < T_sim - 1e-6:
            t_next = min(t_cur + step_s, T_sim)

            # Build state observation
            t_since = t_cur - t_f
            state   = state_obs(Vdc_pre, V2_pre, 0.0,
                                dVdc_dt, dV2_dt, sc_id, t_since, last_action)
            action, _ = sac.predict(state.reshape(1,-1), deterministic=True)
            m_sh, m_se_d, m_se_q = float(action[0][0]), float(action[0][1]), float(action[0][2])
            last_action = np.array([m_sh, m_se_d, m_se_q], dtype=np.float32)

            # Apply action and advance one step
            set_mode9_action(eng, model, m_sh, m_se_d, m_se_q)
            eng.set_param(model, 'StopTime', str(round(t_next, 6)), nargout=0)

            in_k = eng.Simulink.SimulationInput(model)
            in_k = eng.setModelParameter(in_k, 'FastRestart', 'on')
            out_k = eng.sim(in_k)

            Vdc_k  = np.array(out_k.get('V_dc')).flatten() / VDC_NOM
            I2_k   = np.array(out_k.get('I2_abc'))
            Vdc_all.extend(Vdc_k.tolist())
            I2_all.extend(np.max(np.abs(I2_k), axis=1).tolist())

            Vdc_new = Vdc_k[-1]; V2_new = V2_pre  # simplified
            dVdc_dt = (Vdc_new - Vdc_pre) / step_s
            Vdc_pre = Vdc_new
            t_cur   = t_next

        Vdc_arr = np.array(Vdc_all) if Vdc_all else np.array([1.0])
        I2_arr  = np.array(I2_all)  / I2_NOM_PK if I2_all else np.array([0.0])
        vdc_min = float(np.min(Vdc_arr))
        vdc_max = float(np.max(Vdc_arr))
        i2_max  = float(np.max(I2_arr))
        lvrt    = vdc_min >= 0.75 and vdc_max <= 1.25 and i2_max <= 3.0

        results.append({'scenario_idx':i+1,'sc_id':sc_id,
                        'vdc_min':round(vdc_min,4),'vdc_max':round(vdc_max,4),
                        'i2_max':round(i2_max,4),'lvrt_pass':bool(lvrt)})

        if (i+1) % 10 == 0:
            el = time.time()-t_start
            passes = sum(r['lvrt_pass'] for r in results)
            print(f'  [{i+1:3d}/350]  {el:.0f}s  pass={passes}/{i+1}')

    eng.set_param(model, 'FastRestart', 'off', nargout=0)

    passes = sum(r['lvrt_pass'] for r in results)
    rate   = 100.0 * passes / len(results)
    print(f'\nOnline SAC LVRT: {rate:.2f}%')
    out_path = RESULTS_DIR / 'sac_mode9_online.json'
    out_path.write_text(json.dumps({'lvrt_pass_pct':round(rate,2),
                                    'results':results},indent=2),encoding='utf-8')
    print(f'Saved → {out_path}')
    return {'pass_rate': rate, 'results': results}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', default=str(MODEL_DIR/'sac_hpt_direct_best.zip'),
                        help='SAC model checkpoint (.zip)')
    parser.add_argument('--scenario-level', action='store_true',
                        help='Scenario-level validation (one action per scenario)')
    parser.add_argument('--online', action='store_true',
                        help='Online validation (SAC re-queries every 5ms during fault)')
    parser.add_argument('--step-ms', type=float, default=5.0,
                        help='Step size for online validation (ms)')
    args = parser.parse_args()

    if not (args.scenario_level or args.online):
        print('Specify --scenario-level or --online (or both).')
        parser.print_help()
        return

    print(f'Loading SAC from {args.checkpoint}')
    sac = SAC.load(args.checkpoint)
    print(f'Policy loaded.  Action space: {sac.action_space}')

    if args.scenario_level:
        validate_scenario_level(sac, args.checkpoint)
    if args.online:
        validate_online(sac, step_ms=args.step_ms)


if __name__ == '__main__':
    main()
