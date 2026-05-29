"""
Unified traditional-vs-AI fault diagnosis comparison.

This script reads the current HPT_RAW_DIR dataset, evaluates:
  - traditional baselines from traditional_fault_baselines.py
  - the saved PyTorch AI checkpoint for the same dataset

and writes a concise Markdown + JSON report under results/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from data_loader import (
    build_fault_dataset,
    make_val_loader,
    FAULT_CLASSES,
    N_CLASSES,
    RAW_DIR,
    WINDOW_SIZE,
)
from sklearn.ensemble import RandomForestClassifier

from traditional_fault_baselines import run as run_traditional, make_features, flatten_dataset
from lstm_fault_detector import CKPT_PATH, create_model, resolve_device, checkpoint_path_for_arch

try:
    from msffn_fault_detector import evaluate as _evaluate_msffn, MSFFN, CKPT_PATH as MSFFN_CKPT_PATH
    _HAS_MSFFN = True
except Exception:
    _HAS_MSFFN = False


RESULTS_DIR = Path(__file__).resolve().parent.parent / 'results'
RESULTS_DIR.mkdir(exist_ok=True)


def evaluate_ai_checkpoint(device_name: str = 'auto', arch_name: str = 'auto'):
    ckpt_path = checkpoint_path_for_arch(arch_name)
    if not ckpt_path.exists():
        return None

    requested_device = device_name
    if arch_name in {'lstm', 'cnn_lstm'} and device_name in {'auto', 'dml'}:
        requested_device = 'cpu'

    device, resolved_name, pin_memory = resolve_device(requested_device)
    _, _, test_ds, _ = build_fault_dataset()
    loader = make_val_loader(test_ds, batch_size=512, num_workers=0, pin_memory=pin_memory)

    try:
        ckpt = torch.load(ckpt_path, map_location='cpu')
    except (NotImplementedError, RuntimeError):
        # Checkpoint was saved on DirectML; cannot be loaded on CPU/CUDA
        return None
    arch = ckpt.get('arch', arch_name if arch_name != 'auto' else 'cnn' if resolved_name == 'dml' else 'lstm')
    model = create_model(arch, resolved_name).to(device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    all_pred, all_true = [], []
    infer_times = []
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device)
            t0 = perf_counter()
            pred = model(x).argmax(1).cpu().numpy()
            t1 = perf_counter()
            all_pred.extend(pred)
            all_true.extend(y.numpy())
            infer_times.append((t1 - t0) * 1000.0)

    y_true = np.asarray(all_true)
    y_pred = np.asarray(all_pred)
    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(N_CLASSES)),
        target_names=[FAULT_CLASSES[i] for i in range(N_CLASSES)],
        output_dict=True,
        zero_division=0,
    )
    return {
        'method': f'AI-{arch.upper()}',
        'family': 'AI',
        'accuracy_pct': round(100 * accuracy_score(y_true, y_pred), 2),
        'macro_f1_pct': round(100 * report['macro avg']['f1-score'], 2),
        'weighted_f1_pct': round(100 * report['weighted avg']['f1-score'], 2),
        'detect_latency_ms': round(WINDOW_SIZE / 20_000 * 1000, 3),
        'test_infer_ms_total': round(float(np.sum(infer_times)), 3),
        'classification_report': report,
        'confusion_matrix': confusion_matrix(
            y_true, y_pred, labels=list(range(N_CLASSES))).tolist(),
        'checkpoint': str(ckpt_path),
        'device': resolved_name,
    }


def normalize_traditional(results):
    rows = []
    for name, item in results.items():
        rows.append({
            'method': name,
            'family': 'Traditional',
            'accuracy_pct': item['accuracy_pct'],
            'macro_f1_pct': item['macro_f1_pct'],
            'weighted_f1_pct': item['weighted_f1_pct'],
            'detect_latency_ms': 5.0,
            'test_infer_ms_total': item.get('test_infer_ms_total'),
            'classification_report': item.get('classification_report'),
            'confusion_matrix': item.get('confusion_matrix'),
        })
    return rows


def write_markdown(rows, out_path: Path, dataset_name: str):
    ranked = sorted(rows, key=lambda r: (r['accuracy_pct'], r['macro_f1_pct']), reverse=True)
    best = ranked[0]
    ai_rows = [r for r in ranked if r['family'] == 'AI']
    best_ai = ai_rows[0] if ai_rows else None

    lines = [
        f'# Fault Diagnosis Method Comparison: {dataset_name}',
        '',
        '## Summary',
        '',
        f'- Dataset: `{dataset_name}`',
        f'- Best overall method: `{best["method"]}` ({best["family"]}), '
        f'Accuracy {best["accuracy_pct"]:.2f}%, Macro F1 {best["macro_f1_pct"]:.2f}%',
    ]
    if best_ai is not None:
        gap = best['accuracy_pct'] - best_ai['accuracy_pct']
        lines.append(
            f'- Best AI method: `{best_ai["method"]}`, Accuracy {best_ai["accuracy_pct"]:.2f}%, '
            f'Macro F1 {best_ai["macro_f1_pct"]:.2f}%')
        lines.append(f'- Current AI accuracy gap to best method: {gap:.2f} percentage points')

    lines += [
        '',
        '## Ranked Results',
        '',
        '| Rank | Method | Family | Accuracy | Macro F1 | Weighted F1 | Window Latency |',
        '|---:|---|---|---:|---:|---:|---:|',
    ]
    for idx, row in enumerate(ranked, 1):
        lines.append(
            f'| {idx} | {row["method"]} | {row["family"]} | '
            f'{row["accuracy_pct"]:.2f}% | {row["macro_f1_pct"]:.2f}% | '
            f'{row["weighted_f1_pct"]:.2f}% | {row["detect_latency_ms"]:.1f} ms |')

    lines += [
        '',
        '## Interpretation',
        '',
        '- If traditional feature models win, the dataset still contains stable statistical signatures that shallow models can exploit.',
        '- If AI wins on larger cross-condition data, it indicates the sequence model is learning transient dynamics rather than only handcrafted statistics.',
        '- For the current FRT-controlled data, fault responses are intentionally suppressed by control action, so diagnosis becomes harder and requires more data or stronger temporal models.',
        '',
        '## Recommended Next AI Comparisons',
        '',
        '| Candidate | Why it matters |',
        '|---|---|',
        '| CNN-LSTM | Local waveform features plus temporal state memory |',
        '| TCN | Fast causal temporal convolution for 5 ms online diagnosis |',
        '| Transformer encoder | Better long-range transient attention after fault onset |',
        '| Multi-task AI | Predict fault class, fault phase/switch, and FRT control mode together |',
    ]
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def evaluate_ensemble(device_name: str = 'auto'):
    """MSFFN + RF ensemble: weighted average of softmax probabilities.

    Alpha (weight on RF) is tuned on the validation set, then applied to test set.
    Returns None if MSFFN checkpoint is missing.
    """
    if not _HAS_MSFFN or not MSFFN_CKPT_PATH.exists():
        return None

    device, _, pin = resolve_device(device_name)

    train_ds, val_ds, test_ds, _ = build_fault_dataset()

    # ── MSFFN probabilities ────────────────────────────────────────────────────
    model = MSFFN().to(device)
    ckpt = torch.load(MSFFN_CKPT_PATH, map_location='cpu', weights_only=False)
    model.load_state_dict(ckpt['model_state'])
    model.eval()

    def msffn_proba(ds):
        loader = make_val_loader(ds, batch_size=512, num_workers=0, pin_memory=pin)
        probs, labels = [], []
        with torch.no_grad():
            for x, y in loader:
                logits = model(x.to(device))
                probs.append(torch.softmax(logits, dim=-1).cpu().numpy())
                labels.append(y.numpy())
        return np.concatenate(probs), np.concatenate(labels)

    p_msffn_val,  y_val  = msffn_proba(val_ds)
    p_msffn_test, y_test = msffn_proba(test_ds)

    # ── RF probabilities ───────────────────────────────────────────────────────
    x_train_raw, y_train_raw = flatten_dataset(train_ds)
    x_val_raw,   _           = flatten_dataset(val_ds)
    x_test_raw,  _           = flatten_dataset(test_ds)

    # train RF on train+val features (mirrors traditional_fault_baselines.run)
    x_tv = np.concatenate([x_train_raw, x_val_raw])
    y_tv = np.concatenate([y_train_raw, y_val])
    feat_tv   = make_features(x_tv)
    feat_val  = make_features(x_val_raw)
    feat_test = make_features(x_test_raw)

    rf = RandomForestClassifier(
        n_estimators=350, min_samples_leaf=2,
        class_weight='balanced_subsample', random_state=11, n_jobs=-1,
    )
    rf.fit(feat_tv, y_tv)
    p_rf_val  = rf.predict_proba(feat_val)
    p_rf_test = rf.predict_proba(feat_test)

    # ── Alpha search on validation set ────────────────────────────────────────
    best_alpha, best_val_acc = 0.5, -1.0
    for alpha in np.arange(0.0, 1.01, 0.05):
        p = alpha * p_rf_val + (1 - alpha) * p_msffn_val
        acc = accuracy_score(y_val, p.argmax(axis=1))
        if acc > best_val_acc:
            best_val_acc, best_alpha = acc, float(alpha)

    # ── Final evaluation on test set ──────────────────────────────────────────
    p_ens = best_alpha * p_rf_test + (1 - best_alpha) * p_msffn_test
    y_pred = p_ens.argmax(axis=1)

    report = classification_report(
        y_test, y_pred,
        labels=list(range(N_CLASSES)),
        target_names=[FAULT_CLASSES[i] for i in range(N_CLASSES)],
        output_dict=True, zero_division=0,
    )
    print(f"Ensemble (RF α={best_alpha:.2f} + MSFFN)  "
          f"acc={100*accuracy_score(y_test, y_pred):.2f}%  "
          f"macroF1={100*report['macro avg']['f1-score']:.2f}%")

    return {
        'method': f'Ensemble_RF+MSFFN(α={best_alpha:.2f})',
        'family': 'Ensemble',
        'accuracy_pct': round(100 * accuracy_score(y_test, y_pred), 2),
        'macro_f1_pct': round(100 * report['macro avg']['f1-score'], 2),
        'weighted_f1_pct': round(100 * report['weighted avg']['f1-score'], 2),
        'detect_latency_ms': round(WINDOW_SIZE / 20_000 * 1000, 3),
        'test_infer_ms_total': None,
        'classification_report': report,
        'confusion_matrix': confusion_matrix(
            y_test, y_pred, labels=list(range(N_CLASSES))).tolist(),
        'alpha_rf': best_alpha,
        'val_accuracy_at_best_alpha': round(100 * best_val_acc, 2),
    }


def run(device: str = 'auto', skip_traditional: bool = False):
    rows = []
    if not skip_traditional:
        traditional = run_traditional(force_rebuild=False)
        rows.extend(normalize_traditional(traditional))

    for arch in ['cnn', 'tcn', 'cnn_lstm', 'lstm']:
        ai = evaluate_ai_checkpoint(device, arch)
        if ai is not None:
            rows.append(ai)

    if _HAS_MSFFN:
        msffn_result = _evaluate_msffn(device)
        if msffn_result is not None:
            rows.append(msffn_result)
        ens_result = evaluate_ensemble(device)
        if ens_result is not None:
            rows.append(ens_result)

    out_json = RESULTS_DIR / f'fault_method_comparison_{RAW_DIR.name}.json'
    out_md = RESULTS_DIR / f'fault_method_comparison_{RAW_DIR.name}.md'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({'dataset': RAW_DIR.name, 'rows': rows}, f, ensure_ascii=False, indent=2)
    write_markdown(rows, out_md, RAW_DIR.name)

    print(f'\nSaved {out_json}')
    print(f'Saved {out_md}')
    print('\nRanked summary:')
    for row in sorted(rows, key=lambda r: (r['accuracy_pct'], r['macro_f1_pct']), reverse=True):
        print(f"  {row['method']:20s} {row['family']:12s} "
              f"acc={row['accuracy_pct']:6.2f}% macroF1={row['macro_f1_pct']:6.2f}%")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', default='auto')
    parser.add_argument('--skip-traditional', action='store_true')
    args = parser.parse_args()
    run(device=args.device, skip_traditional=args.skip_traditional)
