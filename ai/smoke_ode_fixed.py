"""Smoke test for ODE after physics fixes."""
import sys, time; sys.path.insert(0, 'ai')
import pandas as pd, numpy as np
from hpt_ode_sim import HPTODESimulator, SCENARIO_TABLE, VDC_NOM, V2_PK, I2_NOM, I2_NOM_PK

table = pd.read_csv(SCENARIO_TABLE)
sim   = HPTODESimulator()
SC_NAMES = {0:'normal',3:'igbt_oc_sh',4:'igbt_oc_se',5:'cap_fault',
            6:'sc_1ph',7:'sc_3ph',8:'cascade'}

print('Smoke test (1 per fault class) after physics fixes:')
print(f'  I2_NOM={I2_NOM:.1f}A RMS -> I2_NOM_PK={I2_NOM_PK:.1f}A peak')
print()
print(f"{'Class':12s}  VdcMin  V2min  I2max  LVRT  time")
print('-'*55)

for sc_id in [0,3,4,5,6,7,8]:
    row = table[table.sc_id==sc_id].iloc[0]
    t0 = time.time()
    m  = sim.simulate(row)
    dt = time.time()-t0
    ok = 'PASS' if m['lvrt_pass'] else 'FAIL'
    print(f"  {SC_NAMES[sc_id]:12s}  {m['vdc_min_pu']:.3f}   {m['v2_min_pu']:.3f}  "
          f"{m['i2_max_pu']:.2f}  {ok}  {dt:.2f}s")

print()
print('I2 check: at rated, I2_pu should be near 1.0 for normal scenario')
