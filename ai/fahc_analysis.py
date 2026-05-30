"""
fahc_analysis.py  —  Fault-Aware Hierarchical Controller (FAHC) analysis
=========================================================================
FAHC separates control into three levels:

  Level 0  Fault detector         (RF/MSFFN, already ≥95.68 %)
  Level 1  Severity estimator     (regression: VdcMin deficit, I2 excess)
  Level 2  Strategy selector      (3 pre-tuned control strategies)
  Level 3  Safety shield          (hard clamp on references)

Strategy table
--------------
  Strategy 0  (sc_id 0,1,2 — normal/IGBT faults)
      Vdc_ref = 800 V   V2_ref = 400 V   I_lim = 3.0 pu
      → unchanged dq double-loop; already passes 94–100 %

  Strategy 1  (sc_id 3 — capacitor fault)
      Vdc_ref = 760 V   V2_ref = 400 V   I_lim = 2.8 pu
      → mild energy-save mode; reduces DC drain; tighter current limit

  Strategy 2  (sc_id 4 — single-phase short-circuit)
      Vdc_ref = 740 V   V2_ref = 380 V   I_lim = 2.8 pu
      → moderate energy-save + allow V2 to dip 5 % less aggressively regulated

  Strategy 3  (sc_id 5,6 — three-phase SC / cascade)
      Vdc_ref = 720 V   V2_ref = 360 V   I_lim = 2.5 pu
      → maximum energy-save; 134 J extra headroom in DC link

Physics rationale for the thresholds
-------------------------------------
  ΔE(800→720) = ½ × 2200 µF × (800² − 720²) = 134 J
  Approximate VdcMin improvement ≈ ΔE / (C × Vdc) = 134 / (2200e-6 × 800) ≈ 76 V ≈ 0.095 pu

  If current VdcMin ∈ [0.65, 0.75], the extra 0.095 pu may push it above the 0.75 limit.
  If VdcMin < 0.55, the deficit is too large for reference adjustment alone.

Usage
-----
  python fahc_analysis.py --analyze  --dq-dir data/raw_switching_hpt_v2_fixed_dq
  python fahc_analysis.py --train-severity --dq-dir data/raw_switching_hpt_v2_fixed_dq
  python fahc_analysis.py --write-strategy-config
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam
from sklearn.metrics import mean_absolute_error, r2_score

PROJECT_ROOT   = Path(__file__).resolve().parent.parent
SCENARIO_TABLE = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
RESULTS_DIR    = PROJECT_ROOT / 'results'
MODEL_DIR      = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# ── Strategy definitions ───────────────────────────────────────────────────────

STRATEGIES = {
    0: {'name': 'standard',      'Vdc_ref': 800, 'V2_ref': 400, 'I_lim': 3.0,
        'sc_ids': [0, 1, 2],
        'rationale': 'Mild/no fault: dq double-loop at nominal setpoints'},
    1: {'name': 'energy_save_1', 'Vdc_ref': 760, 'V2_ref': 400, 'I_lim': 2.8,
        'sc_ids': [3],
        'rationale': 'Cap fault: mild DC-link energy save + tighter I limit'},
    2: {'name': 'energy_save_2', 'Vdc_ref': 740, 'V2_ref': 380, 'I_lim': 2.8,
        'sc_ids': [4],
        'rationale': 'Single-phase SC: moderate energy save + V2 regulation relaxed'},
    3: {'name': 'energy_save_3', 'Vdc_ref': 720, 'V2_ref': 360, 'I_lim': 2.5,
        'sc_ids': [5, 6],
        'rationale': '3-ph SC / cascade: max energy save; ΔE=134 J headroom'},
}

SC_ID_TO_STRATEGY = {sc: sid for sid, s in STRATEGIES.items() for sc in s['sc_ids']}

# Physics estimate: ΔVdcMin per strategy vs standard
# Formula: 0.5×C×(Vdc_nom²−Vref²) / (C×Vdc_nom²) = 0.5×(1−(Vref/Vdc_nom)²)
PHYSICS_DVDC_PU = {
    0: 0.000,
    1: 0.049,   # 0.5×(1−(760/800)²) = 0.049 pu
    2: 0.072,   # 0.5×(1−(740/800)²) = 0.072 pu
    3: 0.095,   # 0.5×(1−(720/800)²) = 0.095 pu
}

VDC_NOM = 800.0
C_DC    = 2200e-6


def _energy_save(v_ref_new: float) -> float:
    return 0.5 * C_DC * (VDC_NOM ** 2 - v_ref_new ** 2)


def _dvdc_improvement(v_ref_new: float) -> float:
    return _energy_save(v_ref_new) / (C_DC * VDC_NOM * VDC_NOM)


# ── Load dq metrics ────────────────────────────────────────────────────────────

def load_dq_metrics(dq_dir: Path) -> list[dict]:
    try:
        from lvrt_metrics import metrics_for_file
    except ImportError as e:
        raise ImportError('lvrt_metrics.py must be importable') from e

    files = sorted(dq_dir.glob('*.mat'))
    if not files:
        raise FileNotFoundError(f'No .mat files in {dq_dir}')
    return [metrics_for_file(p) for p in files]


def scenario_obs(row: pd.Series) -> np.ndarray:
    return np.array([
        row.sc_id / 6.0,
        row.P_load / 400e3,
        row.Q_load / 250e3,
        row.t_fault / 0.05,
        row.fault_variant / 6.0,
        float(row.fault_mag),
        float(row.fault_resistance),
        float(row.ground_resistance),
    ], dtype=np.float32)


# ── Failure analysis ───────────────────────────────────────────────────────────

def analyze_failures(dq_dir: Path) -> None:
    metrics = load_dq_metrics(dq_dir)
    table   = pd.read_csv(SCENARIO_TABLE)

    by_sc: dict[int, dict] = {}
    for m, row in zip(metrics, table.itertuples()):
        sc = int(m['sc_id'])
        if sc not in by_sc:
            by_sc[sc] = {'pass': 0, 'vdc_low': 0, 'i2_high': 0, 'recovery': 0,
                         'vdc_min_all': [], 'i2_max_all': []}
        rec = by_sc[sc]
        vdc_min = float(m['vdc_min_pu_post_fault'])
        i2_max  = float(m['i2_peak_pu_post_fault'])
        rec['vdc_min_all'].append(vdc_min)
        rec['i2_max_all'].append(i2_max)

        if m['lvrt_pass_basic']:
            rec['pass'] += 1
        elif vdc_min < 0.75:
            rec['vdc_low'] += 1
        elif i2_max > 3.0:
            rec['i2_high'] += 1
        else:
            rec['recovery'] += 1

    sc_names = {0:'normal', 1:'igbt_oc_sh', 2:'igbt_oc_se', 3:'cap_fault',
                4:'sc_1ph', 5:'sc_3ph', 6:'cascade'}
    sc_names = {k: v for k, v in sc_names.items()}
    for sid in by_sc:
        if sid not in sc_names:
            sc_names[sid] = f'sc_{sid}'

    print('=' * 70)
    print('FAHC Failure Analysis  (dq double-loop, 350 fixed scenarios)')
    print('=' * 70)
    print(f'{"sc_id":5s} {"name":14s} {"pass":5s} {"vdc_low":7s} {"i2_high":7s} '
          f'{"VdcMin_mean":10s} {"strategy":8s} {"ΔVdcMin_est":11s}')
    print('-' * 70)

    total_pass = 0
    total_estimated_pass = 0

    for sc in sorted(by_sc):
        rec  = by_sc[sc]
        n    = rec['pass'] + rec['vdc_low'] + rec['i2_high'] + rec['recovery']
        strat_id = SC_ID_TO_STRATEGY.get(sc, 0)
        strat    = STRATEGIES[strat_id]
        dv_est   = PHYSICS_DVDC_PU[strat_id]
        vdc_mean = np.mean(rec['vdc_min_all'])

        # Count estimated recoverable: VdcMin in [0.75-dv_est, 0.75)
        recoverable = sum(
            1 for v in rec['vdc_min_all']
            if (0.75 - dv_est) <= v < 0.75 and v >= 0.50
        )
        est_pass = rec['pass'] + recoverable

        print(f'{sc:5d} {sc_names[sc]:14s} {rec["pass"]:5d} {rec["vdc_low"]:7d} '
              f'{rec["i2_high"]:7d} {vdc_mean:10.3f} '
              f'{strat_id:8d} {dv_est:+.3f} pu  '
              f'(recoverable ≈{recoverable})')
        total_pass += rec['pass']
        total_estimated_pass += est_pass

    total = sum(rec['pass'] + rec['vdc_low'] + rec['i2_high'] + rec['recovery']
                for rec in by_sc.values())
    print('-' * 70)
    print(f'Total  dq pass rate    : {total_pass}/{total} = {100*total_pass/total:.1f}%')
    print(f'FAHC estimated pass    : {total_estimated_pass}/{total} = '
          f'{100*total_estimated_pass/total:.1f}%  '
          f'(+{100*(total_estimated_pass-total_pass)/total:.1f} pp)')
    print()
    print('Note: estimates assume physics-based energy savings are achievable.')
    print('Actual improvement requires Simulink validation with Strategy 1-3 modes.')


# ── Severity estimator ─────────────────────────────────────────────────────────

class SeverityEstimator(nn.Module):
    """Predict VdcMin (pu) and I2Max (pu) from scenario parameters.

    Enables FAHC to anticipate severity before the fault occurs and pre-select
    the appropriate control strategy.
    """

    def __init__(self, obs_dim: int = 8, hidden: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.GELU(),
            nn.Linear(hidden, hidden),  nn.GELU(),
            nn.Linear(hidden, 64),      nn.GELU(),
            nn.Linear(64, 2),           # [VdcMin_pu, I2Max_pu]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def train_severity(dq_dir: Path, epochs: int = 300) -> Path:
    """Train severity estimator on existing dq simulation metrics."""
    metrics = load_dq_metrics(dq_dir)
    table   = pd.read_csv(SCENARIO_TABLE)
    assert len(metrics) == len(table), 'Metrics/table length mismatch'

    obs = np.stack([scenario_obs(row) for _, row in table.iterrows()])
    tgt = np.array([
        [float(m['vdc_min_pu_post_fault']), float(m['i2_peak_pu_post_fault'])]
        for m in metrics
    ], dtype=np.float32)

    obs_t = torch.tensor(obs, dtype=torch.float32)
    tgt_t = torch.tensor(tgt, dtype=torch.float32)

    # 80/20 split
    n    = len(obs)
    idx  = np.random.default_rng(42).permutation(n)
    n_tr = int(0.8 * n)
    tr, va = idx[:n_tr], idx[n_tr:]

    model = SeverityEstimator()
    opt   = Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    best_val = float('inf')
    ckpt  = MODEL_DIR / 'fahc_severity_estimator.pt'

    for epoch in range(1, epochs + 1):
        model.train()
        pred = model(obs_t[tr])
        loss = nn.functional.mse_loss(pred, tgt_t[tr])
        opt.zero_grad(); loss.backward(); opt.step()

        if epoch % 50 == 0:
            model.eval()
            with torch.no_grad():
                val_pred = model(obs_t[va]).numpy()
            val_loss = mean_absolute_error(tgt[va], val_pred)
            if val_loss < best_val:
                best_val = val_loss
                torch.save({'model_state': model.state_dict()}, ckpt)
            print(f'  epoch={epoch:4d}  val_MAE={val_loss:.4f}')

    model.eval()
    with torch.no_grad():
        all_pred = model(obs_t).numpy()
    mae_vdc = mean_absolute_error(tgt[:, 0], all_pred[:, 0])
    mae_i2  = mean_absolute_error(tgt[:, 1], all_pred[:, 1])
    r2_vdc  = r2_score(tgt[:, 0], all_pred[:, 0])
    r2_i2   = r2_score(tgt[:, 1], all_pred[:, 1])
    print(f'\nSeverity estimator:')
    print(f'  VdcMin MAE={mae_vdc:.4f} pu   R²={r2_vdc:.3f}')
    print(f'  I2Max  MAE={mae_i2:.4f} pu   R²={r2_i2:.3f}')
    print(f'  Saved → {ckpt}')
    return ckpt


# ── Strategy config output ─────────────────────────────────────────────────────

def write_strategy_config() -> None:
    """Write the FAHC strategy table as JSON for MATLAB to consume."""
    config = {
        'description': 'FAHC strategy table — Simulink ControllerMode=7',
        'strategies': {}
    }
    for sid, s in STRATEGIES.items():
        config['strategies'][str(sid)] = {
            'name':       s['name'],
            'Vdc_ref_V':  s['Vdc_ref'],
            'V2_ref_V':   s['V2_ref'],
            'I_lim_pu':   s['I_lim'],
            'sc_ids':     s['sc_ids'],
            'rationale':  s['rationale'],
            'energy_save_J': round(_energy_save(s['Vdc_ref']), 1),
            'dvdc_est_pu':   round(_dvdc_improvement(s['Vdc_ref']), 4),
        }
    config['sc_id_to_strategy'] = SC_ID_TO_STRATEGY

    out = RESULTS_DIR / 'fahc_strategy_config.json'
    out.write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(f'Strategy config written → {out}')

    print('\nFAHC Strategy Table:')
    print(f'{"sc_id":6s} {"strategy":10s} {"Vdc_ref":8s} {"V2_ref":7s} {"I_lim":6s} '
          f'{"ΔE(J)":7s} {"ΔVdcMin_est":11s}')
    for sid, s in STRATEGIES.items():
        de  = _energy_save(s['Vdc_ref'])
        dv  = _dvdc_improvement(s['Vdc_ref'])
        ids = str(s['sc_ids'])
        print(f'{ids:6s} {s["name"]:15s} {s["Vdc_ref"]:8d} {s["V2_ref"]:7d} '
              f'{s["I_lim"]:6.1f} {de:7.1f} {dv:+.4f} pu')


# ── Full FAHC simulation harness ───────────────────────────────────────────────

def simulate_fahc(n_scenarios: int = 350) -> None:
    """Run all 350 scenarios with FAHC strategy selection.

    Requires Simulink ControllerMode=7 (FAHC mode) to be implemented in
    hpt_switching_model.slx, which reads HPT_FAHC_STRATEGY_ID env variable.

    Expected improvement:
      Strategy-1 on sc_id=3 (cap_fault):   +8-15 pp above dq's ~52 %
      Strategy-2 on sc_id=4 (sc_1ph):      +10-18 pp above dq's ~54 %
      Strategy-3 on sc_id=5,6 (sc_3ph):    +12-20 pp above dq's ~48 %
      Overall:    ~70-76 % LVRT pass rate   (+6-12 pp above dq's 64 %)
    """
    import os, subprocess

    table   = pd.read_csv(SCENARIO_TABLE).head(n_scenarios)
    out_dir = PROJECT_ROOT / 'data' / 'fahc_eval_rollouts'
    out_dir.mkdir(parents=True, exist_ok=True)

    strategy_ids = [SC_ID_TO_STRATEGY.get(int(row.sc_id), 0)
                    for _, row in table.iterrows()]

    strategy_table = pd.DataFrame({
        'rollout_id':   np.arange(1, len(table) + 1),
        'scenario_row': np.arange(1, len(table) + 1),
        'strategy_id':  strategy_ids,
    })
    strategy_table.to_csv(out_dir / 'fahc_strategies.csv', index=False)

    env = os.environ.copy()
    env['HPT_SCENARIO_TABLE']        = 'scenario_table_hpt_v2.csv'
    env['HPT_FAHC_STRATEGY_TABLE']   = str(out_dir / 'fahc_strategies.csv').replace('\\', '/')
    env['HPT_SWITCHING_OUT_DIR']     = str(out_dir).replace('\\', '/')
    env['HPT_CONTROLLER_MODE']       = '7'

    cmd = ['matlab', '-batch',
           "cd('E:/research_space/Hybrid-power-transformer/data_collection');"
           "run('run_switching_scenarios.m');"]

    print(f'Launching FAHC Simulink batch ({len(table)} scenarios) ...')
    cp = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                        capture_output=True, text=True,
                        timeout=max(180, 90 * len(table)))
    if cp.returncode != 0:
        raise RuntimeError(f'MATLAB FAHC batch failed:\n{cp.stdout}\n{cp.stderr}')

    from lvrt_metrics import metrics_for_file
    mat_files = sorted(out_dir.glob('*.mat'))
    metrics_list = [metrics_for_file(p) for p in mat_files]
    pass_rate = 100 * sum(m['lvrt_pass_basic'] for m in metrics_list) / len(metrics_list)

    by_sc: dict[int, list] = {}
    for m in metrics_list:
        by_sc.setdefault(int(m['sc_id']), []).append(m['lvrt_pass_basic'])

    print(f'\nFAHC Results ({len(metrics_list)} scenarios):')
    print(f'  Overall LVRT pass: {pass_rate:.2f}%')
    for sc in sorted(by_sc):
        g = by_sc[sc]
        print(f'  sc_id={sc}  {100*sum(g)/len(g):.1f}%  ({sum(g)}/{len(g)})')

    result = {
        'controller': 'FAHC',
        'n_scenarios': len(metrics_list),
        'pass_rate_pct': round(pass_rate, 2),
        'by_sc_id': {str(k): round(100*sum(v)/len(v), 1) for k, v in by_sc.items()},
        'strategies_used': dict(pd.Series(strategy_ids).value_counts().to_dict()),
    }
    out_json = RESULTS_DIR / 'fahc_eval_result.json'
    out_json.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Result saved → {out_json}')


# ── ET-PIRC-inspired adaptive FAHC threshold ──────────────────────────────────
#
# Concept adapted from Lai et al. IEEE TPEL 2026 (ET-PIRC):
#   The ET-PIRC controller dynamically adjusts K_ET based on tracking error:
#     K_ET(t) = B / (1 + ‖e_d(t)‖)
#   When error is large, K_ET → 0 (PI dominates); when error is small, K_ET → 0.5
#   (PI and RC contribute equally).
#
# For FAHC, we adapt this idea to strategy selection:
#   - Instead of a fixed fault-class → strategy mapping,
#   - Monitor the Vdc error rate (dVdc/dt) and secondary voltage deviation
#   - When error exceeds a trigger threshold A×E_steady, escalate strategy
#   - When error resolves, de-escalate (de-escalation hysteresis to avoid chatter)
#
# This means: even a mis-classified fault can recover via dynamic escalation.
# Reference: ET-PIRC eqs. (26)–(29), adapted to voltage/energy control domain.

class ETFAHCController:
    """Event-Triggered Fault-Aware Hierarchical Controller.

    Augments the static FAHC strategy table with a real-time event-triggered
    escalation mechanism inspired by the ET-PIRC paper (Lai et al. 2026).

    The controller monitors two error signals:
      e_vdc(t) = (Vdc_ref − Vdc) / Vdc_ref     (DC-link relative error)
      e_v2(t)  = (V2_ref − V2_rms) / V2_ref     (secondary voltage relative error)

    Strategy escalation trigger (eq. 28 analogue):
      Trigger when: |e_vdc(t)| > A × e_steady_vdc  OR |e_v2(t)| > A × e_steady_v2
      where A = 3.0 (threshold factor, ET-PIRC recommended range 2–4)

    Dynamic strategy level update (eq. 29 analogue):
      strategy_level(t) = base_level + Δ_escalate
      where Δ_escalate ∈ {0, 1} and decays by 1 after n_min_interval steps without re-trigger.
    """

    # ET-PIRC-adapted constants
    A_TRIGGER   = 3.0      # Trigger threshold factor (A in eq. 28)
    B_SCALE     = 0.5      # De-escalation scale factor (B in eq. 29)
    N_MIN_STEPS = 400      # Minimum trigger interval = 400×50µs = 20ms (1 fundamental cycle)

    # Steady-state error thresholds (from dq baseline at nominal operation)
    E_STEADY_VDC = 0.03    # 3% Vdc steady-state ripple (observed in simulations)
    E_STEADY_V2  = 0.02    # 2% V2 steady-state variation

    # Maximum strategy level (0=S0, 1=S1, 2=S2, 3=S3)
    MAX_LEVEL   = 3

    def __init__(self, base_strategy: int = 0):
        self.base_level   = base_strategy
        self.current_level = base_strategy
        self._steps_since_trigger = self.N_MIN_STEPS  # ready to trigger immediately
        self._trigger_active = False

    def step(self, e_vdc: float, e_v2: float) -> int:
        """Update and return current strategy level.

        Args:
            e_vdc: Relative DC-link error = (Vdc_ref - Vdc) / Vdc_ref
            e_v2:  Relative secondary voltage error = (V2_ref - V2_rms) / V2_ref
        Returns:
            Strategy level (0–3)
        """
        self._steps_since_trigger += 1

        # Check trigger condition (ET-PIRC eq. 28 analogue)
        trigger_vdc = abs(e_vdc) > self.A_TRIGGER * self.E_STEADY_VDC
        trigger_v2  = abs(e_v2)  > self.A_TRIGGER * self.E_STEADY_V2

        if (trigger_vdc or trigger_v2) and self._steps_since_trigger >= self.N_MIN_STEPS:
            # Escalate strategy (ET-PIRC: reduce K_ET when error is large)
            error_magnitude = max(abs(e_vdc) / self.E_STEADY_VDC,
                                  abs(e_v2)  / self.E_STEADY_V2)
            # Map error magnitude to strategy delta: larger error → higher escalation
            if error_magnitude > 10.0:
                delta = 2
            elif error_magnitude > 5.0:
                delta = 1
            else:
                delta = 0
            new_level = min(self.MAX_LEVEL, self.base_level + delta)
            if new_level > self.current_level:
                self.current_level = new_level
                self._steps_since_trigger = 0
                self._trigger_active = True

        elif self._trigger_active and self._steps_since_trigger >= 2 * self.N_MIN_STEPS:
            # De-escalate: one level down after 2 cycles without re-trigger
            self.current_level = max(self.base_level, self.current_level - 1)
            if self.current_level == self.base_level:
                self._trigger_active = False
            self._steps_since_trigger = self.N_MIN_STEPS  # allow new trigger

        return self.current_level

    def reset(self, base_strategy: int | None = None) -> None:
        if base_strategy is not None:
            self.base_level = base_strategy
        self.current_level = self.base_level
        self._steps_since_trigger = self.N_MIN_STEPS
        self._trigger_active = False


def etfahc_strategy_from_signals(
    vdc_trace: np.ndarray,
    v2_trace: np.ndarray,
    vdc_ref: float = 800.0,
    v2_ref: float = 400.0,
    base_strategy: int = 0,
) -> np.ndarray:
    """Apply ET-FAHC to a time-series of Vdc and V2_rms signals.

    Args:
        vdc_trace: Vdc time-series (N,)
        v2_trace:  V2_rms time-series (N,), RMS secondary voltage
        vdc_ref:   DC reference voltage (default 800V)
        v2_ref:    Secondary reference voltage (default 400V)
        base_strategy: Starting strategy level (from fault-class assignment)
    Returns:
        strategy_trace: Strategy level at each sample (N,), values 0–3
    """
    ctrl = ETFAHCController(base_strategy=base_strategy)
    out = np.zeros(len(vdc_trace), dtype=np.int32)
    for i in range(len(vdc_trace)):
        e_vdc = (vdc_ref - vdc_trace[i]) / vdc_ref
        e_v2  = (v2_ref  - v2_trace[i])  / v2_ref
        out[i] = ctrl.step(e_vdc, e_v2)
    return out


def evaluate_etfahc_from_json(json_path: Path) -> dict:
    """Evaluate ET-FAHC improvement over static FAHC using existing scenario metrics.

    Reads existing LVRT metrics JSON and applies ET-FAHC to estimate improvement.
    This is an offline post-hoc analysis (no re-simulation needed).
    """
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # For each scenario, check if ET-FAHC would have escalated and helped
    n_total    = len(data)
    n_pass_static  = sum(1 for d in data if d.get('lvrt_pass', False))
    n_pass_etfahc  = 0
    n_escalated    = 0

    for d in data:
        sc_id     = int(d.get('sc_id', 0))
        base_strat = SC_ID_TO_STRATEGY.get(sc_id, 0)
        vdc_min    = float(d.get('vdc_min_pu', 1.0))
        passed     = bool(d.get('lvrt_pass', False))

        # Simulate: would ET-FAHC have escalated to a higher strategy?
        # If vdc_min is borderline (0.65–0.75), escalation to strategy+1 may help
        if not passed and vdc_min >= 0.65 and vdc_min < 0.75 and base_strat < 3:
            next_strat   = base_strat + 1
            dvdc_next    = PHYSICS_DVDC_PU[next_strat] - PHYSICS_DVDC_PU[base_strat]
            estimated_pass = (vdc_min + dvdc_next) >= 0.75
            if estimated_pass:
                n_escalated += 1
                n_pass_etfahc += 1
                continue

        if passed:
            n_pass_etfahc += 1

    return {
        'n_total':       n_total,
        'pass_static':   n_pass_static,
        'pass_static_pct': round(100 * n_pass_static / n_total, 2),
        'pass_etfahc':   n_pass_etfahc,
        'pass_etfahc_pct': round(100 * n_pass_etfahc / n_total, 2),
        'gain_pp':       round(100 * (n_pass_etfahc - n_pass_static) / n_total, 2),
        'n_escalated':   n_escalated,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--analyze',          action='store_true',
                        help='Print failure analysis and estimated improvement')
    parser.add_argument('--train-severity',   action='store_true',
                        help='Train VdcMin/I2Max severity estimator')
    parser.add_argument('--write-strategy-config', action='store_true',
                        help='Write FAHC strategy table JSON for MATLAB')
    parser.add_argument('--simulate',         action='store_true',
                        help='Run 350-scenario FAHC batch in Simulink (Mode 7)')
    parser.add_argument('--dq-dir', type=str,
                        default=str(PROJECT_ROOT / 'data' / 'raw_switching_hpt_v2_fixed_dq'))
    parser.add_argument('--epochs', type=int, default=300)
    args = parser.parse_args()

    if args.write_strategy_config:
        write_strategy_config()
    if args.analyze:
        analyze_failures(Path(args.dq_dir))
    if args.train_severity:
        train_severity(Path(args.dq_dir), epochs=args.epochs)
    if args.simulate:
        simulate_fahc()

    if not any([args.analyze, args.train_severity,
                args.write_strategy_config, args.simulate]):
        write_strategy_config()
        print()
        print('Run with --analyze --dq-dir <path> for failure breakdown.')
