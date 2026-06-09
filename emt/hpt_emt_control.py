"""
hpt_emt_control.py — SPWM controllers ported verbatim from the Simulink Stateflow
charts (Energy_VSC_SPWM / Regulation_VSC_SPWM), SAC直接调制 path.

These produce gate signals (0/1) for the EMT bridges each time step, replicating the
real switching control (carrier comparison, Vdc PI, protection-floor ladder, SAC直接调制
direct-modulation command, series dq inverse-Park phi9).
"""
from __future__ import annotations
import math

PI = math.pi

class EnergyCtrl:
    """Energy (shunt) VSC SPWM, SAC直接调制 (chart_24)."""
    def __init__(self, dt):
        self.dt = dt; self.ivdc = 0.0
    def gates(self, t, vdc, v2abc, i2_pu, t_fault, m_sh_cmd, mode=9):
        f1, fc = 50.0, 5000.0
        theta = 2*PI*f1*t
        carrier = 2*abs(2*(fc*t - math.floor(fc*t + 0.5))) - 1
        va, vb, vc = v2abc
        vll = math.sqrt(((va-vb)**2 + (vb-vc)**2 + (vc-va)**2)/3)
        vpu = vll/400.0
        ipu = i2_pu
        avdc = abs(vdc)
        evdc = (800.0 - avdc)/800.0
        self.ivdc = min(0.35, max(-0.35, self.ivdc + evdc*self.dt*350))
        m_pre9 = min(0.90, max(0.20, 0.68 + 0.30*evdc + 0.08*self.ivdc))
        if mode == 9:
            iff = 1.0 if t >= t_fault else 0.0
            m = iff*max(0.0, min(0.90, m_sh_cmd)) + (1-iff)*m_pre9
        else:
            m = m_pre9
        # protection-floor ladder (anchored to 800 V)
        if avdc > 920.0 or ipu > 2.0:  m = min(m, 0.25)
        if avdc > 1048.0 or ipu > 3.0: m = min(m, 0.12)
        if avdc < 780.0: m = max(m, 0.64)
        if avdc < 740.0: m = max(m, 0.78)
        if avdc < 700.0: m = max(m, 0.86)
        if avdc < 600.0: m = max(m, 0.90)
        m = min(0.92, max(0.20, m))
        refs = [m*math.sin(theta), m*math.sin(theta-2*PI/3), m*math.sin(theta+2*PI/3)]
        return [1 if r >= carrier else 0 for r in refs], m


class RegulationCtrl:
    """Regulation (series) VSC SPWM, SAC直接调制 (chart_47). Returns per-H-bridge gate."""
    def __init__(self, dt):
        self.dt = dt; self.ivac = 0.0
    def gates(self, t, vdc, v2abc, i2_pu, t_fault, m_se_d, m_se_q, mode=9):
        f1, fc = 50.0, 5000.0
        theta = 2*PI*f1*t + PI/6          # D1-FIX Δ-Y phase offset
        carrier = 2*abs(2*(fc*t - math.floor(fc*t + 0.5))) - 1
        va, vb, vc = v2abc
        vll = math.sqrt(((va-vb)**2 + (vb-vc)**2 + (vc-va)**2)/3)
        vpu = vll/400.0
        phi9 = 0.0
        if mode == 9:
            if vpu >= 0.20:
                d = max(-0.30, min(0.30, m_se_d)); q = max(-0.30, min(0.30, m_se_q))
                m = min(0.30, math.sqrt(d*d + q*q + 1e-12)); phi9 = math.atan2(q, d + 1e-9)
            else:
                ev_d = max(0.0, 1.0 - vpu); m = 0.030 + 0.55*ev_d
                if abs(vdc) < 720.0: m = min(m, 0.06)
                if abs(vdc) > 960.0: m = min(m, 0.04)
                if i2_pu > 2.0: m = min(m, 0.02)
        else:
            m = 0.0
        m = min(0.30, max(0.0, m))
        refs = [m*math.sin(theta+phi9), m*math.sin(theta-2*PI/3+phi9), m*math.sin(theta+2*PI/3+phi9)]
        # each phase = single-phase H-bridge: leg1 gate = ref>=carrier, leg2 = complement
        return [1 if r >= carrier else 0 for r in refs], m
