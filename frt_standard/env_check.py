"""Verify the faithful-DC env reaches the Simulink-matching Vdc equilibria before retraining."""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK','TRUE'); os.environ.setdefault('MKL_THREADING_LAYER','SEQUENTIAL')
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from frt_env import HPTFRTEnv, load_frt_scenarios

scn = load_frt_scenarios(Path(__file__).resolve().parent/'frt_scenarios.csv')
def pick(cat, ft, tV):
    return [s for s in scn if s['category']==cat and s['fault_type']==ft and abs(s['target_V_pu']-tV)<1e-6][0]

def run(s, act, label):
    env = HPTFRTEnv([s], seed=0)
    o,_ = env.reset()
    vdc_fault=[]
    for k in range(200):
        o,r,d,t,info = env.step(np.array(act,np.float32))
        if info['t']>=s['t_fault']+0.05 and info['t']<s['t_fault']+s['fault_dur']*0.20:
            vdc_fault.append(info['Vdc'])
        if d: break
    vmin = min(vdc_fault) if vdc_fault else float('nan')
    print(f"{label:42s} Vdc_fault_min={vmin:.3f}  (V2p={info['V2p']:.2f})")

# action = [i_sh_d(unused), i_sh_q, m_se_d, m_se_q]
print("=== faithful-DC env Vdc equilibria (compare to Simulink ~0.68 deep) ===")
run(pick('LVRT','sym3ph',0.5), [0,0.30,0,0],   "deep sym(0.5) iq=0.30 no-series   -> ~0.68?")
run(pick('LVRT','sym3ph',0.5), [0,0.10,0,0],   "deep sym(0.5) iq=0.10 no-series   -> ~0.93?")
run(pick('LVRT','sym3ph',0.5), [0,0.30,0.2,0], "deep sym(0.5) iq=0.30 +series0.2  -> lower")
run(pick('LVRT','1ph_g',0.75), [0,0.10,0,0],   "mild 1ph_g    iq=0.10 no-series   -> ~1.0?")
run(pick('LVRT','1ph_g',0.75), [0,0.10,0.2,0], "mild 1ph_g    iq=0.10 +series0.2  -> ~0.59?")
