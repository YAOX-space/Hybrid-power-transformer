"""
LVRT/FRT metrics extracted from Simulink .mat scenario outputs.

This script turns raw switching simulations into paper-style indicators:
voltage sag depth, recovery time, DC-link overshoot, current peak, and
reactive-power support.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import mat73
import numpy as np
import scipy.io as sio

from data_loader import PROJECT_ROOT, RAW_DIR, FAULT_CLASSES


RESULTS_DIR = PROJECT_ROOT / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

V2_LL_NOM = 400.0
VDC_NOM = 800.0
S_RATED = 400e3
I2_NOM = S_RATED / (np.sqrt(3) * V2_LL_NOM)


def load_mat(path: Path):
    try:
        return sio.loadmat(path)
    except NotImplementedError:
        return mat73.loadmat(path)


def scalar(value, default=0.0):
    if value is None:
        return default
    arr = np.asarray(value)
    if arr.size == 0:
        return default
    item = arr.flat[0]
    if isinstance(item, np.ndarray):
        return scalar(item, default)
    if isinstance(item, bytes):
        return item.decode('utf-8', errors='replace')
    return item


def arr(mat, key):
    x = np.asarray(mat[key]).squeeze()
    if x.ndim == 1:
        return x
    if x.shape[0] <= 4 and x.shape[1] > x.shape[0]:
        x = x.T
    return x


def phase_to_ll_rms(vabc: np.ndarray) -> np.ndarray:
    vab = vabc[:, 0] - vabc[:, 1]
    vbc = vabc[:, 1] - vabc[:, 2]
    vca = vabc[:, 2] - vabc[:, 0]
    return np.sqrt((vab * vab + vbc * vbc + vca * vca) / 3.0)


def sustained_recovery_time(t, signal_pu, start_t, threshold=0.90, hold_ms=2.0):
    hold = max(1, int(round((hold_ms / 1000.0) / np.median(np.diff(t)))))
    start_idx = int(np.searchsorted(t, start_t))
    ok = signal_pu >= threshold
    for idx in range(start_idx, max(start_idx, len(t) - hold)):
        if np.all(ok[idx:idx + hold]):
            return float((t[idx] - start_t) * 1000.0)
    return None


def infer_fault_window(t, labels, t_fault):
    idx = labels > 0
    if not np.any(idx):
        start = float(t_fault) if t_fault is not None else float(t[0])
        return start, float(t[-1])
    where = np.where(idx)[0]
    return float(t[where[0]]), float(t[where[-1]])


def metrics_for_file(path: Path):
    m = load_mat(path)
    t = arr(m, 't_uniform')
    v2 = arr(m, 'V2_abc')
    i2 = arr(m, 'I2_abc')
    vdc = arr(m, 'V_dc')
    q2 = arr(m, 'Q2') if 'Q2' in m else np.zeros_like(t)
    labels = arr(m, 'fault_labels').astype(int)
    sc_id = int(scalar(m.get('sc_id'), 0))
    sc_label = scalar(m.get('sc_label'), FAULT_CLASSES.get(sc_id, str(sc_id)))
    if isinstance(sc_label, np.str_):
        sc_label = str(sc_label)
    t_fault = float(scalar(m.get('t_fault'), t[0]))

    v2_pu = phase_to_ll_rms(v2) / V2_LL_NOM
    i2_pu = np.max(np.abs(i2), axis=1) / (np.sqrt(2) * I2_NOM)
    vdc_pu = np.abs(vdc) / VDC_NOM
    fault_start, fault_end = infer_fault_window(t, labels, t_fault)
    fmask = (t >= fault_start) & (t <= fault_end)
    post = t >= fault_start

    recovery_ms = sustained_recovery_time(t, v2_pu, fault_start)
    row = {
        'file': path.name,
        'sc_id': sc_id,
        'scenario': str(sc_label),
        'fault_start_s': round(fault_start, 6),
        'fault_end_s': round(fault_end, 6),
        'v2_min_pu_fault': round(float(np.min(v2_pu[fmask])) if np.any(fmask) else float(np.min(v2_pu)), 4),
        'v2_mean_pu_fault': round(float(np.mean(v2_pu[fmask])) if np.any(fmask) else float(np.mean(v2_pu)), 4),
        'v2_recovery_ms_to_0p90': None if recovery_ms is None else round(recovery_ms, 3),
        'vdc_peak_pu_post_fault': round(float(np.max(vdc_pu[post])), 4),
        'vdc_min_pu_post_fault': round(float(np.min(vdc_pu[post])), 4),
        'i2_peak_pu_post_fault': round(float(np.max(i2_pu[post])), 4),
        'q2_abs_peak_kvar_fault': round(float(np.max(np.abs(q2[fmask]))) / 1000.0 if np.any(fmask) else 0.0, 3),
    }
    row['lvrt_pass_basic'] = bool(
        row['vdc_peak_pu_post_fault'] <= 1.25
        and row['vdc_min_pu_post_fault'] >= 0.75
        and row['i2_peak_pu_post_fault'] <= 3.0
        and (row['v2_recovery_ms_to_0p90'] is None or row['v2_recovery_ms_to_0p90'] <= 100.0)
    )
    return row


def summarize(rows):
    scenarios = sorted(set(r['scenario'] for r in rows))
    summary = {}
    for sc in scenarios:
        group = [r for r in rows if r['scenario'] == sc]
        rec = [r['v2_recovery_ms_to_0p90'] for r in group if r['v2_recovery_ms_to_0p90'] is not None]
        summary[sc] = {
            'n': len(group),
            'pass_rate_pct': round(100.0 * sum(r['lvrt_pass_basic'] for r in group) / len(group), 2),
            'v2_min_pu_min': round(float(np.min([r['v2_min_pu_fault'] for r in group])), 4),
            'vdc_peak_pu_max': round(float(np.max([r['vdc_peak_pu_post_fault'] for r in group])), 4),
            'vdc_min_pu_min': round(float(np.min([r['vdc_min_pu_post_fault'] for r in group])), 4),
            'i2_peak_pu_max': round(float(np.max([r['i2_peak_pu_post_fault'] for r in group])), 4),
            'recovery_ms_mean': None if not rec else round(float(np.mean(rec)), 3),
            'recovery_ms_max': None if not rec else round(float(np.max(rec)), 3),
        }
    return summary


def run(raw_dir: Path = RAW_DIR):
    raw_dir = Path(raw_dir).resolve()
    files = sorted(raw_dir.glob('*.mat'))
    if not files:
        raise FileNotFoundError(f'No .mat files found in {raw_dir}')

    rows = [metrics_for_file(p) for p in files]
    summary = summarize(rows)

    csv_path = RESULTS_DIR / f'lvrt_metrics_{raw_dir.name}.csv'
    json_path = RESULTS_DIR / f'lvrt_metrics_{raw_dir.name}.json'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'raw_dir': str(raw_dir), 'summary': summary, 'rows': rows},
                  f, ensure_ascii=False, indent=2)

    print(f'LVRT/FRT metrics from {len(rows)} files')
    for sc, item in summary.items():
        print(
            f"{sc:12s} n={item['n']:3d} pass={item['pass_rate_pct']:6.2f}% "
            f"V2min={item['v2_min_pu_min']:.3f} "
            f"VdcMax={item['vdc_peak_pu_max']:.3f} I2Max={item['i2_peak_pu_max']:.3f}"
        )
    print(f'\nSaved {csv_path}')
    print(f'Saved {json_path}')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-dir', type=str, default=os.environ.get('HPT_RAW_DIR', str(RAW_DIR)))
    args = parser.parse_args()
    run(Path(args.raw_dir))
