"""Relabel HPT switch-level traces with the runtime-selector teacher.

The input trace should contain ``obs_01..obs_24`` rows collected from a
closed-loop actor rollout.  This script evaluates the same base/deep actor
selection rule used by ``add_hpt_sac_controller.m`` and writes a new CSV whose
``actor_action_01..04`` columns contain teacher actions for those visited
states.  It is intended for DAgger-style repair, where the dataset state
distribution comes from a candidate actor but labels come from the safer
runtime selector.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hpt_frt.device.model_io import load_sac
from version_2.sac.experiment_metadata import write_experiment_metadata
from version_2.sac.hpt_voltage_sac_env import ACT_DIM_HPT, OBS_DIM_HPT


RESULTS = ROOT / "lab" / "results" / "hpt_trace_relabels"


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def ensure_field(fields: list[str], name: str) -> None:
    if name not in fields:
        fields.append(name)


def obs_from_row(row: dict[str, str]) -> np.ndarray:
    return np.asarray(
        [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM_HPT + 1)],
        dtype=np.float32,
    )


def runtime_selector_uses_deep(obs: np.ndarray, *, threshold: float) -> bool:
    # MATLAB obs order:
    # obs_02 = normalized grid positive-sequence voltage,
    # obs_15 = topology1 flag,
    # obs_17 = fault-active estimate,
    # obs_18 = recovery-active estimate,
    # obs_21 = remembered minimum grid positive-sequence voltage.
    topology1 = float(obs[14]) >= 0.5
    g_vpos = float(obs[1])
    fault_active = float(obs[16]) >= 0.5
    recovery_active = float(obs[17]) >= 0.5
    v_fault_min = float(obs[20])
    return bool(
        topology1
        and ((g_vpos <= threshold) or (v_fault_min <= threshold))
        and (fault_active or recovery_active)
    )


def predict_action(model: Any, obs: np.ndarray) -> np.ndarray:
    action, _ = model.predict(obs, deterministic=True)
    action = np.asarray(action, dtype=np.float32).reshape(-1)
    if action.size != ACT_DIM_HPT:
        raise ValueError(f"Expected {ACT_DIM_HPT}-D action, got {action.shape}")
    return action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-csv", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--deep-model", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.885)
    parser.add_argument("--out-dir", type=Path, default=RESULTS)
    args = parser.parse_args()

    trace_csv = args.trace_csv.resolve()
    base_model_path = args.base_model.resolve()
    deep_model_path = args.deep_model.resolve()
    if not trace_csv.exists():
        raise FileNotFoundError(trace_csv)
    if not base_model_path.exists():
        raise FileNotFoundError(base_model_path)
    if not deep_model_path.exists():
        raise FileNotFoundError(deep_model_path)

    fields, rows = read_rows(trace_csv)
    for idx in range(1, ACT_DIM_HPT + 1):
        ensure_field(fields, f"teacher_selector_action_{idx:02d}")
        ensure_field(fields, f"original_actor_action_{idx:02d}")
        ensure_field(fields, f"actor_action_{idx:02d}")
        ensure_field(fields, f"action_{idx:02d}")
    ensure_field(fields, "teacher_selector_branch")
    ensure_field(fields, "teacher_selector_threshold")

    base_model = load_sac(base_model_path, device="cpu")
    deep_model = load_sac(deep_model_path, device="cpu")

    deep_count = 0
    for row in rows:
        obs = obs_from_row(row)
        use_deep = runtime_selector_uses_deep(obs, threshold=args.threshold)
        if use_deep:
            deep_count += 1
        action = predict_action(deep_model if use_deep else base_model, obs)
        for idx, value in enumerate(action, start=1):
            original = row.get(f"actor_action_{idx:02d}", "")
            row[f"original_actor_action_{idx:02d}"] = original
            row[f"teacher_selector_action_{idx:02d}"] = f"{float(value):.12g}"
            row[f"actor_action_{idx:02d}"] = f"{float(value):.12g}"
            row[f"action_{idx:02d}"] = f"{float(value):.12g}"
        row["teacher_selector_branch"] = "deep" if use_deep else "base"
        row["teacher_selector_threshold"] = f"{args.threshold:.12g}"

    run_dir = args.out_dir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out_csv = run_dir / "runtime_selector_relabel_trace.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "schema": "hpt-runtime-selector-relabel-v1",
        "run_id": args.run_id,
        "trace_csv": str(trace_csv),
        "base_model": str(base_model_path),
        "deep_model": str(deep_model_path),
        "threshold": args.threshold,
        "row_count": len(rows),
        "deep_branch_count": deep_count,
        "base_branch_count": len(rows) - deep_count,
        "out_csv": str(out_csv),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_runtime_selector_trace_relabel",
        config={
            "threshold": args.threshold,
            "trace_csv": str(trace_csv),
            "base_model": str(base_model_path),
            "deep_model": str(deep_model_path),
        },
        dataset_manifest=trace_csv,
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
