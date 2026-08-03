"""Distill per-case topology2 balanced LVRT successes into one family SAC.

This campaign is deliberately *not* an automatic profile selector.  It uses
previous switch-level passing per-case actors only as a source of trajectory
data, trains one fixed family actor, optionally applies conservative
gate-aware SAC fine-tuning, and then validates that single actor on the family
matrix.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from version_2.sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ACT_DIM,
    COMMON_MODEL_PARAMS,
    OBS_DIM,
    ROOT,
    SIMULINK,
    TRACE_DIR,
    BoundaryCase,
    _matlab_string,
    _matlab_struct,
    build_anchor_from_trace,
    export_actor_for_simulink,
    latest_file,
    matlab_evaluate_actor,
    read_comparison_rows,
    run_logged,
    write_csv,
)

RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"


def make_cases(depths: list[float], durations_ms: list[int]) -> list[BoundaryCase]:
    return [
        BoundaryCase(depth, duration_ms / 1000.0)
        for depth in depths
        for duration_ms in durations_ms
    ]


def parse_float_list(raw: str) -> list[float]:
    return [float(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "pass", "passed"}


def choose_passing_teachers(summary_json: Path) -> list[dict]:
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    chosen: list[dict] = []
    for case in summary.get("cases", []):
        candidates = [
            ("sac_finetune", Path(case["sac_finetune_model"]), Path(case["sac_finetune_eval_csv"])),
            ("dq_seed", Path(case["dq_seed_model"]), Path(case["dq_seed_eval_csv"])),
        ]
        selected: dict | None = None
        for source, model_path, eval_csv in candidates:
            with eval_csv.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            actor_rows = [row for row in rows if str(row.get("mode")) == "sac_actor_always_raw"]
            if actor_rows and parse_bool(actor_rows[0].get("voltage_survival_pass")):
                selected = {
                    "label": case["label"],
                    "case": case["case"],
                    "teacher_source": source,
                    "model_path": str(model_path),
                    "eval_csv": str(eval_csv),
                    "teacher_pass_row": actor_rows[0],
                }
                break
        if selected is None:
            raise RuntimeError(f"No passing teacher found for {case.get('label')}")
        chosen.append(selected)
    return chosen


def collect_actor_trace(
    teacher: dict,
    run_dir: Path,
    *,
    fault_start_s: float,
    sample_stride: int,
    actor_filter_tau: float,
) -> Path:
    model_path = Path(teacher["model_path"])
    label = f"family_teacher_{teacher['teacher_source']}_{teacher['label']}"
    case = teacher["case"]
    export_actor_for_simulink(model_path, run_dir, label)
    runner = run_dir / f"collect_{label}.m"
    runner.write_text(
        "\n".join(
            [
                f"cd('{_matlab_string(ROOT)}');",
                f"addpath(genpath('{_matlab_string(SIMULINK)}'));",
                'hpt_trace_topology = "topology2";',
                f"hpt_trace_fault_pu = {float(case['fault_pu']):.12g};",
                f"hpt_trace_fault_duration = {float(case['duration_s']):.12g};",
                f"hpt_trace_fault_start = {fault_start_s:.12g};",
                "hpt_trace_fault_stop_margin = 0.125;",
                "hpt_trace_policy_mode = 1.0;",
                "hpt_trace_actor_select_mode = 3.0;",
                f"hpt_trace_actor_filter_tau = {actor_filter_tau:.12g};",
                f"hpt_trace_model_params = {_matlab_struct(COMMON_MODEL_PARAMS)};",
                f'hpt_trace_run_label = "{label}";',
                f"hpt_trace_sample_stride = {int(sample_stride)};",
                f"run('{_matlab_string(SIMULINK / 'collectors' / 'collect_hpt_v2_trajectory_trace.m')}');",
            ]
        ),
        encoding="utf-8",
    )
    before = time.time()
    run_logged(
        ["matlab", "-batch", f"run('{_matlab_string(runner)}')"],
        cwd=ROOT,
        log_path=run_dir / f"{label}_collect.log",
    )
    return latest_file(
        f"trajectory_trace_topology2_{label}_*.csv",
        after=before,
        directory=TRACE_DIR,
    )


def combine_raw_anchor_datasets(anchor_files: list[Path], out_npz: Path, out_json: Path) -> dict:
    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    sources: list[dict] = []
    for anchor in anchor_files:
        data = np.load(anchor)
        obs = np.asarray(data["observations"], dtype=np.float32)
        actions = np.asarray(data["actions"], dtype=np.float32)
        if obs.ndim != 2 or obs.shape[1] != OBS_DIM:
            raise RuntimeError(f"Bad observations in {anchor}: {obs.shape}")
        if actions.ndim != 2 or actions.shape[1] != ACT_DIM:
            raise RuntimeError(f"Bad actions in {anchor}: {actions.shape}")
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
    actions = np.concatenate(action_parts, axis=0)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_npz, observations=observations, actions=actions)
    summary = {
        "schema": "hpt_t2_balanced_lvrt_family_distilled_anchor_v1",
        "dataset": str(out_npz),
        "samples": int(observations.shape[0]),
        "source_count": len(anchor_files),
        "sources": sources,
        "action_mean": [float(v) for v in np.mean(actions, axis=0)],
        "action_min": [float(v) for v in np.min(actions, axis=0)],
        "action_max": [float(v) for v in np.max(actions, axis=0)],
        "teacher_source": "switch_level_passing_per_case_actor_traces",
        "deployment_note": "one fixed actor is trained from these traces; no runtime profile selection",
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def train_family_bc_actor(
    anchor_npz: Path,
    run_dir: Path,
    *,
    bc_epochs: int,
    train_depths: list[float],
    train_durations_ms: list[int],
    fault_start_s: float,
) -> Path:
    model_out = MODELS / f"hpt_t2_bal_lvrt_family_distilled_bc_{run_dir.name}.zip"
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
        "8e-5",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "10,10,18,18",
        "--eval-rollouts",
        "0",
        "--run-id",
        f"{run_dir.name}_family_distilled_bc",
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_distilled_bc_train.log")
    return model_out


def train_family_gate_sac_actor(
    seed_model: Path,
    anchor_npz: Path,
    run_dir: Path,
    *,
    sac_steps: int,
    train_depths: list[float],
    train_durations_ms: list[int],
    fault_start_s: float,
) -> Path:
    model_out = MODELS / f"hpt_t2_bal_lvrt_family_distilled_gate_sac_{run_dir.name}.zip"
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
        "1e-8",
        "--sac-support-regularization-weight",
        "40000",
        "--sac-support-regularization-batch-size",
        "512",
        "--sac-support-anchor-dataset",
        str(anchor_npz),
        "--sac-support-action-weights",
        "30,30,80,80",
        "--sac-support-nearest-replay",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        "4",
        "--behavior-anchor-interval-steps",
        "80",
        "--behavior-anchor-lr",
        "8e-6",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "24,24,70,70",
        "--eval-rollouts",
        "0",
        "--run-id",
        f"{run_dir.name}_family_distilled_gate_sac",
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--grid-current-reward-weight",
        "150",
        "--grid-current-margin-reward-weight",
        "900",
        "--grid-current-margin-pu",
        "0.10",
        "--grid-reactive-reward-weight",
        "0",
        "--envelope-reward-weight",
        "1400",
        "--lv-margin-reward-weight",
        "2600",
        "--lv-margin-pu",
        "0.025",
        "--calibrated-survival-reward-weight",
        "18000",
        "--vdc-soft-reward-weight",
        "360",
        "--vdc-bounds-reward-weight",
        "120000",
        "--vdc-margin-reward-weight",
        "65000",
        "--vdc-margin-pu",
        "0.06",
        "--action-slew-weight",
        "0.22",
        "--calibration-ood-reward-weight",
        "80",
        "--proxy-vdc-reward-downshift-pu",
        "0.20",
        "--proxy-grid-current-reward-upshift-pu",
        "0.32",
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_distilled_gate_sac_train.log")
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
    def f(value: object) -> float:
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return float("nan")

    summary: dict[str, dict] = {}
    controllers = sorted({str(row.get("controller") or "") for row in rows})
    for controller in controllers:
        subset = [row for row in rows if str(row.get("controller") or "") == controller]
        actor_subset = [
            row for row in subset
            if str(row.get("mode") or "") != "conventional_dq" or controller == "strong_dq"
        ]
        pass_count = sum(parse_bool(row.get("voltage_survival_pass")) for row in actor_subset)
        count = len(actor_subset)
        summary[controller] = {
            "count": count,
            "voltage_survival_pass_count": pass_count,
            "voltage_survival_pass_rate": pass_count / count if count else 0.0,
            "mean_score": float(np.nanmean([f(row.get("control_score")) for row in actor_subset])) if count else float("nan"),
            "vdc_pass_count": sum(parse_bool(row.get("gbt_vdc_survive_pass")) for row in actor_subset),
            "grid_current_pass_count": sum(parse_bool(row.get("gbt_grid_current_limit_pass")) for row in actor_subset),
            "lv_envelope_pass_count": sum(parse_bool(row.get("gbt_voltage_envelope_pass")) for row in actor_subset),
            "recovery_pass_count": sum(parse_bool(row.get("recovery_envelope_pass")) for row in actor_subset),
            "action_limit_pass_count": sum(parse_bool(row.get("gbt_action_limit_pass")) for row in actor_subset),
            "full_frt_pass_count": sum(parse_bool(row.get("full_frt_pass")) for row in actor_subset),
        }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-summary-json",
        type=Path,
        default=RESULTS / "hpt_t2_bal_lvrt_dqseed_energy_safe_2x2_20260731" / "campaign_summary.json",
    )
    parser.add_argument("--run-id", default=f"hpt_t2_bal_lvrt_family_distill_sac_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--train-depths", default="0.875,0.9")
    parser.add_argument("--train-durations-ms", default="100,120")
    parser.add_argument("--eval-depths", default="0.875,0.9")
    parser.add_argument("--eval-durations-ms", default="100,120")
    parser.add_argument("--fault-start-s", type=float, default=0.08)
    parser.add_argument("--anchor-min-time-s", type=float, default=0.02)
    parser.add_argument("--bc-epochs", type=int, default=700)
    parser.add_argument("--sac-steps", type=int, default=1600)
    parser.add_argument("--sample-stride", type=int, default=100)
    parser.add_argument("--actor-filter-tau", type=float, default=0.001)
    parser.add_argument("--skip-sac", action="store_true")
    args = parser.parse_args()

    train_depths = parse_float_list(args.train_depths)
    train_durations = parse_int_list(args.train_durations_ms)
    eval_cases = make_cases(parse_float_list(args.eval_depths), parse_int_list(args.eval_durations_ms))

    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    teachers = choose_passing_teachers(args.source_summary_json)
    (run_dir / "chosen_teachers.json").write_text(json.dumps(teachers, indent=2), encoding="utf-8")

    anchor_files: list[Path] = []
    trace_records: list[dict] = []
    for teacher in teachers:
        teacher_dir = run_dir / "teacher_traces" / teacher["label"]
        teacher_dir.mkdir(parents=True, exist_ok=True)
        trace_csv = collect_actor_trace(
            teacher,
            teacher_dir,
            fault_start_s=args.fault_start_s,
            sample_stride=args.sample_stride,
            actor_filter_tau=args.actor_filter_tau,
        )
        anchor_npz = teacher_dir / f"{teacher['label']}_{teacher['teacher_source']}_actor_anchor.npz"
        anchor_json = teacher_dir / f"{teacher['label']}_{teacher['teacher_source']}_actor_anchor.json"
        anchor_summary = build_anchor_from_trace(
            trace_csv,
            anchor_npz,
            anchor_json,
            min_time_s=args.anchor_min_time_s,
            prefault_repeat=2,
            fault_repeat=14,
            recovery_repeat=9,
            tail_repeat=1,
        )
        anchor_files.append(anchor_npz)
        trace_records.append(
            {
                "teacher": teacher,
                "trace_csv": str(trace_csv),
                "anchor_npz": str(anchor_npz),
                "anchor": anchor_summary,
            }
        )

    family_anchor = run_dir / "family_distilled_actor_anchor.npz"
    family_anchor_json = run_dir / "family_distilled_actor_anchor.json"
    family_anchor_summary = combine_raw_anchor_datasets(anchor_files, family_anchor, family_anchor_json)
    family_anchor_summary["teacher_traces"] = trace_records
    family_anchor_json.write_text(json.dumps(family_anchor_summary, indent=2), encoding="utf-8")

    bc_model = train_family_bc_actor(
        family_anchor,
        run_dir,
        bc_epochs=args.bc_epochs,
        train_depths=train_depths,
        train_durations_ms=train_durations,
        fault_start_s=args.fault_start_s,
    )
    rows = evaluate_actor_matrix(
        eval_cases,
        bc_model,
        run_dir / "eval_family_bc",
        export_tag="family_distilled_bc",
        controller_label="family_distilled_bc",
        fault_start_s=args.fault_start_s,
    )

    sac_model: Path | None = None
    if not args.skip_sac and args.sac_steps > 0:
        sac_model = train_family_gate_sac_actor(
            bc_model,
            family_anchor,
            run_dir,
            sac_steps=args.sac_steps,
            train_depths=train_depths,
            train_durations_ms=train_durations,
            fault_start_s=args.fault_start_s,
        )
        rows.extend(
            evaluate_actor_matrix(
                eval_cases,
                sac_model,
                run_dir / "eval_family_gate_sac",
                export_tag="family_distilled_gate_sac",
                controller_label="family_distilled_gate_sac",
                fault_start_s=args.fault_start_s,
            )
        )

    summary_csv = run_dir / "boundary_summary.csv"
    write_csv(summary_csv, rows)
    summary_json = run_dir / "summary.json"
    summary = summarize_rows(rows, summary_json)
    manifest = {
        "schema": "hpt_t2_balanced_lvrt_family_distill_sac_campaign_v1",
        "run_id": args.run_id,
        "source_summary_json": str(args.source_summary_json),
        "family_anchor": str(family_anchor),
        "family_anchor_json": str(family_anchor_json),
        "bc_model": str(bc_model),
        "sac_model": str(sac_model) if sac_model else None,
        "boundary_summary_csv": str(summary_csv),
        "summary_json": str(summary_json),
        "summary": summary,
        "no_profile_selection": True,
    }
    (run_dir / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copy2(summary_csv, run_dir / "latest_boundary_summary.csv")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
