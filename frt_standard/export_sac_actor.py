"""Export the SAC actor (deterministic mean) network weights + obs/action specs to .mat
so the policy forward pass can run inside the Simulink controller (true closed loop)."""
from pathlib import Path
import numpy as np, scipy.io as sio
from stable_baselines3 import SAC

ROOT = Path(__file__).resolve().parent
m = SAC.load(str(ROOT.parent / 'data' / 'models' / 'sac_frt_best.zip'), device='cpu')
sd = m.policy.actor.state_dict()
print('=== actor params ===')
for k, v in sd.items():
    print(k, tuple(v.shape))
print('obs dim:', m.observation_space.shape)
print('act low :', m.action_space.low)
print('act high:', m.action_space.high)

W = {}
for k, v in sd.items():
    if 'latent_pi' in k or k.startswith('mu.'):
        W[k.replace('.', '_')] = v.cpu().numpy().astype('float64')
W['act_low']  = m.action_space.low.astype('float64')
W['act_high'] = m.action_space.high.astype('float64')

# test (obs, deterministic action) pairs to validate the MATLAB forward pass
rng = np.random.default_rng(0)
obs_test = rng.uniform(-1, 1, size=(6, 21)).astype('float64')
obs_test[:, 0] = rng.uniform(0.4, 1.2, 6)   # plausible Vdc/V2 ranges
act_test = np.array([m.predict(o, deterministic=True)[0] for o in obs_test], dtype='float64')
W['obs_test'] = obs_test
W['act_test'] = act_test
sio.savemat(str(ROOT / 'sac_actor_weights.mat'), W)
print('saved keys:', list(W.keys()))
print('act_test[0]:', act_test[0])
