"""Export the residual-SAC actor (raw best vs EMA best — picks the higher ODE score) to
sac_residual_weights.mat for HLC mode-14, and copy into simulink/."""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json, shutil
from pathlib import Path
import numpy as np, scipy.io as sio
from stable_baselines3 import SAC

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parent / 'data' / 'models'

j = json.loads((ROOT / 'results' / 'residual_train.json').read_text())
pick = 'sac_residual_ema_best.zip' if j.get('best_ema', -1) >= j.get('best', -1) else 'sac_residual_best.zip'
print(f"ODE bests: raw={j.get('best')} ema={j.get('best_ema')} -> exporting {pick}")

m = SAC.load(str(MODELS / pick), device='cpu')
sd = m.policy.actor.state_dict()
W = {k.replace('.', '_'): v.cpu().numpy().astype('float64')
     for k, v in sd.items() if 'latent_pi' in k or k.startswith('mu.')}
W['act_low'] = m.action_space.low.astype('float64')
W['act_high'] = m.action_space.high.astype('float64')
rng = np.random.default_rng(0)
ot = rng.uniform(-1, 1, (4, 21)).astype('float64'); ot[:, 0] = rng.uniform(0.4, 1.2, 4)
W['obs_test'] = ot
W['act_test'] = np.array([m.predict(o, deterministic=True)[0] for o in ot], 'float64')
sio.savemat(str(ROOT / 'sac_residual_weights.mat'), W)
shutil.copy(str(ROOT / 'sac_residual_weights.mat'), str(ROOT / 'simulink' / 'sac_residual_weights.mat'))
print('exported + copied sac_residual_weights.mat  act_test[0]=', W['act_test'][0])
