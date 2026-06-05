"""
hpt_direct_env.py  —  HPT direct continuous control environment.

The SAC agent directly outputs modulation-equivalent signals that bypass
the PI loops, controlling the two VSCs at the most fundamental level:

  Action (3D continuous, physically bounded):
    a[0]  m_sh  ∈ [0.0, 0.9]   shunt VSC modulation index
                                 → drives I_sh ≈ m_sh × V_dc/(2×L_sh×ω)
    a[1]  m_se_d ∈ [-0.3, 0.3] series VSC d-axis modulation
                                 → V_se_d = m_se_d × V_dc/2 / Tse_ratio
    a[2]  m_se_q ∈ [-0.3, 0.3] series VSC q-axis modulation
                                 → V_se_q = m_se_q × V_dc/2 / Tse_ratio

  Physical limits (from simulink/parameters.m):
    |V_se| ≤ 46.2 V  (hardware: Tse transformer limit)
    I_sh   ≤ 173.2 A (hardware: VSC_sh rated current)

  State (17D, all physically observable):
    [0]    V_dc_pu                  DC link voltage (pu)
    [1]    V2_pu                    Secondary voltage (pu)
    [2]    I2_pu                    Secondary current (pu)
    [3]    dVdc_dt_norm             V_dc rate of change (normalised)
    [4]    dV2_dt_norm              V2 rate of change (normalised)
    [5:12] fault_probs[7]           MSFFN fault type probabilities
    [12]   t_since_fault_norm       Time since fault start (normalised)
    [13]   in_fault                 Binary fault flag
    [14:17] last_action[3]          Previous action (smooth control)

  Control frequency:
    Normal operation: 20 Hz (Δt = 50 ms) — coarse, energy-saving
    Fault active:    200 Hz (Δt =  5 ms) — fine, fast response
    Trigger: |dVdc/dt| > 1000 V/s  OR  max(fault_probs[1:]) > 0.30

  Reward (multi-objective, physics-grounded):
    w_vdc     = 10.0   VdcMin below 0.75 pu  (most critical)
    w_v2      =  5.0   V2 deviation from nominal
    w_i2      =  8.0   I2 overcurrent
    w_recovery=  3.0   V2 recovery speed after fault
    w_margin  =  3.0   Continuous Vdc margin incentive

  Physics guarantee:
    All dynamics from the validated HPT averaged-model ODE.
    All bounds from simulink/parameters.m.
    ODE known limitations: cap_fault (sc_id=5) and igbt faults (sc_id=3,4,8)
    have reduced accuracy — SAC will still train but Simulink validation
    is required for those fault classes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from scipy.integrate import solve_ivp

# ── Physical constants (from simulink/parameters.m) ───────────────────────────
VDC_NOM   = 800.0         # V
V2_LL     = 400.0         # V line-line
V2_PH     = V2_LL / np.sqrt(3)
V2_PK     = V2_PH * np.sqrt(2)     # 326.6 V phase peak
OMEGA     = 2 * np.pi * 50.0
C_DC      = 2200e-6       # F
C_DC_CAP  = 680e-6        # F  cap_fault
L_SE_HB   = 1e-3          # H  H-bridge inductance
R_SE_HB   = 0.02          # Ω  H-bridge resistance
TSE_RATIO = 8.66           # H-bridge:LV turns ratio
L_SE      = L_SE_HB / TSE_RATIO**2   # LV-referred = 13.3 µH
R_SE      = R_SE_HB / TSE_RATIO**2   # LV-referred = 2.67×10⁻⁴ Ω
L_SH      = 3e-3           # H  shunt filter
R_SH      = 0.05           # Ω  shunt filter
# Fix #2: shunt voltage must be phase peak (V2_PK), not line-RMS (400V)
# P_sh = (3/2)·V_d·I_d requires V_d = phase peak = 400/√3·√2 ≈ 326.6 V
V_SH_RAT  = V2_PK          # V  = 326.6 V  phase peak (was wrong: 400 V line-RMS)
I_SH_MAX  = 173.2          # A  shunt rated current
V_SE_MAX  = 46.2           # V  series injection hardware limit (LV-side phase peak)
I2_NOM    = 400e3 / (np.sqrt(3) * V2_LL)   # A  ≈ 577 A  (RMS)
# Fix #1: normalisation base must be peak current to match lvrt_metrics.py / Simulink
I2_NOM_PK = I2_NOM * np.sqrt(2)             # A  ≈ 816.5 A  (peak = √2 × RMS)

# ── Action bounds (physical) ───────────────────────────────────────────────────
# m_sh  : shunt VSC modulation index, [0, 0.92] hardware (set 0.90 for margin)
# m_se_d: series d-axis modulation, ± V_se_max / (V_dc/2/Tse) ≈ ±0.30
# m_se_q: series q-axis modulation, same limit
M_SH_MAX   = 0.90
# Fix #5: remove spurious √2.  Simulink clips series modulation at m=0.30
# (Regulation_VSC_SPWM: m=min(0.30,max(0,m))).  Physical derivation:
#   m_max = V_se_max_peak / (V_dc/2 / Tse_ratio) = 46.2 / (800/2/8.66) ≈ 1.0
# but practical SPWM linear region ≤ 1.0, and Simulink enforces 0.30.
M_SE_BOUND = 0.30  # aligned with Simulink SPWM clip (was 1.414 due to spurious √2)

ACTION_LOW  = np.array([0.0,       -M_SE_BOUND, -M_SE_BOUND], dtype=np.float32)
ACTION_HIGH = np.array([M_SH_MAX,  +M_SE_BOUND, +M_SE_BOUND], dtype=np.float32)

# ── Reward weights ─────────────────────────────────────────────────────────────
W_VDC      = 10.0   # VdcMin penalty (most critical)
W_V2       =  5.0   # V2 deviation
W_I2       =  8.0   # overcurrent
W_RECOVERY =  3.0   # V2 recovery speed
W_MARGIN   =  3.0   # Vdc margin incentive
# Series VSC modulation penalty: discourages excessive m_se which drains DC in Simulink.
# With W_MSE=3.0: at m_se_d=0.12 penalty=-0.043 (small, sc_1ph benefit overcomes it),
# at m_se_d=0.25 penalty=-0.188 (larger, pushes SAC back from high injection).
W_MSE      =  3.0   # series modulation penalty (prevents Simulink DC drain)

# ── Fault detection thresholds ─────────────────────────────────────────────────
DVDC_FAULT_THRESHOLD  = 1000.0    # V/s   — start high-freq if Vdc falling fast
MSFFN_FAULT_THRESHOLD = 0.30      # prob  — start high-freq if fault likely

# ── Calibrated fault impedances ────────────────────────────────────────────────
Z_EFF_3PH = 0.95
Z_EFF_1PH = 0.35

# ── Training enhancements (literature-motivated) ────────────────────────────────
# 1. Episode length: must match Simulink evaluation window (50ms).
# Extended 150ms (v3) made SAC learn long-horizon series injection that drains DC
# in Simulink's 50ms evaluation window — confirmed empirically to be harmful.
T_SIM_TRAIN  = 0.050        # s  — identical to scenario_table_hpt_v2.csv T_sim

# 2. Domain randomisation ranges (uniform multiplicative noise around nominal)
DR_C_DC      = (0.85, 1.15) # DC capacitance ±15%
DR_Z_3PH     = (0.70, 1.30) # 3-phase fault impedance ±30%
DR_Z_1PH     = (0.70, 1.30) # 1-phase fault impedance ±30%
DR_L_SH      = (0.88, 1.12) # Shunt filter inductance ±12%
DR_FAULT_DUR = (0.010, 0.020)  # Fault clearing time 10-20ms (nominal 15ms)

# 3. MSFFN classification noise — simulates real classifier imperfection (~2% error rate)
MSFFN_NOISE_STD = 0.05      # Gaussian noise std on fault probability vector

# 4. Sparse LVRT bonus — episode-end reward when all three LVRT criteria pass
W_LVRT_BONUS = 30.0         # Added to cumulative reward if LVRT passes


# ── Simple MSFFN simulator (uses existing MSFFN if available) ─────────────────

class MSFFNSimulator:
    """Simulate MSFFN output for ODE training.

    During ODE training we don't run the real MSFFN — we approximate its
    output from the scenario parameters.  In real deployment, replace with
    the actual MSFFN inference.
    """

    def __init__(self):
        # 7 classes: 0=normal,3=igbt_oc_sh,4=igbt_oc_se,5=cap_fault,
        #            6=sc_1ph,7=sc_3ph,8=cascade
        self._sc_to_idx = {0:0, 3:1, 4:2, 5:3, 6:4, 7:5, 8:6}

    def predict(self, sc_id: int, t_since_fault: float) -> np.ndarray:
        """Return 7-dim fault probability vector.

        Before fault: mostly normal (class 0).
        After fault onset and 5ms delay: spike to true class.
        """
        probs = np.zeros(7, dtype=np.float32)
        if t_since_fault < 5e-3:
            # Fault not yet classified (5ms detection delay)
            probs[0] = 0.7   # still looks mostly normal
            true_idx = self._sc_to_idx.get(sc_id, 0)
            probs[true_idx] += 0.3
        else:
            # Fault classified
            true_idx = self._sc_to_idx.get(sc_id, 0)
            probs[true_idx] = 0.92
            probs[0] = 0.08   # residual normal probability
        return probs


# ── ODE RHS with direct modulation control ────────────────────────────────────

def _ode_direct(t: float, x: np.ndarray, params: dict) -> np.ndarray:
    """ODE right-hand side with direct modulation index control.

    State: x = [V_dc, V2_d, V2_q, xi_vac_d, xi_vac_q]  (5 states)
    Control: m_sh (shunt modulation), m_se_d, m_se_q (series modulation)
    """
    V_dc   = x[0]
    V2_d   = x[1]
    V2_q   = x[2]
    xi_vac_d = x[3]
    xi_vac_q = x[4]

    sc_id      = params['sc_id']
    t_fault    = params['t_fault']
    T_sim      = params['T_sim']
    P_load     = params['P_load']
    Q_load     = params['Q_load']
    fault_mag  = params['fault_mag']
    fault_res  = params['fault_resistance']
    ground_res = params['ground_resistance']
    # Current action from agent
    m_sh   = params['m_sh']       # shunt modulation [0, 0.90]
    m_se_d = params['m_se_d']     # series d-axis modulation [±0.30]
    m_se_q = params['m_se_q']     # series q-axis modulation [±0.30]

    # ── Randomised physical parameters (from domain randomisation) ────────
    C_dc_scale   = params.get('C_dc_scale', 1.0)
    z_3ph        = params.get('Z_3ph', Z_EFF_3PH)
    z_1ph        = params.get('Z_1ph', Z_EFF_1PH)
    L_sh_eff     = params.get('L_sh',  L_SH)
    fault_dur    = params.get('fault_duration', 0.015)

    # ── Fault-modified capacitance (with randomisation) ────────────────────
    base_C   = C_DC_CAP if sc_id == 5 else C_DC
    C_dc_eff = base_C * C_dc_scale

    # sc_1ph and sc_3ph clear after fault_dur seconds (randomised around 15 ms)
    if sc_id in (6, 7):
        in_fault = (t_fault <= t < t_fault + fault_dur)
    else:
        in_fault = (t_fault <= t)

    # ── Grid voltage during fault ──────────────────────────────────────────
    if not in_fault or sc_id == 0:
        V_g_d = V2_PK;  V_g_q = 0.0
    elif sc_id == 7:    # sc_3ph
        R_f = fault_res + ground_res
        V_g_d = V2_PK * R_f / (z_3ph + R_f);  V_g_q = 0.0
    elif sc_id == 6:    # sc_1ph
        R_f = fault_res + ground_res
        sag = 1.0 - R_f / (z_1ph + R_f)
        V_g_d = V2_PK * (1.0 - 0.55 * sag);  V_g_q = 0.0
    elif sc_id == 8:    # cascade
        V_g_d = V2_PK * 0.97;  V_g_q = 0.0
    else:               # igbt faults, cap_fault: no voltage sag
        V_g_d = V2_PK;  V_g_q = 0.0

    # ── Derive physical signals from modulation indices ────────────────────
    # Series VSC: SPWM averaged output per phase = m × (V_dc/2 / Tse_ratio)
    # This is the fundamental-frequency component in the dq frame.
    # NOTE: The previous code had an erroneous × √2 factor. At m=0.30, Vdc=800V:
    #   Correct: V_se = 0.30 × 400/8.66 = 13.87V  (always < 46.2V hardware limit)
    #   Wrong:   V_se = 0.30 × 400/8.66 × √2 = 19.6V (still < 46.2V, never clipped)
    # The hardware clip never activates for |m_se| ≤ 0.30 and Vdc ≤ 1000V.
    # The √2 was physically incorrect and inflated series voltage by 41.4%.
    V_se_d = m_se_d * (max(V_dc, 50.0) / 2.0 / TSE_RATIO)
    V_se_q = m_se_q * (max(V_dc, 50.0) / 2.0 / TSE_RATIO)
    # Clip to hardware limit
    V_se_mag = np.hypot(V_se_d, V_se_q)
    if V_se_mag > V_SE_MAX:
        V_se_d *= V_SE_MAX / V_se_mag
        V_se_q *= V_SE_MAX / V_se_mag

    # Shunt VSC: correct d-q averaged model.
    # SPWM average output: V_sh_d = m_sh × (Vdc/2)  (PLL-aligned, d-axis)
    # Inductor current: I_sh_d = (V2_d - V_sh_d) / (ω × L_sh)
    # Positive I_sh_d means current flows from AC bus into DC link (charging).
    # This matches the empirical Simulink equilibrium: at m_sh=0.68, Vdc=800V,
    # V2_d=326.6V → V_sh=272V → I_sh=58.4A → P_sh=28.6kW (PI balance point).
    V_sh_d = m_sh * (max(V_dc, 50.0) / 2.0)
    I_sh_d = np.clip((V2_d - V_sh_d) / (OMEGA * L_sh_eff), -I_SH_MAX, I_SH_MAX)

    # ── Load current (constant P+jQ) ───────────────────────────────────────
    V2_mag2 = max(V2_d**2 + V2_q**2, (V2_PK * 0.05)**2)
    I_ld_d  = (2.0/3.0) * (P_load * V2_d + Q_load * V2_q) / V2_mag2
    I_ld_q  = (2.0/3.0) * (P_load * V2_q - Q_load * V2_d) / V2_mag2
    I_ld    = np.hypot(I_ld_d, I_ld_q)
    I_lim_A = 3.0 * I2_NOM_PK   # Fix #1: limiter in peak amps (3 pu × I2_NOM_PK)
    if I_ld > I_lim_A:
        s = I_lim_A / (I_ld + 1e-9)
        I_ld_d *= s;  I_ld_q *= s

    # ── V2 steady-state and dynamics ──────────────────────────────────────
    V2_ss_d = V_g_d + V_se_d - R_SE * I_ld_d + OMEGA * L_SE * I_ld_q
    V2_ss_q = V_g_q + V_se_q - R_SE * I_ld_q - OMEGA * L_SE * I_ld_d
    tau_V2  = 5e-3
    dV2_d   = (V2_ss_d - V2_d) / tau_V2
    dV2_q   = (V2_ss_q - V2_q) / tau_V2

    # ── DC power balance ───────────────────────────────────────────────────
    P_se_out = 1.5 * (V_se_d * I_ld_d + V_se_q * I_ld_q)
    # Fix: P_sh must use actual V2_d (not constant V_SH_RAT = V2_PK).
    # During sc_3ph fault, V2_d ≈ 0 → P_sh = 0 (no power transfer across shorted bus).
    # Using fixed V2_PK overestimated P_sh during faults and was physically incorrect.
    P_sh_in  = 1.5 * V2_d * I_sh_d

    # IGBT fault on shunt VSC: reduce P_sh proportionally
    if in_fault and sc_id in (3, 8):
        P_sh_in *= max(0.0, 1.0 - fault_mag)

    P_dc_net = P_sh_in - P_se_out
    dV_dc    = P_dc_net / (C_dc_eff * max(V_dc, 50.0))

    # ── AC voltage PI integrators (track V2 for next step reference) ───────
    # These capture accumulated V2 error — used in state observation only
    V2_ref_d = V2_PK
    dxi_vac_d = 50.0 * (V2_ref_d - V2_d)   # Ki_vac = 50 from parameters.m
    dxi_vac_q = 50.0 * (0.0       - V2_q)

    return np.array([dV_dc, dV2_d, dV2_q, dxi_vac_d, dxi_vac_q], dtype=np.float64)


# ── HPT Direct-Control Gymnasium Environment ───────────────────────────────────

class HPTDirectEnv(gym.Env):
    """Gymnasium environment for SAC direct continuous control of HPT.

    Each episode simulates one fault scenario.
    Agent decides [m_sh, m_se_d, m_se_q] every Δt (5ms during fault, 50ms normal).

    State: 17-dimensional physically observable vector.
    Action: 3-dimensional continuous (physical SPWM modulation indices).
    """

    metadata = {'render_modes': []}

    def __init__(
        self,
        scenarios: list[dict],  # list of scenario dicts from CSV
        msffn: Optional[MSFFNSimulator] = None,
        seed: int = 42,
        train_mode: bool = True,   # True: 150ms episode + DR + MSFFN noise
    ):
        super().__init__()
        self.scenarios   = scenarios
        self.msffn       = msffn or MSFFNSimulator()
        self.rng         = np.random.default_rng(seed)
        self.train_mode  = train_mode

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(17,), dtype=np.float32
        )
        self.action_space = spaces.Box(
            low=ACTION_LOW, high=ACTION_HIGH, dtype=np.float32
        )

        # Episode state
        self._sc       = None
        self._x        = None           # ODE state
        self._t        = 0.0
        self._last_act = np.zeros(3, dtype=np.float32)
        self._dVdc_dt  = 0.0
        self._dV2_dt   = 0.0
        self._in_fault = False
        self._t_fault_start = None
        self._V_dc_prev = VDC_NOM
        self._V2_prev   = V2_PK
        self._x_prev    = None

        # LVRT tracking for sparse end-of-episode reward
        self._vdc_min_ep = 1.0
        self._vdc_max_ep = 0.0
        self._i2_max_ep  = 0.0

        # Domain randomisation parameters (set in reset)
        self._dr = {}

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._sc = self.scenarios[int(self.rng.integers(len(self.scenarios)))]

        # ── Domain randomisation (training mode only) ──────────────────────
        if self.train_mode:
            def _u(lo, hi): return float(self.rng.uniform(lo, hi))
            self._dr = {
                'C_dc_scale':    _u(*DR_C_DC),
                'Z_3ph':         Z_EFF_3PH * _u(*DR_Z_3PH),
                'Z_1ph':         Z_EFF_1PH * _u(*DR_Z_1PH),
                'L_sh':          L_SH      * _u(*DR_L_SH),
                'fault_duration': _u(*DR_FAULT_DUR),
            }
        else:
            self._dr = {}   # use nominal values for evaluation / Simulink matching

        # ── Episode T_sim override ─────────────────────────────────────────
        # Training: 150ms covers full 50 Hz recovery oscillation (3 cycles).
        # Evaluation/validation: keep scenario's original T_sim (50ms).
        self._T_sim = T_SIM_TRAIN if self.train_mode else float(self._sc['T_sim'])

        # ── LVRT tracking reset (for sparse end-of-episode bonus) ──────────
        self._vdc_min_ep = 1.5   # will shrink to actual min
        self._vdc_max_ep = 0.0   # will grow to actual max
        self._i2_max_ep  = 0.0

        # ── Steady-state initial conditions ───────────────────────────────
        P = self._sc['P_load']
        Q = self._sc['Q_load']
        L_sh_eff = self._dr.get('L_sh', L_SH)

        V2d0 = V2_PK
        I_ld_d0 = (2.0/3.0) * P / V2d0
        I_ld_q0 = -(2.0/3.0) * Q / V2d0
        V_se_d0 = R_SE * I_ld_d0 - OMEGA * L_SE * I_ld_q0
        V_se_q0 = R_SE * I_ld_q0 + OMEGA * L_SE * I_ld_d0
        P_se_ss = 1.5 * (V_se_d0 * I_ld_d0 + V_se_q0 * I_ld_q0)
        I_sh_ss = P_se_ss / (1.5 * V2d0) if V2d0 > 1.0 else 0.0
        V_sh_ss = V2d0 - I_sh_ss * OMEGA * L_sh_eff
        m_sh_ss = float(np.clip(V_sh_ss / (VDC_NOM / 2.0), 0.0, M_SH_MAX))

        self._x = np.array([VDC_NOM, V2d0, 0.0, I_ld_d0 * 0.01, 0.0])
        self._t = 0.0
        # Convert steady-state series voltage (V) → modulation index.
        # After removing the spurious √2: m_se = V_se / (Vdc/2/Tse_ratio)
        V_se_scale = VDC_NOM / 2.0 / TSE_RATIO   # = 46.18V at nominal Vdc
        self._last_act = np.array([m_sh_ss,
                                    V_se_d0 / V_se_scale,
                                    V_se_q0 / V_se_scale],
                                   dtype=np.float32)
        self._last_act = np.clip(self._last_act, ACTION_LOW, ACTION_HIGH)
        self._dVdc_dt  = 0.0
        self._dV2_dt   = 0.0
        self._in_fault = False
        self._t_fault_start = None
        self._V_dc_prev = VDC_NOM
        self._V2_prev   = V2_PK

        return self._get_obs(), {}

    def step(self, action: np.ndarray):
        action = np.clip(action, ACTION_LOW, ACTION_HIGH).astype(np.float32)
        self._last_act = action

        # Fixed 5ms step — matches Mode 8 exchange frequency.
        # Variable-frequency handled implicitly: agent adapts behaviour
        # via in_fault flag and dVdc/dt in the observation.
        Δt = 5e-3

        sc     = self._sc
        t_f    = sc['t_fault']
        T_sim  = self._T_sim   # use episode override (150ms train / 50ms eval)
        params = dict(
            sc_id=sc['sc_id'], t_fault=t_f, T_sim=T_sim,
            P_load=sc['P_load'], Q_load=sc['Q_load'],
            fault_mag=sc['fault_mag'],
            fault_resistance=sc['fault_resistance'],
            ground_resistance=sc['ground_resistance'],
            m_sh=float(action[0]), m_se_d=float(action[1]), m_se_q=float(action[2]),
            # domain randomisation params (empty dict = nominal values)
            **self._dr,
        )

        t_end  = min(self._t + Δt, T_sim)
        dt_sub = 1e-3   # 1ms sub-step (5 steps per 5ms — adequate for outer-loop dynamics)
        t_cur  = self._t
        x_cur  = self._x.copy()
        while t_cur < t_end - 1e-9:
            dt_i = min(dt_sub, t_end - t_cur)
            dx   = _ode_direct(t_cur, x_cur, params)
            x_cur = x_cur + dt_i * dx
            # Guard against V_dc going below 0
            x_cur[0] = max(x_cur[0], 10.0)
            t_cur += dt_i
        self._x = x_cur
        self._t = t_end

        V_dc   = self._x[0]
        V2_d   = self._x[1]
        V2_q   = self._x[2]
        V_dc_pu = V_dc / VDC_NOM
        V2_pu   = np.hypot(V2_d, V2_q) / V2_PK
        # Fix #1: I_ld from dq power is peak current; normalise by peak base I2_NOM_PK
        I_ld_mag = (2.0/3.0) * np.hypot(sc['P_load'], sc['Q_load']) / max(np.hypot(V2_d, V2_q), 1.0)
        I2_pu   = I_ld_mag / I2_NOM_PK   # peak/peak_base → 1.0 pu at rated

        # Rate of change (for state and fault detection)
        self._dVdc_dt = (V_dc - self._V_dc_prev) / Δt
        self._dV2_dt  = (np.hypot(V2_d, V2_q) - self._V2_prev) / Δt
        self._V_dc_prev = V_dc
        self._V2_prev   = np.hypot(V2_d, V2_q)

        # Update fault state
        in_fault_now = self._t >= t_f
        if in_fault_now and not self._in_fault:
            self._t_fault_start = self._t
        self._in_fault = in_fault_now

        # Switch to high-frequency if fault detected
        if (abs(self._dVdc_dt) > DVDC_FAULT_THRESHOLD or
                self._msffn_fault_prob() > MSFFN_FAULT_THRESHOLD):
            self._in_fault = True

        # ── LVRT tracking (post-fault window only) ────────────────────────
        if self._t >= t_f:
            self._vdc_min_ep = min(self._vdc_min_ep, V_dc_pu)
            self._vdc_max_ep = max(self._vdc_max_ep, V_dc_pu)
            self._i2_max_ep  = max(self._i2_max_ep,  I2_pu)

        # ── Reward ────────────────────────────────────────────────────────
        reward = self._compute_reward(V_dc_pu, V2_pu, I2_pu, Δt)

        # ── Termination ───────────────────────────────────────────────────
        terminated = (self._t >= T_sim - 1e-6)
        truncated  = False

        # ── Sparse LVRT bonus at episode end ──────────────────────────────
        # Directly rewards achieving all three LVRT criteria over the full episode.
        # This bridges the gap between step-wise quadratic penalties and the binary
        # LVRT pass/fail metric used in Simulink validation.
        if terminated and self.train_mode:
            lvrt_ok = (self._vdc_min_ep >= 0.75 and
                       self._vdc_max_ep <= 1.25 and
                       self._i2_max_ep  <= 3.0)
            reward += W_LVRT_BONUS if lvrt_ok else 0.0

        obs  = self._get_obs()
        info = {
            'V_dc_pu':  round(V_dc_pu, 4),
            'V2_pu':    round(V2_pu,   4),
            'I2_pu':    round(I2_pu,   4),
            't':        round(self._t,  4),
            'in_fault': self._in_fault,
            'lvrt_vdc_min': round(self._vdc_min_ep, 4),
            'lvrt_vdc_max': round(self._vdc_max_ep, 4),
            'lvrt_i2_max':  round(self._i2_max_ep,  4),
        }
        return obs, float(reward), terminated, truncated, info

    def _compute_reward(self, V_dc_pu, V2_pu, I2_pu, Δt):
        """Multi-objective physically-grounded reward.

        Key fix: penalise BOTH undervoltage (V_dc < 0.75) AND overvoltage
        (V_dc > 1.10).  Without the overvoltage penalty, the agent learns to
        maximise m_sh always, causing V_dc to spike above 1.25 pu (LVRT fail).
        """
        t_f  = self._sc['t_fault']
        in_f = self._t >= t_f

        # ── VdcMin penalty: keep V_dc above 0.75 pu ─────────────────────
        r_vdc_low  = -W_VDC * max(0.0, 0.75 - V_dc_pu)**2

        # ── VdcMax penalty: keep V_dc below 1.10 pu ─────────────────────
        # 1.10 pu = 880V provides safety margin below 1.25 pu LVRT limit
        r_vdc_high = -W_VDC * max(0.0, V_dc_pu - 1.10)**2

        # ── V2 deviation from nominal ─────────────────────────────────────
        r_v2   = -W_V2  * (V2_pu - 1.0)**2

        # ── Overcurrent ───────────────────────────────────────────────────
        r_i2   = -W_I2  * max(0.0, I2_pu - 3.0)**2

        # ── Vdc margin: incentive to stay in [0.80, 1.05] ──────────────
        # Positive only when V_dc is in the healthy operating band.
        # Clamped so it never rewards overvoltage.
        r_margin = 0.0
        if in_f:
            healthy_margin = min(V_dc_pu, 1.05) - 0.75   # 0 at 0.75, max 0.30
            r_margin = W_MARGIN * max(0.0, healthy_margin)

        # ── V2 recovery speed ─────────────────────────────────────────────
        r_recovery = 0.0
        if not in_f and self._t_fault_start is not None:
            t_since_clear = self._t - (self._sc['t_fault'] + 0.015)
            if t_since_clear > 0 and V2_pu >= 0.90:
                r_recovery = W_RECOVERY * (1.0 - t_since_clear / 0.10)

        # ── Series VSC modulation penalty ─────────────────────────────────
        # Penalises large m_se_d / m_se_q to prevent SAC learning excessive
        # series injection. In the real Simulink model high m_se drains DC
        # (P_se = V_se × I_load) in ways not fully captured by the ODE.
        # With W_MSE=3: m_se=0.12 → -0.043 (small; sc_1ph V2 benefit wins),
        #               m_se=0.25 → -0.188 (larger; pushes back from excess).
        m_se_d = float(self._last_act[1])
        m_se_q = float(self._last_act[2])
        r_mse = -W_MSE * (m_se_d**2 + m_se_q**2)

        return r_vdc_low + r_vdc_high + r_v2 + r_i2 + r_margin + r_recovery + r_mse

    def _get_obs(self) -> np.ndarray:
        """Build 17-dim observation vector."""
        V_dc   = self._x[0]
        V2_d   = self._x[1]
        V2_q   = self._x[2]
        V_dc_pu = np.clip(V_dc / VDC_NOM, 0.0, 1.5)
        V2_pu   = np.clip(np.hypot(V2_d, V2_q) / V2_PK, 0.0, 1.5)
        I_ld    = (2.0/3.0) * np.hypot(self._sc['P_load'], self._sc['Q_load']) \
                  / max(np.hypot(V2_d, V2_q), 1.0)
        I2_pu   = np.clip(I_ld / I2_NOM_PK, 0.0, 5.0)   # Fix #1: peak base

        dVdc_norm = np.clip(self._dVdc_dt / 10000.0, -1.0, 1.0)
        dV2_norm  = np.clip(self._dV2_dt  /  5000.0, -1.0, 1.0)

        t_f         = self._sc['t_fault']
        t_since_f   = max(0.0, self._t - t_f)
        t_since_norm = np.clip(t_since_f / 0.05, 0.0, 1.0)
        in_fault     = float(self._in_fault)

        fault_probs = self.msffn.predict(self._sc['sc_id'], t_since_f)

        # MSFFN noise injection (training only): simulates real classifier imperfection
        # Real MSFFN has ~97.8% accuracy → ~2% mis-classification → noisy probabilities.
        # Adding Gaussian noise + re-normalisation makes SAC robust to classification errors.
        if self.train_mode and MSFFN_NOISE_STD > 0:
            noise = self.rng.standard_normal(7).astype(np.float32) * MSFFN_NOISE_STD
            fault_probs = np.clip(fault_probs + noise, 0.0, 1.0)
            prob_sum = fault_probs.sum()
            if prob_sum > 1e-6:
                fault_probs = fault_probs / prob_sum

        obs = np.concatenate([
            [V_dc_pu, V2_pu, I2_pu, dVdc_norm, dV2_norm],  # 5
            fault_probs,                                      # 7
            [t_since_norm, in_fault],                        # 2
            self._last_act,                                   # 3
        ]).astype(np.float32)
        return obs

    def _msffn_fault_prob(self) -> float:
        """Probability of any non-normal fault (used for freq switch)."""
        t_f       = self._sc['t_fault']
        t_since_f = max(0.0, self._t - t_f)
        probs     = self.msffn.predict(self._sc['sc_id'], t_since_f)
        return float(1.0 - probs[0])   # 1 - P(normal)

    def render(self): pass


# ── Scenario loader ────────────────────────────────────────────────────────────

def load_scenarios(
    csv_path: Path,
    sc_ids: Optional[list] = None,
) -> list[dict]:
    """Load scenario table as list of dicts for HPTDirectEnv."""
    import pandas as pd
    T = pd.read_csv(csv_path)
    if sc_ids is not None:
        T = T[T.sc_id.isin(sc_ids)]
    return T.to_dict('records')


if __name__ == '__main__':
    import time
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    SCEN_CSV     = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'

    print('Loading scenarios...')
    scenarios = load_scenarios(SCEN_CSV)
    print(f'Loaded {len(scenarios)} scenarios')

    env = HPTDirectEnv(scenarios, seed=42)
    obs, _ = env.reset()
    print(f'Obs shape: {obs.shape}  Action shape: {env.action_space.shape}')
    print(f'Obs example: {obs[:5]}')

    # Quick performance test
    print('\nRunning 5 episodes with random actions...')
    for ep in range(5):
        obs, _ = env.reset()
        total_r = 0.0
        steps   = 0
        t0      = time.time()
        done    = False
        while not done:
            action = env.action_space.sample()
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            steps   += 1
            done = term or trunc
        dt = time.time() - t0
        print(f'  ep={ep+1}  steps={steps:3d}  reward={total_r:7.2f}  '
              f'VdcMin={info["V_dc_pu"]:.3f}  t={dt:.2f}s')
