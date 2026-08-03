"""Protected SAC fine-tune campaign with switch-level validation after chunks.

This runner is intentionally conservative.  It starts from a switch-level
validated BC/DAgger actor, runs short proxy-SAC chunks with behavior anchoring,
exports each candidate to the dynamic Simulink actor entry point, and validates
the candidate immediately in the switch-level model.  The campaign stops on the
first voltage-survival failure unless explicitly told otherwise.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from version_2.sac.experiment_metadata import write_experiment_metadata
from version_2.sac.summaries.summarize_sac_reward_traces import summarize_sac_reward_traces


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK_DIR = ROOT / "version_2" / "simulink"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"


DEFAULT_INIT = (
    MODELS
    / "hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_dagger_dagger1.zip"
)


def safe_token(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text)).strip("_")


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def matlab_vector(values: list[float]) -> str:
    return "[" + " ".join(f"{value:.12g}" for value in values) + "]"


def parse_float_vector(text: str) -> list[float]:
    value = (text or "").strip()
    if not value:
        return []
    value = value.strip("[]()")
    return [float(part) for part in value.replace(",", " ").split() if part]


def run_cmd(
    cmd: list[str],
    *,
    run_dir: Path,
    log_name: str,
    timeout_s: int,
    allow_fail: bool = False,
) -> subprocess.CompletedProcess[str]:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    elapsed = time.time() - started
    log = run_dir / "logs" / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + f"\n\nELAPSED_S:\n{elapsed:.3f}\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def latest_new_file(directory: Path, pattern: str, before: set[Path]) -> Path | None:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    return None


def b(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def f(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_control_summary(path: Path) -> dict[str, Any]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = {row.get("mode", ""): dict(row) for row in csv.DictReader(handle)}
    conv = rows.get("conventional_dq", {})
    sac = rows.get("sac_actor_always_raw", {})
    return {
        "control_csv": str(path),
        "conventional_pass": b(conv.get("voltage_survival_pass")),
        "conventional_score": f(conv.get("control_score")),
        "sac_pass": b(sac.get("voltage_survival_pass")),
        "sac_score": f(sac.get("control_score")),
        "sac_full_frt_pass": b(sac.get("full_frt_pass")),
        "sac_reason": sac.get("voltage_survival_reason", ""),
        "sac_full_frt_reason": sac.get("full_frt_reason", ""),
        "sac_lv_mean": f(sac.get("lv_mean")),
        "sac_lv_recovery_mean": f(sac.get("lv_recovery_mean")),
        "sac_vdc_min": f(sac.get("vdc_min")),
        "sac_vdc_max": f(sac.get("vdc_max")),
        "sac_action_max_abs": f(sac.get("action_max_abs")),
        "sac_cmd_action_max_abs": f(sac.get("cmd_action_max_abs")),
        "sac_envelope_violation_max_pu": f(sac.get("envelope_violation_max_pu"), 0.0),
        "sac_recovery_violation_max_pu": f(sac.get("recovery_violation_max_pu"), 0.0),
        "sac_fault_lv_band_violation_max_pu": f(
            sac.get("fault_lv_band_violation_max_pu"), 0.0
        ),
    }


def is_meaningful_score_improvement(best_score: float, baseline_score: float, tol: float) -> bool:
    if math.isinf(baseline_score):
        return math.isfinite(best_score)
    return (baseline_score - best_score) > tol


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def jsonable_config(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in vars(args).items():
        out[key] = str(value) if isinstance(value, Path) else value
    return out


def trainable_curriculum(curriculum: str) -> str:
    """Map experiment labels to curricula accepted by the SAC trainer.

    Stage-5 score-optimization manifests use descriptive labels so reports keep
    the target family visible.  The underlying trainer still exposes a smaller
    set of reusable curricula, so campaign-level labels need this explicit
    adapter before spawning the trainer.
    """
    mapping = {
        "scoreopt_topology1_lvrt_a": "topology1_a_lvrt090_60ms",
        "scoreopt_topology1_lvrt_ab": "topology1_ab_lvrt090_60ms",
        "scoreopt_topology1_hvrt_a": "topology1_hvrt110_60ms",
        "scoreopt_topology1_hvrt_ab": "topology1_hvrt110_60ms",
    }
    return mapping.get(curriculum, curriculum)


def train_chunk_cmd(args: argparse.Namespace, *, chunk: int, init_model: Path, model_out: Path) -> list[str]:
    return [
        "py",
        "-3",
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--run-id",
        f"{args.run_id}_chunk{chunk:02d}_train",
        "--curriculum",
        trainable_curriculum(args.curriculum),
        "--init-model",
        str(init_model),
        "--model-out",
        str(model_out),
        "--seed",
        str(args.seed + chunk),
        "--steps",
        str(args.chunk_steps),
        "--n-envs",
        "1",
        "--learning-rate",
        str(args.learning_rate),
        "--eval-rollouts",
        "1",
        "--reg-q-limit",
        "0.8",
        "--teacher-prior-weight",
        str(args.teacher_prior_weight),
        "--envelope-reward-weight",
        str(args.envelope_reward_weight),
        "--calibrated-survival-reward-weight",
        str(args.calibrated_survival_reward_weight),
        "--calibration-ood-reward-weight",
        str(args.calibration_ood_reward_weight),
        "--grid-current-reward-weight",
        str(args.grid_current_reward_weight),
        "--action-slew-weight",
        str(args.action_slew_weight),
        "--behavior-anchor-epochs",
        str(args.behavior_anchor_epochs),
        "--behavior-anchor-interval-steps",
        str(args.behavior_anchor_interval_steps),
        "--behavior-anchor-episodes",
        str(args.behavior_anchor_episodes),
        "--behavior-anchor-noise-std",
        str(args.behavior_anchor_noise_std),
        "--behavior-anchor-lr",
        str(args.behavior_anchor_lr),
        "--behavior-anchor-action-weights",
        args.behavior_anchor_action_weights,
    ]


def matlab_eval_statement(args: argparse.Namespace, *, label: str) -> str:
    fault_items = [
        matlab_string(args.eval_case_name),
        f"{args.eval_fault_pu:.12g}",
        f"{args.eval_duration_s:.12g}",
    ]
    phase = parse_float_vector(args.eval_fault_phase_pu)
    if phase:
        fault_items.append(matlab_vector(phase))

    base_rchop = (800.0**2) / 120e3
    model_params: list[tuple[str, float]] = [
        ("hpt_chopper_threshold", args.chopper_threshold),
        ("hpt_rchop", base_rchop * args.rchop_scale),
    ]
    if args.phase_override:
        fault_clear = args.fault_start_s + args.eval_duration_s
        model_params.extend(
            [
                ("hpt_sac_phase_override_enable", 1.0),
                ("hpt_sac_phase_fault_start_s", args.fault_start_s),
                ("hpt_sac_phase_fault_clear_s", fault_clear),
                ("hpt_sac_phase_recovery_end_s", fault_clear + args.fault_stop_margin_s),
            ]
        )
    params = "struct(" + ",".join(f"'{key}',{value:.12g}" for key, value in model_params) + ")"
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(args.eval_topology)}",
        "hpt_compare_scenario_type='fault'",
        "hpt_compare_modes=string({'conventional_dq','sac_actor_always_raw'})",
        "hpt_compare_faults={ " + ", ".join(fault_items) + " }",
        f"hpt_compare_model_params={params}",
        f"hpt_compare_fault_start={args.fault_start_s:.12g}",
        f"hpt_compare_fault_stop_margin={args.fault_stop_margin_s:.12g}",
        f"hpt_compare_fault_settle_s={args.fault_settle_s:.12g}",
        f"hpt_compare_actor_filter_tau={args.actor_filter_tau:.12g}",
        f"hpt_compare_run_label={matlab_string(label)}",
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
    ]
    return "; ".join(statements)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"hpt_protected_sacft_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--init-model", type=Path, default=DEFAULT_INIT)
    parser.add_argument("--curriculum", default="topology2_a_hvrt105_60ms")
    parser.add_argument("--eval-topology", default="topology2")
    parser.add_argument("--eval-case-name", default="ablation_t2_a_hvrt105_60ms")
    parser.add_argument("--eval-fault-pu", type=float, default=1.05)
    parser.add_argument("--eval-duration-s", type=float, default=0.06)
    parser.add_argument("--eval-fault-phase-pu", default="1.05,1.0,1.0")
    parser.add_argument("--fault-start-s", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin-s", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.02)
    parser.add_argument("--chopper-threshold", type=float, default=780.0)
    parser.add_argument("--rchop-scale", type=float, default=0.65)
    parser.add_argument("--actor-filter-tau", type=float, default=0.001)
    parser.add_argument("--phase-override", action="store_true")
    parser.add_argument("--max-chunks", type=int, default=10)
    parser.add_argument("--chunk-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--teacher-prior-weight", type=float, default=50.0)
    parser.add_argument("--envelope-reward-weight", type=float, default=320.0)
    parser.add_argument("--calibrated-survival-reward-weight", type=float, default=180.0)
    parser.add_argument("--calibration-ood-reward-weight", type=float, default=320.0)
    parser.add_argument("--grid-current-reward-weight", type=float, default=80.0)
    parser.add_argument("--action-slew-weight", type=float, default=0.12)
    parser.add_argument("--behavior-anchor-epochs", type=int, default=12)
    parser.add_argument("--behavior-anchor-interval-steps", type=int, default=50)
    parser.add_argument("--behavior-anchor-episodes", type=int, default=3)
    parser.add_argument("--behavior-anchor-noise-std", type=float, default=0.004)
    parser.add_argument("--behavior-anchor-lr", type=float, default=1e-5)
    parser.add_argument("--behavior-anchor-action-weights", default="8,4,20,20")
    parser.add_argument("--baseline-score", type=float, default=125.845970922945)
    parser.add_argument("--improvement-tol", type=float, default=1e-3)
    parser.add_argument(
        "--advance-policy",
        choices=["always", "pass", "improve"],
        default="improve",
        help=(
            "Which candidate becomes the next warm start.  'improve' keeps the "
            "search in the switch-level validated local trust region."
        ),
    )
    parser.add_argument("--continue-after-fail", action="store_true")
    parser.add_argument("--train-timeout-s", type=int, default=900)
    parser.add_argument("--matlab-timeout-s", type=int, default=1200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    dynamic_actor = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"
    backup = run_dir / "hpt_sac_actor_weights_dynamic_backup_before_protected_sacft.mat"
    if dynamic_actor.exists():
        shutil.copy2(dynamic_actor, backup)

    rows: list[dict[str, Any]] = []
    current_model = args.init_model
    best_model = current_model
    best_score = args.baseline_score if math.isfinite(args.baseline_score) else float("inf")
    stopped_reason = ""
    try:
        for chunk in range(1, args.max_chunks + 1):
            model_out = MODELS / f"{args.run_id}_chunk{chunk:02d}.zip"
            train_proc = run_cmd(
                train_chunk_cmd(args, chunk=chunk, init_model=current_model, model_out=model_out),
                run_dir=run_dir,
                log_name=f"train_chunk{chunk:02d}.log",
                timeout_s=args.train_timeout_s,
                allow_fail=True,
            )
            if train_proc.returncode != 0:
                stopped_reason = f"train_returncode_{train_proc.returncode}"
                rows.append({"chunk": chunk, "stage": "train", "returncode": train_proc.returncode})
                break

            export_proc = run_cmd(
                [
                    "py",
                    "-3",
                    "-m",
                    "version_2.sac.export_hpt_sac_actor",
                    "--model",
                    str(model_out),
                    "--out",
                    str(dynamic_actor),
                ],
                run_dir=run_dir,
                log_name=f"export_chunk{chunk:02d}.log",
                timeout_s=300,
                allow_fail=True,
            )
            if export_proc.returncode != 0:
                stopped_reason = f"export_returncode_{export_proc.returncode}"
                rows.append({"chunk": chunk, "stage": "export", "returncode": export_proc.returncode})
                break

            before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
            label = f"{args.run_id}_chunk{chunk:02d}_switch"
            eval_proc = run_cmd(
                ["matlab", "-batch", matlab_eval_statement(args, label=label)],
                run_dir=run_dir,
                log_name=f"switch_eval_chunk{chunk:02d}.log",
                timeout_s=args.matlab_timeout_s,
                allow_fail=True,
            )
            csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
            row: dict[str, Any] = {
                "chunk": chunk,
                "model_path": str(model_out),
                "train_returncode": train_proc.returncode,
                "export_returncode": export_proc.returncode,
                "eval_returncode": eval_proc.returncode,
                "control_csv": str(csv_path) if csv_path else "",
            }
            if csv_path is not None:
                row.update(read_control_summary(csv_path))
                improved = bool(
                    row["sac_pass"]
                    and is_meaningful_score_improvement(
                        float(row["sac_score"]), best_score, args.improvement_tol
                    )
                )
                row["improved_vs_current_best"] = improved
                row["score_delta_vs_current_best"] = (
                    best_score - float(row["sac_score"]) if row.get("sac_score") is not None else float("nan")
                )
                if improved:
                    best_score = row["sac_score"]
                    best_model = model_out
            rows.append(row)
            write_csv(run_dir / "protected_sac_finetune_chunks.csv", rows)

            hard_fail = (
                not bool(row.get("sac_pass"))
                or float(row.get("sac_action_max_abs", 99.0)) > 0.9501
                or float(row.get("sac_vdc_max", 0.0)) > 1000.0
                or float(row.get("sac_vdc_min", 9999.0)) < 650.0
            )
            if hard_fail and not args.continue_after_fail:
                stopped_reason = "switch_level_hard_fail"
                break
            if args.advance_policy == "always":
                current_model = model_out
            elif args.advance_policy == "pass" and bool(row.get("sac_pass")):
                current_model = model_out
            elif args.advance_policy == "improve" and bool(row.get("improved_vs_current_best")):
                current_model = model_out
    finally:
        if backup.exists():
            shutil.copy2(backup, dynamic_actor)

    reward_summary: dict[str, Any] = {}
    try:
        reward_summary = summarize_sac_reward_traces(run_dir)
    except Exception as exc:  # pragma: no cover - reporting must not hide run evidence
        reward_summary = {"error": f"{type(exc).__name__}: {exc}"}

    summary = {
        "schema": "hpt-protected-sac-finetune-campaign-v1",
        "run_id": args.run_id,
        "run_dir": str(run_dir),
        "init_model": str(args.init_model),
        "chunk_steps": args.chunk_steps,
        "max_chunks": args.max_chunks,
        "advance_policy": args.advance_policy,
        "rows": len(rows),
        "best_score": best_score,
        "best_model": str(best_model),
        "baseline_score": args.baseline_score,
        "improvement_tol": args.improvement_tol,
        "score_delta_vs_baseline": args.baseline_score - best_score
        if math.isfinite(args.baseline_score)
        else None,
        "improved_over_bc_dagger": is_meaningful_score_improvement(
            best_score, args.baseline_score, args.improvement_tol
        ),
        "stopped_reason": stopped_reason,
        "results_csv": str(run_dir / "protected_sac_finetune_chunks.csv"),
        "reward_summary": reward_summary,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(run_dir / "protected_sac_finetune_chunks.csv", rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_protected_sac_finetune",
        config=jsonable_config(args),
        policy_checkpoint=Path(summary["best_model"]),
        extra={"summary": summary},
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
