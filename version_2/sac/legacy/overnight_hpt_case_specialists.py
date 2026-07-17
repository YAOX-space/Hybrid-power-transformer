"""Run an 8-hour per-case HPT SAC specialist loop.

This script intentionally does not pursue one unified SAC.  It follows the
previous-version expert idea: one topology/case specialist is trained and
validated against the switch-level Simulink model before being kept.

Current first target:
    topology1 / steady / grid_9000V

The loop performs closed-loop DAgger:
    1. evaluate current actor on the switch-level case and collect trace,
    2. train a specialist on that rollout with a physical fixed target,
    3. export the actor to Simulink,
    4. re-evaluate on the same switch-level case,
    5. keep only candidates that pass the Simulink window.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "version_2").is_dir() and (parent / "lab").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root from legacy runner path")


ROOT = find_repo_root()
SIMULINK = ROOT / "version_2" / "simulink"
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SINGLE_CASE_DIR = RESULTS / "hpt_v2_sac_single_case"
TRACE_DIR = RESULTS / "hpt_v2_sac_single_case_actor_traces"

STEADY_MAT = SIMULINK / "hpt_sac_actor_weights.mat"
DYNAMIC_MAT = SIMULINK / "hpt_sac_actor_weights_dynamic.mat"
BEST_STEADY_INIT = MODELS / "hpt_voltage_sac_currentref_steady_fullteacher_settled.zip"


@dataclass
class Score:
    csv_path: str
    trace_path: str
    passed: bool
    score: float
    reason: str
    lv_mean: float
    lv_unbalance: float
    vdc_mean: float
    vdc_min: float
    action_max_abs: float
    reg_d_mean: float
    reg_q_mean: float
    energy_d_mean: float
    energy_q_mean: float


@dataclass
class Iteration:
    index: int
    target: str
    init_model: str
    trace_csv: str
    model_path: str
    actor_mat: str
    score: Score | None
    improved: bool
    promoted: bool
    elapsed_s: float
    notes: list[str]


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_cmd(cmd: list[str], log_path: Path, timeout_s: int | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
            )
            return int(proc.returncode)
        except subprocess.TimeoutExpired:
            log.write(f"\nTIMEOUT after {timeout_s} s\n")
            return 124
        except Exception as exc:
            log.write(f"\nCOMMAND_EXCEPTION {type(exc).__name__}: {exc}\n")
            return 125


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def parse_score(csv_path: Path, trace_path: Path) -> Score:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise RuntimeError(f"Expected one row in {csv_path}, got {len(rows)}")
    row = rows[0]
    passed = str(row.get("within_window", "")).strip().lower() in {"1", "true"}
    lv = float(row.get("lv_mean") or 0.0)
    vdc_mean = float(row.get("vdc_mean") or 0.0)
    vdc_min = float(row.get("vdc_min") or 0.0)
    action_max = float(row.get("action_max_abs") or 0.0)
    score = abs(lv - 207.0) / 5.0
    score += max(0.0, 760.0 - vdc_mean) / 10.0
    score += max(0.0, action_max - 0.9501) * 100.0
    if not passed:
        score += 100.0
    return Score(
        csv_path=str(csv_path),
        trace_path=str(trace_path),
        passed=passed,
        score=float(score),
        reason=str(row.get("window_reason", "")),
        lv_mean=lv,
        lv_unbalance=float(row.get("lv_unbalance") or 0.0),
        vdc_mean=vdc_mean,
        vdc_min=vdc_min,
        action_max_abs=action_max,
        reg_d_mean=float(row.get("reg_d_mean") or 0.0),
        reg_q_mean=float(row.get("reg_q_mean") or 0.0),
        energy_d_mean=float(row.get("energy_d_mean") or 0.0),
        energy_q_mean=float(row.get("energy_q_mean") or 0.0),
    )


def eval_topology1_grid9000(run_dir: Path, label: str) -> tuple[Score | None, int]:
    code = (
        f"cd('{SIMULINK.as_posix()}'); "
        "hpt_eval_topology='topology1'; "
        "hpt_eval_scenario_type='steady'; "
        "hpt_eval_case_name='grid_9000V'; "
        "hpt_eval_energy_enable=1.0; "
        "eval_hpt_v2_sac_single_case;"
    )
    rc = run_cmd(["matlab", "-batch", code], run_dir / "logs" / f"{label}_eval.log", 1800)
    if rc != 0:
        return None, rc
    csv_path = latest_csv(SINGLE_CASE_DIR, "single_case_topology1_steady_grid_9000V_*.csv")
    trace_path = latest_csv(TRACE_DIR, "single_actor_trace_topology1_steady_grid_9000V_*.csv")
    return parse_score(csv_path, trace_path), 0


def train_candidate(
    run_dir: Path,
    index: int,
    trace_csv: Path,
    target: str,
    init_model: Path,
    *,
    epochs: int,
    repeat: int,
    action_weights: str,
    seed: int,
) -> tuple[Path, int]:
    model_out = MODELS / "hpt_case_specialists" / (
        f"{run_dir.name}_topology1_grid9000_it{index:03d}.zip"
    )
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.pretrain_hpt_actor_bc",
        "--run-id",
        f"{run_dir.name}_it{index:03d}",
        "--curriculum",
        "steady_step4",
        "--teacher-source",
        "execution_guard",
        "--episodes-per-scenario",
        "0",
        "--noise-std",
        "0.02",
        "--epochs",
        str(epochs),
        "--batch-size",
        "512",
        "--seed",
        str(seed + index),
        "--switch-trace-csv",
        str(trace_csv),
        "--switch-trace-repeat",
        str(repeat),
        "--switch-trace-scenario-types",
        "steady",
        "--switch-trace-topologies",
        "topology1",
        "--switch-trace-condition-classes",
        "steady",
        "--switch-trace-case-contains",
        "grid_9000V",
        "--switch-trace-window-zones",
        "steady",
        "--switch-trace-fixed-target",
        target,
        "--energy-limit",
        "0.95",
        "--action-weights",
        action_weights,
        "--init-model",
        str(init_model),
        "--model-out",
        str(model_out),
    ]
    rc = run_cmd(cmd, run_dir / "logs" / f"it{index:03d}_train.log", 2400)
    return model_out, rc


def export_actor(model: Path, actor_mat: Path, run_dir: Path, index: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "-m",
            "version_2.sac.export_hpt_sac_actor",
            "--model",
            str(model),
            "--out",
            str(actor_mat),
        ],
        run_dir / "logs" / f"it{index:03d}_export.log",
        300,
    )


def write_status(run_dir: Path, records: list[Iteration], status: str, best: Score | None) -> None:
    payload = {
        "status": status,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "records": [asdict(r) for r in records],
        "best": asdict(best) if best else None,
    }
    (run_dir / "status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# HPT Case Specialist 8h Run",
        "",
        f"- Status: `{status}`",
        f"- Updated: `{payload['updated']}`",
        f"- Iterations: `{len(records)}`",
        "",
    ]
    if best:
        lines.extend(
            [
                "## Best",
                "",
                f"- pass `{best.passed}` score `{best.score:.3f}` reason `{best.reason}`",
                f"- LV `{best.lv_mean:.3f}` VdcMean `{best.vdc_mean:.3f}` VdcMin `{best.vdc_min:.3f}`",
                f"- actions reg_d `{best.reg_d_mean:.3f}` reg_q `{best.reg_q_mean:.3f}` "
                f"energy_d `{best.energy_d_mean:.3f}` energy_q `{best.energy_q_mean:.3f}`",
                "",
            ]
        )
    lines.append("## Iterations")
    lines.append("")
    for rec in records[-20:]:
        sc = rec.score
        if sc:
            lines.append(
                f"- it `{rec.index}` target `{rec.target}` pass `{sc.passed}` "
                f"score `{sc.score:.3f}` LV `{sc.lv_mean:.3f}` "
                f"VdcMean `{sc.vdc_mean:.3f}` reason `{sc.reason}`"
            )
        else:
            lines.append(f"- it `{rec.index}` target `{rec.target}` no score notes `{'; '.join(rec.notes)}`")
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--max-iterations", type=int, default=999)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--repeat", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--action-weights", default="4,64,24,64")
    parser.add_argument(
        "--targets",
        default="0.55,0,0.4,0;0.52,0,0.4,0;0.58,0,0.4,0;0.55,0,0.6,0;0.50,0,0.4,0",
    )
    args = parser.parse_args()

    run_dir = RESULTS / f"hpt_case_specialists_8h_{stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    backup = run_dir / "actor_backups"
    copy_file(STEADY_MAT, backup / "hpt_sac_actor_weights_start.mat")
    copy_file(DYNAMIC_MAT, backup / "hpt_sac_actor_weights_dynamic_start.mat")
    (RESULTS / ".hpt_case_specialists_8h_current.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status_path": str(run_dir / "status.json"),
                "report_path": str(run_dir / "REPORT.md"),
                "pid": os.getpid(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records: list[Iteration] = []
    targets = [t.strip() for t in args.targets.split(";") if t.strip()]
    deadline = time.time() + max(0.01, args.hours) * 3600.0
    best_score, rc = eval_topology1_grid9000(run_dir, "baseline")
    best = best_score
    current_trace = Path(best_score.trace_path) if best_score else latest_csv(
        TRACE_DIR, "single_actor_trace_topology1_steady_grid_9000V_*.csv"
    )
    current_init = BEST_STEADY_INIT
    write_status(run_dir, records, "running", best)

    try:
        for index in range(args.max_iterations):
            if time.time() >= deadline:
                break
            start = time.time()
            target = targets[index % len(targets)]
            notes: list[str] = []
            model_path, train_rc = train_candidate(
                run_dir,
                index,
                current_trace,
                target,
                current_init,
                epochs=args.epochs,
                repeat=args.repeat,
                action_weights=args.action_weights,
                seed=args.seed,
            )
            actor_mat = run_dir / "actors" / f"topology1_grid9000_it{index:03d}.mat"
            score = None
            improved = False
            promoted = False
            if train_rc != 0:
                notes.append(f"train rc={train_rc}")
            elif export_actor(model_path, actor_mat, run_dir, index) != 0:
                notes.append("export failed")
            else:
                copy_file(actor_mat, STEADY_MAT)
                copy_file(backup / "hpt_sac_actor_weights_dynamic_start.mat", DYNAMIC_MAT)
                score, eval_rc = eval_topology1_grid9000(run_dir, f"it{index:03d}")
                if eval_rc != 0 or score is None:
                    notes.append(f"eval rc={eval_rc}")
                else:
                    current_trace = Path(score.trace_path)
                    if best is None or score.score < best.score:
                        improved = True
                        best = score
                        current_init = model_path
                        copy_file(actor_mat, run_dir / "best" / "topology1_grid9000.mat")
                        copy_file(model_path, run_dir / "best" / model_path.name)
                    if score.passed:
                        promoted = True
                        copy_file(actor_mat, run_dir / "promoted" / "topology1_grid9000.mat")
                        copy_file(model_path, run_dir / "promoted" / model_path.name)
                        notes.append("passed switch-level single case")

            records.append(
                Iteration(
                    index=index,
                    target=target,
                    init_model=str(current_init),
                    trace_csv=str(current_trace),
                    model_path=str(model_path),
                    actor_mat=str(actor_mat),
                    score=score,
                    improved=improved,
                    promoted=promoted,
                    elapsed_s=time.time() - start,
                    notes=notes,
                )
            )
            write_status(run_dir, records, "running", best)
    finally:
        copy_file(backup / "hpt_sac_actor_weights_start.mat", STEADY_MAT)
        copy_file(backup / "hpt_sac_actor_weights_dynamic_start.mat", DYNAMIC_MAT)
        write_status(run_dir, records, "complete", best)
        print(str(run_dir), flush=True)


if __name__ == "__main__":
    main()
