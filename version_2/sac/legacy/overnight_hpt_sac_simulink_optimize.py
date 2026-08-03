"""Overnight HPT SAC optimization loop with Simulink-in-the-loop validation.

The SAC actor is still trained on the fast averaged proxy.  Every candidate is
then exported and evaluated on the switch-level Simulink models.  A candidate is
only promoted if the Simulink validation score improves and all configured
assertions pass.
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
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from ..experiment_metadata import write_experiment_metadata
except ImportError:  # pragma: no cover - keeps direct script execution working.
    from version_2.sac.experiment_metadata import write_experiment_metadata


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "version_2").is_dir() and (parent / "lab").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root from legacy runner path")


ROOT = find_repo_root()
RESULTS = ROOT / "lab" / "results"
SIMULINK = ROOT / "version_2" / "simulink"
MODELS = ROOT / "data" / "models"
STEADY_ACTOR = SIMULINK / "hpt_sac_actor_weights.mat"
DYNAMIC_ACTOR = SIMULINK / "hpt_sac_actor_weights_dynamic.mat"
TOPOLOGY_MODELS = {
    "topology1": SIMULINK / "topoloty1" / "hpt_v2_1to1_switchlevel.slx",
    "topology2": SIMULINK / "topology2" / "hpt_v2_topology2_paper.slx",
}


@dataclass
class ValidationScore:
    name: str
    csv_path: str
    score: float
    passed: bool
    max_lv_error: float
    max_unbalance: float
    max_lv_peak: float
    min_lv_rms: float
    min_vdc: float
    failing_reasons: list[str]


@dataclass
class IterationRecord:
    iteration: int
    curriculum: str
    seed: int
    steps: int
    model_path: str
    actor_mat: str
    proxy_summary: dict
    steady_score: ValidationScore | None
    dynamic_score: ValidationScore | None
    promoted_steady: bool
    promoted_dynamic: bool
    elapsed_s: float
    notes: list[str]


def now_stamp() -> str:
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
        except subprocess.TimeoutExpired:
            log.write(f"\nTIMEOUT after {timeout_s} s\n")
            log.flush()
            return 124
        except Exception as exc:  # keep overnight supervisor alive on tooling failures.
            log.write(f"\nCOMMAND_EXCEPTION: {type(exc).__name__}: {exc}\n")
            log.flush()
            return 125
    return int(proc.returncode)


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No CSV files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def f(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return default
    return float(value)


def boolish(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def score_step4(csv_path: Path) -> ValidationScore:
    rows = [r for r in read_csv(csv_path) if r.get("mode") == "sac_actor"]
    constraints = {
        "hpt_v2_1to1_switchlevel": (200.0, 210.0, 6.0, 760.0, 920.0),
        "hpt_v2_topology2_paper": (198.0, 212.0, 8.0, 760.0, 930.0),
    }
    penalty = 0.0
    reasons: list[str] = []
    max_lv_error = 0.0
    max_unbalance = 0.0
    max_lv_peak = 0.0
    min_lv_rms = 0.0
    min_vdc = float("inf")
    for row in rows:
        model = str(row.get("model"))
        lv_lo, lv_hi, ub_hi, vdc_lo, vdc_hi = constraints[model]
        lv = f(row, "lv_rms_mean")
        ub = f(row, "lv_unbalance")
        vdc = f(row, "vdc_mean")
        vdc_min = f(row, "vdc_min")
        act = f(row, "action_max_abs")
        max_lv_error = max(max_lv_error, abs(lv - 207.0))
        max_unbalance = max(max_unbalance, ub)
        min_vdc = min(min_vdc, vdc_min)
        penalty += abs(lv - 207.0) / 5.0 + ub / max(ub_hi, 1.0)
        if lv < lv_lo or lv > lv_hi:
            reasons.append(f"{model}:lv={lv:.3f}")
            penalty += 100.0 + abs(lv - min(max(lv, lv_lo), lv_hi))
        if ub > ub_hi:
            reasons.append(f"{model}:unbalance={ub:.3f}")
            penalty += 50.0 + (ub - ub_hi)
        if vdc < vdc_lo or vdc > vdc_hi:
            reasons.append(f"{model}:vdc_mean={vdc:.3f}")
            penalty += 50.0 + abs(vdc - min(max(vdc, vdc_lo), vdc_hi)) / 20.0
        if act > 0.9501:
            reasons.append(f"{model}:action={act:.3f}")
            penalty += 50.0 + (act - 0.95) * 100.0
    if not rows:
        reasons.append("no_sac_actor_rows")
        penalty = 1e9
        min_vdc = 0.0
    return ValidationScore(
        name="step4",
        csv_path=str(csv_path),
        score=float(penalty),
        passed=not reasons,
        max_lv_error=float(max_lv_error),
        max_unbalance=float(max_unbalance),
        max_lv_peak=float(max_lv_peak),
        min_lv_rms=float(min_lv_rms),
        min_vdc=float(min_vdc),
        failing_reasons=reasons,
    )


def score_fault(csv_path: Path) -> ValidationScore:
    rows = [r for r in read_csv(csv_path) if r.get("mode") == "sac_actor"]
    constraints = {
        # topology, fault/recovery LV window, Vdc floor, transient peak ceiling,
        # transient RMS floor.  The old score let topology2 pass with 255-274 V
        # short peaks; this guard keeps Simulink promotion aligned with a usable
        # HPT voltage regulator rather than only a good settled average.
        "topology1": (196.0, 214.0, 650.0, 235.0, 180.0),
        "topology2": (194.0, 220.0, 620.0, 235.0, 180.0),
    }
    penalty = 0.0
    reasons: list[str] = []
    max_lv_error = 0.0
    max_lv_peak = 0.0
    min_lv_rms = float("inf")
    min_vdc = float("inf")
    for row in rows:
        topology = str(row.get("topology"))
        lv_lo, lv_hi, vdc_lo, peak_hi, min_floor = constraints[topology]
        lv_fault = f(row, "lv_fault_rms_mean")
        lv_recovery = f(row, "lv_recovery_rms_mean")
        lv_peak = f(row, "lv_peak_rms", lv_recovery)
        lv_min = f(row, "lv_min_rms", lv_fault)
        vdc_min = f(row, "vdc_min")
        act = f(row, "action_max_abs")
        max_lv_error = max(max_lv_error, abs(lv_fault - 207.0), abs(lv_recovery - 207.0))
        max_lv_peak = max(max_lv_peak, lv_peak)
        min_lv_rms = min(min_lv_rms, lv_min)
        min_vdc = min(min_vdc, vdc_min)
        penalty += (
            abs(lv_fault - 207.0) / 8.0
            + abs(lv_recovery - 207.0) / 8.0
            + max(0.0, lv_peak - 207.0) / 20.0
            + max(0.0, 207.0 - lv_min) / 20.0
        )
        for label, lv in (("fault", lv_fault), ("recovery", lv_recovery)):
            if lv < lv_lo or lv > lv_hi:
                reasons.append(f"{topology}:{row.get('fault')}:{label}_lv={lv:.3f}")
                penalty += 100.0 + abs(lv - min(max(lv, lv_lo), lv_hi))
        if lv_peak > peak_hi:
            reasons.append(f"{topology}:{row.get('fault')}:lv_peak={lv_peak:.3f}")
            penalty += 100.0 + (lv_peak - peak_hi)
        if lv_min < min_floor:
            reasons.append(f"{topology}:{row.get('fault')}:lv_min={lv_min:.3f}")
            penalty += 100.0 + (min_floor - lv_min)
        if vdc_min < vdc_lo:
            reasons.append(f"{topology}:{row.get('fault')}:vdc_min={vdc_min:.3f}")
            penalty += 100.0 + (vdc_lo - vdc_min) / 20.0
        if act > 0.9501:
            reasons.append(f"{topology}:{row.get('fault')}:action={act:.3f}")
            penalty += 50.0 + (act - 0.95) * 100.0
    if not rows:
        reasons.append("no_sac_actor_rows")
        penalty = 1e9
        max_lv_peak = 0.0
        min_lv_rms = 0.0
        min_vdc = 0.0
    return ValidationScore(
        name="fault_transition",
        csv_path=str(csv_path),
        score=float(penalty),
        passed=not reasons,
        max_lv_error=float(max_lv_error),
        max_unbalance=0.0,
        max_lv_peak=float(max_lv_peak),
        min_lv_rms=float(min_lv_rms),
        min_vdc=float(min_vdc),
        failing_reasons=reasons,
    )


def run_step4(run_dir: Path, label: str) -> ValidationScore:
    code = f"run('{(SIMULINK / 'tests' / 'test_hpt_v2_sac_switchlevel_voltage_regulation.m').as_posix()}')"
    rc = run_cmd(["matlab", "-batch", code], run_dir / "logs" / f"{label}_step4.log", timeout_s=1800)
    if rc != 0:
        return ValidationScore("step4", "", 1e9, False, 0.0, 0.0, 0.0, 0.0, 0.0, [f"matlab_rc={rc}"])
    csv_path = latest_csv(RESULTS / "hpt_v2_sac_switchlevel_step4", "switchlevel_sac_step4_*.csv")
    return score_step4(csv_path)


def run_fault(run_dir: Path, label: str) -> ValidationScore:
    code = f"run('{(SIMULINK / 'tests' / 'test_hpt_v2_sac_fault_transition.m').as_posix()}')"
    rc = run_cmd(["matlab", "-batch", code], run_dir / "logs" / f"{label}_fault.log", timeout_s=2400)
    if rc != 0:
        return ValidationScore("fault_transition", "", 1e9, False, 0.0, 0.0, 0.0, 0.0, 0.0, [f"matlab_rc={rc}"])
    csv_path = latest_csv(RESULTS / "hpt_v2_sac_fault_transition", "hpt_v2_sac_fault_transition_*.csv")
    return score_fault(csv_path)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def render_report(
    run_dir: Path,
    started_at: str,
    baseline_step4: ValidationScore,
    baseline_fault: ValidationScore,
    records: list[IterationRecord],
    best_steady: ValidationScore,
    best_dynamic: ValidationScore,
    notes: Iterable[str],
) -> None:
    lines: list[str] = []
    lines.append("# HPT SAC Overnight Optimization Report")
    lines.append("")
    lines.append(f"- Started: `{started_at}`")
    lines.append(f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append(f"- Run dir: `{run_dir}`")
    lines.append("")
    lines.append("## Current Best Simulink Scores")
    lines.append("")
    lines.append(
        f"- Steady step4: score `{best_steady.score:.3f}`, pass `{best_steady.passed}`, "
        f"max LV error `{best_steady.max_lv_error:.3f} V`, max unbalance `{best_steady.max_unbalance:.3f} V`, "
        f"min Vdc `{best_steady.min_vdc:.3f} V`"
    )
    lines.append(
        f"- Fault transition: score `{best_dynamic.score:.3f}`, pass `{best_dynamic.passed}`, "
        f"max LV error `{best_dynamic.max_lv_error:.3f} V`, max LV peak `{best_dynamic.max_lv_peak:.3f} V`, "
        f"min LV RMS `{best_dynamic.min_lv_rms:.3f} V`, min Vdc `{best_dynamic.min_vdc:.3f} V`"
    )
    lines.append("")
    lines.append("## Baseline At Launch")
    lines.append("")
    lines.append(f"- Step4 CSV: `{baseline_step4.csv_path}`")
    lines.append(f"- Fault CSV: `{baseline_fault.csv_path}`")
    lines.append("")
    lines.append("## Iterations")
    lines.append("")
    if not records:
        lines.append("No optimization iteration completed yet.")
    for rec in records:
        lines.append(
            f"- Iter `{rec.iteration}` `{rec.curriculum}` seed `{rec.seed}` steps `{rec.steps}` "
            f"promote steady `{rec.promoted_steady}` dynamic `{rec.promoted_dynamic}` "
            f"elapsed `{rec.elapsed_s/60:.1f} min`"
        )
        if rec.steady_score:
            lines.append(
                f"  - steady score `{rec.steady_score.score:.3f}`, pass `{rec.steady_score.passed}`, "
                f"CSV `{rec.steady_score.csv_path}`"
            )
        if rec.dynamic_score:
            lines.append(
                f"  - fault score `{rec.dynamic_score.score:.3f}`, pass `{rec.dynamic_score.passed}`, "
                f"peak `{rec.dynamic_score.max_lv_peak:.3f} V`, min LV `{rec.dynamic_score.min_lv_rms:.3f} V`, "
                f"CSV `{rec.dynamic_score.csv_path}`"
            )
        if rec.notes:
            lines.append("  - notes: " + "; ".join(rec.notes))
    lines.append("")
    lines.append("## Proxy / Simulink Gap Notes")
    lines.append("")
    lines.extend(f"- {note}" for note in notes)
    lines.append("")
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def train_candidate(
    run_dir: Path,
    iteration: int,
    curriculum: str,
    seed: int,
    steps: int,
    init_model: Path | None,
    n_envs: int,
) -> tuple[Path, Path, dict, int]:
    model_path = MODELS / "hpt_overnight" / f"hpt_sac_{run_dir.name}_iter{iteration:03d}.zip"
    actor_path = run_dir / "candidates" / f"hpt_sac_actor_iter{iteration:03d}.mat"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.offline.train_hpt_voltage_sac",
        "--steps",
        str(steps),
        "--n-envs",
        str(n_envs),
        "--seed",
        str(seed),
        "--curriculum",
        curriculum,
        "--model-out",
        str(model_path),
        "--eval-rollouts",
        "0",
        "--export",
        "--export-out",
        str(actor_path),
    ]
    if init_model is not None and init_model.exists():
        cmd.extend(["--init-model", str(init_model)])
    rc = run_cmd(cmd, run_dir / "logs" / f"iter{iteration:03d}_train.log", timeout_s=7200)
    return model_path, actor_path, load_json(model_path.with_suffix(".json")), rc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--train-steps", type=int, default=60_000)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=999)
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    run_dir = RESULTS / f"hpt_sac_overnight_{now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "STARTED").write_text(started_at, encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_sac_overnight_simulink_optimize",
        config={
            "hours": args.hours,
            "train_steps": args.train_steps,
            "n_envs": args.n_envs,
            "seed": args.seed,
            "dry_run": bool(args.dry_run),
            "max_iterations": args.max_iterations,
        },
        topology_models=TOPOLOGY_MODELS,
        policy_checkpoint=STEADY_ACTOR,
        extra={
            "started_at": started_at,
            "steady_actor": str(STEADY_ACTOR),
            "dynamic_actor": str(DYNAMIC_ACTOR),
            "status_path": str(run_dir / "status.json"),
            "report_path": str(run_dir / "REPORT.md"),
        },
    )
    write_json(
        RESULTS / ".hpt_sac_overnight_current.json",
        {
            "run_dir": str(run_dir),
            "started": started_at,
            "pid": os.getpid(),
            "status_path": str(run_dir / "status.json"),
            "report_path": str(run_dir / "REPORT.md"),
        },
    )
    print(f"RUN_DIR={run_dir}", flush=True)

    backup_dir = run_dir / "actor_backups"
    copy_file(STEADY_ACTOR, backup_dir / "hpt_sac_actor_weights_start.mat")
    copy_file(DYNAMIC_ACTOR, backup_dir / "hpt_sac_actor_weights_dynamic_start.mat")

    notes = [
        "The proxy remains an averaged environment; Simulink switch-level validation is the source of record.",
        "Candidates are promoted only after passing the switch-level Simulink constraints, including fault-transition LV peak/min guards.",
        "The previous topology2 dynamic gap was traced to a Simulink hard-coded top2_reg_d override; the controller now keeps SAC direct and only applies physical clipping.",
        "The energy bridge is kept on the conventional DC-link loop; SAC energy outputs are logged but not promoted to direct bridge control in this run.",
    ]

    baseline_step4 = run_step4(run_dir, "baseline")
    baseline_fault = run_fault(run_dir, "baseline")
    best_steady = baseline_step4
    best_dynamic = baseline_fault
    copy_file(STEADY_ACTOR, backup_dir / "hpt_sac_actor_weights_best.mat")
    copy_file(DYNAMIC_ACTOR, backup_dir / "hpt_sac_actor_weights_dynamic_best.mat")

    records: list[IterationRecord] = []
    render_report(run_dir, started_at, baseline_step4, baseline_fault, records, best_steady, best_dynamic, notes)
    write_json(
        run_dir / "status.json",
        {
            "status": "baseline_complete" if not args.dry_run else "dry_run_complete",
            "run_dir": str(run_dir),
            "baseline_step4": asdict(baseline_step4),
            "baseline_fault": asdict(baseline_fault),
        },
    )
    if args.dry_run:
        print(str(run_dir), flush=True)
        return

    deadline = time.time() + args.hours * 3600.0
    curricula = ["all", "switch_fault_transition", "topology2_fault"]
    init_models = {
        "all": MODELS / "hpt_voltage_sac_best.zip",
        "switch_fault_transition": MODELS / "hpt_voltage_sac_switch_fault_candidate.zip",
        "topology2_fault": MODELS / "hpt_voltage_sac_topology2_fault_candidate.zip",
    }
    last_models = dict(init_models)

    iteration = 0
    while time.time() < deadline and iteration < args.max_iterations:
        iter_start = time.time()
        curriculum = curricula[iteration % len(curricula)]
        seed = args.seed + iteration
        model_path, actor_path, proxy_summary, rc = train_candidate(
            run_dir,
            iteration,
            curriculum,
            seed,
            args.train_steps,
            last_models.get(curriculum),
            args.n_envs,
        )
        rec_notes: list[str] = []
        promoted_steady = False
        promoted_dynamic = False
        steady_score: ValidationScore | None = None
        dynamic_score: ValidationScore | None = None

        if rc != 0 or not actor_path.exists():
            rec_notes.append(f"training/export failed rc={rc}")
        else:
            if model_path.exists():
                last_models[curriculum] = model_path
            # Steady actor evaluation: candidate replaces the steady actor only.
            copy_file(actor_path, STEADY_ACTOR)
            copy_file(backup_dir / "hpt_sac_actor_weights_dynamic_best.mat", DYNAMIC_ACTOR)
            steady_score = run_step4(run_dir, f"iter{iteration:03d}_steady")
            if steady_score.passed and steady_score.score < best_steady.score:
                promoted_steady = True
                best_steady = steady_score
                copy_file(actor_path, backup_dir / "hpt_sac_actor_weights_best.mat")
                rec_notes.append("promoted steady actor")
            else:
                copy_file(backup_dir / "hpt_sac_actor_weights_best.mat", STEADY_ACTOR)

            # Dynamic actor evaluation: candidate replaces the dynamic actor only.
            copy_file(backup_dir / "hpt_sac_actor_weights_best.mat", STEADY_ACTOR)
            copy_file(actor_path, DYNAMIC_ACTOR)
            dynamic_score = run_fault(run_dir, f"iter{iteration:03d}_dynamic")
            if dynamic_score.passed and dynamic_score.score < best_dynamic.score:
                promoted_dynamic = True
                best_dynamic = dynamic_score
                copy_file(actor_path, backup_dir / "hpt_sac_actor_weights_dynamic_best.mat")
                rec_notes.append("promoted dynamic actor")
            else:
                copy_file(backup_dir / "hpt_sac_actor_weights_dynamic_best.mat", DYNAMIC_ACTOR)

        # Ensure active actors are the current Simulink-best pair after every iteration.
        copy_file(backup_dir / "hpt_sac_actor_weights_best.mat", STEADY_ACTOR)
        copy_file(backup_dir / "hpt_sac_actor_weights_dynamic_best.mat", DYNAMIC_ACTOR)

        record = IterationRecord(
            iteration=iteration,
            curriculum=curriculum,
            seed=seed,
            steps=args.train_steps,
            model_path=str(model_path),
            actor_mat=str(actor_path),
            proxy_summary=proxy_summary,
            steady_score=steady_score,
            dynamic_score=dynamic_score,
            promoted_steady=promoted_steady,
            promoted_dynamic=promoted_dynamic,
            elapsed_s=time.time() - iter_start,
            notes=rec_notes,
        )
        records.append(record)
        write_json(
            run_dir / "status.json",
            {
                "status": "running",
                "updated": datetime.now().isoformat(timespec="seconds"),
                "deadline_epoch": deadline,
                "best_steady": asdict(best_steady),
                "best_dynamic": asdict(best_dynamic),
                "iterations": [asdict(r) for r in records],
            },
        )
        render_report(run_dir, started_at, baseline_step4, baseline_fault, records, best_steady, best_dynamic, notes)
        iteration += 1

    write_json(
        run_dir / "status.json",
        {
            "status": "complete",
            "updated": datetime.now().isoformat(timespec="seconds"),
            "best_steady": asdict(best_steady),
            "best_dynamic": asdict(best_dynamic),
            "iterations": [asdict(r) for r in records],
        },
    )
    render_report(run_dir, started_at, baseline_step4, baseline_fault, records, best_steady, best_dynamic, notes)
    print(str(run_dir), flush=True)


if __name__ == "__main__":
    main()

