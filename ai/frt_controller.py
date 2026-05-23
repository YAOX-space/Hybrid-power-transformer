"""
frt_controller.py  — Method E
Fault Ride-Through controller with intelligent energy redistribution.

This controller activates AFTER fault detection (Method C) and localization
(Method D). It redistributes power among healthy ports to:
  1. Maintain DC bus voltage stability
  2. Preserve maximum possible load supply
  3. Recover within <5ms (matching the project spec)

Approach:
  - Rule-based fast response (sub-ms) for immediate current limiting
  - RL policy (offline trained) for optimal multi-objective redistribution
  - Graceful degradation: if RL not available, fall back to rule-based

Compatible with:
  - Python real-time loop (for co-simulation)
  - MATLAB Simulink (via MATLAB Function block calling Python or compiled ONNX)

Usage:
  python frt_controller.py --demo               # simulated FRT event demo
  python frt_controller.py --train-rl           # train RL policy offline
"""

import argparse
import time
from pathlib import Path
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import torch
import torch.nn as nn

from data_loader import MODEL_DIR, PROC_DIR

CKPT_FRT = MODEL_DIR / 'frt_policy.pt'

# ── System constants (must match parameters.m) ─────────────────────────────────
V_DC_NOM    = 800.0    # Nominal DC bus voltage (V)
V_SEC_NOM   = 400.0    # Nominal secondary voltage (V)
I_MAX_PU    = 1.0      # Max converter current (pu)
V_SE_MAX_PU = 1.0      # Max series voltage injection (pu)

# ── FRT Response timing ─────────────────────────────────────────────────────────
T_FAST_MS   = 0.5      # Fast rule-based response: <0.5ms (immediate)
T_RL_MS     = 5.0      # RL optimal redistribution: <5ms
T_RECOVERY  = 100.0    # Max allowed recovery time (ms)


# ══════════════════════════════════════════════════════════════════════════════
class FaultType(IntEnum):
    NORMAL      = 0
    IGBT_OC_SH  = 1
    IGBT_OC_SE  = 2
    CAP_FAULT   = 3
    SC_1PH      = 4
    SC_3PH      = 5
    CASCADE     = 6


@dataclass
class SystemState:
    """Normalized system state (all in pu unless noted)."""
    V1_pu:      float = 1.0
    V2_pu:      float = 1.0
    Vdc_pu:     float = 1.0
    Ish_d_pu:   float = 0.0
    Ish_q_pu:   float = 0.0
    Ise_d_pu:   float = 0.0
    Ise_q_pu:   float = 0.0
    P1_pu:      float = 0.8
    Q1_pu:      float = 0.1
    fault_type: int   = 0
    fault_severity: float = 0.0   # 0=none, 1=severe
    t_since_fault_ms: float = 0.0


@dataclass
class FRTCommand:
    """Control commands issued during fault ride-through."""
    Vse_d_pu:    float = 0.0   # Series voltage d-component
    Vse_q_pu:    float = 0.0   # Series voltage q-component
    Ish_d_pu:    float = 0.0   # Shunt converter d-current
    Ish_q_pu:    float = 0.0   # Shunt converter q-current
    mode:        int   = 1     # 1=voltage_reg, 2=reactive, 3=power_flow
    gate_block:  bool  = False # True = block faulted converter gates
    load_shed:   float = 0.0   # Load shedding factor (0=none, 1=full shed)


# ══════════════════════════════════════════════════════════════════════════════
class FRTPolicy(nn.Module):
    """
    Offline-trained neural policy for fault ride-through energy redistribution.
    Input:  11-dim state vector
    Output: 5-dim continuous action [Vse_d, Vse_q, Ish_d, Ish_q, load_shed]
    """

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(11, 256), nn.ReLU(),
            nn.Linear(256, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, 5),
            nn.Tanh(),   # All outputs in (-1, 1), scaled by action bounds
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ══════════════════════════════════════════════════════════════════════════════
class FaultRideThroughController:
    """
    Two-stage FRT controller:
    Stage 1 (immediate, <0.5ms): Rule-based — gate blocking, current limiting
    Stage 2 (optimal,  <5ms):   RL policy — energy redistribution

    This architecture ensures hard real-time safety while optimizing recovery.
    """

    def __init__(self, use_rl: bool = True, device: str = 'cpu'):
        self.use_rl = use_rl and CKPT_FRT.exists()
        self.device = device

        if self.use_rl:
            self.policy = FRTPolicy().to(device)
            ckpt = torch.load(CKPT_FRT, map_location=device)
            self.policy.load_state_dict(ckpt['policy_state'])
            self.policy.eval()
            print('FRT: RL policy loaded')
        else:
            self.policy = None
            print('FRT: Rule-based mode (RL policy not available)')

        self.fault_active    = False
        self.fault_type      = FaultType.NORMAL
        self.fault_onset_ms  = 0.0
        self.pre_fault_state: SystemState = None

    # ── PUBLIC API ────────────────────────────────────────────────────────────

    def on_fault_detected(self, fault_type: int, state: SystemState,
                          t_ms: float):
        """
        Called immediately when LSTM detector triggers.
        Stores pre-fault state for recovery reference.
        """
        if not self.fault_active:
            self.fault_active   = True
            self.fault_type     = FaultType(fault_type)
            self.fault_onset_ms = t_ms
            self.pre_fault_state = state
            print(f'[FRT] Fault detected at t={t_ms:.2f}ms: {self.fault_type.name}')

    def on_fault_cleared(self, t_ms: float):
        """Called when fault clears (external breaker or auto-recovery)."""
        if self.fault_active:
            duration = t_ms - self.fault_onset_ms
            print(f'[FRT] Fault cleared at t={t_ms:.2f}ms (duration={duration:.1f}ms)')
            self.fault_active = False
            self.fault_type   = FaultType.NORMAL

    def compute_frt_command(self, state: SystemState,
                            t_ms: float) -> FRTCommand:
        """
        Main control entry point. Returns FRT commands for the given state.
        Called every control cycle (50µs = 0.05ms).
        """
        if not self.fault_active:
            return FRTCommand()   # No fault — pass through to normal controller

        t_since = t_ms - self.fault_onset_ms

        # Stage 1: Immediate rule-based response (0 – T_FAST_MS)
        cmd = self._rule_based_response(state, t_since)

        # Stage 2: RL optimal redistribution (after T_FAST_MS)
        if self.use_rl and t_since >= T_FAST_MS:
            cmd = self._rl_response(state, t_since, cmd)

        return cmd

    # ── STAGE 1: RULE-BASED ───────────────────────────────────────────────────

    def _rule_based_response(self, s: SystemState,
                             t_since_ms: float) -> FRTCommand:
        """
        Fast deterministic response based on fault type.
        Executes within one control cycle (<0.05ms latency).
        """
        cmd = FRTCommand()

        if self.fault_type == FaultType.IGBT_OC_SH:
            # Shunt converter IGBT fault:
            # → Block VSC_sh gates (prevent circulating current)
            # → Transfer DC bus maintenance to VSC_se modulation
            cmd.gate_block = True
            cmd.Ish_d_pu   = 0.0   # Force shunt to zero
            cmd.Ish_q_pu   = 0.0
            # VSC_se picks up DC voltage regulation (emergency mode)
            cmd.Vse_d_pu   = np.clip((1.0 - s.Vdc_pu) * 2.0, -0.5, 0.5)
            cmd.mode       = 1

        elif self.fault_type == FaultType.IGBT_OC_SE:
            # Series converter IGBT fault:
            # → Bypass the faulted phase (set Vse → 0 for that phase)
            # → Maintain regulation via remaining healthy phases
            cmd.Vse_d_pu   = 0.0
            cmd.Vse_q_pu   = 0.0
            cmd.Ish_d_pu   = np.clip((1.0 - s.Vdc_pu) * 1.5, -I_MAX_PU, I_MAX_PU)
            cmd.mode       = 2  # Switch to reactive compensation

        elif self.fault_type == FaultType.CAP_FAULT:
            # DC capacitor fault: V_dc drops → immediate over-modulation risk
            # → Reduce VSC_se output (less reactive power demand)
            # → VSC_sh absorbs remaining power to maintain bus
            cmd.Vse_d_pu   = np.clip(s.Ise_d_pu * 0.5, -0.3, 0.3)
            cmd.Vse_q_pu   = np.clip(s.Ise_q_pu * 0.5, -0.3, 0.3)
            cmd.Ish_d_pu   = np.clip((1.0 - s.Vdc_pu) * 3.0, -I_MAX_PU, I_MAX_PU)
            cmd.mode       = 1

        elif self.fault_type in (FaultType.SC_1PH, FaultType.SC_3PH):
            # AC short circuit: inject reactive current for voltage support
            # Based on grid code requirement (similar to Jia Ke's FRT method):
            # Δiq = K * (1 - V_pcc) for voltage dip support
            V_dip = 1.0 - s.V2_pu
            K_support = 2.0
            cmd.Ish_q_pu   = np.clip(-K_support * V_dip, -I_MAX_PU, I_MAX_PU)
            cmd.Ish_d_pu   = np.sqrt(max(0, I_MAX_PU**2 - cmd.Ish_q_pu**2))
            cmd.Vse_d_pu   = np.clip((1.0 - s.Vdc_pu) * 1.0, -0.5, 0.5)
            cmd.mode       = 2  # Reactive compensation priority

        elif self.fault_type == FaultType.CASCADE:
            # Cascade fault: conservative load shedding + DC protection
            cmd.load_shed  = min(0.5, (s.Vdc_pu - 1.3) * 2.0) if s.Vdc_pu > 1.1 else 0.0
            cmd.Vse_d_pu   = 0.0
            cmd.Vse_q_pu   = 0.0
            cmd.Ish_d_pu   = np.clip((1.0 - s.Vdc_pu) * 2.0, -I_MAX_PU, I_MAX_PU)
            cmd.mode       = 1

        return cmd

    # ── STAGE 2: RL OPTIMAL ───────────────────────────────────────────────────

    def _rl_response(self, s: SystemState, t_since_ms: float,
                     rule_cmd: FRTCommand) -> FRTCommand:
        """
        RL policy refines the rule-based command for optimal redistribution.
        State vector: [V1, V2, Vdc, Ish_d, Ish_q, Ise_d, Ise_q, P1, Q1,
                       fault_type_normalized, t_since_normalized]
        """
        state_vec = np.array([
            s.V1_pu, s.V2_pu, s.Vdc_pu,
            s.Ish_d_pu, s.Ish_q_pu, s.Ise_d_pu, s.Ise_q_pu,
            s.P1_pu, s.Q1_pu,
            s.fault_type / 6.0,         # normalize fault type
            min(t_since_ms / T_RECOVERY, 1.0),  # normalize time
        ], dtype=np.float32)

        x = torch.from_numpy(state_vec[np.newaxis]).to(self.device)
        with torch.no_grad():
            action = self.policy(x)[0].cpu().numpy()  # (-1, 1) range

        # Scale to physical limits
        cmd = FRTCommand(
            Vse_d_pu   = float(action[0] * V_SE_MAX_PU),
            Vse_q_pu   = float(action[1] * V_SE_MAX_PU),
            Ish_d_pu   = float(action[2] * I_MAX_PU),
            Ish_q_pu   = float(action[3] * I_MAX_PU),
            load_shed  = float((action[4] + 1) / 2),   # map (-1,1) → (0,1)
            gate_block = rule_cmd.gate_block,           # keep safety from Stage 1
            mode       = rule_cmd.mode,
        )

        # Hard safety: current magnitude constraint
        I_mag = np.sqrt(cmd.Ish_d_pu**2 + cmd.Ish_q_pu**2)
        if I_mag > I_MAX_PU:
            cmd.Ish_d_pu /= I_mag
            cmd.Ish_q_pu /= I_mag

        V_mag = np.sqrt(cmd.Vse_d_pu**2 + cmd.Vse_q_pu**2)
        if V_mag > V_SE_MAX_PU:
            cmd.Vse_d_pu /= V_mag
            cmd.Vse_q_pu /= V_mag

        return cmd


# ══════════════════════════════════════════════════════════════════════════════
def train_rl_policy(n_episodes: int = 5000):
    """
    Trains the FRT RL policy using offline experience from simulated fault events.
    Uses a simple Actor-Critic approach with simulated environment transitions.

    For full MATLAB-integrated training, see drl_trainer.m.
    This offline variant can train on pre-collected .mat data.
    """
    policy = FRTPolicy()
    optimizer = torch.optim.Adam(policy.parameters(), lr=3e-4)

    print(f'Training FRT policy on {n_episodes} simulated episodes...')
    losses = []

    for ep in range(n_episodes):
        # Sample a random fault scenario
        fault = np.random.randint(1, 7)
        severity = np.random.uniform(0.3, 1.0)

        # Simulate episode
        states, rewards, actions = [], [], []
        s = SystemState(
            V1_pu=np.random.uniform(0.9, 1.1),
            V2_pu=1.0 - severity * 0.3,   # Voltage dip
            Vdc_pu=1.0 + (np.random.rand() - 0.5) * 0.2,
            fault_type=fault,
            fault_severity=severity,
        )

        for step in range(100):  # 100 steps × 50µs = 5ms FRT window
            t_ms = step * 0.05

            sv = np.array([s.V1_pu, s.V2_pu, s.Vdc_pu,
                           s.Ish_d_pu, s.Ish_q_pu, s.Ise_d_pu, s.Ise_q_pu,
                           s.P1_pu, s.Q1_pu,
                           s.fault_type/6, min(t_ms/T_RECOVERY, 1.0)],
                          dtype=np.float32)

            x = torch.from_numpy(sv[np.newaxis])
            a = policy(x)[0]
            actions.append(a)

            # Reward: voltage recovery + DC stability + no load shed
            V2_err  = abs(s.V2_pu - 1.0)
            Vdc_err = abs(s.Vdc_pu - 1.0)
            load_shed = float((a[4].item() + 1) / 2)
            r = -5*V2_err**2 - 3*Vdc_err**2 - 2*load_shed**2 + 0.1
            rewards.append(r)

            # Simplified state transition (rule-of-thumb physics)
            Vse_d = a[0].item()
            Ish_d = a[2].item()
            s.V2_pu   = np.clip(s.V2_pu + 0.02*Vse_d - 0.01*severity, 0.5, 1.2)
            s.Vdc_pu  = np.clip(s.Vdc_pu + 0.03*Ish_d - 0.005, 0.7, 1.4)

        # Compute discounted returns
        gamma = 0.99
        G = 0.0
        returns = []
        for r in reversed(rewards):
            G = r + gamma * G
            returns.insert(0, G)

        # Policy gradient (REINFORCE)
        returns_t = torch.tensor(returns, dtype=torch.float32)
        returns_t = (returns_t - returns_t.mean()) / (returns_t.std() + 1e-8)

        loss = 0.0
        for a, G_t in zip(actions, returns_t):
            loss = loss - G_t * a.mean()   # maximize expected return

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
        optimizer.step()

        losses.append(float(loss))
        if ep % 500 == 0:
            print(f'  Episode {ep:5d}  Loss: {np.mean(losses[-50:]):.4f}  '
                  f'Last return: {sum(rewards):.2f}')

    torch.save({'policy_state': policy.state_dict()}, CKPT_FRT)
    print(f'\nFRT policy saved to: {CKPT_FRT}')


# ══════════════════════════════════════════════════════════════════════════════
def demo_frt():
    """Demonstrates FRT controller response to simulated fault events."""
    print('=== FRT Controller Demo ===\n')

    # Try to load RL policy, fall back to rule-based
    ctrl = FaultRideThroughController(use_rl=CKPT_FRT.exists())

    # Simulate a 3-phase short circuit event
    s = SystemState(V1_pu=1.0, V2_pu=0.6, Vdc_pu=1.05,
                    Ish_d_pu=0.5, P1_pu=0.8, Q1_pu=0.1)

    print('Fault event: 3-phase AC short circuit (V2 = 0.6 pu)')
    ctrl.on_fault_detected(FaultType.SC_3PH, s, t_ms=1000.0)

    print(f'\n{"t_ms":>8}  {"V2_pu":>6}  {"Vdc_pu":>7}  {"Ish_q":>6}  '
          f'{"Vse_d":>6}  {"shed":>5}')
    print('-' * 50)

    for step in range(200):  # 10ms at 50µs steps
        t_ms  = 1000.0 + step * 0.05
        cmd   = ctrl.compute_frt_command(s, t_ms)

        # Simplified state update
        s.V2_pu   = np.clip(s.V2_pu  + 0.005*abs(cmd.Ish_q_pu) + 0.002, 0.5, 1.05)
        s.Vdc_pu  = np.clip(s.Vdc_pu + 0.002*cmd.Ish_d_pu - 0.001, 0.8, 1.3)

        if step % 20 == 0:
            print(f'{t_ms:>8.2f}  {s.V2_pu:>6.3f}  {s.Vdc_pu:>7.3f}  '
                  f'{cmd.Ish_q_pu:>6.3f}  {cmd.Vse_d_pu:>6.3f}  {cmd.load_shed:>5.3f}')

        if s.V2_pu > 0.90:
            ctrl.on_fault_cleared(t_ms)
            print(f'\nVoltage recovered to {s.V2_pu:.3f} pu at t={t_ms:.2f}ms')
            print(f'Recovery time: {t_ms-1000.0:.1f} ms')
            break


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HPT Fault Ride-Through Controller')
    parser.add_argument('--demo',     action='store_true', help='Run demo')
    parser.add_argument('--train-rl', action='store_true', help='Train RL policy')
    parser.add_argument('--episodes', type=int, default=5000)
    args = parser.parse_args()

    if args.demo:
        demo_frt()
    elif args.train_rl:
        train_rl_policy(n_episodes=args.episodes)
    else:
        parser.print_help()
