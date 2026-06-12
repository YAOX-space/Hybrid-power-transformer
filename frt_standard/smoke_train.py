"""Smoke test: can SAC train+predict in this env at all? (numpy BLAS matmul was segfaulting.)"""
import sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
print("1) imports...", flush=True)
import numpy as np
print("   numpy", np.__version__, flush=True)
try:
    a = np.random.rand(64,64); b = a@a; print("   numpy matmul OK", float(b[0,0]), flush=True)
except Exception:
    traceback.print_exc()
import torch
print("   torch", torch.__version__, flush=True)
try:
    t = torch.rand(64,64); r = t@t; print("   torch matmul OK", float(r[0,0]), flush=True)
except Exception:
    traceback.print_exc()
from stable_baselines3 import SAC
from frt_env import HPTFRTEnv, load_frt_scenarios
print("2) build env + SAC...", flush=True)
scen = [s for s in load_frt_scenarios(Path(__file__).resolve().parent/'frt_scenarios.csv')
        if s['category']=='HVRT' and s['fault_type']=='swell_3ph']
print("   hvrt_sym scenarios:", len(scen), flush=True)
env = HPTFRTEnv(scen, seed=1)
o,_ = env.reset()
print("   obs shape", o.shape, flush=True)
sac = SAC('MlpPolicy', env, policy_kwargs=dict(net_arch=[256,256,256]),
          buffer_size=5000, batch_size=64, device='cpu', verbose=0, seed=0)
print("3) predict...", flush=True)
a,_ = sac.predict(o, deterministic=True); print("   predict OK", a, flush=True)
print("4) learn 600 steps...", flush=True)
sac.learn(total_timesteps=600); print("   learn OK", flush=True)
print("SMOKE PASS", flush=True)
