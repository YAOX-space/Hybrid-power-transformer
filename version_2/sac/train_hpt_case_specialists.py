"""Train per-topology/per-case HPT SAC specialists and validate on switch level.

This runner follows the previous-version expert idea, but maps it to the
version_2 HPT models:

- one actor per steady grid/topology or fault/topology case;
- switch-level step traces are used as the immediate teacher data;
- every candidate is exported and tested on the corresponding raw guard=0
  switch-level case before it can be marked successful.

It intentionally does not build the final Simulink actor bank yet.  The purpose
is to identify which specialist policies actually survive the physical
switch-level plants before hard-wiring a router.
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


ROOT = Path(__file__).resolve().parents[2]
SIMULINK = ROOT / "version_2" / "simulink"
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
TRACE_DIR = RESULTS / "hpt_v2_sac_step_traces"
FRT_TEACHER_TRACE_DIR = RESULTS / "hpt_v2_frt_teacher_traces"
SINGLE_CASE_DIR = RESULTS / "hpt_v2_sac_single_case"

STEADY_MAT = SIMULINK / "hpt_sac_actor_weights.mat"
DYNAMIC_MAT = SIMULINK / "hpt_sac_actor_weights_dynamic.mat"
BEST_STEADY_INIT = MODELS / "hpt_voltage_sac_currentref_steady_fullteacher_settled.zip"
BEST_DYNAMIC_INIT = MODELS / "hpt_voltage_sac_currentref_dynamic_fullteacher_settled.zip"


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    topology: str
    scenario_type: str
    case_name: str
    condition_classes: str
    init_model: Path
    export_slot: str
    curriculum: str
    fixed_target: str | None = None


@dataclass
class CaseScore:
    csv_path: str
    passed: bool
    score: float
    fail_reason: str
    lv_mean: float
    lv_recovery_mean: float
    lv_peak: float
    lv_min: float
    vdc_mean: float
    vdc_min: float
    action_max_abs: float
    reg_d_mean: float
    reg_q_mean: float
    energy_d_mean: float
    energy_q_mean: float


@dataclass
class SpecialistRecord:
    spec: dict
    baseline: CaseScore | None
    model_path: str
    actor_mat: str
    candidate: CaseScore | None
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


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def default_specs() -> list[SpecialistSpec]:
    specs: list[SpecialistSpec] = []
    for topology in ("topology1", "topology2"):
        for grid in ("grid_9000V", "grid_10000V", "grid_11000V"):
            specs.append(
                SpecialistSpec(
                    name=f"{topology}_steady_{grid.lower()}",
                    topology=topology,
                    scenario_type="steady",
                    case_name=grid,
                    condition_classes="steady",
                    init_model=BEST_STEADY_INIT,
                    export_slot="steady",
                    curriculum="steady_step4",
                    fixed_target=(
                        "0.55,0,0.4,0"
                        if topology == "topology1" and grid == "grid_9000V"
                        else None
                    ),
                )
            )
        for case_name, cls in (
            ("sag_0p20", "lvrt"),
            ("sag_0p50", "lvrt"),
            ("sag_0p75", "lvrt"),
            ("sag_0p85", "lvrt"),
            ("sag_0p90", "lvrt"),
            ("swell_1p10", "hvrt"),
            ("swell_1p20", "hvrt"),
            ("swell_1p25", "hvrt"),
            ("swell_1p30", "hvrt"),
        ):
            specs.append(
                SpecialistSpec(
                    name=f"{topology}_fault_{case_name}",
                    topology=topology,
                    scenario_type="fault",
                    case_name=case_name,
                    condition_classes=cls,
                    init_model=BEST_DYNAMIC_INIT,
                    export_slot="dynamic",
                    curriculum="expanded_fault_transition",
                )
            )
    return specs


def spec_to_dict(spec: SpecialistSpec) -> dict:
    out = asdict(spec)
    out["init_model"] = str(spec.init_model)
    return out


def fixed_target_uses_energy(spec: SpecialistSpec) -> bool:
    if not spec.fixed_target:
        return False
    parts = [float(p.strip()) for p in spec.fixed_target.split(",") if p.strip()]
    return len(parts) >= 4 and (abs(parts[2]) > 1e-9 or abs(parts[3]) > 1e-9)


def interesting_specs() -> list[SpecialistSpec]:
    """Current failing best-case specialists.

    These are the cases that still fail the best raw guard=0 smoke matrix.
    """

    return [
        s
        for s in default_specs()
        if (
            (s.topology == "topology1" and s.scenario_type == "steady")
            or (s.topology == "topology2" and s.scenario_type == "fault")
        )
    ]


def score_case(csv_path: Path) -> CaseScore:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise RuntimeError(f"Expected one single-case row in {csv_path}, got {len(rows)}")
    row = rows[0]
    passed = str(row.get("within_window", "")).strip().lower() in {"1", "true"}
    reason = str(row.get("window_reason", ""))
    lv_mean = float(row.get("lv_mean") or 0.0)
    lv_recovery = float(row.get("lv_recovery_mean") or "nan")
    lv_peak = float(row.get("lv_peak") or 0.0)
    lv_min = float(row.get("lv_min") or 0.0)
    vdc_mean = float(row.get("vdc_mean") or 0.0)
    vdc_min = float(row.get("vdc_min") or 0.0)
    action_max = float(row.get("action_max_abs") or 0.0)
    penalty = 0.0
    if not passed:
        penalty += 100.0
    penalty += abs(lv_mean - 207.0) / 5.0
    if row.get("scenario_type") == "fault":
        penalty += abs(lv_recovery - 207.0) / 5.0
        penalty += max(0.0, lv_peak - 235.0) / 3.0
        penalty += max(0.0, 180.0 - lv_min) / 3.0
    penalty += max(0.0, 650.0 - vdc_min) / 10.0
    penalty += max(0.0, action_max - 0.9501) * 100.0
    return CaseScore(
        csv_path=str(csv_path),
        passed=passed,
        score=float(penalty),
        fail_reason=reason,
        lv_mean=lv_mean,
        lv_recovery_mean=lv_recovery,
        lv_peak=lv_peak,
        lv_min=lv_min,
        vdc_mean=vdc_mean,
        vdc_min=vdc_min,
        action_max_abs=action_max,
        reg_d_mean=float(row.get("reg_d_mean") or 0.0),
        reg_q_mean=float(row.get("reg_q_mean") or 0.0),
        energy_d_mean=float(row.get("energy_d_mean") or 0.0),
        energy_q_mean=float(row.get("energy_q_mean") or 0.0),
    )


def better(candidate: CaseScore, baseline: CaseScore) -> bool:
    if candidate.passed != baseline.passed:
        return candidate.passed
    return candidate.score < baseline.score


def eval_single_case(
    run_dir: Path,
    spec: SpecialistSpec,
    label: str,
    *,
    energy_enable: float,
) -> tuple[CaseScore | None, int]:
    code = (
        f"cd('{SIMULINK.as_posix()}'); "
        f"hpt_eval_topology='{spec.topology}'; "
        f"hpt_eval_scenario_type='{spec.scenario_type}'; "
        f"hpt_eval_case_name='{spec.case_name}'; "
        f"hpt_eval_energy_enable={float(energy_enable):.12g}; "
        "eval_hpt_v2_sac_single_case;"
    )
    rc = run_cmd(
        ["matlab", "-batch", code],
        run_dir / "logs" / f"{label}_{spec.name}_single_case.log",
        timeout_s=1800,
    )
    if rc != 0:
        return None, rc
    safe = f"{spec.topology}_{spec.scenario_type}_{spec.case_name}"
    return score_case(latest_csv(SINGLE_CASE_DIR, f"single_case_{safe}_*.csv")), 0


def train_specialist(
    run_dir: Path,
    spec: SpecialistSpec,
    trace_csv: Path,
    *,
    epochs: int,
    repeat: int,
    seed: int,
) -> tuple[Path, int]:
    model_out = MODELS / "hpt_case_specialists" / f"{run_dir.name}_{spec.name}.zip"
    window_zones = "steady" if spec.scenario_type == "steady" else "fault,recovery"
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.pretrain_hpt_actor_bc",
        "--run-id",
        f"{run_dir.name}_{spec.name}",
        "--curriculum",
        spec.curriculum,
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
        str(seed),
        "--switch-trace-csv",
        str(trace_csv),
        "--switch-trace-repeat",
        str(repeat),
        "--switch-trace-scenario-types",
        spec.scenario_type,
        "--switch-trace-topologies",
        spec.topology,
        "--switch-trace-condition-classes",
        spec.condition_classes,
        "--switch-trace-case-contains",
        spec.case_name,
        "--switch-trace-window-zones",
        window_zones,
    ]
    if spec.fixed_target:
        cmd.extend(["--switch-trace-fixed-target", spec.fixed_target])
    cmd.extend([
        "--energy-limit",
        "0.95",
    ])
    if spec.scenario_type == "steady" and not fixed_target_uses_energy(spec):
        cmd.append("--zero-energy-targets")
    cmd.extend([
        "--action-weights",
        "4,8,8,8",
        "--init-model",
        str(spec.init_model),
        "--model-out",
        str(model_out),
    ])
    rc = run_cmd(cmd, run_dir / "logs" / f"train_{spec.name}.log", timeout_s=2400)
    return model_out, rc


def export_actor(model: Path, out_mat: Path, run_dir: Path, spec: SpecialistSpec) -> int:
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
        run_dir / "logs" / f"export_{spec.name}.log",
        timeout_s=300,
    )


def write_report(run_dir: Path, records: list[SpecialistRecord], status: str) -> None:
    lines = [
        "# HPT Per-Case SAC Specialist Report",
        "",
        f"- Status: `{status}`",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Records: `{len(records)}`",
        "",
        "## Specialists",
        "",
    ]
    for rec in records:
        spec = rec.spec
        baseline = rec.baseline
        cand = rec.candidate
        lines.append(
            f"- `{spec['name']}` promoted `{rec.promoted}` elapsed `{rec.elapsed_s/60:.1f} min`"
        )
        if baseline:
            lines.append(
                f"  - baseline pass `{baseline.passed}` score `{baseline.score:.3f}` "
                f"LV `{baseline.lv_mean:.3f}` VdcMin `{baseline.vdc_min:.3f}` reason `{baseline.fail_reason}`"
            )
        if cand:
            lines.append(
                f"  - candidate pass `{cand.passed}` score `{cand.score:.3f}` "
                f"LV `{cand.lv_mean:.3f}` VdcMin `{cand.vdc_min:.3f}` reason `{cand.fail_reason}`"
            )
        if rec.notes:
            lines.append("  - notes: " + "; ".join(rec.notes))
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": status,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-csv", type=Path, default=None)
    parser.add_argument("--frt-trace-csv", type=Path, default=None)
    parser.add_argument("--all-cases", action="store_true")
    parser.add_argument("--topology", default="all")
    parser.add_argument("--scenario-type", default="all")
    parser.add_argument("--case-name", default="all")
    parser.add_argument("--max-specialists", type=int, default=999)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--repeat", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument(
        "--energy-enable",
        type=float,
        default=0.0,
        help="Whether single-case validation lets SAC drive the energy bridge. Default 0 keeps the physical DC-link loop.",
    )
    args = parser.parse_args()

    run_dir = RESULTS / f"hpt_case_specialists_{now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_csv = args.trace_csv or latest_csv(TRACE_DIR, "step_traces_*.csv")
    frt_trace_csv = args.frt_trace_csv or latest_csv(FRT_TEACHER_TRACE_DIR, "frt_teacher_*_traces.csv")
    specs = default_specs() if args.all_cases else interesting_specs()
    if args.topology != "all":
        specs = [s for s in specs if s.topology == args.topology]
    if args.scenario_type != "all":
        specs = [s for s in specs if s.scenario_type == args.scenario_type]
    if args.case_name != "all":
        specs = [s for s in specs if s.case_name == args.case_name]
    specs = specs[: max(0, int(args.max_specialists))]

    backup = run_dir / "actor_backups"
    copy_file(STEADY_MAT, backup / "hpt_sac_actor_weights_start.mat")
    copy_file(DYNAMIC_MAT, backup / "hpt_sac_actor_weights_dynamic_start.mat")
    (RESULTS / ".hpt_case_specialists_current.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "trace_csv": str(trace_csv),
                "frt_trace_csv": str(frt_trace_csv),
                "status_path": str(run_dir / "status.json"),
                "report_path": str(run_dir / "REPORT.md"),
                "pid": os.getpid(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records: list[SpecialistRecord] = []
    write_report(run_dir, records, "running")

    for i, spec in enumerate(specs):
        start = time.time()
        notes: list[str] = []
        baseline = None
        candidate = None
        promoted = False
        model_path = Path("")
        actor_mat = run_dir / "actors" / f"{spec.name}.mat"
        try:
            baseline, rc = eval_single_case(
                run_dir, spec, "baseline", energy_enable=args.energy_enable
            )
            if rc != 0 or baseline is None:
                notes.append(f"baseline single-case eval failed rc={rc}")
            model_path, rc = train_specialist(
                run_dir,
                spec,
                frt_trace_csv if spec.scenario_type == "fault" else trace_csv,
                epochs=args.epochs,
                repeat=args.repeat,
                seed=args.seed + i,
            )
            if rc != 0:
                notes.append(f"train failed rc={rc}")
                raise RuntimeError("train failed")
            if export_actor(model_path, actor_mat, run_dir, spec) != 0:
                notes.append("export failed")
                raise RuntimeError("export failed")

            if spec.export_slot == "steady":
                copy_file(actor_mat, STEADY_MAT)
                copy_file(backup / "hpt_sac_actor_weights_dynamic_start.mat", DYNAMIC_MAT)
            else:
                copy_file(backup / "hpt_sac_actor_weights_start.mat", STEADY_MAT)
                copy_file(actor_mat, DYNAMIC_MAT)
            candidate, rc = eval_single_case(
                run_dir, spec, "candidate", energy_enable=args.energy_enable
            )
            if rc != 0 or candidate is None:
                notes.append(f"candidate single-case eval failed rc={rc}")
            elif candidate.passed:
                promoted = True
                copy_file(actor_mat, run_dir / "promoted" / f"{spec.name}.mat")
                notes.append("candidate passed this case")
            elif baseline is not None and better(candidate, baseline):
                notes.append("candidate improved this case but did not pass")
            else:
                notes.append("candidate did not improve this case")
        except Exception as exc:
            notes.append(f"exception={type(exc).__name__}:{exc}")
        finally:
            copy_file(backup / "hpt_sac_actor_weights_start.mat", STEADY_MAT)
            copy_file(backup / "hpt_sac_actor_weights_dynamic_start.mat", DYNAMIC_MAT)

        records.append(
            SpecialistRecord(
                spec=spec_to_dict(spec),
                baseline=baseline,
                model_path=str(model_path),
                actor_mat=str(actor_mat),
                candidate=candidate,
                promoted=promoted,
                elapsed_s=time.time() - start,
                notes=notes,
            )
        )
        write_report(run_dir, records, "running")

    write_report(run_dir, records, "complete")
    print(str(run_dir), flush=True)


if __name__ == "__main__":
    main()
