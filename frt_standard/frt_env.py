"""
frt_env.py — upgraded averaged-ODE training environment for STANDARD FRT (FRT_SPEC.md).

Differences vs ai/hpt_direct_env.py (the old single-sequence env):
  + positive AND negative sequence terminal voltage (true asymmetric faults)
  + reactive-priority current injection (shunt i_sh_q -> grid voltage support, ≤0.3 pu PE cap)
  + current limiting (reactive priority, active curtailed under the limit)
  + GB/T voltage-time ride-through envelope -> "stay-connected" criterion
  + 4-D action [i_sh_d, i_sh_q, m_se_d, m_se_q]; ~22-D observation

ALL quantities in per-unit (1.0 = nominal terminal voltage / rated current).
This is a TRAINING SURROGATE (fast, approximate); Simulink remains the authority.

Time: a TSCALE factor compresses the GB/T seconds-scale curve so training episodes
stay short (the policy is scale-invariant for the relative criteria; absolute-time
fidelity is a Simulink-validation concern, see FRT_SPEC §"时间尺度").
"""
from __future__ import annotations
import math
import numpy as np
import gymnasium as gym
from gymnasium import spaces

# ── per-unit constants ──────────────────────────────────────────────────────────
VDC_NOM   = 1.0                 # DC bus pu (nominal)
I_Q_MAX   = 0.25                # reactive cmd cap (v3: 0.30→0.25, leaves margin vs 0.35 limit for 2ω peaks on asymmetric faults)
I_CONV_MAX= 0.35                # total shunt converter current limit, pu (reactive priority)
V_SE_MAX  = 0.20                # series injection ±20% [task book / Shang]
# DC damping-resistor load as a pu power coefficient: P_load = Vdc_pu² · K_DC,
# K_DC = (800²/8.2)/400e3 ≈ 0.195 pu  (the 78 kW bleeder normalized to the 400 kVA base)
K_DC      = (800**2 / 8.2) / 400e3
DC_TAU    = 2 * 704.0 / 400e3   # DC capacitor time const = 2·E_dc/P_base ≈ 3.5 ms
TAU_V2    = 0.010              # terminal-voltage first-order lag (s)
# ── Simulink-calibrated effectiveness gains (2026-06-09) ──────────────────────────
# Measured on hpt_frt_full.slx: shunt reactive iq=0.30pu → LV +2.2% at SCR=3
#   ⇒ K_q ≈ 0.073 at SCR=3, i.e. K_Q_BASE = 0.073·3 ≈ 0.22 (was 1.0 = ~4.5× too optimistic).
# Series m_se_d=0.10 → LV +4.7% ⇒ effective gain ≈ 0.47 (was 1.0 = ~2× too optimistic).
# This closes the ODE→Simulink optimism gap so the policy learns realistic actuator authority.
K_Q_BASE  = 0.22              # reactive→voltage gain (Simulink-calibrated; weak grid → larger)
SE_GAIN   = 0.47              # series-injection voltage effectiveness (Simulink-calibrated)

FRT_FAULTS = ['normal', 'sym3ph', '1ph_g', '2ph', '2ph_g', 'swell']  # state fault classes
F2I = {f: i for i, f in enumerate(FRT_FAULTS)}

DT      = 2e-3                  # control step (s)
TSCALE  = 0.20                 # compress GB/T seconds-curve for training (see header)


def fault_sequence(ftype: str, targetV: float):
    """Map fault type + residual/swell level → imposed grid positive/negative seq voltage (pu).
    Standard shunt-fault sequence approximations (documented in FRT_SPEC)."""
    if ftype in ('sym3ph',):            return targetV, 0.0
    if ftype in ('swell_3ph', 'swell'): return targetV, 0.0
    if ftype == '1ph_g':   return (2 + targetV) / 3.0, (1 - targetV) / 3.0
    if ftype == '2ph':     return (1 + targetV) / 2.0, (1 - targetV) / 2.0
    if ftype == '2ph_g':   return (1 + 2*targetV) / 3.0, (1 - targetV) / 3.0
    if ftype == 'swell_1ph': return (2 + targetV) / 3.0, abs(targetV - 1) / 3.0
    return 1.0, 0.0


def lvrt_envelope(t_rel, residual, reach09=2.0, ts=TSCALE):
    """GB/T LVRT lower boundary (pu) at time t_rel after fault onset (compressed by ts)."""
    hold = 0.625 * ts
    reach = reach09 * ts
    if t_rel < 0:        return 0.9
    if t_rel <= hold:    return max(0.0, residual - 0.05)        # ride window: just above residual
    if t_rel <= reach:   return residual + (0.9 - residual) * (t_rel - hold) / (reach - hold)
    return 0.9


class HPTFRTEnv(gym.Env):
    """Standard-FRT averaged-ODE environment. 4-D action, ~22-D observation."""
    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__()
        self.scn = list(scenarios)
        self.rng = np.random.default_rng(seed)
        self.train_mode = train_mode
        self.action_space = spaces.Box(
            low=np.array([0.0, -I_Q_MAX, -V_SE_MAX, -V_SE_MAX], np.float32),
            high=np.array([I_CONV_MAX, I_Q_MAX, V_SE_MAX, V_SE_MAX], np.float32))
        self.observation_space = spaces.Box(-5, 5, shape=(21,), dtype=np.float32)
        self._i = 0

    # ── grid voltage imposed by the scenario at time t ──────────────────────────
    def _grid_seq(self, t):
        s = self._sc
        t_f, dur = s['t_fault'], s['fault_dur'] * TSCALE
        if t < t_f or t > t_f + dur:
            return 1.0, 0.0                      # pre/post fault: nominal
        return self._Vg_p, self._Vg_n

    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        s = self.scn[self._i % len(self.scn)]; self._i += 1
        self._sc = s
        self._Vg_p, self._Vg_n = fault_sequence(s['fault_type'], float(s['target_V_pu']))
        self.scr = float(s['scr'])
        self.K_q = K_Q_BASE / self.scr           # reactive→voltage gain (weak grid → larger)
        # state: [Vdc, V2p, V2n, xi]  (positive/negative seq terminal mag, integrator)
        self.Vdc = 1.0
        self.V2p = 1.0
        self.V2n = 0.0
        self.xi  = 0.0
        self.t   = 0.0
        self.tripped = False
        self._iq = 0.0
        self._last_a = np.zeros(4, np.float32)
        self._fp = F2I.get('sym3ph' if s['category']=='LVRT' and s['fault_type']=='sym3ph'
                           else ('swell' if s['category']=='HVRT' else s['fault_type']), 0)
        return self._obs(), {}

    def _obs(self):
        s = self._sc
        in_fault = float(s['t_fault'] <= self.t <= s['t_fault'] + s['fault_dur']*TSCALE)
        vdev = 0.9 - self.V2p
        iq_ref = self._iq_ref()
        iq_err = iq_ref - self._iq
        probs = np.zeros(6, np.float32)
        if in_fault: probs[self._fp] = 0.92; probs[0] += 0.08
        else: probs[0] = 1.0
        o = np.array([
            self.Vdc, self.V2p, self.V2n, abs(self._iq),
            0.0, 0.0,                       # dVdc, dV2 placeholders (filled by deltas if needed)
            vdev, iq_err, self._iq,
            *probs,
            min(1.0, max(0.0, (self.t - s['t_fault'])/ (0.5))), in_fault,
            *self._last_a,
        ], dtype=np.float32)
        return np.clip(o, -5, 5)

    def _iq_ref(self):
        """GB/T reactive droop reference (pu), capped at PE limit."""
        if self.V2p < 0.9:                       # LVRT: inject capacitive (positive)
            return min(I_Q_MAX, 1.5 * (0.9 - self.V2p))
        if self.V2p > 1.1:                       # HVRT: absorb (negative)
            return max(-I_Q_MAX, -1.5 * (self.V2p - 1.1))
        return 0.0

    def step(self, action):
        a = np.asarray(action, np.float32)
        i_sh_d, i_sh_q, m_se_d, m_se_q = [float(x) for x in a]
        # current limit (reactive priority): cap iq, then active fits under total limit
        i_sh_q = float(np.clip(i_sh_q, -I_Q_MAX, I_Q_MAX))
        id_max = math.sqrt(max(0.0, I_CONV_MAX**2 - i_sh_q**2))
        i_sh_d = float(np.clip(i_sh_d, 0.0, id_max))
        self._iq = i_sh_q

        Vg_p, Vg_n = self._grid_seq(self.t)
        # series injection magnitude limited
        V_se_d = float(np.clip(m_se_d, -V_SE_MAX, V_SE_MAX))
        V_se_q = float(np.clip(m_se_q, -V_SE_MAX, V_SE_MAX))

        # ── positive-seq terminal voltage: grid + series support + reactive boost ──
        # actuator gains Simulink-calibrated (SE_GAIN, K_q) — see constants block
        V2p_ss = Vg_p + SE_GAIN * V_se_d + self.K_q * i_sh_q
        V2p_ss = max(0.0, V2p_ss)
        self.V2p += (V2p_ss - self.V2p) * (DT / TAU_V2)
        # ── negative-seq: grid neg-seq, reduced by series q-axis (neg-seq compensation) ──
        V2n_ss = max(0.0, Vg_n - abs(V_se_q))
        self.V2n += (V2n_ss - self.V2n) * (DT / TAU_V2)

        # ── DC bus: active in (shunt, MV-fed) − series drain − damping load ──
        # Sub-stepped (the ~3.5 ms cap is stiff vs the 2 ms control step) + clamped.
        P_sh = Vg_p * i_sh_d                               # shunt on MV side → uses grid-seq voltage
        P_se = 0.5 * math.hypot(V_se_d, V_se_q)            # series H-bridge DC drain (pu)
        nsub = 10
        hsub = DT / nsub
        for _ in range(nsub):
            P_dc_load = self.Vdc**2 * K_DC                 # 8.2 Ω bleeder ≈ 0.195 pu
            dVdc = (P_sh - P_se - P_dc_load) / (DC_TAU * max(0.2, self.Vdc))
            self.Vdc = min(1.6, max(0.05, self.Vdc + dVdc * hsub))

        self.t += DT
        self._last_a = a

        # ── envelope / trip check ───────────────────────────────────────────────
        s = self._sc
        t_rel = self.t - s['t_fault']
        if s['category'] == 'LVRT':
            env = lvrt_envelope(t_rel, float(s['target_V_pu']))
            if self.V2p < env - 0.001:
                self.tripped = True
        else:  # HVRT upper boundary
            if self.V2p > 1.30 + 0.02:
                self.tripped = True

        # ── reward (FRT_SPEC §1 五条判据) ─────────────────────────────────────────
        iq_ref = self._iq_ref()
        r_connect = -20.0 if self.tripped else 0.0
        r_reactive = -5.0 * abs(iq_ref - i_sh_q)   # v3: balanced (-3 orig → -8 overshot → -5)
        r_limit = -5.0 * max(0.0, math.hypot(i_sh_d, i_sh_q) - I_CONV_MAX)
        r_v2 = -5.0 * abs(1.0 - self.V2p) - 3.0 * self.V2n
        r_vdc = -10.0 * max(0.0, 0.75 - self.Vdc) - 5.0 * max(0.0, self.Vdc - 1.25)
        reward = r_connect + r_reactive + r_limit + r_v2 + r_vdc + 1.0  # +1 alive

        done = self.t >= float(s['T_sim']) * TSCALE or self.tripped
        info = {'V2p': self.V2p, 'V2n': self.V2n, 'Vdc': self.Vdc, 'iq': i_sh_q,
                'iq_ref': iq_ref, 'tripped': self.tripped, 't': self.t}
        return self._obs(), float(reward), bool(done), False, info


def load_frt_scenarios(csv_path):
    import csv
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append({k: (float(v) if k not in ('category', 'fault_type', 'grid') else v)
                         for k, v in r.items()})
    return rows
