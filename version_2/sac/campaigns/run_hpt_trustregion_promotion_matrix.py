"""Run protected SAC fine-tune over a manifest of specialist promotion targets."""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from version_2.sac.experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"
DEFAULT_MANIFEST = (
    ROOT
    / "version_2"
    / "sac"
    / "experiments"
    / "trustregion_promotion_targets_20260726.csv"
)


def safe_token(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text)).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def parse_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def row_command(args: argparse.Namespace, row: dict[str, str], index: int) -> tuple[str, list[str]]:
    case_id = row["case_id"]
    run_id = f"{args.run_id}_{index:02d}_{safe_token(case_id)}"
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.campaigns.run_hpt_protected_sac_finetune",
        "--run-id",
        run_id,
        "--init-model",
        row["init_model"],
        "--curriculum",
        row["curriculum"],
        "--eval-topology",
        row["eval_topology"],
        "--eval-case-name",
        row["eval_case_name"],
        "--eval-fault-pu",
        row["eval_fault_pu"],
        "--eval-duration-s",
        row["eval_duration_s"],
        "--fault-start-s",
        row["fault_start_s"],
        "--fault-stop-margin-s",
        row["fault_stop_margin_s"],
        "--fault-settle-s",
        row["fault_settle_s"],
        "--chopper-threshold",
        row["chopper_threshold"],
        "--rchop-scale",
        row["rchop_scale"],
        "--actor-filter-tau",
        row["actor_filter_tau"],
        "--baseline-score",
        row.get("baseline_score", "nan") or "nan",
        "--max-chunks",
        str(args.max_chunks),
        "--chunk-steps",
        str(args.chunk_steps),
        "--learning-rate",
        str(args.learning_rate),
        "--teacher-prior-weight",
        str(args.teacher_prior_weight),
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
        "--advance-policy",
        args.advance_policy,
        "--train-timeout-s",
        str(args.train_timeout_s),
        "--matlab-timeout-s",
        str(args.matlab_timeout_s),
    ]
    if row.get("eval_fault_phase_pu", "").strip():
        cmd.extend(["--eval-fault-phase-pu", row["eval_fault_phase_pu"]])
    else:
        cmd.extend(["--eval-fault-phase-pu", ""])
    if parse_bool(row.get("phase_override", "false")):
        cmd.append("--phase-override")
    if args.continue_after_fail:
        cmd.append("--continue-after-fail")
    return run_id, cmd


def summarize_child(run_id: str, row: dict[str, str], returncode: int, elapsed_s: float) -> dict[str, Any]:
    summary_path = RESULTS / run_id / "summary.json"
    out: dict[str, Any] = {
        "case_id": row.get("case_id", ""),
        "curriculum": row.get("curriculum", ""),
        "run_id": run_id,
        "returncode": returncode,
        "elapsed_s": elapsed_s,
        "summary_path": str(summary_path) if summary_path.exists() else "",
    }
    if summary_path.exists():
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        out.update(
            {
                "best_model": data.get("best_model", ""),
                "best_score": data.get("best_score", ""),
                "baseline_score": data.get("baseline_score", ""),
                "score_delta_vs_baseline": data.get("score_delta_vs_baseline", ""),
                "improved_over_bc_dagger": data.get("improved_over_bc_dagger", ""),
                "stopped_reason": data.get("stopped_reason", ""),
                "rows": data.get("rows", ""),
            }
        )
    return out


def write_report(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    completed = [row for row in rows if row.get("returncode") == 0]
    improved = [row for row in rows if str(row.get("improved_over_bc_dagger")).lower() == "true"]
    failed = [row for row in rows if row.get("returncode") != 0]
    lines = [
        "# HPT Trust-Region Specialist Promotion Matrix",
        "",
        f"Run directory: `{run_dir}`",
        f"Completed cases: {len(completed)} / {len(rows)}",
        f"Improved cases: {len(improved)}",
        f"Failed cases: {len(failed)}",
        "",
        "## Case Summary",
        "",
        "| case | return | best score | delta | improved | stopped |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {case_id} | {returncode} | {best_score} | {score_delta_vs_baseline} | "
            "{improved_over_bc_dagger} | {stopped_reason} |".format(**row)
        )
    run_dir.joinpath("REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"hpt_trustregion_promotion_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--max-chunks", type=int, default=4)
    parser.add_argument("--chunk-steps", type=int, default=80)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--teacher-prior-weight", type=float, default=50.0)
    parser.add_argument("--behavior-anchor-epochs", type=int, default=10)
    parser.add_argument("--behavior-anchor-interval-steps", type=int, default=40)
    parser.add_argument("--behavior-anchor-episodes", type=int, default=3)
    parser.add_argument("--behavior-anchor-noise-std", type=float, default=0.004)
    parser.add_argument("--behavior-anchor-lr", type=float, default=1e-5)
    parser.add_argument("--behavior-anchor-action-weights", default="8,4,20,20")
    parser.add_argument("--advance-policy", choices=["always", "pass", "improve"], default="improve")
    parser.add_argument("--continue-after-fail", action="store_true")
    parser.add_argument("--train-timeout-s", type=int, default=900)
    parser.add_argument("--matlab-timeout-s", type=int, default=1200)
    parser.add_argument("--skip-existing", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = read_csv(args.manifest)
    if args.case_id:
        wanted = set(args.case_id)
        rows = [row for row in rows if row.get("case_id") in wanted]
    if args.max_cases > 0:
        rows = rows[: args.max_cases]
    if not rows:
        raise ValueError("No promotion targets selected")

    summaries: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        child_run_id, cmd = row_command(args, row, index)
        summary_path = RESULTS / child_run_id / "summary.json"
        if args.skip_existing and summary_path.exists():
            summaries.append(summarize_child(child_run_id, row, 0, 0.0))
            write_csv(run_dir / "promotion_summary.csv", summaries)
            write_report(run_dir, summaries)
            continue
        started = time.time()
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
        elapsed = time.time() - started
        log_path = run_dir / "logs" / f"{index:02d}_{safe_token(row['case_id'])}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "COMMAND:\n"
            + " ".join(cmd)
            + f"\n\nELAPSED_S:\n{elapsed:.3f}\n\nSTDOUT:\n"
            + proc.stdout
            + "\n\nSTDERR:\n"
            + proc.stderr,
            encoding="utf-8",
        )
        summaries.append(summarize_child(child_run_id, row, proc.returncode, elapsed))
        write_csv(run_dir / "promotion_summary.csv", summaries)
        write_report(run_dir, summaries)
        if proc.returncode != 0 and not args.continue_after_fail:
            break

    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trustregion_promotion_matrix",
        config={
            "manifest": str(args.manifest),
            "case_id": args.case_id,
            "max_cases": args.max_cases,
            "max_chunks": args.max_chunks,
            "chunk_steps": args.chunk_steps,
            "learning_rate": args.learning_rate,
            "teacher_prior_weight": args.teacher_prior_weight,
            "behavior_anchor_epochs": args.behavior_anchor_epochs,
            "behavior_anchor_interval_steps": args.behavior_anchor_interval_steps,
            "behavior_anchor_episodes": args.behavior_anchor_episodes,
            "behavior_anchor_noise_std": args.behavior_anchor_noise_std,
            "behavior_anchor_lr": args.behavior_anchor_lr,
            "behavior_anchor_action_weights": args.behavior_anchor_action_weights,
            "advance_policy": args.advance_policy,
        },
        extra={"summary_csv": str(run_dir / "promotion_summary.csv")},
    )
    print(json.dumps({"run_id": args.run_id, "run_dir": str(run_dir), "cases": len(summaries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
