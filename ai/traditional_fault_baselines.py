"""
Traditional fault-diagnosis baselines for the HPT switching dataset.

The goal is to compare the current deep temporal CNN/LSTM route against
classical, reproducible baselines on exactly the same Simulink windows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import RidgeClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from data_loader import build_fault_dataset, FAULT_CLASSES, N_CLASSES, RAW_DIR


RESULTS_DIR = Path(__file__).resolve().parent.parent / 'results'
RESULTS_DIR.mkdir(exist_ok=True)


def flatten_dataset(dataset):
    return dataset.X.numpy(), dataset.y.numpy()


def make_features(windows: np.ndarray) -> np.ndarray:
    """Convert (N, T, C) signal windows into classical statistical features."""
    x = windows
    dx = np.diff(x, axis=1)
    feats = [
        x.mean(axis=1),
        x.std(axis=1),
        np.sqrt((x * x).mean(axis=1)),
        x.min(axis=1),
        x.max(axis=1),
        np.ptp(x, axis=1),
        x[:, -1, :] - x[:, 0, :],
        np.abs(dx).mean(axis=1),
        np.abs(dx).max(axis=1),
    ]
    return np.concatenate(feats, axis=1)


def threshold_rules(x_feat: np.ndarray, train_feat: np.ndarray, train_y: np.ndarray) -> np.ndarray:
    """
    Deterministic residual-threshold baseline.

    It first detects whether a window is abnormal using distance from the normal
    centroid, then assigns the nearest fault centroid. This mirrors traditional
    residual/prototype logic without sequence learning.
    """
    normal = train_feat[train_y == 0]
    mu0 = normal.mean(axis=0)
    sigma0 = normal.std(axis=0) + 1e-6
    normal_score = np.linalg.norm((train_feat[train_y == 0] - mu0) / sigma0, axis=1)
    threshold = float(np.percentile(normal_score, 99.0))

    centroids = []
    for cls in range(N_CLASSES):
        rows = train_feat[train_y == cls]
        centroids.append(rows.mean(axis=0) if len(rows) else mu0)
    centroids = np.stack(centroids)

    score = np.linalg.norm((x_feat - mu0) / sigma0, axis=1)
    dist = np.linalg.norm(
        ((x_feat[:, None, :] - centroids[None, :, :]) / sigma0),
        axis=2,
    )
    pred = dist.argmin(axis=1)
    pred[score <= threshold] = 0
    return pred


class ELMClassifier:
    """Small extreme-learning-machine baseline with a ridge output layer."""

    def __init__(self, hidden_size: int = 512, seed: int = 7):
        self.hidden_size = hidden_size
        self.rng = np.random.default_rng(seed)
        self.scaler = StandardScaler()
        self.out = RidgeClassifier(alpha=1.0)
        self.W = None
        self.b = None

    def _hidden(self, x):
        z = x @ self.W + self.b
        return np.tanh(z)

    def fit(self, x, y):
        xs = self.scaler.fit_transform(x)
        self.W = self.rng.normal(0.0, 1.0 / np.sqrt(xs.shape[1]), size=(xs.shape[1], self.hidden_size))
        self.b = self.rng.normal(0.0, 0.1, size=(self.hidden_size,))
        self.out.fit(self._hidden(xs), y)
        return self

    def predict(self, x):
        xs = self.scaler.transform(x)
        return self.out.predict(self._hidden(xs))


def evaluate_predictions(name: str, y_true: np.ndarray, y_pred: np.ndarray, train_ms: float, infer_ms: float):
    labels = list(range(N_CLASSES))
    report = classification_report(
        y_true, y_pred,
        labels=labels,
        target_names=[FAULT_CLASSES[i] for i in labels],
        output_dict=True,
        zero_division=0,
    )
    result = {
        'method': name,
        'accuracy_pct': round(100 * accuracy_score(y_true, y_pred), 2),
        'macro_f1_pct': round(100 * report['macro avg']['f1-score'], 2),
        'weighted_f1_pct': round(100 * report['weighted avg']['f1-score'], 2),
        'train_ms': round(train_ms, 2),
        'test_infer_ms_total': round(infer_ms, 2),
        'classification_report': report,
        'confusion_matrix': confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }
    print(f"{name:18s} acc={result['accuracy_pct']:6.2f}%  macroF1={result['macro_f1_pct']:6.2f}%")
    return result


def run(force_rebuild: bool = False):
    train_ds, val_ds, test_ds, _ = build_fault_dataset(force_rebuild=force_rebuild)
    x_train0, y_train0 = flatten_dataset(train_ds)
    x_val, y_val = flatten_dataset(val_ds)
    x_test0, y_test = flatten_dataset(test_ds)

    x_train0 = np.concatenate([x_train0, x_val], axis=0)
    y_train = np.concatenate([y_train0, y_val], axis=0)

    x_train = make_features(x_train0)
    x_test = make_features(x_test0)

    results = {}

    t0 = perf_counter()
    y_pred = threshold_rules(x_test, x_train, y_train)
    t1 = perf_counter()
    results['threshold_centroid'] = evaluate_predictions(
        'threshold_centroid', y_test, y_pred, 0.0, (t1 - t0) * 1000)

    models = {
        'svm_rbf': make_pipeline(
            StandardScaler(),
            SVC(C=8.0, gamma='scale', class_weight='balanced'),
        ),
        'random_forest': RandomForestClassifier(
            n_estimators=350,
            min_samples_leaf=2,
            class_weight='balanced_subsample',
            random_state=11,
            n_jobs=-1,
        ),
        'elm': ELMClassifier(hidden_size=768, seed=13),
    }

    for name, model in models.items():
        t0 = perf_counter()
        model.fit(x_train, y_train)
        t1 = perf_counter()
        y_pred = model.predict(x_test)
        t2 = perf_counter()
        results[name] = evaluate_predictions(
            name, y_test, y_pred, (t1 - t0) * 1000, (t2 - t1) * 1000)

    out_path = RESULTS_DIR / f'traditional_fault_baselines_{RAW_DIR.name}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'\nSaved baseline report to {out_path}')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force-rebuild', action='store_true')
    args = parser.parse_args()
    run(force_rebuild=args.force_rebuild)
