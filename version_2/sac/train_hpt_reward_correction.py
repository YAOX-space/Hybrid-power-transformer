"""Train a switch-level reward correction model for HPT FRT actions.

The calibrated averaged proxy is useful for coarse screening, but the reward
alignment report shows that it can rank HVRT energy and joint actions
incorrectly.  This script learns a small supervised correction from the
switch-level reward-alignment detail table:

    corrected_return = proxy_return + f(scenario, action, proxy_metrics)

Only features available before a new switch-level rollout are used.  The
Simulink-derived reward is used as the label and for held-out evaluation.
"""
from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:  # HistGradientBoosting is optional across sklearn versions.
    from sklearn.ensemble import HistGradientBoostingRegressor
except Exception:  # pragma: no cover - version dependent
    HistGradientBoostingRegressor = None  # type: ignore[assignment]

from version_2.sac.measure_hpt_reward_alignment import (
    DEFAULT_OUT_DIR as ALIGNMENT_DIR,
    f,
    latest_csv,
    read_csv,
    s,
    summarize,
    write_csv,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_reward_correction"


FLOAT_FEATURES = (
    "grid_pu",
    "raw_m_reg_d",
    "raw_m_reg_q",
    "raw_m_energy_d",
    "raw_m_energy_q",
    "reg_d_mean",
    "reg_q_mean",
    "energy_d_mean",
    "energy_q_mean",
    "proxy_return",
    "proxy_lv_mean",
    "proxy_vdc_mean",
    "proxy_vdc_soft",
    "proxy_wrong_sign",
)

STRING_FEATURES = ("topology", "category", "mode")


def _feature_engineering(row: dict[str, Any]) -> dict[str, float]:
    grid_error = f(row, "grid_pu", 1.0) - 1.0
    reg_d = f(row, "raw_m_reg_d")
    reg_q = f(row, "raw_m_reg_q")
    energy_d = f(row, "raw_m_energy_d")
    energy_q = f(row, "raw_m_energy_q")
    reg_mag = float(math.hypot(reg_d, reg_q))
    energy_mag = float(math.hypot(energy_d, energy_q))
    return {
        "grid_error": grid_error,
        "grid_error_abs": abs(grid_error),
        "reg_mag": reg_mag,
        "energy_mag": energy_mag,
        "reg_energy_dot": reg_d * energy_d + reg_q * energy_q,
        "grid_reg_d": grid_error * reg_d,
        "grid_reg_q": grid_error * reg_q,
        "grid_energy_d": grid_error * energy_d,
        "grid_energy_q": grid_error * energy_q,
        "proxy_lv_error": f(row, "proxy_lv_mean", 1.0) - 1.0,
        "proxy_vdc_low_margin": f(row, "proxy_vdc_mean", 1.0) - 0.8125,
        "proxy_vdc_high_margin": 1.1625 - f(row, "proxy_vdc_mean", 1.0),
    }


def _categories(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        key: sorted({s(row, key) for row in rows})
        for key in STRING_FEATURES
    }


def build_features(
    rows: list[dict[str, Any]],
    categories: dict[str, list[str]],
) -> tuple[np.ndarray, list[str]]:
    feature_names: list[str] = []
    values: list[list[float]] = []

    engineered_names = list(_feature_engineering(rows[0]).keys()) if rows else []
    feature_names.extend(FLOAT_FEATURES)
    feature_names.extend(engineered_names)
    for key in STRING_FEATURES:
        feature_names.extend([f"{key}={value}" for value in categories[key]])

    for row in rows:
        row_values = [f(row, key) for key in FLOAT_FEATURES]
        engineered = _feature_engineering(row)
        row_values.extend(engineered[name] for name in engineered_names)
        for key in STRING_FEATURES:
            value = s(row, key)
            row_values.extend(1.0 if value == category else 0.0 for category in categories[key])
        values.append(row_values)
    return np.asarray(values, dtype=float), feature_names


def split_rows(
    rows: list[dict[str, Any]],
    *,
    holdout_stride: int,
    holdout_offset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((s(row, "topology"), s(row, "category"), s(row, "mode")), []).append(row)

    train: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: f(item, "row_index"))
        for idx, row in enumerate(group):
            if (idx + holdout_offset) % holdout_stride == 0:
                test.append(row)
            else:
                train.append(row)

    if not train or not test:
        raise ValueError("Empty train/test split; adjust holdout stride or input detail table.")
    return train, test


def make_models(seed: int) -> dict[str, Any]:
    models: dict[str, Any] = {
        "ridge": Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=2.0)),
            ]
        ),
        "random_forest": RandomForestRegressor(
            n_estimators=500,
            min_samples_leaf=2,
            random_state=seed,
            n_jobs=-1,
        ),
        "extra_trees": ExtraTreesRegressor(
            n_estimators=600,
            min_samples_leaf=2,
            random_state=seed,
            n_jobs=-1,
        ),
    }
    if HistGradientBoostingRegressor is not None:
        models["hist_gradient_boosting"] = HistGradientBoostingRegressor(
            max_iter=350,
            learning_rate=0.045,
            max_leaf_nodes=12,
            l2_regularization=0.02,
            random_state=seed,
        )
    return models


def with_corrected_return(
    rows: list[dict[str, Any]],
    corrected_return: np.ndarray,
) -> list[dict[str, Any]]:
    corrected: list[dict[str, Any]] = []
    for row, value in zip(rows, corrected_return):
        new_row = deepcopy(row)
        new_row["uncorrected_proxy_return"] = f(row, "proxy_return")
        new_row["corrected_proxy_return"] = float(value)
        new_row["predicted_reward_correction"] = float(value - f(row, "proxy_return"))
        new_row["proxy_return"] = float(value)
        corrected.append(new_row)
    return corrected


def weak_groups(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weak: list[dict[str, Any]] = []
    for row in summary:
        rho = f(row, "spearman_proxy_vs_switch_reward", float("nan"))
        top_k = max(1.0, f(row, "top_k", 1.0))
        overlap_fraction = f(row, "top_k_overlap_fraction")
        percentile = f(row, "proxy_top1_switch_percentile", float("nan"))
        if math.isnan(rho):
            continue
        if rho < 0.65 or overlap_fraction < 1.0 / top_k or percentile > 0.50:
            weak.append(row)
    return weak


def aggregate(summary: list[dict[str, Any]]) -> dict[str, float]:
    rhos = [
        f(row, "spearman_proxy_vs_switch_reward", float("nan"))
        for row in summary
        if not math.isnan(f(row, "spearman_proxy_vs_switch_reward", float("nan")))
    ]
    overlaps = [f(row, "top_k_overlap_fraction") for row in summary]
    percentiles = [
        f(row, "proxy_top1_switch_percentile", float("nan"))
        for row in summary
        if not math.isnan(f(row, "proxy_top1_switch_percentile", float("nan")))
    ]
    return {
        "groups": float(len(summary)),
        "weak_groups": float(len(weak_groups(summary))),
        "mean_spearman": float(np.mean(rhos)) if rhos else float("nan"),
        "mean_topk_overlap_fraction": float(np.mean(overlaps)) if overlaps else float("nan"),
        "mean_top1_switch_percentile": float(np.mean(percentiles)) if percentiles else float("nan"),
    }


def model_score(summary: list[dict[str, Any]]) -> tuple[float, float, float]:
    metrics = aggregate(summary)
    # Lower is better for weak groups and top-1 percentile; higher is better
    # for Spearman.  This is a model-selection score, not a scientific metric.
    return (
        metrics["weak_groups"],
        -metrics["mean_spearman"],
        metrics["mean_top1_switch_percentile"],
    )


def write_report(
    path: Path,
    *,
    detail_csv: Path,
    best_model: str,
    baseline_test_summary: list[dict[str, Any]],
    corrected_test_summary: list[dict[str, Any]],
    baseline_full_summary: list[dict[str, Any]],
    corrected_full_summary: list[dict[str, Any]],
    candidate_metrics: list[dict[str, Any]],
) -> None:
    base_test = aggregate(baseline_test_summary)
    corr_test = aggregate(corrected_test_summary)
    base_full = aggregate(baseline_full_summary)
    corr_full = aggregate(corrected_full_summary)

    lines = [
        "# HPT Reward Correction Report",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Detail input: `{detail_csv}`",
        f"- Selected model: `{best_model}`",
        "",
        "## Method",
        "",
        "- Target: `switch_reward_like - proxy_return`.",
        "- Features: topology/category/mode, grid depth, raw and averaged actions, and proxy LV/Vdc/reward signals.",
        "- Excluded features: direct proxy-vs-Simulink gap columns and switch-level outputs.",
        "- Evaluation: deterministic held-out action rows inside each topology/category/mode group.",
        "",
        "## Held-Out Action Evaluation",
        "",
        "| Metric | Baseline proxy | Corrected proxy |",
        "| --- | ---: | ---: |",
        f"| Weak groups | {base_test['weak_groups']:.0f} / {base_test['groups']:.0f} | {corr_test['weak_groups']:.0f} / {corr_test['groups']:.0f} |",
        f"| Mean Spearman | {base_test['mean_spearman']:.3f} | {corr_test['mean_spearman']:.3f} |",
        f"| Mean top-k overlap fraction | {base_test['mean_topk_overlap_fraction']:.3f} | {corr_test['mean_topk_overlap_fraction']:.3f} |",
        f"| Mean proxy-top1 switch percentile | {base_test['mean_top1_switch_percentile']:.3f} | {corr_test['mean_top1_switch_percentile']:.3f} |",
        "",
        "## Full Matrix Sanity Check",
        "",
        "| Metric | Baseline proxy | Corrected proxy |",
        "| --- | ---: | ---: |",
        f"| Weak groups | {base_full['weak_groups']:.0f} / {base_full['groups']:.0f} | {corr_full['weak_groups']:.0f} / {corr_full['groups']:.0f} |",
        f"| Mean Spearman | {base_full['mean_spearman']:.3f} | {corr_full['mean_spearman']:.3f} |",
        f"| Mean top-k overlap fraction | {base_full['mean_topk_overlap_fraction']:.3f} | {corr_full['mean_topk_overlap_fraction']:.3f} |",
        f"| Mean proxy-top1 switch percentile | {base_full['mean_top1_switch_percentile']:.3f} | {corr_full['mean_top1_switch_percentile']:.3f} |",
        "",
        "## Candidate Models",
        "",
        "| Model | Holdout weak | Holdout mean Spearman | Holdout mean top1 percentile |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in sorted(candidate_metrics, key=lambda item: item["model"]):
        lines.append(
            f"| {row['model']} | {row['weak_groups']:.0f} | "
            f"{row['mean_spearman']:.3f} | {row['mean_top1_switch_percentile']:.3f} |"
        )

    weak = weak_groups(corrected_test_summary)
    if weak:
        lines.extend(["", "## Remaining Weak Held-Out Groups", ""])
        for row in weak:
            lines.append(
                "- "
                f"`{row['topology']} {row['category']} {row['mode']}`: "
                f"rho `{f(row, 'spearman_proxy_vs_switch_reward'):.3f}`, "
                f"top1 percentile `{f(row, 'proxy_top1_switch_percentile'):.3f}`, "
                f"top-k overlap `{int(f(row, 'top_k_overlap'))}/{int(f(row, 'top_k'))}`"
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This is a reward-alignment repair baseline.  It improves the proxy's",
            "action-ranking signal for candidate generation, but it is not a final",
            "switch-level validation.  Any actor trained with this corrected signal",
            "still has to pass the switch-level matrix before promotion.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detail-csv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout-stride", type=int, default=5)
    parser.add_argument("--holdout-offset", type=int, default=0)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    detail_csv = args.detail_csv or latest_csv(ALIGNMENT_DIR, "reward_alignment_*_detail.csv")
    rows = read_csv(detail_csv)
    rows = [row for row in rows if np.isfinite(f(row, "proxy_return", float("nan")))]
    train_rows, test_rows = split_rows(
        rows,
        holdout_stride=args.holdout_stride,
        holdout_offset=args.holdout_offset,
    )

    categories = _categories(rows)
    x_train, feature_names = build_features(train_rows, categories)
    x_test, _ = build_features(test_rows, categories)
    x_all, _ = build_features(rows, categories)
    y_train = np.asarray(
        [f(row, "switch_reward_like") - f(row, "proxy_return") for row in train_rows],
        dtype=float,
    )

    baseline_test_summary = summarize(test_rows)
    baseline_full_summary = summarize(rows)

    candidate_metrics: list[dict[str, Any]] = []
    fitted: dict[str, Any] = {}
    corrected_by_model: dict[str, list[dict[str, Any]]] = {}
    full_corrected_by_model: dict[str, list[dict[str, Any]]] = {}
    for name, model in make_models(args.seed).items():
        model.fit(x_train, y_train)
        fitted[name] = model
        test_pred = np.asarray(model.predict(x_test), dtype=float)
        full_pred = np.asarray(model.predict(x_all), dtype=float)
        corrected_test = with_corrected_return(
            test_rows,
            np.asarray([f(row, "proxy_return") for row in test_rows], dtype=float) + test_pred,
        )
        corrected_full = with_corrected_return(
            rows,
            np.asarray([f(row, "proxy_return") for row in rows], dtype=float) + full_pred,
        )
        corrected_by_model[name] = corrected_test
        full_corrected_by_model[name] = corrected_full
        metrics = aggregate(summarize(corrected_test))
        metrics["model"] = name
        candidate_metrics.append(metrics)

    best_name = min(
        corrected_by_model,
        key=lambda name: model_score(summarize(corrected_by_model[name])),
    )
    corrected_test_detail = corrected_by_model[best_name]
    corrected_full_detail = full_corrected_by_model[best_name]
    corrected_test_summary = summarize(corrected_test_detail)
    corrected_full_summary = summarize(corrected_full_detail)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.out_dir / f"reward_correction_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    corrected_test_csv = run_dir / "corrected_holdout_detail.csv"
    corrected_test_summary_csv = run_dir / "corrected_holdout_summary.csv"
    baseline_test_summary_csv = run_dir / "baseline_holdout_summary.csv"
    corrected_full_summary_csv = run_dir / "corrected_full_summary.csv"
    candidate_csv = run_dir / "candidate_model_metrics.csv"
    report_md = run_dir / "REPORT.md"
    model_path = run_dir / "reward_correction_model.joblib"
    manifest_path = run_dir / "manifest.json"

    write_csv(corrected_test_csv, corrected_test_detail)
    write_csv(corrected_test_summary_csv, corrected_test_summary)
    write_csv(baseline_test_summary_csv, baseline_test_summary)
    write_csv(corrected_full_summary_csv, corrected_full_summary)
    write_csv(candidate_csv, candidate_metrics)
    joblib.dump(
        {
            "model": fitted[best_name],
            "model_name": best_name,
            "feature_names": feature_names,
            "categories": categories,
            "float_features": FLOAT_FEATURES,
            "string_features": STRING_FEATURES,
        },
        model_path,
    )
    write_report(
        report_md,
        detail_csv=detail_csv,
        best_model=best_name,
        baseline_test_summary=baseline_test_summary,
        corrected_test_summary=corrected_test_summary,
        baseline_full_summary=baseline_full_summary,
        corrected_full_summary=corrected_full_summary,
        candidate_metrics=candidate_metrics,
    )
    manifest = {
        "detail_csv": str(detail_csv),
        "run_dir": str(run_dir),
        "selected_model": best_name,
        "train_rows": len(train_rows),
        "holdout_rows": len(test_rows),
        "feature_count": len(feature_names),
        "baseline_holdout": aggregate(baseline_test_summary),
        "corrected_holdout": aggregate(corrected_test_summary),
        "baseline_full": aggregate(baseline_full_summary),
        "corrected_full": aggregate(corrected_full_summary),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
