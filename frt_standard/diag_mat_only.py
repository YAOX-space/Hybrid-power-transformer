"""Pure scipy/numpy: what does the EXPORTED .mat policy (= exactly what Simulink runs) command?"""
import numpy as np, scipy.io as sio

def build_obs(V2p, V2n, fp_idx, in_fault=1.0, Vdc=1.0, tfrac=0.3, last_a=(0,0,0,0)):
    vdev = 0.9 - V2p
    iq_ref = min(0.30, 1.5*(0.9-V2p)) if V2p < 0.9 else (max(-0.30,-1.5*(V2p-1.1)) if V2p>1.1 else 0.0)
    iq = last_a[1]; iq_err = iq_ref - iq
    probs = np.zeros(6);
    if in_fault: probs[fp_idx]=0.92; probs[0]+=0.08
    else: probs[0]=1.0
    return np.clip(np.array([Vdc,V2p,V2n,abs(iq),0.,0., vdev,iq_err,iq, *probs, tfrac,in_fault, *last_a]),-5,5)

def fwd(W, obs):
    h=np.maximum(0,W['latent_pi_0_weight'].reshape(256,21)@obs+W['latent_pi_0_bias'].reshape(256))
    h=np.maximum(0,W['latent_pi_2_weight'].reshape(256,256)@h+W['latent_pi_2_bias'].reshape(256))
    h=np.maximum(0,W['latent_pi_4_weight'].reshape(256,256)@h+W['latent_pi_4_bias'].reshape(256))
    mu=W['mu_weight'].reshape(4,256)@h+W['mu_bias'].reshape(4)
    at=np.tanh(mu); alo=W['act_low'].reshape(4); ahi=W['act_high'].reshape(4)
    return alo+0.5*(at+1)*(ahi-alo)

for name in ['asym','sym','hvrt']:
    W=sio.loadmat(f"frt_standard/sac_{name}_weights.mat")
    fp = {'asym':2,'sym':1,'hvrt':5}[name]
    print(f"\n=== {name} expert (.mat, fp={fp}) ===")
    print(f"{'V2p':>5} {'V2n':>5} {'iq_ref':>7} | {'iq':>7} {'id':>7} {'mse_d':>7} {'mse_q':>7}")
    if name=='hvrt': rows=[(1.30,0.0),(1.25,0.0),(1.20,0.0),(1.15,0.0)]
    else: rows=[(0.85,0.10),(0.80,0.12),(0.70,0.15),(0.60,0.18),(0.50,0.20),(0.40,0.22)]
    for V2p,V2n in rows:
        a=fwd(W, build_obs(V2p,V2n,fp))
        if V2p<0.9: iq_ref=min(0.30,1.5*(0.9-V2p))
        elif V2p>1.1: iq_ref=max(-0.30,-1.5*(V2p-1.1))
        else: iq_ref=0.0
        print(f"{V2p:5.2f} {V2n:5.2f} {iq_ref:7.3f} | {a[1]:7.3f} {a[0]:7.3f} {a[2]:7.3f} {a[3]:7.3f}")
