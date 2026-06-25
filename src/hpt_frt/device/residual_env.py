"""residual_env.py — environment for canonical Mode 6 (MPC-assisted residual SAC), the EXTENSION
(NOT the main method, NOT pure SAC; main method = Mode 5, frt_env.py). Internal HLC dispatch mi==14.
Action = MPC closed-form prior + bounded residual. Canonical naming per CONTROL_MODES.md.

ACTION INTERFACE: structurally 3-D — the vestigial dim 0 is bounded to ~0 (upper bound 0.01) and
zeroed in step(), so the train/deploy interface is consistent (no 4-D-vs-3-D mismatch), unlike the
Mode 3/5 frt_env.py which carries a vestigial 4th dim.

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
from .frt_env import HPTFRTEnv, V_SE_MAX
from .frt_env_v2 import HPTFRTEnvV2, N_ACT_V2

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


def mpc_prior3(V2p, Vdc):
    """Mode-8 analytic MPC law as the frt-v2 3-D vector [iq, mse_d, mse_q] (drops the vestigial i_d)."""
    p4 = mpc_prior(V2p, Vdc)
    return np.array([p4[1], p4[2], p4[3]], np.float32)


class HPTFRTResidualEnvV2(HPTFRTEnvV2):
    """frt-v2 RESIDUAL env (audit round-4 C.2): inherits the 3-D action + 20-D DE-PRIVILEGED obs +
    VERSIONED trip envelope from HPTFRTEnvV2 (NOT the legacy 4-D/21-D contract). The agent outputs a
    bounded 3-D residual [iq, mse_d, mse_q] on the analytic MPC prior."""

    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        self.action_space = spaces.Box(
            low=np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([RES_IQ, RES_MSE, RES_MSE], np.float32))

    def step(self, action):
        res = np.asarray(action, np.float32).reshape(N_ACT_V2)
        tot = mpc_prior3(self.V2p, self.Vdc) + res
        cap = IQ_CAP_ASYM if (self._sc['category'] == 'LVRT'
                              and self._sc['fault_type'] in ASYM_FT) else IQ_CAP
        tot[0] = float(np.clip(tot[0], -cap, cap))            # iq
        tot[1] = float(np.clip(tot[1], -V_SE_MAX, V_SE_MAX))  # mse_d
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))  # mse_q
        obs, r, done, trunc, info = super().step(tot)
        s = self._sc
        if s['category'] == 'LVRT':
            in_fault = s['t_fault'] <= self.t <= s['t_fault'] + s['fault_dur'] * 0.20
            if in_fault:
                r += -8.0 * max(0.0, float(s['target_V_pu']) - 0.02 - self.V2p)
        return obs, float(r), done, trunc, info


class HPTFRTResidualEnv(HPTFRTEnv):
    """LEGACY frt-v1 residual env (4-D action / 21-D obs / privileged label obs / legacy envelope).
    Kept only for `--legacy` reproduction; new training uses HPTFRTResidualEnvV2. Do NOT use for P3."""

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
