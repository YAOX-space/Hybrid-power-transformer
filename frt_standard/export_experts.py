"""Export the 3 specialist SAC actors' weights to sac_{name}_weights.mat for Simulink closed-loop."""
from pathlib import Path
import numpy as np, scipy.io as sio
from stable_baselines3 import SAC

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parent / 'data' / 'models'
for name in ['sym', 'asym', 'hvrt']:
    m = SAC.load(str(MODELS / f'sac_{name}_best.zip'), device='cpu')
    sd = m.policy.actor.state_dict()
    W = {k.replace('.', '_'): v.cpu().numpy().astype('float64')
         for k, v in sd.items() if 'latent_pi' in k or k.startswith('mu.')}
    W['act_low'] = m.action_space.low.astype('float64')
    W['act_high'] = m.action_space.high.astype('float64')
    rng = np.random.default_rng(0)
    ot = rng.uniform(-1, 1, (4, 21)).astype('float64'); ot[:, 0] = rng.uniform(0.4, 1.2, 4)
    W['obs_test'] = ot
    W['act_test'] = np.array([m.predict(o, deterministic=True)[0] for o in ot], 'float64')
    sio.savemat(str(ROOT / f'sac_{name}_weights.mat'), W)
    print(f'exported sac_{name}_weights.mat  act_test[0]={W["act_test"][0]}')
print('done')
