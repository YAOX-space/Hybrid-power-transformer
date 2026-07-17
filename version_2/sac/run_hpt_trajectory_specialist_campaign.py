"""Run a trajectory-level HPT direct-SAC specialist campaign.

This script automates the workflow that was first proven manually on
``topology2 / LVRT / 0.95 pu / 80 ms``:

1. Validate a trajectory action schedule in the switch-level model.
2. Collect 2-ms switch-level observation/action traces for that trajectory.
3. Behavior-clone a 24-D/4-D actor from those traces.
4. Optionally run DAgger iterations: collect actor-visited states, relabel
   them with a safe target action and Vdc feedback, and retrain.
5. Export the final actor and evaluate it against ``conventional_dq`` in
   ``sac_actor_always_raw`` mode.

The campaign is intentionally scenario-specialist.  It does not claim full FRT
certification; promotion is based on the staged voltage-survival gate and
score improvement over the conventional baseline.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .build_hpt_action_trajectory import TrajectorySpec, make_trajectory, write_csv, write_mat
from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK_DIR = ROOT / "version_2" / "simulink"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"
TRACE_DIR = RESULTS / "hpt_v2_trajectory_traces"


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def latest_new_file(directory: Path, pattern: str, before: set[Path]) -> Path:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    files = sorted(after, key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files match {directory / pattern}")
    return files[-1]


def run_command(cmd: list[str], *, run_dir: Path, log_name: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    (run_dir / log_name).write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def summarize_control_csv(path: Path, policy_mode: str) -> dict[str, Any]:
    rows = read_csv(path)
    by_mode = {row.get("mode", ""): row for row in rows}
    baseline = by_mode.get("conventional_dq", {})
    policy = by_mode.get(policy_mode, {})
    baseline_pass = truthy(baseline.get("voltage_survival_pass", ""))
    policy_pass = truthy(policy.get("voltage_survival_pass", ""))
    baseline_score = to_float(baseline.get("control_score"))
    policy_score = to_float(policy.get("control_score"))
    return {
        "control_csv": str(path),
        "baseline_voltage_pass": baseline_pass,
        "policy_voltage_pass": policy_pass,
        "baseline_score": baseline_score,
        "policy_score": policy_score,
        "policy_beats_baseline": bool(
            (policy_pass and not baseline_pass)
            or (
                policy_pass
                and baseline_pass
                and math.isfinite(policy_score)
                and math.isfinite(baseline_score)
                and policy_score < baseline_score
            )
        ),
        "policy_full_frt_pass": truthy(policy.get("full_frt_pass", "")),
        "policy_voltage_reason": policy.get("voltage_survival_reason", ""),
        "policy_full_frt_reason": policy.get("full_frt_reason", ""),
        "policy_lv_mean": to_float(policy.get("lv_mean")),
        "policy_lv_recovery_mean": to_float(policy.get("lv_recovery_mean")),
        "policy_vdc_min": to_float(policy.get("vdc_min")),
        "policy_vdc_max": to_float(policy.get("vdc_max")),
        "policy_action_max_abs": to_float(policy.get("action_max_abs")),
        "policy_cmd_action_max_abs": to_float(policy.get("cmd_action_max_abs")),
        "policy_cmd_m_reg_d_mean": to_float(policy.get("cmd_m_reg_d_mean")),
        "policy_cmd_m_energy_d_mean": to_float(policy.get("cmd_m_energy_d_mean")),
    }


def make_case_name(duration_s: float, fault_pu: float) -> str:
    return f"lvrt_{int(round(duration_s * 1000)):03d}ms_{fault_pu:.3f}pu".replace(".", "p")


def build_initial_trajectory(args: argparse.Namespace, run_dir: Path) -> Path:
    stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
    spec = TrajectorySpec(
        preset=args.preset,
        dt=args.decision_dt,
        stop_time=stop_time,
        base_action=tuple(args.base_action),
        start_action=tuple(args.start_action),
        action=tuple(args.action),
        step_time=args.step_time,
        ramp_start=args.ramp_start,
        ramp_end=args.ramp_end,
        down_start=args.down_start,
        down_end=args.down_end,
    )
    t, action = make_trajectory(spec)
    path = run_dir / "initial_trajectory.mat"
    write_mat(path, t, action)
    write_csv(run_dir / "initial_trajectory.csv", t, action)
    write_json(
        run_dir / "initial_trajectory.json",
        {
            "schema": "hpt-trajectory-specialist-initial-trajectory-v1",
            "spec": spec.__dict__,
            "n_points": int(t.shape[0]),
            "path": str(path),
        },
    )
    return path


def validate_trajectory(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        f"{args.run_id}_trajectory_validation",
        "--topology",
        args.topology,
        "--preset",
        args.preset,
        "--fault-pu",
        str(args.fault_pu),
        "--duration-s",
        str(args.duration_s),
        "--fault-start",
        str(args.fault_start),
        "--fault-stop-margin",
        str(args.fault_stop_margin),
        "--decision-dt",
        str(args.decision_dt),
        "--step-time",
        str(args.step_time),
        "--ramp-start",
        str(args.ramp_start),
        "--ramp-end",
        str(args.ramp_end),
        "--action",
        *[str(x) for x in args.action],
        "--start-action",
        *[str(x) for x in args.start_action],
        "--base-action",
        *[str(x) for x in args.base_action],
        "--timeout-s",
        str(args.matlab_timeout_s),
    ]
    if args.down_start is not None:
        cmd += ["--down-start", str(args.down_start)]
    if args.down_end is not None:
        cmd += ["--down-end", str(args.down_end)]
    run_command(cmd, run_dir=run_dir, log_name="trajectory_validation.log", timeout_s=args.matlab_timeout_s + 60)
    summary_path = RESULTS / f"{args.run_id}_trajectory_validation" / "summary.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    write_json(run_dir / "trajectory_validation_summary.json", data)
    return data


def collect_trace(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    label: str,
    policy_mode: float,
    actor_select_mode: float,
    trajectory_file: Path | None,
) -> Path:
    before = set(TRACE_DIR.glob("trajectory_trace_*.csv"))
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_trace_topology={matlab_string(args.topology)}",
        f"hpt_trace_fault_pu={args.fault_pu:.12g}",
        f"hpt_trace_fault_duration={args.duration_s:.12g}",
        f"hpt_trace_fault_start={args.fault_start:.12g}",
        f"hpt_trace_fault_stop_margin={args.fault_stop_margin:.12g}",
        f"hpt_trace_run_label={matlab_string(label)}",
        f"hpt_trace_policy_mode={policy_mode:.12g}",
        f"hpt_trace_actor_select_mode={actor_select_mode:.12g}",
    ]
    if trajectory_file is not None:
        statements.append(
            f"hpt_trace_trajectory_file={matlab_string(str(trajectory_file).replace(chr(92), '/'))}"
        )
    statements.append("collect_hpt_v2_trajectory_trace")
    proc = run_command(
        [args.matlab_cmd, "-batch", "; ".join(statements)],
        run_dir=run_dir,
        log_name=f"collect_trace_{safe_token(label)}.log",
        timeout_s=args.matlab_timeout_s,
    )
    path = latest_new_file(TRACE_DIR, "trajectory_trace_*.csv", before)
    (run_dir / f"trace_{safe_token(label)}.txt").write_text(str(path), encoding="utf-8")
    return path


def train_bc(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    trace_csv: Path,
    run_id: str,
    model_out: Path,
    init_model: Path | None,
    fixed_target: list[float] | None,
    vdc_feedback_gain: float,
) -> dict[str, Any]:
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.pretrain_hpt_actor_bc",
        "--run-id",
        run_id,
        "--episodes-per-scenario",
        "0",
        "--switch-trace-csv",
        str(trace_csv),
        "--switch-trace-repeat",
        str(args.switch_trace_repeat),
        "--switch-trace-scenario-types",
        "fault",
        "--switch-trace-topologies",
        args.topology,
        "--switch-trace-case-contains",
        args.case_contains,
        "--switch-trace-window-zones",
        args.window_zones,
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--lr",
        str(args.lr),
        "--model-out",
        str(model_out),
    ]
    if init_model is not None:
        cmd += ["--init-model", str(init_model)]
    if fixed_target is not None:
        cmd += ["--switch-trace-fixed-target", ",".join(str(x) for x in fixed_target)]
    if vdc_feedback_gain != 0.0:
        cmd += [
            "--switch-trace-energy-vdc-feedback-gain",
            str(vdc_feedback_gain),
            "--switch-trace-energy-vdc-ref-pu",
            str(args.vdc_feedback_ref_pu),
        ]
    if args.bc_obs_noise_repeat > 0 and args.bc_obs_noise_std > 0:
        cmd += [
            "--bc-obs-noise-std",
            str(args.bc_obs_noise_std),
            "--bc-obs-noise-repeat",
            str(args.bc_obs_noise_repeat),
        ]
    run_command(cmd, run_dir=run_dir, log_name=f"train_{safe_token(run_id)}.log", timeout_s=args.train_timeout_s)
    summary = json.loads((RESULTS / run_id / "summary.json").read_text(encoding="utf-8"))
    metrics = summary.get("metrics", {})
    if int(metrics.get("switch_trace_augmented_samples", 0)) <= 0:
        raise RuntimeError(
            "BC training did not consume any switch trace samples. "
            f"trace_csv={trace_csv}, case_contains={args.case_contains}, "
            f"topology={args.topology}, window_zones={args.window_zones}"
        )
    write_json(run_dir / f"train_summary_{safe_token(run_id)}.json", summary)
    return summary


def export_actor(args: argparse.Namespace, run_dir: Path, *, model: Path, out: Path, label: str) -> None:
    run_command(
        [
            "py",
            "-3",
            "-m",
            "version_2.sac.export_hpt_sac_actor",
            "--model",
            str(model),
            "--out",
            str(out),
        ],
        run_dir=run_dir,
        log_name=f"export_{safe_token(label)}.log",
        timeout_s=300,
    )


def evaluate_actor(args: argparse.Namespace, run_dir: Path, *, label: str) -> dict[str, Any]:
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    case_name = args.case_name or make_case_name(args.duration_s, args.fault_pu)
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(args.topology)}",
        "hpt_compare_scenario_type='fault'",
        "hpt_compare_modes=string({'conventional_dq','sac_actor_always_raw'})",
        f"hpt_compare_faults={{ {matlab_string(case_name)}, {args.fault_pu:.12g}, {args.duration_s:.12g} }}",
        f"hpt_compare_fault_start={args.fault_start:.12g}",
        f"hpt_compare_fault_stop_margin={args.fault_stop_margin:.12g}",
        f"hpt_compare_run_label={matlab_string(label)}",
        "eval_hpt_v2_control_comparison",
    ]
    run_command(
        [args.matlab_cmd, "-batch", "; ".join(statements)],
        run_dir=run_dir,
        log_name=f"eval_actor_{safe_token(label)}.log",
        timeout_s=args.matlab_timeout_s,
    )
    csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
    summary = summarize_control_csv(csv_path, "sac_actor_always_raw")
    write_json(run_dir / f"eval_summary_{safe_token(label)}.json", summary)
    return summary


def write_report(run_dir: Path, summary: dict[str, Any]) -> None:
    evals = summary.get("actor_evaluations", [])
    lines = [
        "# HPT Trajectory Specialist Campaign",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Topology: `{summary['topology']}`",
        f"- Fault: `{summary['fault_pu']} pu / {summary['duration_s']} s`",
        f"- Final model: `{summary.get('final_model', '')}`",
        f"- Final exported actor: `{summary.get('final_actor_mat', '')}`",
        f"- Promoted voltage-survival: `{summary.get('promoted_voltage_survival', False)}`",
        f"- Promoted beats conventional: `{summary.get('promoted_beats_baseline', False)}`",
        "",
        "## Evaluations",
        "",
        "| Iteration | Voltage Pass | Beat | Score | Baseline | Vdc min/max | LV mean/recovery | Reason |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in evals:
        lines.append(
            f"| `{item['label']}` | {item['policy_voltage_pass']} | "
            f"{item['policy_beats_baseline']} | {item['policy_score']:.3f} | "
            f"{item['baseline_score']:.3f} | {item['policy_vdc_min']:.2f}/{item['policy_vdc_max']:.2f} | "
            f"{item['policy_lv_mean']:.2f}/{item['policy_lv_recovery_mean']:.2f} | "
            f"`{item['policy_voltage_reason'] or item['policy_full_frt_reason']}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2", choices=["topology1", "topology2"])
    parser.add_argument("--fault-pu", type=float, default=0.95)
    parser.add_argument("--duration-s", type=float, default=0.08)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--case-name", default="")
    parser.add_argument(
        "--preset",
        default="constant",
        choices=["zero", "constant", "step", "ramp", "two_stage", "two_stage_window", "fault_window"],
    )
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument("--action", type=float, nargs=4, default=[0.172, 0.0, 0.022, 0.002])
    parser.add_argument("--start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--safe-target", type=float, nargs=4, default=[0.172, 0.0, 0.014, 0.002])
    parser.add_argument("--step-time", type=float, default=0.035)
    parser.add_argument("--ramp-start", type=float, default=0.035)
    parser.add_argument("--ramp-end", type=float, default=0.055)
    parser.add_argument("--down-start", type=float, default=None)
    parser.add_argument("--down-end", type=float, default=None)
    parser.add_argument("--dagger-iters", type=int, default=2)
    parser.add_argument("--vdc-feedback-gain", type=float, default=0.10)
    parser.add_argument("--vdc-feedback-ref-pu", type=float, default=1.0)
    parser.add_argument("--switch-trace-repeat", type=int, default=64)
    parser.add_argument("--window-zones", default="all")
    parser.add_argument("--case-contains", default="")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--bc-obs-noise-std", type=float, default=0.012)
    parser.add_argument("--bc-obs-noise-repeat", type=int, default=4)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--matlab-timeout-s", type=int, default=1200)
    parser.add_argument("--train-timeout-s", type=int, default=600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.case_contains == "":
        args.case_contains = make_case_name(args.duration_s, args.fault_pu)
    args.run_id = args.run_id or (
        f"hpt_traj_specialist_{safe_token(args.topology)}_"
        f"{safe_token(args.case_contains)}_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)

    trajectory_file = build_initial_trajectory(args, run_dir)
    trajectory_summary = validate_trajectory(args, run_dir)
    trajectory_trace = collect_trace(
        args,
        run_dir,
        label="trajectory_teacher",
        policy_mode=-2.0,
        actor_select_mode=0.0,
        trajectory_file=trajectory_file,
    )

    model = MODELS / f"{args.run_id}_bc0.zip"
    train_summaries: list[dict[str, Any]] = []
    actor_evals: list[dict[str, Any]] = []
    train_summaries.append(
        train_bc(
            args,
            run_dir,
            trace_csv=trajectory_trace,
            run_id=f"{args.run_id}_bc0",
            model_out=model,
            init_model=None,
            fixed_target=None,
            vdc_feedback_gain=0.0,
        )
    )

    actor_mat = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"
    export_actor(args, run_dir, model=model, out=actor_mat, label="bc0_dynamic")
    eval_summary = evaluate_actor(args, run_dir, label=f"{args.run_id}_bc0_actor")
    eval_summary["label"] = "bc0"
    eval_summary["model_path"] = str(model)
    actor_evals.append(eval_summary)

    for idx in range(1, max(0, args.dagger_iters) + 1):
        actor_trace = collect_trace(
            args,
            run_dir,
            label=f"actor_dagger{idx}_trace",
            policy_mode=1.0,
            actor_select_mode=3.0,
            trajectory_file=None,
        )
        next_model = MODELS / f"{args.run_id}_dagger{idx}.zip"
        train_summaries.append(
            train_bc(
                args,
                run_dir,
                trace_csv=actor_trace,
                run_id=f"{args.run_id}_dagger{idx}",
                model_out=next_model,
                init_model=model,
                fixed_target=list(args.safe_target),
                vdc_feedback_gain=args.vdc_feedback_gain,
            )
        )
        model = next_model
        export_actor(args, run_dir, model=model, out=actor_mat, label=f"dagger{idx}_dynamic")
        eval_summary = evaluate_actor(args, run_dir, label=f"{args.run_id}_dagger{idx}_actor")
        eval_summary["label"] = f"dagger{idx}"
        eval_summary["model_path"] = str(model)
        actor_evals.append(eval_summary)

    best = min(
        actor_evals,
        key=lambda item: (
            not item["policy_voltage_pass"],
            not item["policy_beats_baseline"],
            item["policy_score"],
        ),
    )
    best_model = Path(best["model_path"])
    final_actor = SIMULINK_DIR / f"hpt_sac_actor_weights_{safe_token(args.run_id)}.mat"
    export_actor(args, run_dir, model=best_model, out=final_actor, label=f"final_specialist_{best['label']}")
    summary = {
        "schema": "hpt-trajectory-specialist-campaign-v1",
        "run_id": args.run_id,
        "topology": args.topology,
        "fault_pu": args.fault_pu,
        "duration_s": args.duration_s,
        "trajectory_summary": trajectory_summary,
        "trajectory_trace": str(trajectory_trace),
        "train_summaries": train_summaries,
        "actor_evaluations": actor_evals,
        "best_actor_evaluation": best,
        "final_model": str(best_model),
        "final_actor_mat": str(final_actor),
        "promoted_voltage_survival": bool(best["policy_voltage_pass"]),
        "promoted_beats_baseline": bool(best["policy_beats_baseline"]),
        "config": vars(args),
    }
    write_json(run_dir / "summary.json", summary)
    write_report(run_dir, summary)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trajectory_specialist_campaign",
        config=summary["config"],
        dataset_manifest=trajectory_trace,
        policy_checkpoint=model,
        extra={
            "summary_path": str(run_dir / "summary.json"),
            "final_actor_mat": str(final_actor),
        },
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
