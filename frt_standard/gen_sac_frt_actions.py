"""
gen_sac_frt_actions.py — generate SAC action setpoints for the full-HPT Simulink
comparison.  For a representative subset (one scenario per fault_type×target_V×scr
LVRT combo), roll out the trained SAC on the ODE env and record the mean fault-window
4-D action, then map to Simulink interface units.

Output: frt_standard/sac_frt_actions.csv  with one row per scenario:
  scenario_id, fault_type, target_V_pu, scr, Rg_ohm, Lg_H, t_fault, fault_dur, T_sim,
  sac_iq_A (= i_sh_q*I_sh_max), sac_mse_d, sac_mse_q
"""
import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from stable_baselines3 import SAC
from frt_env import HPTFRTEnv, load_frt_scenarios, TSCALE

ROOT = Path(__file__).resolve().parent
SCEN = ROOT / 'frt_scenarios.csv'
MODEL = ROOT.parent / 'data' / 'models' / 'sac_frt_best.zip'
OUT  = ROOT / 'sac_frt_actions.csv'
I_SH_MAX = 173.2

def main():
    scen = load_frt_scenarios(SCEN)
    # representative subset: first scenario of each (fault_type, target_V, scr) LVRT combo
    seen, subset = set(), []
    for s in scen:
        if s['category'] != 'LVRT':
            continue
        key = (s['fault_type'], round(float(s['target_V_pu']),2), round(float(s['scr']),1))
        if key in seen:
            continue
        seen.add(key); subset.append(s)
    print(f'selected {len(subset)} representative LVRT scenarios')

    sac = SAC.load(str(MODEL), device='cpu')
    rows = []
    for s in subset:
        env = HPTFRTEnv([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        t_f = float(s['t_fault']); dur = float(s['fault_dur'])*TSCALE
        acc = []  # actions during fault window
        done = False
        while not done:
            a, _ = sac.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            if t_f <= info['t'] <= t_f + dur:
                acc.append(np.asarray(a, float))
            done = term or trunc
        am = np.mean(acc, axis=0) if acc else np.zeros(4)
        # action = [i_sh_d, i_sh_q, m_se_d, m_se_q]
        rows.append(dict(
            scenario_id=int(s['scenario_id']), fault_type=s['fault_type'],
            target_V_pu=float(s['target_V_pu']), scr=float(s['scr']),
            Rg_ohm=float(s['Rg_ohm']), Lg_H=float(s['Lg_H']),
            t_fault=t_f, fault_dur=float(s['fault_dur']), T_sim=float(s['T_sim']),
            sac_iq_A=round(float(am[1])*I_SH_MAX,3),
            sac_mse_d=round(float(am[2]),4), sac_mse_q=round(float(am[3]),4)))
        print(f"  {s['fault_type']:7s} V={s['target_V_pu']:.2f} scr={s['scr']:.0f}: "
              f"iq={rows[-1]['sac_iq_A']:.1f}A mse_d={rows[-1]['sac_mse_d']:.3f} mse_q={rows[-1]['sac_mse_q']:.3f}")

    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f'wrote {OUT}  ({len(rows)} rows)')

if __name__ == '__main__':
    main()
