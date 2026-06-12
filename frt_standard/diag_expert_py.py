"""Probe the asym expert directly: what iq does it command on a 1ph_g undervoltage obs?
Also cross-check the exported .mat weights produce the same action (export integrity)."""
import numpy as np, scipy.io as sio, zipfile, io, torch

def build_obs(V2p, V2n, fp_idx, in_fault=1.0, Vdc=1.0, tfrac=0.3, last_a=(0,0,0,0)):
    vdev = 0.9 - V2p
    iq_ref = min(0.30, 1.5*(0.9-V2p)) if V2p < 0.9 else (max(-0.30,-1.5*(V2p-1.1)) if V2p>1.1 else 0.0)
    iq = last_a[1]
    iq_err = iq_ref - iq
    probs = np.zeros(6, np.float32)
    if in_fault: probs[fp_idx]=0.92; probs[0]+=0.08
    else: probs[0]=1.0
    o = np.array([Vdc, V2p, V2n, abs(iq), 0.0,0.0, vdev, iq_err, iq, *probs, tfrac, in_fault, *last_a], np.float32)
    return np.clip(o,-5,5)

def mat_forward(W, obs):
    h = np.maximum(0, W['latent_pi_0_weight'].reshape(256,21)@obs + W['latent_pi_0_bias'].reshape(256))
    h = np.maximum(0, W['latent_pi_2_weight'].reshape(256,256)@h + W['latent_pi_2_bias'].reshape(256))
    h = np.maximum(0, W['latent_pi_4_weight'].reshape(256,256)@h + W['latent_pi_4_bias'].reshape(256))
    mu = W['mu_weight'].reshape(4,256)@h + W['mu_bias'].reshape(4)
    at = np.tanh(mu); alo=W['act_low'].reshape(4); ahi=W['act_high'].reshape(4)
    return alo + 0.5*(at+1)*(ahi-alo)

def load_actor_from_zip(zip_path):
    """Extract actor MLP weights directly from SB3 zip state_dict (no predict, no segfault)."""
    with zipfile.ZipFile(zip_path) as z:
        with z.open("policy.pth") as f:
            sd = torch.load(io.BytesIO(f.read()), map_location="cpu", weights_only=False)
    g = lambda k: sd[k].numpy()
    return {
        'latent_pi_0_weight': g('actor.latent_pi.0.weight'), 'latent_pi_0_bias': g('actor.latent_pi.0.bias'),
        'latent_pi_2_weight': g('actor.latent_pi.2.weight'), 'latent_pi_2_bias': g('actor.latent_pi.2.bias'),
        'latent_pi_4_weight': g('actor.latent_pi.4.weight'), 'latent_pi_4_bias': g('actor.latent_pi.4.bias'),
        'mu_weight': g('actor.mu.weight'), 'mu_bias': g('actor.mu.bias'),
        'act_low': np.array([0.0,-0.30,-0.20,-0.20]), 'act_high': np.array([0.35,0.30,0.20,0.20]),
    }

Wmat = sio.loadmat("frt_standard/sac_asym_weights.mat")
Wzip = load_actor_from_zip("data/models/sac_asym_best.zip")

print("=== asym expert iq vs positive-seq residual (1ph_g, fp=2) ===")
print(f"{'V2p':>5} {'V2n':>5} {'iq_ref':>7} | {'zip iq':>8} {'mat iq':>8} | {'id':>6} {'mse_d':>7} {'mse_q':>7}")
for V2p, V2n in [(0.85,0.10),(0.80,0.12),(0.70,0.15),(0.60,0.18),(0.50,0.20),(0.40,0.22)]:
    obs = build_obs(V2p, V2n, 2)
    az = mat_forward(Wzip, obs); am = mat_forward(Wmat, obs)
    iq_ref = min(0.30, 1.5*(0.9-V2p))
    print(f"{V2p:5.2f} {V2n:5.2f} {iq_ref:7.3f} | {az[1]:8.3f} {am[1]:8.3f} | {az[0]:6.3f} {az[2]:7.3f} {az[3]:7.3f}")

print("\n=== sym expert on symmetric undervoltage (fp=1) ===")
Wsym = load_actor_from_zip("data/models/sac_sym_best.zip")
print(f"{'V2p':>5} {'iq_ref':>7} | {'sym iq':>8} {'sym id':>7}")
for V2p in [0.75,0.60,0.50,0.40,0.20]:
    a = mat_forward(Wsym, build_obs(V2p, 0.0, 1))
    print(f"{V2p:5.2f} {min(0.30,1.5*(0.9-V2p)):7.3f} | {a[1]:8.3f} {a[0]:7.3f}")
