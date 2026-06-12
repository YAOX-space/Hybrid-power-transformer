"""w3_headroom.py — quantify where coordination can still act:
(a) borderline band: device-evals with v_load just below 0.90 (flippable by collective-Q lift
    of ~0.01-0.03 pu, the W2-measured fleet effect at 10 units);
(b) distribution of local sags (how much of the failure mass is physically out of reach).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from w3_scenarios import gen_scenarios, evaluate

vload, vlocal = [], []
for sc in gen_scenarios(400):
    r = evaluate(sc, 'droop_full')
    if r is None:
        continue
    for h in r['hpt']:
        vload.append(h['v_load']); vlocal.append(h['v'])
vload = np.array(vload); vlocal = np.array(vlocal)
n = len(vload)
print(f'device evals: {n}')
print(f'load_strict pass (v_load>=0.90):      {100*np.mean(vload>=0.90):.1f}%')
print(f'borderline 0.87<=v_load<0.90:          {100*np.mean((vload>=0.87)&(vload<0.90)):.1f}%  <- flippable by ~0.03 pu fleet-Q')
print(f'borderline 0.85<=v_load<0.90:          {100*np.mean((vload>=0.85)&(vload<0.90)):.1f}%')
print(f'deep loss  v_load<0.70:                {100*np.mean(vload<0.70):.1f}%  <- physically out of reach (sag too deep)')
print(f'local sag distribution: <0.2: {100*np.mean(vlocal<0.2):.1f}%  0.2-0.5: {100*np.mean((vlocal>=0.2)&(vlocal<0.5)):.1f}%  '
      f'0.5-0.8: {100*np.mean((vlocal>=0.5)&(vlocal<0.8)):.1f}%  >=0.8: {100*np.mean(vlocal>=0.8):.1f}%')
