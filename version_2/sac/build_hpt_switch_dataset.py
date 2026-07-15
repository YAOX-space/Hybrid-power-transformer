"""Build a compact HPT switch-level dataset from labeled Simulink sweeps."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .experiment_metadata import sha256_file, write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROXY_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_proxy_sweep"
DEFAULT_ENERGY_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_energy_sweep"
DEFAULT_FAULT_SWEEP_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_fault_fixed_reg_sweep"
DEFAULT_DATA_ROOT = ROOT / "version_2" / "data" / "hpt_switch_rollouts"

FEATURE_NAMES = [
    "topology1",
    "topology2",
    "grid_pu",
    "raw_m_reg_d",
    "raw_m_reg_q",
    "raw_m_energy_d",
    "raw_m_energy_q",
    "effective_m_reg_d",
    "effective_m_reg_q",
    "effective_m_energy_d",
    "effective_m_energy_q",
    "controller_enabled",
    "is_reg_sweep",
    "is_energy_sweep",
    "is_fault_sweep",
]

TARGET_NAMES = [
    "lv_pu_mean",
    "vdc_pu_mean",
    "vdc_min_pu",
    "vdc_max_pu",
    "lv_unbalance_pu",
    "energy_i_rms_scaled",
]


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, Any] = {}
            for key, value in raw.items():
                try:
                    row[key] = float(value)
                except (TypeError, ValueError):
                    row[key] = value
            rows.append(row)
    return rows


def val(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return float(default)
    return float(value)


def effective(row: dict[str, Any], preferred: str, fallback: str) -> float:
    return val(row, preferred, val(row, fallback, 0.0))


def featurize(row: dict[str, Any], sweep: str) -> tuple[list[float], list[float], dict[str, Any]]:
    topology = str(row.get("topology", "")).lower()
    action_semantics = str(row.get("action_semantics", ""))
    controller_enabled = 0.0 if action_semantics.startswith("controller_disabled") else 1.0
    target_phase = max(val(row, "target_phase_rms", 207.0), 1.0)
    vdc_mean = val(row, "vdc_mean", 800.0)
    if abs(vdc_mean) > 5.0:
        vdc_mean = vdc_mean / 800.0
    vdc_min = val(row, "vdc_min", 800.0)
    if abs(vdc_min) > 5.0:
        vdc_min = vdc_min / 800.0
    vdc_max = val(row, "vdc_max", 800.0)
    if abs(vdc_max) > 5.0:
        vdc_max = vdc_max / 800.0

    raw_reg_d = val(
        row,
        "raw_m_reg_d",
        val(row, "cmd_m_reg_d", val(row, "reg_d", val(row, "reg_d_mean", 0.0))),
    )
    raw_reg_q = val(row, "raw_m_reg_q", val(row, "cmd_m_reg_q", val(row, "reg_q_mean", 0.0)))
    raw_energy_d = val(
        row, "raw_m_energy_d", val(row, "cmd_m_energy_d", val(row, "energy_d_mean", 0.0))
    )
    raw_energy_q = val(
        row, "raw_m_energy_q", val(row, "cmd_m_energy_q", val(row, "energy_q_mean", 0.0))
    )

    feature = [
        1.0 if topology == "topology1" else 0.0,
        1.0 if topology == "topology2" else 0.0,
        val(row, "grid_pu", val(row, "fault_pu", val(row, "grid_V", 10000.0) / 10000.0)),
        raw_reg_d,
        raw_reg_q,
        raw_energy_d,
        raw_energy_q,
        effective(row, "effective_m_reg_d_mean", "reg_d_mean"),
        effective(row, "effective_m_reg_q_mean", "reg_q_mean"),
        effective(row, "effective_m_energy_d_mean", "energy_d_mean"),
        effective(row, "effective_m_energy_q_mean", "energy_q_mean"),
        controller_enabled,
        1.0 if sweep == "reg" else 0.0,
        1.0 if sweep == "energy" else 0.0,
        1.0 if sweep == "fault" else 0.0,
    ]
    target = [
        val(
            row,
            "lv_pu_mean",
            val(row, "lv_fault_rms_mean", val(row, "lv_rms_mean", target_phase)) / target_phase,
        ),
        vdc_mean,
        vdc_min,
        vdc_max,
        val(row, "lv_unbalance", 0.0) / target_phase,
        val(row, "energy_i_rms_mean", 0.0) / 400.0,
    ]
    meta = {
        "sweep": sweep,
        "model": str(row.get("model", "")),
        "topology": topology,
        "grid_pu": feature[2],
        "action_semantics": action_semantics,
    }
    return feature, target, meta


def split_indices(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    n_train = max(1, int(round(0.70 * n)))
    n_val = max(1, int(round(0.15 * n)))
    if n_train + n_val >= n:
        n_train = max(1, n - 2)
        n_val = 1
    return {
        "train": np.sort(idx[:n_train]),
        "val": np.sort(idx[n_train : n_train + n_val]),
        "test": np.sort(idx[n_train + n_val :]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-sweep-csv", type=Path, default=None)
    parser.add_argument("--energy-sweep-csv", type=Path, default=None)
    parser.add_argument("--fault-sweep-csv", type=Path, default=None)
    parser.add_argument("--include-fault-sweep", action="store_true")
    parser.add_argument("--proxy-sweep-dir", type=Path, default=DEFAULT_PROXY_SWEEP_DIR)
    parser.add_argument("--energy-sweep-dir", type=Path, default=DEFAULT_ENERGY_SWEEP_DIR)
    parser.add_argument("--fault-sweep-dir", type=Path, default=DEFAULT_FAULT_SWEEP_DIR)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--seed", type=int, default=20260715)
    args = parser.parse_args()

    proxy_csv = args.proxy_sweep_csv or latest_csv(args.proxy_sweep_dir, "hpt_v2_sac_proxy_sweep_*.csv")
    energy_csv = args.energy_sweep_csv or latest_csv(
        args.energy_sweep_dir, "hpt_v2_sac_energy_sweep_*.csv"
    )
    fault_csv = None
    if args.fault_sweep_csv is not None:
        fault_csv = args.fault_sweep_csv
    elif args.include_fault_sweep:
        fault_csv = latest_csv(args.fault_sweep_dir, "hpt_v2_fault_fixed_reg_sweep_*.csv")
    features: list[list[float]] = []
    targets: list[list[float]] = []
    metas: list[dict[str, Any]] = []
    for row in read_rows(proxy_csv):
        x, y, meta = featurize(row, "reg")
        features.append(x)
        targets.append(y)
        metas.append(meta)
    for row in read_rows(energy_csv):
        x, y, meta = featurize(row, "energy")
        features.append(x)
        targets.append(y)
        metas.append(meta)
    if fault_csv is not None:
        for row in read_rows(fault_csv):
            x, y, meta = featurize(row, "fault")
            features.append(x)
            targets.append(y)
            metas.append(meta)

    X = np.asarray(features, dtype=np.float32)
    Y = np.asarray(targets, dtype=np.float32)
    splits = split_indices(X.shape[0], args.seed)
    run_id = args.run_id or f"hpt_switch_dataset_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_dir / "dataset.npz",
        X=X,
        Y=Y,
        train_idx=splits["train"],
        val_idx=splits["val"],
        test_idx=splits["test"],
        feature_names=np.asarray(FEATURE_NAMES, dtype=object),
        target_names=np.asarray(TARGET_NAMES, dtype=object),
    )
    row_meta_path = out_dir / "row_meta.json"
    row_meta_path.write_text(json.dumps(metas, indent=2), encoding="utf-8")
    manifest = {
        "schema": "hpt-v2-switch-dataset-v1",
        "run_id": run_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "proxy_sweep_csv": str(proxy_csv),
        "energy_sweep_csv": str(energy_csv),
        "fault_sweep_csv": str(fault_csv) if fault_csv is not None else None,
        "proxy_sweep_hash": sha256_file(proxy_csv),
        "energy_sweep_hash": sha256_file(energy_csv),
        "fault_sweep_hash": sha256_file(fault_csv) if fault_csv is not None else None,
        "dataset_npz": str(out_dir / "dataset.npz"),
        "row_meta_json": str(row_meta_path),
        "feature_names": FEATURE_NAMES,
        "target_names": TARGET_NAMES,
        "row_count": int(X.shape[0]),
        "split_counts": {name: int(len(idx)) for name, idx in splits.items()},
        "topologies": sorted({m["topology"] for m in metas}),
        "sweeps": sorted({m["sweep"] for m in metas}),
        "action_semantics": sorted({m["action_semantics"] for m in metas if m["action_semantics"]}),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_switch_dataset_build",
        config={
            "seed": args.seed,
            "proxy_sweep_csv": str(proxy_csv),
            "energy_sweep_csv": str(energy_csv),
            "fault_sweep_csv": str(fault_csv) if fault_csv is not None else None,
        },
        dataset_manifest=out_dir / "manifest.json",
        extra={"manifest": manifest},
    )
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
