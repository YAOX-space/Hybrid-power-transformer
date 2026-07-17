"""Run the version-2 full-action HPT recalibration and specialist campaign.

This runner executes the research sequence after changing the data contract to
separate command actions from measured switch-level responses:

1. collect a fresh switch-level FRT matrix;
2. regenerate ``hpt_proxy_calibration.json`` from that matrix;
3. run proxy gap, reward alignment, and energy command-response diagnostics;
4. rebuild the boundary full-action dataset;
5. train per-topology/per-fault offline specialists;
6. validate selected candidates against the strong conventional baseline in
   switch-level Simulink.

Every stage writes a log and the campaign writes ``status.json`` after each
stage, so interrupted runs can be audited and manually resumed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
SIMULINK = ROOT / "version_2" / "simulink"
RESULTS = ROOT / "lab" / "results"
FRT_MATRIX_DIR = RESULTS / "hpt_v2_frt_calibration_matrix"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"


@dataclass
class StageRecord:
    name: str
    command: list[str]
    returncode: int | None = None
    elapsed_s: float = 0.0
    log: str = ""
    started_at: str = ""
    finished_at: str = ""
    notes: str = ""


def latest(path: Path, pattern: str) -> Path:
    files = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {path / pattern}")
    return files[-1]


def latest_control(pattern: str) -> Path:
    files = sorted(
        (p for p in CONTROL_DIR.glob(pattern) if "_summary" not in p.stem),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise FileNotFoundError(f"No files matching {CONTROL_DIR / pattern}")
    return files[-1]


def matlab_batch(statement: str) -> list[str]:
    return ["matlab", "-batch", statement]


def py_module(module: str, *args: str | Path) -> list[str]:
    return [sys.executable, "-m", module, *[str(x) for x in args]]


def write_status(run_dir: Path, records: list[StageRecord], extra: dict) -> None:
    status = {
        "run_dir": str(run_dir),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "records": [asdict(r) for r in records],
        **extra,
    }
    (run_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def run_stage(run_dir: Path, name: str, command: list[str], *, timeout_s: int | None = None) -> StageRecord:
    log_path = run_dir / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rec = StageRecord(
        name=name,
        command=command,
        log=str(log_path),
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("$ " + subprocess.list2cmdline(command) + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                command,
                cwd=str(ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
            )
            rec.returncode = int(proc.returncode)
        except subprocess.TimeoutExpired:
            rec.returncode = 124
            rec.notes = f"timeout_after_{timeout_s}s"
            log.write(f"\nTIMEOUT after {timeout_s} s\n")
        except Exception as exc:
            rec.returncode = 125
            rec.notes = f"{type(exc).__name__}: {exc}"
            log.write(f"\nCOMMAND_EXCEPTION {type(exc).__name__}: {exc}\n")
    rec.elapsed_s = time.time() - t0
    rec.finished_at = datetime.now().isoformat(timespec="seconds")
    return rec


def make_report(run_dir: Path, records: list[StageRecord], artifacts: dict[str, str]) -> None:
    lines = [
        "# HPT Full-Action Recalibration Campaign",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
        "## Stages",
        "",
        "| Stage | Return | Elapsed s | Log |",
        "| --- | ---: | ---: | --- |",
    ]
    for rec in records:
        lines.append(
            f"| `{rec.name}` | `{rec.returncode}` | `{rec.elapsed_s:.1f}` | `{rec.log}` |"
        )
    lines.extend(["", "## Artifacts", ""])
    for key, value in artifacts.items():
        lines.append(f"- `{key}`: `{value}`")
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--matrix-mode", default="full", choices=["pilot", "holdout", "full"])
    parser.add_argument("--topology", default="all", choices=["topology1", "topology2", "all"])
    parser.add_argument("--skip-matrix", action="store_true")
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--trace-csv", type=Path, default=None)
    parser.add_argument("--offline-epochs", type=int, default=500)
    parser.add_argument("--switch-max-cases", type=int, default=8)
    parser.add_argument("--switch-topology", default="all", choices=["topology1", "topology2", "all"])
    parser.add_argument("--switch-category", default="all", choices=["LVRT", "HVRT", "all"])
    parser.add_argument("--keep-going", action="store_true", help="Continue after failed diagnostic stages.")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("hpt_full_action_recalibration_%Y%m%d_%H%M%S")
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    records: list[StageRecord] = []
    artifacts: dict[str, str] = {}

    def append_and_check(rec: StageRecord, *, fatal: bool = True) -> bool:
        records.append(rec)
        write_status(run_dir, records, {"artifacts": artifacts})
        make_report(run_dir, records, artifacts)
        if rec.returncode != 0 and fatal and not args.keep_going:
            return False
        return True

    if args.skip_matrix:
        matrix_csv = args.matrix_csv or latest(FRT_MATRIX_DIR, "frt_calibration_matrix_*.csv")
        trace_csv = args.trace_csv or latest(FRT_MATRIX_DIR, "frt_calibration_traces_*.csv")
    else:
        statement = (
            "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); "
            f"hpt_calib_mode='{args.matrix_mode}'; "
            f"hpt_calib_topology='{args.topology}'; "
            "collect_hpt_v2_frt_calibration_matrix;"
        )
        before = set(FRT_MATRIX_DIR.glob("frt_calibration_matrix_*.csv"))
        rec = run_stage(run_dir, "01_collect_frt_matrix", matlab_batch(statement), timeout_s=None)
        if not append_and_check(rec):
            return rec.returncode or 1
        after = set(FRT_MATRIX_DIR.glob("frt_calibration_matrix_*.csv"))
        new_matrix = sorted(after - before, key=lambda p: p.stat().st_mtime)
        matrix_csv = new_matrix[-1] if new_matrix else latest(FRT_MATRIX_DIR, "frt_calibration_matrix_*.csv")
        trace_csv = latest(FRT_MATRIX_DIR, "frt_calibration_traces_*.csv")

    artifacts["matrix_csv"] = str(matrix_csv)
    artifacts["trace_csv"] = str(trace_csv)

    stage_commands: list[tuple[str, list[str], bool]] = [
        (
            "02_calibrate_proxy",
            py_module("version_2.sac.calibrate_hpt_frt_proxy_from_matrix", "--matrix-csv", matrix_csv),
            True,
        ),
        (
            "03_proxy_gap",
            py_module("version_2.sac.measure_hpt_frt_proxy_gap", "--matrix-csv", matrix_csv),
            False,
        ),
        (
            "04_reward_alignment",
            py_module("version_2.sac.measure_hpt_reward_alignment", "--matrix-csv", matrix_csv),
            False,
        ),
        (
            "05_energy_cmd_response",
            py_module(
                "version_2.sac.fit_hpt_energy_cmd_response",
                "--matrix-csv",
                matrix_csv,
                "--run-id",
                run_id,
            ),
            False,
        ),
    ]
    for name, command, fatal in stage_commands:
        rec = run_stage(run_dir, name, command)
        if not append_and_check(rec, fatal=fatal):
            return rec.returncode or 1

    conventional_boundary = latest_control("control_comparison_*conventional_boundary*.csv")
    artifacts["conventional_boundary_csv"] = str(conventional_boundary)
    rec = run_stage(
        run_dir,
        "06_build_full_action_dataset",
        py_module(
            "version_2.sac.build_hpt_boundary_full_action_dataset",
            "--conventional-csv",
            conventional_boundary,
            "--matrix-csv",
            matrix_csv,
            "--candidate-selection",
            "near_boundary_depths",
            "--run-id",
            run_id,
        ),
    )
    if not append_and_check(rec):
        return rec.returncode or 1

    dataset_csv = ROOT / "version_2" / "data" / "hpt_boundary_full_action" / run_id / "dataset.csv"
    artifacts["dataset_csv"] = str(dataset_csv)
    rec = run_stage(
        run_dir,
        "07_train_offline_specialists",
        py_module(
            "version_2.sac.train_hpt_offline_full_action_baselines",
            "--dataset-csv",
            dataset_csv,
            "--run-id",
            run_id,
            "--topology",
            "all",
            "--category",
            "all",
            "--duration-ms",
            "all",
            "--max-cases",
            "0",
            "--epochs",
            str(args.offline_epochs),
            "--batch-size",
            "32",
            "--algorithms",
            "auto",
            "--group-specialists",
        ),
    )
    if not append_and_check(rec):
        return rec.returncode or 1

    case_results = RESULTS / run_id / "case_results.csv"
    if not case_results.exists():
        alt = RESULTS / "hpt_offline_full_action_group_boundary" / "case_results.csv"
        case_results = alt if alt.exists() else case_results
    artifacts["offline_case_results_csv"] = str(case_results)
    rec = run_stage(
        run_dir,
        "08_switch_validate",
        py_module(
            "version_2.sac.validate_hpt_offline_actions_switchlevel",
            "--case-results-csv",
            case_results,
            "--run-id",
            run_id,
            "--topology",
            args.switch_topology,
            "--category",
            args.switch_category,
            "--algorithm-contains",
            "awac_style",
            "--max-cases",
            str(args.switch_max_cases),
        ),
        timeout_s=None,
    )
    if not append_and_check(rec, fatal=False):
        return rec.returncode or 1

    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_full_action_recalibration_campaign",
        config=vars(args),
        dataset_manifest=matrix_csv,
        extra={"artifacts": artifacts},
    )
    make_report(run_dir, records, artifacts)
    print(json.dumps({"run_dir": str(run_dir), "artifacts": artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
