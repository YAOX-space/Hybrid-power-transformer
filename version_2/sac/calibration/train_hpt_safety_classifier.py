"""Train a switch-data safety classifier for HPT direct SAC.

The classifier is a support mask for later SAC/MOPO training.  It predicts
whether a topology/context/action sample is inside the observed safe operating
region using switch-level sweep labels.  It is not a controller.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

from version_2.sac.experiment_metadata import sha256_file, write_experiment_metadata
from version_2.sac.calibration.train_hpt_learned_proxy import DEFAULT_DATA_ROOT, latest_dataset, load_dataset


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_OUT_ROOT = ROOT / "version_2" / "data" / "hpt_safety_classifier"


def label_safety(
    Y: np.ndarray,
    target_names: list[str],
    *,
    lv_low: float = 0.75,
    lv_high: float = 1.25,
    vdc_min_low: float = 0.70,
    vdc_mean_low: float = 0.50,
    vdc_max_high: float = 1.70,
    unbalance_high: float = 0.12,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    idx = {name: i for i, name in enumerate(target_names)}
    lv = Y[:, idx["lv_pu_mean"]]
    vdc_mean = Y[:, idx["vdc_pu_mean"]]
    vdc_min = Y[:, idx["vdc_min_pu"]]
    vdc_max = Y[:, idx["vdc_max_pu"]]
    unbalance = Y[:, idx["lv_unbalance_pu"]]
    checks = {
        "lv_in_range": (lv >= lv_low) & (lv <= lv_high),
        "vdc_mean_survives": vdc_mean >= vdc_mean_low,
        "vdc_min_survives": vdc_min >= vdc_min_low,
        "vdc_max_bounded": vdc_max <= vdc_max_high,
        "unbalance_bounded": unbalance <= unbalance_high,
    }
    safe = np.logical_and.reduce(list(checks.values())).astype(np.int64)
    return safe, checks


def split_metrics(name: str, y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray) -> dict[str, Any]:
    labels = [0, 1]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=labels,
        zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        "split": name,
        "rows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "confusion_matrix_labels": ["unsafe", "safe"],
        "confusion_matrix": cm.astype(int).tolist(),
        "unsafe_precision": float(precision[0]),
        "unsafe_recall": float(recall[0]),
        "unsafe_f1": float(f1[0]),
        "unsafe_support": int(support[0]),
        "safe_precision": float(precision[1]),
        "safe_recall": float(recall[1]),
        "safe_f1": float(f1[1]),
        "safe_support": int(support[1]),
        "mean_safe_probability": float(np.mean(y_score)),
    }


def choose_safe_threshold(
    y_true: np.ndarray,
    y_score: np.ndarray,
    *,
    target_unsafe_recall: float = 0.95,
) -> tuple[float, dict[str, float]]:
    """Choose a conservative safe-probability threshold on validation data.

    Samples with ``safe_probability >= threshold`` are predicted safe.  Raising
    the threshold makes the classifier more conservative and improves unsafe
    recall at the cost of rejecting some safe samples.
    """

    best: tuple[float, float, float, float] | None = None
    fallback: tuple[float, float, float, float] | None = None
    for threshold in np.linspace(0.0, 1.0, 201):
        y_pred = (y_score >= threshold).astype(np.int64)
        metric = split_metrics("threshold_search", y_true, y_pred, y_score)
        unsafe_recall = float(metric["unsafe_recall"])
        safe_recall = float(metric["safe_recall"])
        accuracy = float(metric["accuracy"])
        candidate = (threshold, unsafe_recall, safe_recall, accuracy)
        if fallback is None or unsafe_recall > fallback[1] or (
            unsafe_recall == fallback[1] and safe_recall > fallback[2]
        ):
            fallback = candidate
        if unsafe_recall >= target_unsafe_recall:
            if best is None or safe_recall > best[2] or (
                safe_recall == best[2] and accuracy > best[3]
            ):
                best = candidate
    chosen = best or fallback
    if chosen is None:
        return 0.5, {"unsafe_recall": 0.0, "safe_recall": 0.0, "accuracy": 0.0}
    return float(chosen[0]), {
        "unsafe_recall": float(chosen[1]),
        "safe_recall": float(chosen[2]),
        "accuracy": float(chosen[3]),
    }


def write_predictions(
    path: Path,
    idx: np.ndarray,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["row_index", "safe_true", "safe_pred", "safe_probability"],
        )
        writer.writeheader()
        for local_i, row_idx in enumerate(idx):
            writer.writerow(
                {
                    "row_index": int(row_idx),
                    "safe_true": int(y_true[local_i]),
                    "safe_pred": int(y_pred[local_i]),
                    "safe_probability": float(y_score[local_i]),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--safe-threshold", default="auto")
    parser.add_argument("--min-safe-threshold", type=float, default=0.75)
    parser.add_argument("--target-unsafe-recall", type=float, default=0.95)
    parser.add_argument("--lv-low", type=float, default=0.75)
    parser.add_argument("--lv-high", type=float, default=1.25)
    parser.add_argument("--vdc-min-low", type=float, default=0.70)
    parser.add_argument("--vdc-mean-low", type=float, default=0.50)
    parser.add_argument("--vdc-max-high", type=float, default=1.70)
    parser.add_argument("--unbalance-high", type=float, default=0.12)
    args = parser.parse_args()

    dataset_path = args.dataset or latest_dataset(args.dataset_root)
    ds = load_dataset(dataset_path)
    labels, checks = label_safety(
        ds["Y"],
        ds["target_names"],
        lv_low=args.lv_low,
        lv_high=args.lv_high,
        vdc_min_low=args.vdc_min_low,
        vdc_mean_low=args.vdc_mean_low,
        vdc_max_high=args.vdc_max_high,
        unbalance_high=args.unbalance_high,
    )
    if len(np.unique(labels[ds["train_idx"]])) < 2:
        raise ValueError("Training split has only one safety class; collect broader switch data.")

    clf = RandomForestClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=args.seed,
    )
    clf.fit(ds["X"][ds["train_idx"]], labels[ds["train_idx"]])

    run_id = args.run_id or f"hpt_safety_classifier_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "classifier.joblib"

    threshold_idx = np.unique(np.concatenate([ds["train_idx"], ds["val_idx"]]))
    threshold_score = clf.predict_proba(ds["X"][threshold_idx])[:, 1]
    if str(args.safe_threshold).lower() == "auto":
        safe_threshold, threshold_metrics = choose_safe_threshold(
            labels[threshold_idx],
            threshold_score,
            target_unsafe_recall=args.target_unsafe_recall,
        )
    else:
        safe_threshold = float(args.safe_threshold)
        threshold_metrics = split_metrics(
            "threshold_user",
            labels[threshold_idx],
            (threshold_score >= safe_threshold).astype(np.int64),
            threshold_score,
        )
    if str(args.safe_threshold).lower() == "auto":
        safe_threshold = max(float(safe_threshold), float(args.min_safe_threshold))
        threshold_metrics = split_metrics(
            "threshold_auto_with_floor",
            labels[threshold_idx],
            (threshold_score >= safe_threshold).astype(np.int64),
            threshold_score,
        )

    metrics = {}
    for split in ("train", "val", "test"):
        idx = ds[f"{split}_idx"]
        y_true = labels[idx]
        y_score = clf.predict_proba(ds["X"][idx])[:, 1]
        y_pred = (y_score >= safe_threshold).astype(np.int64)
        metrics[split] = split_metrics(split, y_true, y_pred, y_score)
        write_predictions(out_dir / f"{split}_predictions.csv", idx, y_true, y_pred, y_score)

    check_counts = {
        name: {
            "pass": int(np.sum(mask)),
            "fail": int(mask.shape[0] - np.sum(mask)),
        }
        for name, mask in checks.items()
    }
    summary = {
        "schema": "hpt-safety-classifier-summary-v1",
        "run_id": run_id,
        "dataset": str(ds["path"]),
        "dataset_hash": sha256_file(ds["path"]),
        "model_path": str(model_path),
        "rows": int(ds["X"].shape[0]),
        "safe_rows": int(np.sum(labels)),
        "unsafe_rows": int(labels.shape[0] - np.sum(labels)),
        "feature_names": ds["feature_names"],
        "target_names": ds["target_names"],
        "check_counts": check_counts,
        "safe_probability_threshold": safe_threshold,
        "threshold_selection": threshold_metrics,
        "metrics": metrics,
    }
    thresholds = {
        "lv_low": args.lv_low,
        "lv_high": args.lv_high,
        "vdc_min_low": args.vdc_min_low,
        "vdc_mean_low": args.vdc_mean_low,
        "vdc_max_high": args.vdc_max_high,
        "unbalance_high": args.unbalance_high,
    }
    joblib.dump(
        {
            "schema": "hpt-safety-classifier-v1",
            "classifier": clf,
            "feature_names": ds["feature_names"],
            "target_names": ds["target_names"],
            "target_thresholds": thresholds,
            "safe_probability_threshold": safe_threshold,
        },
        model_path,
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_safety_classifier_train",
        config={
            "seed": args.seed,
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "safe_threshold": str(args.safe_threshold),
            "min_safe_threshold": args.min_safe_threshold,
            "selected_safe_probability_threshold": safe_threshold,
            "target_unsafe_recall": args.target_unsafe_recall,
            "thresholds": thresholds,
        },
        dataset_manifest=ds["path"].parent / "manifest.json",
        extra={
            "summary_path": str(out_dir / "summary.json"),
            "model_path": str(model_path),
            "dataset_hash": summary["dataset_hash"],
        },
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()


