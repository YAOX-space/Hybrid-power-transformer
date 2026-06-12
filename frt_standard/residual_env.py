"""residual_env.py — Residual-SAC environment: action = MPC closed-form prior + bounded residual.

Literature basis: residual RL with a model-based prior (Residual-MPC'25, Residual-MPPI ICLR'25):
the prior provides a safe floor (here: the mode-8 analytic MPC, 79.7% full-320), the policy
learns only the residual — concentrating capacity on what the equilibrium model cannot express
(asymmetric 2ω dynamics, per-condition fine-tuning).

ONE policy for ALL 320 scenarios (the prior handles domain logic; tests whether the 4-expert
split is still needed once a strong prior exists).

Also adds the criteria-aligned connect-margin reward (the one criterion the base reward missed).
"""
from __future__ import annotations
import numpy as np
from gymnasium import spaces
from frt_env import HPTFRTEnv, I_CONV_MAX, V_SE_MAX

IQ_CAP   = 0.27          # total reactive cap (headroom rule, symmetric faults)
IQ_CAP_ASYM = 0.24       # tighter cap on asymmetric faults: measured peak ≈ cmd × k_2ω (k≈1.3-1.4
                         # from m14-v1 forensics: sustained 0.27 cmd broke the 0.35 measured-peak
                         # limit on 1ph_g) — the ODE cannot see measurement ripple, so the limit
                         # criterion is enforced via this calibrated command-level cap instead.
RES_IQ   = 0.10          # residual authority on iq (pu)
RES_MSE  = 0.06          # residual authority on series d/q

ASYM_FT = ('1ph_g', '2ph', '2ph_g')


def mpc_prior(V2p, Vdc):
    """Mode-8 analytic MPC law in ODE conventions (V_se_d>0 = boost). Returns 4-vector."""
    if V2p < 0.9:
        iq = min(IQ_CAP, 1.5 * (0.9 - V2p))
        sag_iq = 0.08 * iq / max(0.3, V2p)
        mb = min(0.2, max(0.0, (1.0 - 0.82 - sag_iq) / 1.9))
        fb = min(1.0, max(0.0, (Vdc - 0.80) / 0.04))      # measured-Vdc receding feedback
        return np.array([0.0, iq, mb * fb, 0.0], np.float32)
    if V2p > 1.1:
        iq = max(-IQ_CAP, -1.5 * (V2p - 1.1))
        mb = -min(0.2, 1.5 * (V2p - 1.1))                 # anti-boost (negative V_se_d)
        return np.array([0.0, iq, mb, 0.0], np.float32)
    return np.zeros(4, np.float32)


class HPTFRTResidualEnv(HPTFRTEnv):
    """Same dynamics/obs as HPTFRTEnv; the agent outputs a bounded RESIDUAL on the MPC prior."""

    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        # dim 0 (i_sh_d) is dead in deployment; keep a tiny nonzero width to avoid divide-by-zero
        # in SB3's action scaling.
        self.action_space = spaces.Box(
            low=np.array([0.0, -RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([0.01, RES_IQ,  RES_MSE,  RES_MSE], np.float32))

    def step(self, action):
        res = np.asarray(action, np.float32)
        pri = mpc_prior(self.V2p, self.Vdc)
        tot = pri + res
        # asym-aware reactive cap (deployment mirror: HLC clips at 0.24 when V2n>0.05 & V2p<0.9)
        cap = IQ_CAP_ASYM if (self._sc['category'] == 'LVRT'
                              and self._sc['fault_type'] in ASYM_FT) else IQ_CAP
        tot[1] = float(np.clip(tot[1], -cap, cap))
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))
        tot[3] = float(np.clip(tot[3], -V_SE_MAX, V_SE_MAX))
        tot[0] = 0.0                                        # i_sh_d unused (discarded in Simulink)
        obs, r, done, trunc, info = super().step(tot)
        # criteria-aligned connect margin (the criterion the base reward missed): during an LVRT
        # fault keep V2p at/above the calibrated target tV (reference) with a small margin.
        s = self._sc
        if s['category'] == 'LVRT':
            in_fault = s['t_fault'] <= self.t <= s['t_fault'] + s['fault_dur'] * 0.20
            if in_fault:
                r += -8.0 * max(0.0, float(s['target_V_pu']) - 0.02 - self.V2p)
        return obs, float(r), done, trunc, info
