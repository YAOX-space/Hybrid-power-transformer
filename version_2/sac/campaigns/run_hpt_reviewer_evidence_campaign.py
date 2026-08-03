"""Run reviewer-facing evidence experiments for the HPT SAC paper.

This campaign fills the four evidence gaps called out in
``paper/reviewer_critique_action_plan.md``:

1. teacher / BC / BC+DAgger ablation on two representative cases;
2. conventional-dq baseline tuning/boundary sweep;
3. proxy hold-out rollout alignment;
4. reduced robustness matrix for accepted switch-level specialists.

The script is intentionally an orchestrator.  It does not modify Simulink model
structure or SAC training logic.  Each subprocess writes its own result folder;
this script captures commands, logs, and a top-level index report.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"
SIMULINK_DIR = ROOT / "version_2" / "simulink"


@dataclass(frozen=True)
class AblationCase:
    key: str
    topology: str
    case_name: str
    fault_pu: float
    duration_s: float
    fault_start: float
    chopper_threshold: float
    rchop_scale: float
    actor_filter_tau: float
    base_action: tuple[float, float, float, float]
    safe_target: tuple[float, float, float, float]
    phase_pu: tuple[float, float, float] | None = None
    trajectory_file: Path | None = None


ABLATION_CASES = [
    AblationCase(
        key="topology2_a_hvrt105_60ms",
        topology="topology2",
        case_name="ablation_t2_a_hvrt105_60ms",
        fault_pu=1.05,
        duration_s=0.060,
        fault_start=0.035,
        chopper_threshold=780.0,
        rchop_scale=0.65,
        actor_filter_tau=0.001,
        base_action=(0.30, 0.0, 0.05, 0.0),
        safe_target=(0.12, 0.0, 0.02, 0.0),
        phase_pu=(1.05, 1.0, 1.0),
        trajectory_file=RESULTS
        / "hpt_exact_t2_a_hvrt105_60ms_strongpos_actor_daggertraj_20260725"
        / "initial_trajectory.mat",
    ),
    AblationCase(
        key="topology1_balanced_lvrt090_80ms",
        topology="topology1",
        case_name="ablation_t1_lvrt090_80ms",
        fault_pu=0.90,
        duration_s=0.080,
        fault_start=0.080,
        chopper_threshold=850.0,
        rchop_scale=1.0,
        actor_filter_tau=0.001,
        base_action=(0.50, 0.0, -0.05, 0.0),
        safe_target=(0.18, 0.0, -0.02, 0.0),
        trajectory_file=RESULTS
        / "hpt_exact_t1_lvrt090_80ms_fault_recovery_mid_actor_daggertraj_20260725"
        / "initial_trajectory.mat",
    ),
]


def safe_token(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text)).strip("_")


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    run_dir: Path,
    log_name: str,
    timeout_s: int,
    allow_fail: bool = False,
) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    elapsed = time.time() - started
    log_path = run_dir / "logs" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    row = {
        "name": log_name,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "elapsed_s": elapsed,
        "log": str(log_path),
    }
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return row


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def first_json(directory: Path, pattern: str) -> tuple[Path | None, dict[str, Any]]:
    matches = sorted(directory.glob(pattern))
    if not matches:
        return None, {}
    path = matches[0]
    return path, read_json_if_exists(path)


def latest_file(directory: Path, pattern: str, after_time: float) -> Path | None:
    if not directory.exists():
        return None
    files = [p for p in directory.glob(pattern) if p.stat().st_mtime >= after_time]
    if not files:
        return None
    return sorted(files, key=lambda p: p.stat().st_mtime)[-1]


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
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def ablation_cmd(case: AblationCase, *, run_id: str, dagger_iters: int, epochs: int) -> list[str]:
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.run_hpt_trajectory_specialist_campaign",
        "--run-id",
        run_id,
        "--topology",
        case.topology,
        "--case-name",
        case.case_name,
        "--fault-pu",
        str(case.fault_pu),
        "--duration-s",
        str(case.duration_s),
        "--fault-start",
        str(case.fault_start),
        "--fault-stop-margin",
        "0.125",
        "--fault-settle-s",
        "0.020",
        "--chopper-threshold",
        str(case.chopper_threshold),
        "--rchop-scale",
        str(case.rchop_scale),
        "--actor-filter-tau",
        str(case.actor_filter_tau),
        "--preset",
        "fault_window",
        "--base-action",
        *[str(x) for x in case.base_action],
        "--safe-target",
        *[str(x) for x in case.safe_target],
        "--dagger-iters",
        str(dagger_iters),
        "--epochs",
        str(epochs),
        "--dagger-label-source",
        "trajectory",
        "--matlab-timeout-s",
        "1200",
        "--train-timeout-s",
        "900",
    ]
    if case.trajectory_file is not None:
        cmd += ["--trajectory-file", str(case.trajectory_file)]
    if case.phase_pu is not None:
        cmd += ["--fault-phase-pu", *[str(x) for x in case.phase_pu]]
    return cmd


def teacher_cmd(case: AblationCase, *, run_id: str) -> list[str]:
    cmd = [
        "py",
        "-3",
        "-m",
        "version_2.sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        run_id,
        "--topology",
        case.topology,
        "--case-name",
        case.case_name,
        "--fault-pu",
        str(case.fault_pu),
        "--duration-s",
        str(case.duration_s),
        "--fault-start",
        str(case.fault_start),
        "--fault-stop-margin",
        "0.125",
        "--fault-settle-s",
        "0.020",
        "--chopper-threshold",
        str(case.chopper_threshold),
        "--rchop-scale",
        str(case.rchop_scale),
        "--preset",
        "fault_window",
        "--base-action",
        *[str(x) for x in case.base_action],
        "--action",
        *[str(x) for x in case.safe_target],
        "--timeout-s",
        "1200",
    ]
    if case.trajectory_file is not None:
        cmd += ["--trajectory-file", str(case.trajectory_file)]
    if case.phase_pu is not None:
        cmd += ["--fault-phase-pu", *[str(x) for x in case.phase_pu]]
    return cmd


def run_ablation(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in ABLATION_CASES[: args.max_ablation_cases]:
        variants = [
            ("teacher_replay", teacher_cmd(case, run_id=f"{args.run_id}_{case.key}_teacher")),
            (
                "bc_actor",
                ablation_cmd(
                    case,
                    run_id=f"{args.run_id}_{case.key}_bc",
                    dagger_iters=0,
                    epochs=args.ablation_epochs,
                ),
            ),
            (
                "bc_dagger_actor",
                ablation_cmd(
                    case,
                    run_id=f"{args.run_id}_{case.key}_dagger",
                    dagger_iters=1,
                    epochs=args.ablation_epochs,
                ),
            ),
        ]
        for variant, cmd in variants:
            stage_start = time.time()
            result = run_cmd(
                cmd,
                cwd=ROOT,
                run_dir=run_dir,
                log_name=f"ablation_{safe_token(case.key)}_{variant}.log",
                timeout_s=args.ablation_timeout_s,
                allow_fail=True,
            )
            summary_path = RESULTS / f"{args.run_id}_{case.key}_{'teacher' if variant == 'teacher_replay' else ('bc' if variant == 'bc_actor' else 'dagger')}" / "summary.json"
            summary = read_json_if_exists(summary_path)
            rows.append(
                {
                    "stage": "ablation",
                    "case_key": case.key,
                    "variant": variant,
                    **result,
                    "summary_path": str(summary_path) if summary_path.exists() else "",
                    "voltage_pass": summary.get("promoted_voltage_survival", summary.get("trajectory_voltage_pass", "")),
                    "beats_conventional": summary.get("promoted_beats_baseline", summary.get("trajectory_beats_baseline", "")),
                    "elapsed_stage_s": time.time() - stage_start,
                }
            )
    write_csv(run_dir / "ablation_results.csv", rows)
    return rows


def run_baseline_tuning(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    params = [
        ("scale045", 0.45, 0.45),
        ("scale055", 0.55, 0.55),
        ("scale070", 0.70, 0.70),
    ][: args.max_baseline_param_sets]
    for label, reg_scale, energy_scale in params:
        start = time.time()
        statement = (
            "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); "
            "hpt_boundary_topology='all'; "
            "hpt_boundary_durations=[0.060]; "
            "hpt_boundary_lvrt_depths=[0.95 0.90 0.85]; "
            "hpt_boundary_hvrt_depths=[1.05 1.10 1.15]; "
            f"hpt_boundary_run_label='{args.run_id}_baseline_{label}'; "
            "hpt_boundary_conventional_params=struct("
            f"'hpt_conventional_reg_scale',{reg_scale},"
            f"'hpt_conventional_energy_scale',{energy_scale}); "
            "run(fullfile(pwd,'sweeps','sweep_hpt_v2_conventional_boundary.m'));"
        )
        result = run_cmd(
            ["matlab", "-batch", statement],
            cwd=ROOT,
            run_dir=run_dir,
            log_name=f"baseline_tuning_{label}.log",
            timeout_s=args.matlab_timeout_s,
            allow_fail=True,
        )
        csv_path = latest_file(
            RESULTS / "hpt_v2_control_comparison",
            "control_comparison_*.csv",
            start,
        )
        rows.append(
            {
                "stage": "baseline_tuning",
                "label": label,
                "reg_scale": reg_scale,
                "energy_scale": energy_scale,
                **result,
                "control_csv": str(csv_path) if csv_path else "",
            }
        )
    write_csv(run_dir / "baseline_tuning_results.csv", rows)
    return rows


def run_proxy_holdout(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    matrices = [
        ROOT / "lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_193807.csv",
        ROOT / "lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_175951.csv",
    ][: args.max_proxy_matrices]
    for matrix in matrices:
        out_dir = run_dir / "proxy_holdout" / matrix.stem
        cmd = [
            "py",
            "-3",
            "-m",
            "version_2.sac.calibration.verify_hpt_proxy_rollout_alignment",
            "--matrix-csv",
            str(matrix),
            "--out-dir",
            str(out_dir),
        ]
        result = run_cmd(
            cmd,
            cwd=ROOT,
            run_dir=run_dir,
            log_name=f"proxy_holdout_{safe_token(matrix.stem)}.log",
            timeout_s=args.proxy_timeout_s,
            allow_fail=True,
        )
        summary_path, summary = first_json(out_dir, "*_summary.json")
        rows.append(
            {
                "stage": "proxy_holdout",
                "matrix": str(matrix),
                **result,
                "out_dir": str(out_dir),
                "summary_path": str(summary_path) if summary_path else "",
                **{f"summary_{k}": v for k, v in summary.items() if isinstance(v, (str, int, float, bool))},
            }
        )
    write_csv(run_dir / "proxy_holdout_results.csv", rows)
    return rows


def make_variant_manifest(
    source: Path,
    out: Path,
    *,
    max_cases: int,
    variant: str,
    fault_start_delta: float = 0.0,
    rchop_scale_mult: float = 1.0,
    actor_filter_tau: float | None = None,
) -> Path:
    with source.open("r", newline="", encoding="utf-8-sig") as f:
        rows = [dict(r) for r in csv.DictReader(f)]
        fields = list(rows[0].keys())
    rows = rows[:max_cases]
    for row in rows:
        row["case_id"] = f"{row['case_id']}_{variant}"
        row["fault_start_s"] = f"{float(row.get('fault_start_s') or 0.035) + fault_start_delta:.6f}"
        row["rchop_scale"] = f"{float(row.get('rchop_scale') or 1.0) * rchop_scale_mult:.6f}"
        if actor_filter_tau is not None:
            row["actor_filter_tau"] = f"{actor_filter_tau:.6f}"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return out


def run_robustness(args: argparse.Namespace, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = Path(args.robustness_source_manifest)
    if not source.is_absolute():
        source = ROOT / source
    variants = [
        ("fault_start_plus5ms", {"fault_start_delta": 0.005}),
        ("fault_start_minus5ms", {"fault_start_delta": -0.005}),
        ("rchop_plus10pct", {"rchop_scale_mult": 1.10}),
        ("actor_tau_2ms", {"actor_filter_tau": 0.002}),
    ][: args.max_robustness_variants]
    for name, kwargs in variants:
        manifest = make_variant_manifest(
            source,
            run_dir / "robustness_manifests" / f"{name}.csv",
            max_cases=args.max_robustness_cases,
            variant=name,
            **kwargs,
        )
        result = run_cmd(
            [
                "py",
                "-3",
                "-m",
                "version_2.sac.validate_hpt_accepted_specialists",
                "--manifest",
                str(manifest),
                "--run-id",
                f"{args.run_id}_robust_{name}",
                "--timeout-s",
                str(args.matlab_timeout_s),
            ],
            cwd=ROOT,
            run_dir=run_dir,
            log_name=f"robustness_{name}.log",
            timeout_s=args.robustness_timeout_s,
            allow_fail=True,
        )
        summary_path = RESULTS / f"{args.run_id}_robust_{name}" / "summary.json"
        summary = read_json_if_exists(summary_path)
        rows.append(
            {
                "stage": "robustness",
                "variant": name,
                "source_manifest": str(source),
                "manifest": str(manifest),
                **result,
                "summary_path": str(summary_path) if summary_path.exists() else "",
                **{f"summary_{k}": v for k, v in summary.items() if isinstance(v, (str, int, float, bool))},
            }
        )
    write_csv(run_dir / "robustness_results.csv", rows)
    return rows


def write_report(run_dir: Path, all_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Reviewer Evidence Campaign",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Total subprocesses: `{len(all_rows)}`",
        "",
        "| Stage | Item | Return | Key output |",
        "| --- | --- | ---: | --- |",
    ]
    for row in all_rows:
        item = row.get("case_key") or row.get("label") or row.get("matrix") or row.get("variant") or row.get("name")
        output = row.get("summary_path") or row.get("control_csv") or row.get("out_dir") or row.get("log")
        lines.append(
            f"| {row.get('stage','')} | `{item}` | {row.get('returncode','')} | `{output}` |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- `returncode=0` means the subprocess completed. Inspect the linked summary/CSV for pass/fail.",
        "- Nonzero subprocesses are retained as diagnostic evidence; they are not promoted.",
        "- Ablation SAC fine-tune is intentionally not inferred from BC/DAgger; it must be added as a separate validated row before claiming SAC policy-improvement beyond imitation.",
    ]
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"hpt_reviewer_evidence_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument(
        "--stage",
        choices=["all", "ablation", "baseline", "proxy", "robustness"],
        default="all",
    )
    parser.add_argument("--ablation-epochs", type=int, default=120)
    parser.add_argument("--max-ablation-cases", type=int, default=2)
    parser.add_argument("--max-baseline-param-sets", type=int, default=3)
    parser.add_argument("--max-proxy-matrices", type=int, default=2)
    parser.add_argument("--max-robustness-cases", type=int, default=2)
    parser.add_argument("--max-robustness-variants", type=int, default=4)
    parser.add_argument(
        "--robustness-source-manifest",
        default="version_2/sac/experiments/stage4_promoted_specialists_20260727.csv",
        help="Accepted-specialist manifest used to build reduced robustness variants.",
    )
    parser.add_argument("--matlab-timeout-s", type=int, default=1800)
    parser.add_argument("--ablation-timeout-s", type=int, default=2400)
    parser.add_argument("--proxy-timeout-s", type=int, default=900)
    parser.add_argument("--robustness-timeout-s", type=int, default=2400)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    if args.stage in {"all", "ablation"}:
        all_rows.extend(run_ablation(args, run_dir))
    if args.stage in {"all", "baseline"}:
        all_rows.extend(run_baseline_tuning(args, run_dir))
    if args.stage in {"all", "proxy"}:
        all_rows.extend(run_proxy_holdout(args, run_dir))
    if args.stage in {"all", "robustness"}:
        all_rows.extend(run_robustness(args, run_dir))

    write_csv(run_dir / "campaign_results.csv", all_rows)
    summary = {
        "schema": "hpt-reviewer-evidence-campaign-v1",
        "run_id": args.run_id,
        "run_dir": str(run_dir),
        "stage": args.stage,
        "subprocess_count": len(all_rows),
        "nonzero_count": sum(1 for r in all_rows if int(r.get("returncode", 0)) != 0),
        "campaign_results": str(run_dir / "campaign_results.csv"),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(run_dir, all_rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_reviewer_evidence_campaign",
        config=vars(args),
        extra={"summary": summary},
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
