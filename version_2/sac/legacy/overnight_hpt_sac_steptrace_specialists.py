"""Run an automated HPT SAC specialist search using switch-level step traces.

This runner is intentionally conservative:

1. Collect switch-level per-step traces.
2. Train one steady actor and one dynamic actor from filtered trace subsets.
3. Export them to the Simulink actor MAT files.
4. Run the raw guard=0 switch-level smoke test.
5. Promote the candidate only if it improves the raw smoke score.

It is a research runner, not a final controller generator.
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
STEADY_MAT = SIMULINK / "hpt_sac_actor_weights.mat"
DYNAMIC_MAT = SIMULINK / "hpt_sac_actor_weights_dynamic.mat"
BEST_STEADY_INIT = MODELS / "hpt_voltage_sac_currentref_steady_fullteacher_settled.zip"
BEST_DYNAMIC_INIT = MODELS / "hpt_voltage_sac_currentref_dynamic_fullteacher_settled.zip"


@dataclass
class SmokeScore:
    csv_path: str
    passed: int
    total: int
    score: float
    fail_summary: list[str]


@dataclass
class Iteration:
    index: int
    variant: str
    trace_csv: str
    steady_model: str
    dynamic_model: str
    smoke: SmokeScore | None
    promoted: bool
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


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def export_actor(model: Path, out_mat: Path, log_path: Path) -> int:
    return run_cmd(
        [
            sys.executable,
            "-m",
            "version_2.sac.export_hpt_sac_actor",
            "--model",
            str(model),
            "--out",
            str(out_mat),
        ],
        log_path,
        timeout_s=300,
    )


def train_actor(
    *,
    run_dir: Path,
    role: str,
    iteration: int,
    variant: dict,
    trace_csv: Path,
    init_model: Path,
) -> tuple[Path, int]:
    model_out = MODELS / "hpt_steptrace_specialists" / (
        f"{run_dir.name}_{iteration:03d}_{role}_{variant['name']}.zip"
    )
    if role == "steady":
        cmd = [
            sys.executable,
            "-m",
            "version_2.sac.pretrain_hpt_actor_bc",
            "--run-id",
            f"{run_dir.name}_{iteration:03d}_steady_{variant['name']}",
            "--curriculum",
            "steady_step4",
            "--teacher-source",
            "execution_guard",
            "--episodes-per-scenario",
            "2",
            "--noise-std",
            "0.02",
            "--epochs",
            str(variant["steady_epochs"]),
            "--batch-size",
            "512",
            "--switch-trace-csv",
            str(trace_csv),
            "--switch-trace-repeat",
            str(variant["steady_repeat"]),
            "--switch-trace-scenario-types",
            "steady",
            "--switch-trace-condition-classes",
            "steady",
            "--energy-limit",
            "0.95",
            "--init-model",
            str(init_model),
            "--model-out",
            str(model_out),
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "version_2.sac.pretrain_hpt_actor_bc",
            "--run-id",
            f"{run_dir.name}_{iteration:03d}_dynamic_{variant['name']}",
            "--curriculum",
            "expanded_fault_transition",
            "--teacher-source",
            "execution_guard",
            "--episodes-per-scenario",
            "2",
            "--noise-std",
            "0.03",
            "--epochs",
            str(variant["dynamic_epochs"]),
            "--batch-size",
            "512",
            "--switch-trace-csv",
            str(trace_csv),
            "--switch-trace-repeat",
            str(variant["dynamic_repeat"]),
            "--switch-trace-scenario-types",
            "fault",
            "--switch-trace-condition-classes",
            variant["dynamic_classes"],
            "--switch-trace-topologies",
            variant.get("dynamic_topologies", "all"),
            "--energy-limit",
            "0.95",
            "--init-model",
            str(init_model),
            "--model-out",
            str(model_out),
        ]
    rc = run_cmd(cmd, run_dir / "logs" / f"iter{iteration:03d}_{role}_{variant['name']}.log", timeout_s=1800)
    return model_out, rc


def collect_trace(run_dir: Path, iteration: int) -> tuple[Path | None, int]:
    rc = run_cmd(
        [
            "matlab",
            "-batch",
            "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); collect_hpt_v2_sac_step_traces;",
        ],
        run_dir / "logs" / f"iter{iteration:03d}_collect_step_trace.log",
        timeout_s=2400,
    )
    if rc != 0:
        return None, rc
    return latest_csv(RESULTS / "hpt_v2_sac_step_traces", "step_traces_*.csv"), 0


def run_smoke(run_dir: Path, iteration: int) -> tuple[Path | None, int]:
    rc = run_cmd(
        [
            "matlab",
            "-batch",
            "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); eval_hpt_v2_sac_raw_switchlevel_smoke;",
        ],
        run_dir / "logs" / f"iter{iteration:03d}_raw_smoke.log",
        timeout_s=1800,
    )
    if rc != 0:
        return None, rc
    return latest_csv(RESULTS / "hpt_v2_sac_raw_switchlevel_smoke", "raw_sac_switchlevel_smoke_*.csv"), 0


def score_smoke(csv_path: Path) -> SmokeScore:
    rows: list[dict[str, str]]
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("mode") == "sac_actor_raw_guard0"]
    passed = 0
    penalty = 0.0
    fail_summary: list[str] = []
    for row in rows:
        ok = str(row.get("within_window", "")).strip().lower() in {"1", "true"}
        if ok:
            passed += 1
        else:
            reason = row.get("window_reason", "")
            fail_summary.append(f"{row.get('topology')}:{row.get('scenario_type')}:{row.get('case_name')}:{reason}")
            penalty += 100.0
        lv = float(row.get("lv_mean") or 207.0)
        vdc_min = float(row.get("vdc_min") or 0.0)
        penalty += abs(lv - 207.0) / 10.0
        penalty += max(0.0, 650.0 - vdc_min) / 20.0
        if row.get("scenario_type") == "fault":
            lv_peak = float(row.get("lv_peak") or 207.0)
            lv_min = float(row.get("lv_min") or 207.0)
            penalty += max(0.0, lv_peak - 235.0) / 5.0
            penalty += max(0.0, 180.0 - lv_min) / 5.0
    return SmokeScore(
        csv_path=str(csv_path),
        passed=passed,
        total=len(rows),
        score=float(penalty),
        fail_summary=fail_summary,
    )


def better(candidate: SmokeScore, best: SmokeScore) -> bool:
    if candidate.passed != best.passed:
        return candidate.passed > best.passed
    return candidate.score < best.score


def write_report(run_dir: Path, best: SmokeScore, records: list[Iteration], status: str) -> None:
    lines = [
        "# HPT SAC Step-Trace Specialist Overnight Report",
        "",
        f"- Status: `{status}`",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Best: `{best.passed}/{best.total}`, score `{best.score:.3f}`",
        f"- Best CSV: `{best.csv_path}`",
        "",
        "## Iterations",
        "",
    ]
    for rec in records:
        if rec.smoke is None:
            smoke_text = "no smoke"
        else:
            smoke_text = f"{rec.smoke.passed}/{rec.smoke.total}, score {rec.smoke.score:.3f}"
        lines.append(
            f"- `{rec.index}` `{rec.variant}` promoted `{rec.promoted}` smoke `{smoke_text}` "
            f"elapsed `{rec.elapsed_s/60:.1f} min`"
        )
        if rec.notes:
            lines.append("  - " + "; ".join(rec.notes))
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": status,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "best": asdict(best),
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--max-iterations", type=int, default=999)
    parser.add_argument("--reuse-latest-trace", action="store_true")
    args = parser.parse_args()

    run_dir = RESULTS / f"hpt_sac_steptrace_specialists_{now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "RUN_DIR.txt").write_text(str(run_dir), encoding="utf-8")
    (RESULTS / ".hpt_sac_steptrace_specialists_current.json").write_text(
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

    best_dir = run_dir / "best"
    copy(STEADY_MAT, best_dir / "hpt_sac_actor_weights.mat")
    copy(DYNAMIC_MAT, best_dir / "hpt_sac_actor_weights_dynamic.mat")
    baseline_csv, baseline_rc = run_smoke(run_dir, -1)
    if baseline_rc != 0 or baseline_csv is None:
        baseline_csv = latest_csv(RESULTS / "hpt_v2_sac_raw_switchlevel_smoke", "raw_sac_switchlevel_smoke_*.csv")
    best = score_smoke(baseline_csv)

    variants = [
        {
            "name": "shallow_all_r128",
            "steady_repeat": 64,
            "dynamic_repeat": 128,
            "steady_epochs": 35,
            "dynamic_epochs": 45,
            "dynamic_classes": "shallow_lvrt,shallow_hvrt",
        },
        {
            "name": "shallow_top2_r256",
            "steady_repeat": 32,
            "dynamic_repeat": 256,
            "steady_epochs": 30,
            "dynamic_epochs": 55,
            "dynamic_classes": "shallow_lvrt,shallow_hvrt",
            "dynamic_topologies": "topology2",
        },
        {
            "name": "fault_all_r96",
            "steady_repeat": 32,
            "dynamic_repeat": 96,
            "steady_epochs": 30,
            "dynamic_epochs": 45,
            "dynamic_classes": "deep_lvrt,shallow_lvrt,shallow_hvrt,high_hvrt",
        },
    ]

    deadline = time.time() + args.hours * 3600.0
    records: list[Iteration] = []
    write_report(run_dir, best, records, "running")

    iteration = 0
    while time.time() < deadline and iteration < args.max_iterations:
        start = time.time()
        variant = variants[iteration % len(variants)]
        notes: list[str] = []
        promoted = False
        trace_csv: Path | None = None
        smoke: SmokeScore | None = None

        try:
            if args.reuse_latest_trace:
                trace_csv = latest_csv(RESULTS / "hpt_v2_sac_step_traces", "step_traces_*.csv")
            else:
                trace_csv, rc = collect_trace(run_dir, iteration)
                if rc != 0 or trace_csv is None:
                    notes.append(f"trace collection failed rc={rc}")
                    raise RuntimeError("trace collection failed")

            steady_model, rc = train_actor(
                run_dir=run_dir,
                role="steady",
                iteration=iteration,
                variant=variant,
                trace_csv=trace_csv,
                init_model=BEST_STEADY_INIT,
            )
            if rc != 0:
                notes.append(f"steady train failed rc={rc}")
                raise RuntimeError("steady train failed")

            dynamic_model, rc = train_actor(
                run_dir=run_dir,
                role="dynamic",
                iteration=iteration,
                variant=variant,
                trace_csv=trace_csv,
                init_model=BEST_DYNAMIC_INIT,
            )
            if rc != 0:
                notes.append(f"dynamic train failed rc={rc}")
                raise RuntimeError("dynamic train failed")

            if export_actor(steady_model, STEADY_MAT, run_dir / "logs" / f"iter{iteration:03d}_export_steady.log") != 0:
                notes.append("steady export failed")
                raise RuntimeError("steady export failed")
            if export_actor(dynamic_model, DYNAMIC_MAT, run_dir / "logs" / f"iter{iteration:03d}_export_dynamic.log") != 0:
                notes.append("dynamic export failed")
                raise RuntimeError("dynamic export failed")

            smoke_csv, rc = run_smoke(run_dir, iteration)
            if rc != 0 or smoke_csv is None:
                notes.append(f"smoke failed rc={rc}")
                raise RuntimeError("smoke failed")
            smoke = score_smoke(smoke_csv)
            if better(smoke, best):
                best = smoke
                promoted = True
                copy(STEADY_MAT, best_dir / "hpt_sac_actor_weights.mat")
                copy(DYNAMIC_MAT, best_dir / "hpt_sac_actor_weights_dynamic.mat")
                notes.append("promoted")
            else:
                copy(best_dir / "hpt_sac_actor_weights.mat", STEADY_MAT)
                copy(best_dir / "hpt_sac_actor_weights_dynamic.mat", DYNAMIC_MAT)
                notes.append("restored previous best")
        except Exception as exc:
            notes.append(f"exception={type(exc).__name__}:{exc}")
            copy(best_dir / "hpt_sac_actor_weights.mat", STEADY_MAT)
            copy(best_dir / "hpt_sac_actor_weights_dynamic.mat", DYNAMIC_MAT)
            steady_model = Path("")
            dynamic_model = Path("")

        record = Iteration(
            index=iteration,
            variant=variant["name"],
            trace_csv=str(trace_csv) if trace_csv else "",
            steady_model=str(steady_model),
            dynamic_model=str(dynamic_model),
            smoke=smoke,
            promoted=promoted,
            elapsed_s=time.time() - start,
            notes=notes,
        )
        records.append(record)
        write_report(run_dir, best, records, "running")
        iteration += 1

    copy(best_dir / "hpt_sac_actor_weights.mat", STEADY_MAT)
    copy(best_dir / "hpt_sac_actor_weights_dynamic.mat", DYNAMIC_MAT)
    write_report(run_dir, best, records, "complete")
    print(str(run_dir), flush=True)


if __name__ == "__main__":
    main()
