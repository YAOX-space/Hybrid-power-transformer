"""Family-level topology2 balanced LVRT gate-aware SAC campaign.

This campaign intentionally trains one actor for a small LVRT family instead of
one actor per fault point.  It avoids automatic profile selection: the exported
candidate is a single fixed policy produced by the gate-aware SAC fine-tune.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from version_2.sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ACT_DIM,
    BoundaryCase,
    OBS_DIM,
    ROOT,
    RESULTS,
    MODELS,
    build_anchor_from_trace,
    export_actor_for_simulink,
    matlab_collect_dq_trace,
    matlab_evaluate_actor,
    read_comparison_rows,
    run_logged,
    write_csv,
)


def parse_float_list(raw: str) -> list[float]:
    return [float(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def make_cases(depths: list[float], durations_ms: list[int]) -> list[BoundaryCase]:
    return [BoundaryCase(depth, duration_ms / 1000.0) for depth in depths for duration_ms in durations_ms]


def apply_calibrated_energy_targets(
    observations: np.ndarray,
    actions: np.ndarray,
    *,
    energy_d_fault: float = 0.0,
    energy_q_fault: float = 0.80,
) -> tuple[np.ndarray, dict]:
    """Inject calibration-derived energy support into dq-regulation anchors.

    The strong dq trace is still used for the regulating branch.  The energy
    branch target is replaced only during fault/recovery observations, using the
    sign and magnitude identified by the aligned topology2 energy-branch probe.
    This avoids hand-search pre-ramp profiles while preventing BC/support loss
    from pinning the energy head at zero.
    """

    if observations.shape[1] != OBS_DIM or actions.shape[1] != ACT_DIM:
        raise RuntimeError(
            f"Bad family anchor shape for energy augmentation: "
            f"obs={observations.shape}, actions={actions.shape}"
        )
    augmented = np.array(actions, copy=True)
    fault_active = observations[:, 16] > 0.5
    recovery_active = observations[:, 17] > 0.5
    active = fault_active | recovery_active
    before = np.array(actions[:, 2:4], copy=True)
    augmented[active, 2] = float(energy_d_fault)
    augmented[active, 3] = float(energy_q_fault)
    delta = augmented[:, 2:4] - before
    summary = {
        "schema": "hpt_family_energy_augmented_anchor_v1",
        "source": "aligned_topology2_energy_branch_probe",
        "active_samples": int(np.count_nonzero(active)),
        "total_samples": int(actions.shape[0]),
        "energy_d_fault_target": float(energy_d_fault),
        "energy_q_fault_target": float(energy_q_fault),
        "mean_energy_delta": [float(v) for v in np.mean(delta, axis=0)],
        "max_abs_energy_delta": [float(v) for v in np.max(np.abs(delta), axis=0)],
    }
    return augmented, summary


def combine_anchor_datasets(anchor_files: list[Path], out_npz: Path, out_json: Path) -> dict:
    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    sources: list[dict] = []
    for anchor in anchor_files:
        data = np.load(anchor)
        obs = np.asarray(data["observations"], dtype=np.float32)
        actions = np.asarray(data["actions"], dtype=np.float32)
        if obs.ndim != 2 or actions.ndim != 2:
            raise RuntimeError(f"Bad anchor shape in {anchor}: {obs.shape}, {actions.shape}")
        obs_parts.append(obs)
        action_parts.append(actions)
        sources.append(
            {
                "path": str(anchor),
                "samples": int(obs.shape[0]),
                "action_mean": [float(v) for v in np.mean(actions, axis=0)],
                "action_min": [float(v) for v in np.min(actions, axis=0)],
                "action_max": [float(v) for v in np.max(actions, axis=0)],
            }
        )
    observations = np.concatenate(obs_parts, axis=0)
    raw_actions = np.concatenate(action_parts, axis=0)
    actions, energy_summary = apply_calibrated_energy_targets(observations, raw_actions)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        observations=observations,
        actions=actions,
        raw_dq_actions=raw_actions,
    )
    summary = {
        "schema": "hpt_family_anchor_dataset_v1",
        "dataset": str(out_npz),
        "samples": int(observations.shape[0]),
        "source_count": len(anchor_files),
        "sources": sources,
        "energy_augmentation": energy_summary,
        "action_mean": [float(v) for v in np.mean(actions, axis=0)],
        "action_min": [float(v) for v in np.min(actions, axis=0)],
        "action_max": [float(v) for v in np.max(actions, axis=0)],
        "raw_dq_action_mean": [float(v) for v in np.mean(raw_actions, axis=0)],
        "teacher_source": "strong_conventional_dq_regulation_plus_calibrated_energy_support",
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def collect_family_anchor(
    train_cases: list[BoundaryCase],
    run_dir: Path,
    *,
    fault_start_s: float,
    anchor_min_time_s: float,
) -> tuple[Path, dict]:
    anchor_files: list[Path] = []
    per_case: list[dict] = []
    for case in train_cases:
        case_dir = run_dir / "anchors" / case.label
        case_dir.mkdir(parents=True, exist_ok=True)
        trace_csv = matlab_collect_dq_trace(case, case_dir, fault_start_s=fault_start_s)
        anchor_npz = case_dir / f"{case.label}_dq_anchor.npz"
        anchor_json = case_dir / f"{case.label}_dq_anchor.json"
        summary = build_anchor_from_trace(
            trace_csv,
            anchor_npz,
            anchor_json,
            min_time_s=anchor_min_time_s,
            prefault_repeat=2,
            fault_repeat=12,
            recovery_repeat=8,
            tail_repeat=1,
        )
        anchor_files.append(anchor_npz)
        per_case.append({"case": asdict(case), "trace_csv": str(trace_csv), "anchor": summary})
    family_npz = run_dir / "family_dq_anchor.npz"
    family_json = run_dir / "family_dq_anchor.json"
    family_summary = combine_anchor_datasets(anchor_files, family_npz, family_json)
    family_summary["per_case"] = per_case
    family_json.write_text(json.dumps(family_summary, indent=2), encoding="utf-8")
    return family_npz, family_summary


def train_family_seed_actor(
    anchor_npz: Path,
    run_dir: Path,
    *,
    bc_epochs: int,
    seed: int,
    fault_start_s: float,
    train_depths: list[float],
    train_durations_ms: list[int],
) -> Path:
    model_out = MODELS / f"hpt_t2_bal_lvrt_family_gate_seed_{run_dir.name}.zip"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--family-topology",
        "topology2",
        "--family-fault-pus",
        ",".join(f"{value:.6g}" for value in train_depths),
        "--family-fault-durations-ms",
        ",".join(str(value) for value in train_durations_ms),
        "--family-fault-start-s",
        f"{fault_start_s:.12g}",
        "--family-category",
        "LVRT",
        "--family-phase-key",
        "abc",
        "--controller-heads",
        "split",
        "--steps",
        "1",
        "--n-envs",
        "1",
        "--learning-rate",
        "1e-9",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        str(bc_epochs),
        "--behavior-anchor-interval-steps",
        "1",
        "--behavior-anchor-lr",
        "1e-4",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "8,6,12,12",
        "--eval-rollouts",
        "0",
        "--run-id",
        f"{run_dir.name}_family_seed",
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_seed_train.log")
    return model_out


def train_family_gate_sac(
    seed_model: Path,
    anchor_npz: Path,
    run_dir: Path,
    *,
    sac_steps: int,
    seed: int,
    fault_start_s: float,
    train_depths: list[float],
    train_durations_ms: list[int],
) -> Path:
    model_out = MODELS / f"hpt_t2_bal_lvrt_family_gate_sac_{run_dir.name}.zip"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--family-topology",
        "topology2",
        "--family-fault-pus",
        ",".join(f"{value:.6g}" for value in train_depths),
        "--family-fault-durations-ms",
        ",".join(str(value) for value in train_durations_ms),
        "--family-fault-start-s",
        f"{fault_start_s:.12g}",
        "--family-category",
        "LVRT",
        "--family-phase-key",
        "abc",
        "--controller-heads",
        "split",
        "--init-model",
        str(seed_model),
        "--steps",
        str(sac_steps),
        "--n-envs",
        "4",
        "--learning-rate",
        "3e-8",
        "--sac-support-regularization-weight",
        "9000",
        "--sac-support-regularization-batch-size",
        "256",
        "--sac-support-anchor-dataset",
        str(anchor_npz),
        "--sac-support-action-weights",
        "28,24,3,3",
        "--sac-support-nearest-replay",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        "8",
        "--behavior-anchor-interval-steps",
        "120",
        "--behavior-anchor-lr",
        "1.0e-5",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "24,20,2,2",
        "--eval-rollouts",
        "0",
        "--run-id",
        f"{run_dir.name}_family_gate_sac",
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--grid-current-reward-weight",
        "140",
        "--grid-current-margin-reward-weight",
        "650",
        "--grid-current-margin-pu",
        "0.08",
        "--grid-reactive-reward-weight",
        "0",
        "--envelope-reward-weight",
        "1200",
        "--lv-margin-reward-weight",
        "2200",
        "--lv-margin-pu",
        "0.025",
        "--calibrated-survival-reward-weight",
        "15000",
        "--vdc-soft-reward-weight",
        "320",
        "--vdc-bounds-reward-weight",
        "90000",
        "--vdc-margin-reward-weight",
        "45000",
        "--vdc-margin-pu",
        "0.055",
        "--action-slew-weight",
        "0.18",
        "--calibration-ood-reward-weight",
        "60",
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_gate_sac_train.log")
    return model_out


def evaluate_actor_matrix(
    cases: list[BoundaryCase],
    model_path: Path,
    run_dir: Path,
    *,
    export_tag: str,
    controller_label: str,
    fault_start_s: float,
) -> list[dict]:
    actor_archive = export_actor_for_simulink(model_path, run_dir, export_tag)
    rows: list[dict] = []
    for case in cases:
        csv_path = matlab_evaluate_actor(
            case,
            run_dir,
            tag=f"{export_tag}_{case.label}",
            fault_start_s=fault_start_s,
        )
        for row in read_comparison_rows(csv_path, controller_label=controller_label):
            row["family_eval_label"] = case.label
            row["family_fault_pu"] = f"{case.fault_pu:.6g}"
            row["family_duration_ms"] = str(case.duration_ms)
            row["actor_archive"] = str(actor_archive)
            rows.append(row)
    return rows


def summarize_rows(rows: list[dict], out_path: Path) -> dict:
    def parse_pass(value: object) -> bool:
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "pass", "passed"}

    def parse_float(value: object) -> float:
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return float("nan")

    controllers = sorted({str(row.get("controller") or "") for row in rows})
    summary: dict[str, dict] = {}
    for controller in controllers:
        subset = [row for row in rows if str(row.get("controller") or "") == controller]
        pass_count = sum(parse_pass(row.get("voltage_survival_pass")) for row in subset)
        envelope_count = sum(parse_pass(row.get("envelope_pass")) for row in subset)
        recovery_count = sum(parse_pass(row.get("recovery_envelope_pass")) for row in subset)
        vdc_count = sum(parse_pass(row.get("gbt_vdc_survive_pass")) for row in subset)
        current_count = sum(parse_pass(row.get("gbt_grid_current_limit_pass")) for row in subset)
        scores = [parse_float(row.get("control_score")) for row in subset]
        vdc_min = [parse_float(row.get("vdc_min")) for row in subset]
        current_peak = [parse_float(row.get("grid_current_peak_pu")) for row in subset]
        summary[controller] = {
            "rows": len(subset),
            "pass_count": int(pass_count),
            "envelope_pass_count": int(envelope_count),
            "recovery_pass_count": int(recovery_count),
            "vdc_pass_count": int(vdc_count),
            "grid_current_pass_count": int(current_count),
            "score_mean": float(np.nanmean(scores)) if scores else float("nan"),
            "score_min": float(np.nanmin(scores)) if scores else float("nan"),
            "score_max": float(np.nanmax(scores)) if scores else float("nan"),
            "vdc_min_min_v": float(np.nanmin(vdc_min)) if vdc_min else float("nan"),
            "vdc_min_mean_v": float(np.nanmean(vdc_min)) if vdc_min else float("nan"),
            "grid_current_peak_max_pu": float(np.nanmax(current_peak))
            if current_peak
            else float("nan"),
        }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--train-depths", default="0.875,0.90")
    parser.add_argument("--train-durations-ms", default="100,120")
    parser.add_argument("--eval-depths", default=None)
    parser.add_argument("--eval-durations-ms", default=None)
    parser.add_argument("--bc-epochs", type=int, default=140)
    parser.add_argument("--sac-steps", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--fault-start-s", type=float, default=0.080)
    parser.add_argument("--anchor-min-time-s", type=float, default=0.020)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--family-anchor", type=Path, default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_t2_bal_lvrt_family_gate_sac_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    train_depths = parse_float_list(args.train_depths)
    train_durations_ms = parse_int_list(args.train_durations_ms)
    eval_depths = parse_float_list(args.eval_depths or args.train_depths)
    eval_durations_ms = parse_int_list(args.eval_durations_ms or args.train_durations_ms)
    train_cases = make_cases(train_depths, train_durations_ms)
    eval_cases = make_cases(eval_depths, eval_durations_ms)

    metadata = {
        "run_id": run_id,
        "hypothesis": (
            "A single topology2 balanced LVRT family-level split-head SAC actor, "
            "trained with gate-aware margin rewards and switch-trace support, "
            "can pass more switch-level voltage-survival cases than strong dq "
            "without automatic profile selection."
        ),
        "topology": "topology2",
        "fault_family": "balanced_lvrt",
        "train_cases": [{**asdict(case), "label": case.label} for case in train_cases],
        "eval_cases": [{**asdict(case), "label": case.label} for case in eval_cases],
        "bc_epochs": int(args.bc_epochs),
        "sac_steps": int(args.sac_steps),
        "seed": int(args.seed),
        "fault_start_s": float(args.fault_start_s),
        "anchor_min_time_s": float(args.anchor_min_time_s),
        "profile_selection": "disabled",
        "sac_mode": "single_fixed_family_actor_full_head",
    }
    (run_dir / "campaign_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    if args.skip_collect:
        if args.family_anchor is None:
            raise ValueError("--skip-collect requires --family-anchor")
        family_anchor = args.family_anchor
        anchor_summary = {"dataset": str(family_anchor), "reused": True}
    else:
        family_anchor, anchor_summary = collect_family_anchor(
            train_cases,
            run_dir,
            fault_start_s=args.fault_start_s,
            anchor_min_time_s=args.anchor_min_time_s,
        )

    seed_model = train_family_seed_actor(
        family_anchor,
        run_dir,
        bc_epochs=args.bc_epochs,
        seed=args.seed,
        fault_start_s=args.fault_start_s,
        train_depths=train_depths,
        train_durations_ms=train_durations_ms,
    )
    seed_rows = evaluate_actor_matrix(
        eval_cases,
        seed_model,
        run_dir / "eval_seed",
        export_tag="family_seed",
        controller_label="family_dq_seed_before_sac",
        fault_start_s=args.fault_start_s,
    )

    sac_model = train_family_gate_sac(
        seed_model,
        family_anchor,
        run_dir,
        sac_steps=args.sac_steps,
        seed=args.seed + 1000,
        fault_start_s=args.fault_start_s,
        train_depths=train_depths,
        train_durations_ms=train_durations_ms,
    )
    sac_rows = evaluate_actor_matrix(
        eval_cases,
        sac_model,
        run_dir / "eval_sac",
        export_tag="family_gate_sac",
        controller_label="family_gate_sac_after_finetune",
        fault_start_s=args.fault_start_s,
    )

    rows = seed_rows + sac_rows
    write_csv(run_dir / "family_gate_sac_comparison_rows.csv", rows)
    summary = summarize_rows(rows, run_dir / "family_gate_sac_summary.json")
    final = {
        "metadata": metadata,
        "anchor_summary": anchor_summary,
        "family_anchor": str(family_anchor),
        "seed_model": str(seed_model),
        "sac_model": str(sac_model),
        "summary": summary,
        "comparison_csv": str(run_dir / "family_gate_sac_comparison_rows.csv"),
    }
    (run_dir / "campaign_summary.json").write_text(
        json.dumps(final, indent=2),
        encoding="utf-8",
    )
    shutil.copy2(seed_model.with_suffix(".json"), run_dir / "seed_model_summary.json")
    shutil.copy2(sac_model.with_suffix(".json"), run_dir / "sac_model_summary.json")
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2), flush=True)


if __name__ == "__main__":
    main()
