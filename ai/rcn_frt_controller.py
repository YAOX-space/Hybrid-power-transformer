"""
rcn_frt_controller.py  —  Reference Conditioning Network (RCN) for HPT FRT
============================================================================
Core idea
---------
  The dq double-loop controller fails not because its PI loops are weak, but
  because its *references* are fixed:
      Vdc_ref = 800 V  (constant)
      V2_ref  = 400 V  (constant)
      I_limit = 3.0 pu (constant)

  During deep voltage faults the controller wastes DC-link energy trying to
  maintain 800 V while the capacitor drains.  Lowering Vdc_ref by ~80 V
  saves ΔE = ½C(800²−720²) = 134 J, which can keep VdcMin above the 0.75 pu
  threshold in borderline scenarios.

  RCN is a small MLP that maps scenario parameters → optimal reference
  adjustments fed back into the existing dq controller:
      ΔVdc_ref ∈ [−80, +40] V    (default 800 V)
      ΔV2_ref  ∈ [−40, +20] V    (default 400 V)
      ΔI_lim   ∈ [−0.5, +0.5] pu (default 3.0 pu)

Two-phase training
------------------
  Phase 1  offline  : train on physics-estimated optimal references derived
                      from existing 350 dq-loop .mat files (no new Simulink).
                      This gives a reasonable starting policy immediately.
  Phase 2  online   : run grid-search Simulink experiments to find true optimal
                      references for borderline scenarios; re-train RCN on real
                      data.  The harness for this is implemented below.

Usage
-----
  # Phase 1 — offline training on physics estimates
  python rcn_frt_controller.py --analyze --dq-dir data/raw_switching_hpt_v2_fixed_dq
  python rcn_frt_controller.py --train-offline

  # Phase 2 — Simulink grid-search (needs MATLAB)
  python rcn_frt_controller.py --grid-search --dq-dir data/raw_switching_hpt_v2_fixed_dq
  python rcn_frt_controller.py --train-online --grid-data results/rcn_grid_search.json

  # Evaluate trained RCN policy against dq baseline
  python rcn_frt_controller.py --eval-checkpoint data/models/rcn_frt_best.pt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.optim.lr_scheduler import CosineAnnealingLR

PROJECT_ROOT   = Path(__file__).resolve().parent.parent
SCENARIO_TABLE = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
RESULTS_DIR    = PROJECT_ROOT / 'results'
MODEL_DIR      = PROJECT_ROOT / 'data' / 'models'
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# ── Physical constants ─────────────────────────────────────────────────────────
VDC_NOM   = 800.0      # V
V2_NOM    = 400.0      # V
C_DC      = 2200e-6    # F
VDC_MIN_LIMIT = 0.75   # pu
I2_MAX_LIMIT  = 3.0    # pu

# Reference adjustment bounds
VDC_REF_DELTA_MIN = -80.0    # V  (800 → 720 minimum)
VDC_REF_DELTA_MAX = +40.0    # V  (800 → 840 maximum)
V2_REF_DELTA_MIN  = -40.0    # V
V2_REF_DELTA_MAX  = +20.0    # V
ILIM_DELTA_MIN    = -0.5     # pu
ILIM_DELTA_MAX    = +0.5     # pu


# ── Physics helpers ────────────────────────────────────────────────────────────

def energy_saved_by_lower_vdc_ref(delta_vdc: float) -> float:
    """Energy (J) saved when Vdc_ref is reduced by |delta_vdc| volts."""
    v_high = VDC_NOM
    v_low  = VDC_NOM + delta_vdc   # delta_vdc < 0
    return 0.5 * C_DC * (v_high ** 2 - v_low ** 2)


def vdc_min_improvement_estimate(vdc_min_pu: float, delta_vdc_ref: float) -> float:
    """Rough estimate of VdcMin improvement (pu) when Vdc_ref is reduced.

    When the controller targets a lower voltage, it stops 'fighting' to restore
    to 800 V during the fault.  The saved energy ΔE keeps the capacitor charged
    higher, improving VdcMin.  This is a first-order estimate only.
    """
    if delta_vdc_ref >= 0:
        return 0.0
    e_saved   = energy_saved_by_lower_vdc_ref(delta_vdc_ref)
    # Approximate: ΔVdc ≈ ΔE / (C * Vdc_nominal)
    dv_approx = e_saved / (C_DC * VDC_NOM)
    return dv_approx / VDC_NOM   # convert to pu


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ScenarioMetrics:
    scenario_id:   int
    sc_id:         int
    vdc_min_pu:    float
    vdc_max_pu:    float
    i2_max_pu:     float
    recovery_ms:   float
    lvrt_pass:     bool
    failure_cause: str   # 'vdc_low'|'i2_high'|'recovery'|'vdc_high'|'pass'

    @property
    def needs_energy_save(self) -> bool:
        return self.failure_cause == 'vdc_low' and self.vdc_min_pu > 0.55

    @property
    def needs_current_limit(self) -> bool:
        return self.failure_cause == 'i2_high' and self.i2_max_pu < 3.4


@dataclass
class OptimalRef:
    scenario_id:    int
    delta_vdc_ref:  float   # V
    delta_v2_ref:   float   # V
    delta_ilim:     float   # pu
    source:         str     # 'physics_estimate' | 'simulink_grid'
    expected_pass:  bool


# ── Load existing dq metrics ───────────────────────────────────────────────────

def load_dq_metrics(dq_dir: Path) -> list[ScenarioMetrics]:
    """Load LVRT metrics from the existing dq double-loop simulation directory."""
    try:
        from lvrt_metrics import metrics_for_file
    except ImportError as e:
        raise ImportError('lvrt_metrics.py must be importable') from e

    mat_files = sorted(dq_dir.glob('*.mat'))
    if not mat_files:
        raise FileNotFoundError(f'No .mat files in {dq_dir}')

    records = []
    for i, path in enumerate(mat_files):
        m = metrics_for_file(path)
        vdc_min = float(m['vdc_min_pu_post_fault'])
        vdc_max = float(m['vdc_peak_pu_post_fault'])
        i2_max  = float(m['i2_peak_pu_post_fault'])
        rec_ms  = float(m['v2_recovery_ms_to_0p90']) if m['v2_recovery_ms_to_0p90'] else 500.0
        passed  = bool(m['lvrt_pass_basic'])

        if passed:
            cause = 'pass'
        elif vdc_min < VDC_MIN_LIMIT:
            cause = 'vdc_low'
        elif i2_max > I2_MAX_LIMIT:
            cause = 'i2_high'
        elif vdc_max > 1.25:
            cause = 'vdc_high'
        else:
            cause = 'recovery'

        records.append(ScenarioMetrics(
            scenario_id=i,
            sc_id=int(m['sc_id']),
            vdc_min_pu=vdc_min,
            vdc_max_pu=vdc_max,
            i2_max_pu=i2_max,
            recovery_ms=rec_ms,
            lvrt_pass=passed,
            failure_cause=cause,
        ))
    return records


# ── Physics-based optimal reference estimation ─────────────────────────────────

def estimate_optimal_refs(metrics: list[ScenarioMetrics]) -> list[OptimalRef]:
    """Assign reference adjustments based on failure type and physics estimates.

    Heuristic rules derived from energy conservation and fault physics:
      vdc_low  + borderline (VdcMin 0.55-0.74)  → lower Vdc_ref to save DC energy
      i2_high  + borderline (I2Max  3.0-3.4)    → tighten current limit earlier
      pass scenarios                             → keep nominal references
      severe vdc_low (< 0.55)                   → aggressive energy-save mode
    """
    refs = []
    for m in metrics:
        if m.lvrt_pass:
            # Passing scenarios: keep nominal, small positive margin for I2
            d_ilim = -0.1 if m.i2_max_pu > 2.8 else 0.0
            refs.append(OptimalRef(m.scenario_id, 0.0, 0.0, d_ilim,
                                   'physics_estimate', True))
            continue

        d_vdc = 0.0
        d_v2  = 0.0
        d_ilim = 0.0
        expected_pass = False

        if m.failure_cause == 'vdc_low':
            deficit = VDC_MIN_LIMIT - m.vdc_min_pu      # pu below threshold
            if deficit < 0.20:
                # Borderline: lower Vdc_ref by ~80 V, this saves ~134 J
                d_vdc = -80.0
                d_v2  = -20.0
                d_ilim = -0.2
                # Estimate improvement
                dv_est = vdc_min_improvement_estimate(m.vdc_min_pu, d_vdc)
                expected_pass = (m.vdc_min_pu + dv_est) >= VDC_MIN_LIMIT
            else:
                # Severe case: maximum energy-save mode
                d_vdc = VDC_REF_DELTA_MIN     # -80 V
                d_v2  = V2_REF_DELTA_MIN      # -40 V
                d_ilim = -0.3
                dv_est = vdc_min_improvement_estimate(m.vdc_min_pu, d_vdc)
                expected_pass = (m.vdc_min_pu + dv_est) >= VDC_MIN_LIMIT

        elif m.failure_cause == 'i2_high':
            excess = m.i2_max_pu - I2_MAX_LIMIT
            if excess < 0.40:
                d_ilim = -min(excess * 1.2, 0.5)
                expected_pass = True  # direct current clamping
            else:
                d_ilim = ILIM_DELTA_MIN
                d_v2   = -20.0
                expected_pass = False  # likely structural limit

        elif m.failure_cause == 'recovery':
            d_vdc  = -40.0
            d_ilim = +0.2   # allow slightly higher current during recovery
            expected_pass = True

        elif m.failure_cause == 'vdc_high':
            d_vdc  = +20.0  # raise setpoint to absorb excess
            expected_pass = True

        refs.append(OptimalRef(m.scenario_id, d_vdc, d_v2, d_ilim,
                               'physics_estimate', expected_pass))
    return refs


# ── Scenario feature vector ────────────────────────────────────────────────────

def scenario_to_obs(row: pd.Series) -> np.ndarray:
    """Convert a scenario table row to a normalised observation vector."""
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


# ── RCN network ────────────────────────────────────────────────────────────────

class RCN(nn.Module):
    """Reference Conditioning Network.

    Outputs normalised reference adjustments in [-1, +1], mapped to physical
    ranges via decode_refs().
    """

    def __init__(self, obs_dim: int = 8, hidden: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.LayerNorm(hidden), nn.GELU(),
            nn.Linear(hidden, hidden),  nn.LayerNorm(hidden), nn.GELU(),
            nn.Linear(hidden, 64),      nn.GELU(),
            nn.Linear(64, 3),
            nn.Tanh(),
        )

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return self.net(obs)   # (B, 3) in [-1, +1]


def decode_refs(action: np.ndarray) -> tuple[float, float, float]:
    """Map normalised action ∈ [-1,+1]³ to physical reference deltas."""
    dvdc  = VDC_REF_DELTA_MIN  + (action[0] + 1) / 2 * (VDC_REF_DELTA_MAX - VDC_REF_DELTA_MIN)
    dv2   = V2_REF_DELTA_MIN   + (action[1] + 1) / 2 * (V2_REF_DELTA_MAX  - V2_REF_DELTA_MIN)
    dilim = ILIM_DELTA_MIN     + (action[2] + 1) / 2 * (ILIM_DELTA_MAX    - ILIM_DELTA_MIN)
    return float(dvdc), float(dv2), float(dilim)


def encode_refs(d_vdc: float, d_v2: float, d_ilim: float) -> np.ndarray:
    """Inverse of decode_refs: physical deltas → normalised [-1,+1]."""
    a0 = 2 * (d_vdc  - VDC_REF_DELTA_MIN)  / (VDC_REF_DELTA_MAX - VDC_REF_DELTA_MIN)  - 1
    a1 = 2 * (d_v2   - V2_REF_DELTA_MIN)   / (V2_REF_DELTA_MAX  - V2_REF_DELTA_MIN)   - 1
    a2 = 2 * (d_ilim - ILIM_DELTA_MIN)     / (ILIM_DELTA_MAX    - ILIM_DELTA_MIN)     - 1
    return np.clip(np.array([a0, a1, a2], dtype=np.float32), -1.0, 1.0)


# ── Offline training ───────────────────────────────────────────────────────────

def train_offline(dq_dir: Path, epochs: int = 200, lr: float = 1e-3) -> Path:
    """Train RCN on physics-estimated reference targets.

    Phase-1 training: no new Simulink required.  Uses energy-conservation
    physics to estimate optimal reference adjustments for failing scenarios.
    """
    print(f'Loading dq metrics from {dq_dir} ...')
    metrics = load_dq_metrics(dq_dir)
    refs    = estimate_optimal_refs(metrics)
    table   = pd.read_csv(SCENARIO_TABLE)

    n_pass  = sum(1 for m in metrics if m.lvrt_pass)
    n_fail  = len(metrics) - n_pass
    n_borderline = sum(1 for r in refs if r.expected_pass and not metrics[r.scenario_id].lvrt_pass)
    print(f'  Total scenarios : {len(metrics)}')
    print(f'  dq pass         : {n_pass}  ({100*n_pass/len(metrics):.1f}%)')
    print(f'  Borderline (physics-estimated recoverable): {n_borderline}')

    obs_list, tgt_list = [], []
    for ref in refs:
        row = table.iloc[ref.scenario_id]
        obs = scenario_to_obs(row)
        tgt = encode_refs(ref.delta_vdc_ref, ref.delta_v2_ref, ref.delta_ilim)
        obs_list.append(obs)
        tgt_list.append(tgt)

    obs_t = torch.tensor(np.stack(obs_list), dtype=torch.float32)
    tgt_t = torch.tensor(np.stack(tgt_list), dtype=torch.float32)

    model = RCN()
    opt   = Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    sched = CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-5)

    for epoch in range(1, epochs + 1):
        model.train()
        pred = model(obs_t)
        loss = nn.functional.mse_loss(pred, tgt_t)
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        if epoch % 50 == 0:
            print(f'  epoch={epoch:4d}  loss={loss.item():.5f}')

    ckpt = MODEL_DIR / 'rcn_frt_offline.pt'
    torch.save({'model_state': model.state_dict(), 'phase': 'offline'}, ckpt)
    print(f'\nOffline RCN saved → {ckpt}')

    report = {
        'phase': 'offline',
        'n_scenarios': len(metrics),
        'dq_pass_pct': round(100 * n_pass / len(metrics), 2),
        'physics_recoverable': n_borderline,
        'physics_estimated_pass_pct': round(
            100 * (n_pass + n_borderline) / len(metrics), 2),
        'failure_breakdown': {
            cause: sum(1 for m in metrics if m.failure_cause == cause)
            for cause in ['pass', 'vdc_low', 'i2_high', 'recovery', 'vdc_high']
        },
    }
    report_path = RESULTS_DIR / 'rcn_frt_offline_analysis.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Analysis saved  → {report_path}')
    return ckpt


# ── Simulink grid-search harness ───────────────────────────────────────────────

GRID_VDC_REF   = [-80, -60, -40, -20, 0, +20]     # delta V
GRID_V2_REF    = [-40, -20, 0]                      # delta V
GRID_ILIM      = [-0.5, -0.3, -0.1, 0.0]           # delta pu


def grid_search_scenario(
    row: pd.Series,
    scenario_row_idx: int,
    out_dir: Path,
    controller_mode: int = 6,   # Mode 6: RCN-modified dq, requires Simulink change
) -> list[dict]:
    """Run Simulink for one scenario across all reference combinations.

    Returns list of dicts: {delta_vdc, delta_v2, delta_ilim, metrics...}
    Requires HPT v2 Simulink model to support ControllerMode=6 with
    HPT_VDC_REF_DELTA, HPT_V2_REF_DELTA, HPT_ILIM_DELTA environment variables.
    """
    from lvrt_metrics import metrics_for_file

    results = []
    for dv in GRID_VDC_REF:
        for dv2 in GRID_V2_REF:
            for di in GRID_ILIM:
                run_id = f'rcn_gs_row{scenario_row_idx:04d}_dv{dv:+d}_dv2{dv2:+d}_di{di:+.1f}'
                run_dir = out_dir / run_id
                run_dir.mkdir(parents=True, exist_ok=True)

                env = os.environ.copy()
                env['HPT_SCENARIO_TABLE']  = 'scenario_table_hpt_v2.csv'
                env['HPT_SCENARIO_ROW']    = str(scenario_row_idx + 1)
                env['HPT_SWITCHING_OUT_DIR'] = str(run_dir).replace('\\', '/')
                env['HPT_CONTROLLER_MODE'] = str(controller_mode)
                env['HPT_VDC_REF_DELTA']   = str(dv)
                env['HPT_V2_REF_DELTA']    = str(dv2)
                env['HPT_ILIM_DELTA']      = str(di)

                cmd = ['matlab', '-batch',
                       "cd('" + os.environ.get('HPT_DATA_COLLECTION', '/Users/yao/Research/THU/summer/data_collection') + "');"
                       "run('run_switching_scenarios.m');"]
                cp = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                                    capture_output=True, text=True, timeout=180)
                if cp.returncode != 0:
                    continue

                mat_files = sorted(run_dir.glob('*.mat'))
                if not mat_files:
                    continue
                m = metrics_for_file(mat_files[0])
                results.append({
                    'scenario_row': scenario_row_idx,
                    'sc_id': int(row.sc_id),
                    'delta_vdc_ref': dv,
                    'delta_v2_ref': dv2,
                    'delta_ilim': di,
                    'lvrt_pass': bool(m['lvrt_pass_basic']),
                    'vdc_min_pu': float(m['vdc_min_pu_post_fault']),
                    'i2_max_pu': float(m['i2_peak_pu_post_fault']),
                    'recovery_ms': m['v2_recovery_ms_to_0p90'] or 500.0,
                })
    return results


def run_grid_search(dq_dir: Path, max_scenarios: int = 100) -> Path:
    """Run grid search on borderline-failing scenarios.

    Targets scenarios that fail with dq control but may pass with adjusted
    references, prioritising those closest to the LVRT boundary.
    """
    metrics  = load_dq_metrics(dq_dir)
    table    = pd.read_csv(SCENARIO_TABLE)
    out_dir  = PROJECT_ROOT / 'data' / 'rcn_grid_search'
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prioritise borderline failures
    candidates = sorted(
        [m for m in metrics if not m.lvrt_pass],
        key=lambda m: -m.vdc_min_pu,   # closest to 0.75 threshold first
    )[:max_scenarios]

    print(f'Grid-searching {len(candidates)} borderline scenarios '
          f'({len(GRID_VDC_REF) * len(GRID_V2_REF) * len(GRID_ILIM)} '
          f'reference combinations each)...')

    all_results = []
    for m in candidates:
        row = table.iloc[m.scenario_id]
        print(f'  scenario {m.scenario_id:3d}  sc_id={m.sc_id}  VdcMin={m.vdc_min_pu:.3f} pu ...')
        results = grid_search_scenario(row, m.scenario_id, out_dir)
        all_results.extend(results)

    out_path = RESULTS_DIR / 'rcn_grid_search.json'
    out_path.write_text(json.dumps(all_results, indent=2), encoding='utf-8')
    print(f'\nGrid search complete: {len(all_results)} runs → {out_path}')
    return out_path


# ── Online training (after grid search) ───────────────────────────────────────

def train_online(grid_data_path: Path, epochs: int = 400, lr: float = 5e-4) -> Path:
    """Train RCN on real Simulink grid-search results (Phase 2)."""
    with open(grid_data_path, encoding='utf-8') as f:
        data = json.load(f)

    table = pd.read_csv(SCENARIO_TABLE)

    # For each scenario, find the reference combination with best LVRT pass + highest VdcMin
    best_by_scenario: dict[int, dict] = {}
    for rec in data:
        sid = rec['scenario_row']
        current_best = best_by_scenario.get(sid)
        if current_best is None or (
            rec['lvrt_pass'] > current_best['lvrt_pass'] or
            (rec['lvrt_pass'] == current_best['lvrt_pass'] and
             rec['vdc_min_pu'] > current_best['vdc_min_pu'])
        ):
            best_by_scenario[sid] = rec

    obs_list, tgt_list = [], []
    for sid, best in best_by_scenario.items():
        row = table.iloc[sid]
        obs = scenario_to_obs(row)
        tgt = encode_refs(best['delta_vdc_ref'], best['delta_v2_ref'], best['delta_ilim'])
        obs_list.append(obs)
        tgt_list.append(tgt)

    obs_t = torch.tensor(np.stack(obs_list), dtype=torch.float32)
    tgt_t = torch.tensor(np.stack(tgt_list), dtype=torch.float32)

    model = RCN()
    ckpt_offline = MODEL_DIR / 'rcn_frt_offline.pt'
    if ckpt_offline.exists():
        model.load_state_dict(torch.load(ckpt_offline, map_location='cpu')['model_state'])
        print('Loaded offline checkpoint as starting point.')

    opt   = Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    sched = CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-6)
    best_loss = float('inf')
    ckpt_best = MODEL_DIR / 'rcn_frt_best.pt'

    for epoch in range(1, epochs + 1):
        model.train()
        pred = model(obs_t)
        loss = nn.functional.mse_loss(pred, tgt_t)
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        if loss.item() < best_loss:
            best_loss = loss.item()
            torch.save({'model_state': model.state_dict(), 'phase': 'online'}, ckpt_best)
        if epoch % 100 == 0:
            print(f'  epoch={epoch:4d}  loss={loss.item():.6f}')

    print(f'\nOnline RCN saved → {ckpt_best}')
    return ckpt_best


# ── Batch evaluation against Simulink ─────────────────────────────────────────

def evaluate_checkpoint(ckpt_path: Path, n_scenarios: int = 350) -> None:
    """Evaluate a trained RCN policy against the fixed 350-scenario table."""
    from lvrt_metrics import metrics_for_file

    table = pd.read_csv(SCENARIO_TABLE).head(n_scenarios)
    model = RCN()
    model.load_state_dict(torch.load(ckpt_path, map_location='cpu')['model_state'])
    model.eval()

    obs = torch.tensor(
        np.stack([scenario_to_obs(table.iloc[i]) for i in range(len(table))]),
        dtype=torch.float32,
    )
    with torch.no_grad():
        actions = model(obs).numpy()

    out_dir = PROJECT_ROOT / 'data' / 'rcn_eval_rollouts' / f'eval_{int(time.time())}'
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_table = pd.DataFrame({
        'rollout_id':   np.arange(1, len(table) + 1),
        'scenario_row': np.arange(1, len(table) + 1),
        'delta_vdc_ref': [decode_refs(a)[0] for a in actions],
        'delta_v2_ref':  [decode_refs(a)[1] for a in actions],
        'delta_ilim':    [decode_refs(a)[2] for a in actions],
    })
    ref_table.to_csv(out_dir / 'rcn_refs.csv', index=False)

    env = os.environ.copy()
    env['HPT_SCENARIO_TABLE']     = 'scenario_table_hpt_v2.csv'
    env['HPT_RCN_REF_TABLE']      = str(out_dir / 'rcn_refs.csv').replace('\\', '/')
    env['HPT_SWITCHING_OUT_DIR']  = str(out_dir).replace('\\', '/')
    env['HPT_CONTROLLER_MODE']    = '6'

    cmd = ['matlab', '-batch',
           "cd('" + os.environ.get('HPT_DATA_COLLECTION', '/Users/yao/Research/THU/summer/data_collection') + "');"
           "run('run_switching_scenarios.m');"]
    cp = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                        capture_output=True, text=True,
                        timeout=max(180, 90 * len(table)))
    if cp.returncode != 0:
        raise RuntimeError(f'MATLAB failed:\n{cp.stdout}\n{cp.stderr}')

    mat_files = sorted(out_dir.glob('*.mat'))
    all_metrics = [metrics_for_file(p) for p in mat_files]
    pass_rate = 100 * sum(m['lvrt_pass_basic'] for m in all_metrics) / len(all_metrics)

    by_sc: dict[int, list] = {}
    for m in all_metrics:
        by_sc.setdefault(int(m['sc_id']), []).append(m['lvrt_pass_basic'])
    print(f'\nRCN evaluation ({len(all_metrics)} scenarios):')
    print(f'  Overall LVRT pass: {pass_rate:.2f}%')
    for sc_id in sorted(by_sc):
        g = by_sc[sc_id]
        print(f'  sc_id={sc_id}  pass={100*sum(g)/len(g):.1f}%  ({sum(g)}/{len(g)})')

    result = {
        'checkpoint': str(ckpt_path),
        'n_scenarios': len(all_metrics),
        'pass_rate_pct': round(pass_rate, 2),
        'by_sc_id': {str(k): round(100*sum(v)/len(v), 1) for k, v in by_sc.items()},
    }
    out_json = RESULTS_DIR / 'rcn_eval_result.json'
    out_json.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Result saved → {out_json}')


# ── Analysis report ────────────────────────────────────────────────────────────

def analyze_and_report(dq_dir: Path) -> None:
    """Print failure analysis and estimated improvement from RCN."""
    metrics = load_dq_metrics(dq_dir)
    refs    = estimate_optimal_refs(metrics)

    n_total      = len(metrics)
    n_pass       = sum(1 for m in metrics if m.lvrt_pass)
    n_vdc_low    = sum(1 for m in metrics if m.failure_cause == 'vdc_low')
    n_i2_high    = sum(1 for m in metrics if m.failure_cause == 'i2_high')
    n_recovery   = sum(1 for m in metrics if m.failure_cause == 'recovery')
    n_recoverable = sum(1 for r in refs
                        if r.expected_pass and not metrics[r.scenario_id].lvrt_pass)

    print('=' * 60)
    print('RCN Failure Analysis & Expected Improvement')
    print('=' * 60)
    print(f'Total scenarios        : {n_total}')
    print(f'dq double-loop pass    : {n_pass}  ({100*n_pass/n_total:.1f}%)')
    print(f'Failure: VdcMin < 0.75 : {n_vdc_low}')
    print(f'Failure: I2Max > 3.0   : {n_i2_high}')
    print(f'Failure: recovery slow : {n_recovery}')
    print()
    print(f'Physics-estimated recoverable by RCN : {n_recoverable}')
    print(f'Estimated RCN LVRT pass rate         : '
          f'{100*(n_pass + n_recoverable)/n_total:.1f}%  '
          f'(+{100*n_recoverable/n_total:.1f} pp vs dq)')
    print()

    print('VdcMin distribution of failing scenarios:')
    fail_vdc = [m.vdc_min_pu for m in metrics if not m.lvrt_pass and m.failure_cause == 'vdc_low']
    for lo, hi in [(0.55, 0.75), (0.40, 0.55), (0.00, 0.40)]:
        cnt = sum(1 for v in fail_vdc if lo <= v < hi)
        label = 'borderline (RCN can help)' if lo >= 0.55 else (
                'severe (partial help)'     if lo >= 0.40 else 'critical (hw limit)')
        print(f'  VdcMin [{lo:.2f},{hi:.2f}): {cnt:3d}  — {label}')


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--analyze',         action='store_true')
    parser.add_argument('--train-offline',   action='store_true')
    parser.add_argument('--grid-search',     action='store_true')
    parser.add_argument('--train-online',    action='store_true')
    parser.add_argument('--eval-checkpoint', type=str, default=None)
    parser.add_argument('--dq-dir',          type=str,
                        default=str(PROJECT_ROOT / 'data' / 'raw_switching_hpt_v2_fixed_dq'))
    parser.add_argument('--grid-data',       type=str,
                        default=str(RESULTS_DIR / 'rcn_grid_search.json'))
    parser.add_argument('--epochs',          type=int, default=400)
    parser.add_argument('--max-gs-scenarios', type=int, default=100)
    args = parser.parse_args()

    dq_dir = Path(args.dq_dir)

    if args.analyze:
        analyze_and_report(dq_dir)
    if args.train_offline:
        train_offline(dq_dir, epochs=args.epochs)
    if args.grid_search:
        run_grid_search(dq_dir, max_scenarios=args.max_gs_scenarios)
    if args.train_online:
        train_online(Path(args.grid_data), epochs=args.epochs)
    if args.eval_checkpoint:
        evaluate_checkpoint(Path(args.eval_checkpoint))
