"""Train and validate one actor per HPT fault family.

This script repairs the previous case-specialist matrix design.  It trains one
family-level actor from multiple cases in a fault family, optionally fine-tunes
that same actor with SAC on the family proxy, and validates the unchanged actor
over a depth-duration matrix in switch-level Simulink.

Evidence produced by this script may be interpreted as a family-specialist
matrix because every cell in the matrix uses the same exported actor.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import numpy as np

from version_2.sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ACT_DIM,
    FAMILY_TIME_NORM_S,
    OBS_DIM,
    ROOT,
    BoundaryCase,
    build_anchor_from_trace,
    export_actor_for_simulink,
    make_family_label,
    matlab_collect_dq_trace,
    matlab_evaluate_actor,
    read_comparison_rows,
    run_logged,
    write_csv,
)
from version_2.sac.expert_workspace import expert_workspace


def parse_float_list(raw: str) -> list[float]:
    return [float(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(float(part.strip())) for part in str(raw).split(",") if part.strip()]


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "pass", "passed"}


def as_float(value: object, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


def make_cases(
    *,
    topology: str,
    category: str,
    phase_key: str,
    family_label: str,
    depths: Iterable[float],
    durations_ms: Iterable[int],
) -> list[BoundaryCase]:
    return [
        BoundaryCase(
            fault_pu=float(depth),
            duration_s=float(duration_ms) / 1000.0,
            topology=topology,
            category=category,
            phase_key=phase_key,
            family_label=family_label,
        )
        for depth in depths
        for duration_ms in durations_ms
    ]


def combine_anchor_datasets(anchor_files: list[Path], out_npz: Path, out_json: Path) -> dict:
    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    sources: list[dict] = []
    for anchor in anchor_files:
        data = np.load(anchor)
        obs = np.asarray(data["observations"], dtype=np.float32)
        actions = np.asarray(data["actions"], dtype=np.float32)
        if obs.ndim != 2 or obs.shape[1] != OBS_DIM:
            raise RuntimeError(f"Bad observation shape in {anchor}: {obs.shape}")
        if actions.ndim != 2 or actions.shape[1] != ACT_DIM:
            raise RuntimeError(f"Bad action shape in {anchor}: {actions.shape}")
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
        "schema": "hpt-family-specialist-anchor-v1",
        "dataset": str(out_npz),
        "samples": int(observations.shape[0]),
        "source_count": len(anchor_files),
        "sources": sources,
        "action_mean": [float(v) for v in np.mean(actions, axis=0)],
        "action_min": [float(v) for v in np.min(actions, axis=0)],
        "action_max": [float(v) for v in np.max(actions, axis=0)],
        "teacher_source": "strong_conventional_dq_family_traces",
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
    anchors: list[Path] = []
    per_case: list[dict] = []
    for case in train_cases:
        case_dir = run_dir / "anchors" / case.label
        case_dir.mkdir(parents=True, exist_ok=True)
        trace_csv = matlab_collect_dq_trace(
            case,
            case_dir,
            fault_start_s=fault_start_s,
            trace_dir=case_dir,
        )
        anchor_npz = case_dir / f"{case.label}_dq_anchor.npz"
        anchor_json = case_dir / f"{case.label}_dq_anchor.json"
        anchor_summary = build_anchor_from_trace(
            trace_csv,
            anchor_npz,
            anchor_json,
            min_time_s=anchor_min_time_s,
            prefault_repeat=2,
            fault_repeat=12,
            recovery_repeat=8,
            tail_repeat=1,
        )
        anchors.append(anchor_npz)
        per_case.append(
            {
                "case": {**asdict(case), "label": case.label},
                "trace_csv": str(trace_csv),
                "anchor_summary": anchor_summary,
            }
        )
    family_npz = run_dir / "family_anchor.npz"
    family_json = run_dir / "family_anchor.json"
    summary = combine_anchor_datasets(anchors, family_npz, family_json)
    summary["per_case"] = per_case
    family_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return family_npz, summary


def train_family_seed_actor(
    *,
    family_label: str,
    topology: str,
    category: str,
    phase_key: str,
    train_depths: list[float],
    train_durations_ms: list[int],
    anchor_npz: Path,
    run_dir: Path,
    bc_epochs: int,
    seed: int,
    fault_start_s: float,
    models_dir: Path,
) -> Path:
    model_out = models_dir / f"hpt_{family_label}_{run_dir.name}_family_seed_actor.zip"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--family-topology",
        topology,
        "--family-fault-pus",
        ",".join(f"{value:.6g}" for value in train_depths),
        "--family-fault-durations-ms",
        ",".join(str(value) for value in train_durations_ms),
        "--family-fault-start-s",
        f"{fault_start_s:.12g}",
        "--family-category",
        category.upper(),
        "--family-phase-key",
        phase_key,
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
        f"{run_dir.name}_{family_label}_seed",
        "--results-root",
        str(run_dir / "training"),
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--fault-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--recovery-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--seed",
        str(seed),
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_seed_train.log")
    return model_out


def train_family_sac_actor(
    *,
    family_label: str,
    topology: str,
    category: str,
    phase_key: str,
    train_depths: list[float],
    train_durations_ms: list[int],
    seed_model: Path,
    anchor_npz: Path,
    run_dir: Path,
    sac_steps: int,
    seed: int,
    fault_start_s: float,
    learning_rate: float,
    support_weight: float,
    vdc_bounds_weight: float,
    vdc_margin_weight: float,
    vdc_margin_pu: float,
    models_dir: Path,
) -> Path:
    model_out = models_dir / f"hpt_{family_label}_{run_dir.name}_family_sac_actor.zip"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--family-topology",
        topology,
        "--family-fault-pus",
        ",".join(f"{value:.6g}" for value in train_depths),
        "--family-fault-durations-ms",
        ",".join(str(value) for value in train_durations_ms),
        "--family-fault-start-s",
        f"{fault_start_s:.12g}",
        "--family-category",
        category.upper(),
        "--family-phase-key",
        phase_key,
        "--controller-heads",
        "split",
        "--init-model",
        str(seed_model),
        "--steps",
        str(sac_steps),
        "--n-envs",
        str(max(1, min(4, len(train_depths) * len(train_durations_ms)))),
        "--learning-rate",
        f"{learning_rate:.12g}",
        "--sac-support-regularization-weight",
        f"{support_weight:.12g}",
        "--sac-support-regularization-batch-size",
        "256",
        "--sac-support-anchor-dataset",
        str(anchor_npz),
        "--sac-support-action-weights",
        "28,24,8,8",
        "--sac-support-nearest-replay",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        "8",
        "--behavior-anchor-interval-steps",
        "60",
        "--behavior-anchor-lr",
        "1e-5",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "24,20,6,6",
        "--eval-rollouts",
        "0",
        "--run-id",
        f"{run_dir.name}_{family_label}_sac",
        "--results-root",
        str(run_dir / "training"),
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--grid-current-reward-weight",
        "180",
        "--grid-current-margin-reward-weight",
        "650",
        "--grid-current-margin-pu",
        "0.08",
        "--grid-reactive-reward-weight",
        "0",
        "--envelope-reward-weight",
        "1600",
        "--lv-margin-reward-weight",
        "3000",
        "--lv-margin-pu",
        "0.025",
        "--calibrated-survival-reward-weight",
        "18000",
        "--vdc-soft-reward-weight",
        "320",
        "--vdc-bounds-reward-weight",
        f"{vdc_bounds_weight:.12g}",
        "--vdc-margin-reward-weight",
        f"{vdc_margin_weight:.12g}",
        "--vdc-margin-pu",
        f"{vdc_margin_pu:.12g}",
        "--proxy-vdc-reward-downshift-pu",
        "0.04",
        "--action-slew-weight",
        "0.16",
        "--calibration-ood-reward-weight",
        "60",
        "--fault-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--recovery-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--seed",
        str(seed),
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "family_sac_train.log")
    return model_out


def evaluate_family_actor(
    *,
    cases: list[BoundaryCase],
    model_path: Path,
    run_dir: Path,
    export_tag: str,
    controller_label: str,
    fault_start_s: float,
    actor_filter_tau: float,
    include_strong_dq: bool,
) -> list[dict]:
    run_dir.mkdir(parents=True, exist_ok=True)
    actor_archive = export_actor_for_simulink(model_path, run_dir, export_tag)
    rows: list[dict] = []
    for case in cases:
        csv_path = matlab_evaluate_actor(
            case,
            run_dir,
            tag=f"{export_tag}_{case.label}",
            fault_start_s=fault_start_s,
            actor_filter_tau=actor_filter_tau,
            compare_dir=run_dir,
        )
        for row in read_comparison_rows(
            csv_path,
            controller_label=controller_label,
            include_strong_dq=include_strong_dq,
        ):
            row["family_eval_label"] = case.label
            row["family_fault_pu"] = f"{case.fault_pu:.6g}"
            row["family_duration_ms"] = str(case.duration_ms)
            if row.get("controller") == controller_label:
                row["actor_archive"] = str(actor_archive)
                row["actor_model"] = str(model_path)
            else:
                row["actor_archive"] = ""
                row["actor_model"] = ""
            rows.append(row)
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row.get("family_eval_label") or row.get("boundary_label") or ""), str(row.get("controller") or ""))
        latest[key] = row
    return list(latest.values())


def summarize_rows(rows: list[dict], out_json: Path) -> dict:
    rows = dedupe_rows(rows)
    by_controller: dict[str, list[dict]] = {}
    for row in rows:
        by_controller.setdefault(str(row.get("controller") or ""), []).append(row)
    summary: dict[str, dict] = {}
    for controller, subset in sorted(by_controller.items()):
        scores = [as_float(row.get("control_score")) for row in subset]
        grid_i = [as_float(row.get("grid_current_peak_pu")) for row in subset]
        env = [as_float(row.get("envelope_violation_max_pu")) for row in subset]
        summary[controller] = {
            "rows": len(subset),
            "voltage_survival_pass_count": sum(truthy(row.get("voltage_survival_pass")) for row in subset),
            "envelope_pass_count": sum(truthy(row.get("envelope_pass")) for row in subset),
            "recovery_pass_count": sum(truthy(row.get("recovery_envelope_pass")) for row in subset),
            "vdc_pass_count": sum(
                as_float(row.get("vdc_min")) >= 650.0
                and as_float(row.get("vdc_max")) <= 1000.0
                for row in subset
            ),
            "gbt_vdc_survive_pass_count": sum(
                truthy(row.get("gbt_vdc_survive_pass")) for row in subset
            ),
            "grid_current_pass_count": sum(truthy(row.get("gbt_grid_current_limit_pass")) for row in subset),
            "score_mean": float(np.nanmean(scores)) if scores else float("nan"),
            "score_min": float(np.nanmin(scores)) if scores else float("nan"),
            "score_max": float(np.nanmax(scores)) if scores else float("nan"),
            "grid_current_peak_max_pu": float(np.nanmax(grid_i)) if grid_i else float("nan"),
            "envelope_violation_max_pu": float(np.nanmax(env)) if env else float("nan"),
        }
    # Pairwise derived counts for seed/SAC versus strong dq.
    by_case: dict[str, dict[str, dict]] = {}
    for row in rows:
        label = str(row.get("family_eval_label") or "")
        by_case.setdefault(label, {})[str(row.get("controller") or "")] = row
    for controller in ("family_seed_before_sac", "family_sac_after_finetune"):
        pass_dq_fail = 0
        score_beats_dq = 0
        for controllers in by_case.values():
            dq = controllers.get("strong_dq", {})
            cand = controllers.get(controller, {})
            if truthy(cand.get("voltage_survival_pass")) and not truthy(dq.get("voltage_survival_pass")):
                pass_dq_fail += 1
            if as_float(cand.get("control_score"), 1e99) < as_float(dq.get("control_score"), 1e99):
                score_beats_dq += 1
        if controller in summary:
            summary[controller]["pass_while_dq_fails_count"] = pass_dq_fail
            summary[controller]["score_beats_dq_count"] = score_beats_dq
    if "family_sac_after_finetune" in summary and "family_seed_before_sac" in summary:
        pass_seed_fail = 0
        score_beats_seed = 0
        for controllers in by_case.values():
            seed = controllers.get("family_seed_before_sac", {})
            sac = controllers.get("family_sac_after_finetune", {})
            if truthy(sac.get("voltage_survival_pass")) and not truthy(seed.get("voltage_survival_pass")):
                pass_seed_fail += 1
            if as_float(sac.get("control_score"), 1e99) < as_float(seed.get("control_score"), 1e99):
                score_beats_seed += 1
        summary["family_sac_after_finetune"]["pass_while_seed_fails_count"] = pass_seed_fail
        summary["family_sac_after_finetune"]["score_beats_seed_count"] = score_beats_seed
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_markdown(run_dir: Path, metadata: dict, summary: dict, rows: list[dict]) -> None:
    lines: list[str] = []
    lines.append("# HPT family-specialist matrix summary")
    lines.append("")
    if metadata.get("eval_only"):
        lines.append(
            "This run evaluates one existing actor across the family matrix; "
            "no training occurs in this run."
        )
    else:
        lines.append(
            "This run trains one actor for the whole fault family, then validates "
            "that same actor across the evaluation matrix."
        )
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    for key in ("family_label", "topology", "category", "phase_key", "train_depths", "train_durations_ms", "eval_depths", "eval_durations_ms"):
        lines.append(f"- {key}: `{metadata.get(key)}`")
    lines.append("")
    lines.append("## Controller Summary")
    lines.append("")
    lines.append(
        "| controller | rows | pass | active Vdc pass | GBT Vdc survive | pass while dq fails | "
        "score < dq | score < seed | score mean | grid I max | env max |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for controller, data in summary.items():
        lines.append(
            "| {c} | {rows} | {vp} | {vdc} | {gbt_vdc} | {pdf} | {sbd} | {sbs} | "
            "{score:.3f} | {gi:.3f} | {env:.5f} |".format(
                c=controller,
                rows=int(data.get("rows", 0)),
                vp=int(data.get("voltage_survival_pass_count", 0)),
                vdc=int(data.get("vdc_pass_count", 0)),
                gbt_vdc=int(data.get("gbt_vdc_survive_pass_count", 0)),
                pdf=int(data.get("pass_while_dq_fails_count", 0)),
                sbd=int(data.get("score_beats_dq_count", 0)),
                sbs=int(data.get("score_beats_seed_count", 0)),
                score=float(data.get("score_mean", float("nan"))),
                gi=float(data.get("grid_current_peak_max_pu", float("nan"))),
                env=float(data.get("envelope_violation_max_pu", float("nan"))),
            )
        )
    lines.append("")
    lines.append("## Per-case rows")
    lines.append("")
    lines.append("| case | controller | pass | reason | score | grid I | env | recovery | Vdc min | actor model |")
    lines.append("|---|---|---:|---|---:|---:|---:|---:|---:|---|")
    for row in dedupe_rows(rows):
        lines.append(
            "| {case} | {ctrl} | {vp} | {reason} | {score:.3f} | {gi:.3f} | {env:.5f} | {rec:.5f} | {vdc:.1f} | {actor} |".format(
                case=row.get("family_eval_label", ""),
                ctrl=row.get("controller", ""),
                vp=row.get("voltage_survival_pass", ""),
                reason=row.get("voltage_survival_reason", ""),
                score=as_float(row.get("control_score")),
                gi=as_float(row.get("grid_current_peak_pu")),
                env=as_float(row.get("envelope_violation_max_pu")),
                rec=as_float(row.get("recovery_violation_max_pu")),
                vdc=as_float(row.get("vdc_min")),
                actor=Path(str(row.get("actor_model", ""))).name,
            )
        )
    (run_dir / "FAMILY_SPECIALIST_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--phase-key", choices=["abc", "a", "b", "c", "ab", "bc", "ca"], default="abc")
    parser.add_argument("--family-label", default="")
    parser.add_argument("--train-depths", default="")
    parser.add_argument("--eval-depths", default="")
    parser.add_argument("--train-durations-ms", default="60,100")
    parser.add_argument("--eval-durations-ms", default="")
    parser.add_argument("--bc-epochs", type=int, default=160)
    parser.add_argument("--sac-steps", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260801)
    parser.add_argument("--fault-start-s", type=float, default=0.080)
    parser.add_argument("--anchor-min-time-s", type=float, default=0.020)
    parser.add_argument("--actor-filter-tau", type=float, default=0.001)
    parser.add_argument("--skip-sac", action="store_true")
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--family-anchor", type=Path, default=None)
    parser.add_argument(
        "--eval-only",
        action="store_true",
        help="Reuse existing family actors and only run switch-level evaluation.",
    )
    parser.add_argument("--reuse-seed-model", type=Path, default=None)
    parser.add_argument("--reuse-sac-model", type=Path, default=None)
    parser.add_argument("--sac-learning-rate", type=float, default=5e-9)
    parser.add_argument("--sac-support-weight", type=float, default=80000.0)
    parser.add_argument("--sac-vdc-bounds-weight", type=float, default=120000.0)
    parser.add_argument("--sac-vdc-margin-weight", type=float, default=180000.0)
    parser.add_argument("--sac-vdc-margin-pu", type=float, default=0.06)
    args = parser.parse_args()

    family_label = args.family_label or make_family_label(args.topology, args.category, args.phase_key)
    default_depths = "1.10,1.15" if args.category.upper() == "HVRT" else "0.875,0.90"
    train_depths = parse_float_list(args.train_depths or default_depths)
    eval_depths = parse_float_list(args.eval_depths or args.train_depths or default_depths)
    train_durations_ms = parse_int_list(args.train_durations_ms)
    eval_durations_ms = parse_int_list(args.eval_durations_ms or args.train_durations_ms)
    train_cases = make_cases(
        topology=args.topology,
        category=args.category,
        phase_key=args.phase_key,
        family_label=family_label,
        depths=train_depths,
        durations_ms=train_durations_ms,
    )
    eval_cases = make_cases(
        topology=args.topology,
        category=args.category,
        phase_key=args.phase_key,
        family_label=family_label,
        depths=eval_depths,
        durations_ms=eval_durations_ms,
    )
    run_id = args.run_id or f"hpt_family_specialist_{family_label}_{time.strftime('%Y%m%d_%H%M%S')}"
    workspace = expert_workspace(
        args.topology,
        args.category,
        args.phase_key,
        create=True,
    )
    run_dir = workspace.results / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "hpt-family-specialist-matrix-v1",
        "run_id": run_id,
        "command": [sys.executable, "-m", "version_2.sac.campaigns.run_hpt_family_specialist_matrix", *sys.argv[1:]],
        "family_label": family_label,
        "topology": args.topology,
        "category": args.category,
        "phase_key": args.phase_key,
        "train_depths": None if args.eval_only else train_depths,
        "eval_depths": eval_depths,
        "train_durations_ms": None if args.eval_only else train_durations_ms,
        "eval_durations_ms": eval_durations_ms,
        "train_cases": (
            []
            if args.eval_only
            else [{**asdict(case), "label": case.label} for case in train_cases]
        ),
        "eval_cases": [{**asdict(case), "label": case.label} for case in eval_cases],
        "bc_epochs": int(args.bc_epochs),
        "sac_steps": int(args.sac_steps),
        "skip_sac": bool(args.skip_sac),
        "eval_only": bool(args.eval_only),
        "training_scope": "not_applicable_eval_only" if args.eval_only else "family_matrix",
        "reuse_seed_model": str(args.reuse_seed_model or ""),
        "reuse_sac_model": str(args.reuse_sac_model or ""),
        "one_actor_per_family": True,
        "voltage_survival_current_gate": True,
        "expert_id": workspace.spec.expert_id,
        "expert_workspace": str(workspace.root),
    }
    (run_dir / "campaign_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    if args.eval_only:
        if args.reuse_seed_model is None and args.reuse_sac_model is None:
            raise ValueError("--eval-only requires --reuse-seed-model and/or --reuse-sac-model")
        family_anchor = args.family_anchor or Path("")
        anchor_summary = {"dataset": str(family_anchor), "reused": bool(args.family_anchor), "eval_only": True}
    elif args.skip_collect:
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

    if args.eval_only:
        seed_model = args.reuse_seed_model
        sac_model = args.reuse_sac_model
        seed_rows = []
        sac_rows = []
        if seed_model is not None:
            seed_rows = evaluate_family_actor(
                cases=eval_cases,
                model_path=seed_model,
                run_dir=run_dir / "eval_seed",
                export_tag="family_seed",
                controller_label="family_seed_before_sac",
                fault_start_s=args.fault_start_s,
                actor_filter_tau=args.actor_filter_tau,
                include_strong_dq=True,
            )
        if sac_model is not None:
            sac_rows = evaluate_family_actor(
                cases=eval_cases,
                model_path=sac_model,
                run_dir=run_dir / "eval_sac",
                export_tag="family_sac",
                controller_label="family_sac_after_finetune",
                fault_start_s=args.fault_start_s,
                actor_filter_tau=args.actor_filter_tau,
                include_strong_dq=seed_model is None,
            )
    else:
        seed_model = train_family_seed_actor(
            family_label=family_label,
            topology=args.topology,
            category=args.category,
            phase_key=args.phase_key,
            train_depths=train_depths,
            train_durations_ms=train_durations_ms,
            anchor_npz=family_anchor,
            run_dir=run_dir,
            bc_epochs=args.bc_epochs,
            seed=args.seed,
            fault_start_s=args.fault_start_s,
            models_dir=workspace.models,
        )
        seed_rows = evaluate_family_actor(
            cases=eval_cases,
            model_path=seed_model,
            run_dir=run_dir / "eval_seed",
            export_tag="family_seed",
            controller_label="family_seed_before_sac",
            fault_start_s=args.fault_start_s,
            actor_filter_tau=args.actor_filter_tau,
            include_strong_dq=True,
        )

        if args.skip_sac:
            sac_model = seed_model
            sac_rows = []
        else:
            sac_model = train_family_sac_actor(
                family_label=family_label,
                topology=args.topology,
                category=args.category,
                phase_key=args.phase_key,
                train_depths=train_depths,
                train_durations_ms=train_durations_ms,
                seed_model=seed_model,
                anchor_npz=family_anchor,
                run_dir=run_dir,
                sac_steps=args.sac_steps,
                seed=args.seed + 1000,
                fault_start_s=args.fault_start_s,
                learning_rate=args.sac_learning_rate,
                support_weight=args.sac_support_weight,
                vdc_bounds_weight=args.sac_vdc_bounds_weight,
                vdc_margin_weight=args.sac_vdc_margin_weight,
                vdc_margin_pu=args.sac_vdc_margin_pu,
                models_dir=workspace.models,
            )
            sac_rows = evaluate_family_actor(
                cases=eval_cases,
                model_path=sac_model,
                run_dir=run_dir / "eval_sac",
                export_tag="family_sac",
                controller_label="family_sac_after_finetune",
                fault_start_s=args.fault_start_s,
                actor_filter_tau=args.actor_filter_tau,
                include_strong_dq=False,
            )

    rows = dedupe_rows(seed_rows + sac_rows)
    # Guard against accidental per-cell actor usage.
    actor_models = {
        row.get("controller"): row.get("actor_model")
        for row in rows
        if row.get("controller") in {"family_seed_before_sac", "family_sac_after_finetune"}
    }
    if (
        seed_model is not None
        and "family_seed_before_sac" in actor_models
        and actor_models["family_seed_before_sac"] != str(seed_model)
    ):
        raise RuntimeError("Seed rows do not all reference the family seed model")
    if (
        not args.skip_sac
        and sac_model is not None
        and actor_models.get("family_sac_after_finetune") != str(sac_model)
    ):
        raise RuntimeError("SAC rows do not all reference the family SAC model")

    comparison_csv = run_dir / "family_specialist_comparison_rows.csv"
    write_csv(comparison_csv, rows)
    summary = summarize_rows(rows, run_dir / "family_specialist_summary.json")
    final = {
        "metadata": metadata,
        "anchor_summary": anchor_summary,
        "family_anchor": str(family_anchor),
        "seed_model": str(seed_model),
        "sac_model": str(sac_model),
        "comparison_csv": str(comparison_csv),
        "summary": summary,
    }
    (run_dir / "campaign_summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    write_markdown(run_dir, metadata, summary, rows)
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2), flush=True)


if __name__ == "__main__":
    main()
