"""
msffn_pipeline.py — MSFFN Fault Detection → FAHC Strategy Selection Pipeline
==============================================================================
Step 1: Load existing Mode-4 Simulink data (350 scenarios).
Step 2: For each scenario, extract the 5 ms window at fault onset and run MSFFN.
Step 3: Map predicted fault class → FAHC strategy (0-3).
Step 4: Write a strategy-table CSV that run_switching_scenarios.m consumes
        via HPT_FAHC_STRATEGY_TABLE when re-running as Mode 7.
Step 5: Print prediction accuracy and per-class strategy coverage.

Usage
-----
  python ai/msffn_pipeline.py
  python ai/msffn_pipeline.py --dq-dir data/raw_switching_hpt_v2_fixed_dq
  python ai/msffn_pipeline.py --out-csv data_collection/msffn_fahc_strategy_table.csv

After this script completes, run MATLAB from the project root:
  cd data_collection
  matlab -batch "run_pipeline_scenarios"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio
import mat73
import torch
from sklearn.metrics import classification_report, confusion_matrix

# ── paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import FAULT_CLASSES, N_CLASSES, F_SAMPLE, WINDOW_SIZE

MODEL_DIR   = PROJECT_ROOT / 'data' / 'models'
PROC_DIR    = PROJECT_ROOT / 'data' / 'processed'
RESULTS_DIR = PROJECT_ROOT / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_DQ_DIR   = PROJECT_ROOT / 'data' / 'raw_switching_hpt_v2_fixed_dq'
DEFAULT_OUT_CSV  = PROJECT_ROOT / 'data_collection' / 'msffn_fahc_strategy_table.csv'
DEFAULT_CONF_THR = 0.80   # only deviate from Strategy 0 if softmax confidence ≥ this

# Fault-class (0-6) → FAHC strategy (0-3)
#   class 0 (normal) / 1 (igbt_oc_sh) / 2 (igbt_oc_se) → strategy 0  (nominal setpoints)
#   class 3 (cap_fault)  → strategy 1  (Vdc_ref=760 V)
#   class 4 (sc_1ph)     → strategy 2  (Vdc_ref=740 V)
#   class 5 (sc_3ph)     → strategy 3  (Vdc_ref=720 V)
#   class 6 (cascade)    → strategy 1  (Vdc_ref=760 V)  ← FIX: was 3, caused 7 failures
#     Reason: cascade Vdc_min mean=0.819pu, well above 0.75pu threshold.
#     S3 (720V ref) reduces charging power and pushes borderline scenarios below 0.75pu.
#     S1 (760V ref) provides mild headroom without destabilising the DC link.
FAULT_CLASS_TO_STRATEGY = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 1}


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_mat(path: Path) -> dict:
    try:
        return sio.loadmat(str(path))
    except NotImplementedError:
        return mat73.loadmat(str(path))


def _squeeze2d(arr: np.ndarray, n_rows: int) -> np.ndarray:
    """Return (n_rows, C) array regardless of MATLAB storage orientation."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 1:
        return a[:, None]
    if a.shape[0] == n_rows:
        return a
    if a.shape[1] == n_rows:
        return a.T
    return a


def extract_window(mat: dict) -> tuple[np.ndarray, int] | None:
    """
    Return (X_window, true_class) where X_window is (WINDOW_SIZE, 9).
    Window starts at fault onset (or last 5 ms for normal scenarios).
    Returns None if the file is too short.
    """
    Vdc    = np.asarray(mat['V_dc'],    dtype=np.float32).squeeze()
    labels = np.asarray(mat['fault_labels'], dtype=np.int32).squeeze()
    N = len(Vdc)
    if N < WINDOW_SIZE:
        return None

    Ish = _squeeze2d(mat['Ish_dq'], N)
    I1  = _squeeze2d(mat['I1_abc'], N)
    I2  = _squeeze2d(mat['I2_abc'], N)

    fault_idx = np.where(labels > 0)[0]
    if len(fault_idx) > 0:
        onset = int(fault_idx[0])
        true_class = int(labels[onset])
    else:
        onset = N - WINDOW_SIZE
        true_class = 0

    start = max(0, onset)
    end   = start + WINDOW_SIZE
    if end > N:
        start = N - WINDOW_SIZE
        end   = N

    # Build feature matrix — order must match HPTMatLoader.X_fault
    Xf = np.column_stack([
        Vdc[start:end],
        Ish[start:end, 0],
        Ish[start:end, 1] if Ish.shape[1] > 1 else np.zeros(WINDOW_SIZE, np.float32),
        I1[start:end, 0], I1[start:end, 1], I1[start:end, 2],
        I2[start:end, 0], I2[start:end, 1], I2[start:end, 2],
    ]).astype(np.float32)   # (WINDOW_SIZE, 9)

    if len(Xf) < WINDOW_SIZE:
        pad = WINDOW_SIZE - len(Xf)
        Xf = np.pad(Xf, ((pad, 0), (0, 0)), mode='edge')

    return Xf, true_class


def find_msffn_checkpoint(override: str | None = None) -> Path:
    # Explicit override via arg or env var takes priority
    env_ckpt = override or os.environ.get('HPT_MSFFN_CKPT', '').strip()
    if env_ckpt:
        p = Path(env_ckpt)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.exists():
            raise FileNotFoundError(f'Specified MSFFN checkpoint not found: {p}')
        return p
    # Sort newest-first so we always pick the most recently trained checkpoint
    candidates = sorted(MODEL_DIR.glob('msffn_fault_detector_*.pt'),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(
            f'No MSFFN checkpoint found in {MODEL_DIR}. '
            'Run: python ai/msffn_fault_detector.py --train')
    for p in candidates:
        if 'fixed_all' in p.name:
            return p
    return candidates[0]


def find_scaler(ckpt_path: Path) -> object:
    # Derive scaler name from checkpoint name
    dataset_tag = ckpt_path.stem.replace('msffn_fault_detector_', '')
    scaler_path = PROC_DIR / f'fault_scaler_{dataset_tag}.pkl'
    if not scaler_path.exists():
        # Fall back to any available scaler
        fallbacks = sorted(PROC_DIR.glob('fault_scaler_*.pkl'))
        if not fallbacks:
            raise FileNotFoundError(
                f'No scaler found in {PROC_DIR}. '
                'Run: python ai/data_loader.py to rebuild the dataset.')
        scaler_path = fallbacks[-1]
    print(f'  scaler  : {scaler_path.name}')
    with open(scaler_path, 'rb') as f:
        return pickle.load(f)


# ── main pipeline ──────────────────────────────────────────────────────────────

def run(dq_dir: Path, out_csv: Path, conf_threshold: float = DEFAULT_CONF_THR,
        ckpt_override: str | None = None):
    from msffn_fault_detector import MSFFN

    dq_dir = dq_dir.resolve()
    mat_files = sorted(dq_dir.glob('*.mat'))
    if not mat_files:
        raise FileNotFoundError(
            f'No .mat files found in {dq_dir}. '
            'Run Simulink Mode-4 scenarios first.')
    print(f'\n=== MSFFN → FAHC Pipeline ===')
    print(f'  input   : {dq_dir} ({len(mat_files)} files)')
    print(f'  out_csv : {out_csv}')
    print(f'  conf thr: {conf_threshold:.2f}')

    # Load model + scaler
    ckpt_path = find_msffn_checkpoint(override=ckpt_override)
    print(f'  model   : {ckpt_path.name}')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    ckpt   = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    model  = MSFFN().to(device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()
    scaler = find_scaler(ckpt_path)
    print(f'  device  : {device}')

    # ── Phase 1: extract windows ───────────────────────────────────────────
    windows, true_classes, scenario_ids, skipped = [], [], [], []
    for path in mat_files:
        try:
            mat = _load_mat(path)
        except Exception as e:
            skipped.append((path.name, str(e)))
            continue
        result = extract_window(mat)
        if result is None:
            skipped.append((path.name, 'too short'))
            continue
        Xf, tc = result
        sid = int(np.asarray(mat.get('scenario_id', -1)).flat[0])
        windows.append(Xf)
        true_classes.append(tc)
        scenario_ids.append(sid)

    if skipped:
        print(f'  skipped : {len(skipped)} files')

    # ── Phase 2: MSFFN batch inference ────────────────────────────────────
    print(f'\nRunning MSFFN on {len(windows)} windows ...')
    X_all = np.stack(windows)            # (M, WINDOW_SIZE, 9)
    M, W, C = X_all.shape
    X_norm = scaler.transform(X_all.reshape(-1, C)).reshape(M, W, C).astype(np.float32)

    BATCH = 256
    predicted_classes, confidences = [], []
    with torch.no_grad():
        for i in range(0, M, BATCH):
            xb  = torch.from_numpy(X_norm[i:i + BATCH]).to(device)
            prob = torch.softmax(model(xb), dim=1)
            predicted_classes.extend(prob.argmax(1).cpu().numpy().tolist())
            confidences.extend(prob.max(1).values.cpu().numpy().tolist())

    pred  = np.array(predicted_classes, dtype=np.int32)
    conf  = np.array(confidences,       dtype=np.float32)
    true  = np.array(true_classes,      dtype=np.int32)

    # Confidence gating: only deviate from Strategy 0 when confidence >= threshold.
    # If MSFFN is uncertain, default to Strategy 0 (= dq double-loop behaviour).
    # This prevents wrong strategies from triggering aggressive current limits.
    raw_strategies = np.array([FAULT_CLASS_TO_STRATEGY[int(p)] for p in pred], dtype=np.int32)
    strategies = np.where(conf >= conf_threshold, raw_strategies, np.zeros(M, dtype=np.int32))
    n_gated = int((conf < conf_threshold).sum())
    print(f'  Confidence gate ({conf_threshold:.2f}): {n_gated}/{M} scenarios '
          f'reverted to Strategy 0')

    # ── Phase 3: write CSV ─────────────────────────────────────────────────
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['scenario_row', 'rollout_id', 'strategy_id',
                           'predicted_class', 'true_class', 'correct',
                           'confidence', 'gated'])
        writer.writeheader()
        for i, sid in enumerate(scenario_ids):
            writer.writerow({
                'scenario_row'    : sid,   # scenario_id = row index in table
                'rollout_id'      : sid,
                'strategy_id'     : int(strategies[i]),
                'predicted_class' : int(pred[i]),
                'true_class'      : int(true[i]),
                'correct'         : int(pred[i] == true[i]),
                'confidence'      : round(float(conf[i]), 4),
                'gated'           : int(conf[i] < conf_threshold),
            })
    print(f'Wrote {len(scenario_ids)} rows to {out_csv}')

    # ── Phase 4: accuracy report ───────────────────────────────────────────
    acc = float((pred == true).mean())
    print(f'\n--- Fault Classification Accuracy: {100*acc:.2f}% ---')
    class_names = [FAULT_CLASSES[i] for i in range(N_CLASSES)]
    print(classification_report(true, pred, labels=list(range(N_CLASSES)),
                                target_names=class_names, zero_division=0))

    # Strategy selection accuracy (what matters for LVRT)
    true_strats  = np.array([FAULT_CLASS_TO_STRATEGY[int(t)] for t in true], dtype=np.int32)
    strat_acc    = float((strategies == true_strats).mean())
    print(f'--- Strategy Selection Accuracy: {100*strat_acc:.2f}% ---')
    print('(A mispredicted fault class that maps to the same strategy still selects correctly.)\n')

    # Strategy distribution
    print('Strategy distribution (predicted):')
    for s in range(4):
        n = int((strategies == s).sum())
        print(f'  Strategy {s}: {n:3d} scenarios')

    # Save summary JSON
    summary = {
        'n_scenarios'           : int(M),
        'conf_threshold'        : conf_threshold,
        'n_gated'               : n_gated,
        'fault_class_accuracy'  : round(acc, 4),
        'strategy_accuracy'     : round(strat_acc, 4),
        'strategy_counts'       : {str(s): int((strategies == s).sum()) for s in range(4)},
        'mean_confidence'       : round(float(conf.mean()), 4),
        'confusion_matrix'      : confusion_matrix(true, pred, labels=list(range(N_CLASSES))).tolist(),
        'msffn_checkpoint'      : str(ckpt_path),
        'dq_dir'                : str(dq_dir),
        'out_csv'               : str(out_csv),
    }
    summary_path = RESULTS_DIR / 'msffn_pipeline_summary.json'
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Summary saved to {summary_path}')

    print('\n=== Next step: run MATLAB ===')
    print('  cd data_collection')
    print('  matlab -batch "run_pipeline_scenarios"')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dq-dir',          type=Path,  default=DEFAULT_DQ_DIR)
    parser.add_argument('--out-csv',         type=Path,  default=DEFAULT_OUT_CSV)
    parser.add_argument('--conf-threshold',  type=float, default=DEFAULT_CONF_THR,
                        help='Minimum softmax confidence to apply a non-zero strategy (default 0.70)')
    parser.add_argument('--ckpt', type=str, default=None,
                        help='Path to a specific MSFFN checkpoint (overrides auto-detection)')
    args = parser.parse_args()
    run(args.dq_dir, args.out_csv, args.conf_threshold, ckpt_override=args.ckpt)
