"""Run and summarize per-topology/per-fault HPT specialist SAC campaigns.

This is the orchestration layer for the current research target: produce
switch-level evaluated specialist actors split by topology and fault family.
It deliberately keeps the training logic in ``run_hpt_trajectory_specialist_campaign``
and only handles case selection, resume/skip behavior, and promotion reporting.

Promotion levels:

* ``full_frt``: switch-level actor passes the full FRT evaluator.
* ``voltage_survival``: switch-level actor passes voltage-survival and beats
  the conventional DQ baseline, but still has full-FRT blockers.
* ``diagnostic``: useful run, but not a deployable specialist.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"


@dataclass(frozen=True)
class SpecialistCase:
    name: str
    topology: str
    fault_pu: float
    duration_s: float
    preset: str
    action: tuple[float, float, float, float]
    start_action: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    base_action: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    safe_target: tuple[float, float, float, float] | None = None
    step_time: float = 0.035
    ramp_start: float = 0.035
    ramp_end: float = 0.055
    down_start: float | None = None
    down_end: float | None = None
    dagger_iters: int = 1
    vdc_feedback_gain: float = 0.0
    q_gate_mode: str = "binary"
    q_gate_lv_min_pu: float = 0.0
    q_gate_lv_full_pu: float = math.inf
    q_gate_time_min_s: float = 0.0
    q_gate_time_full_s: float = math.inf
    q_gate_vdc_min_pu: float = 0.0
    q_gate_vdc_max_pu: float = math.inf
    switch_trace_repeat: int = 32
    epochs: int = 50
    bc_obs_noise_repeat: int = 2
    existing_run_id: str = ""
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def target(self) -> tuple[float, float, float, float]:
        return self.safe_target if self.safe_target is not None else self.action


def default_cases() -> list[SpecialistCase]:
    """Curated first matrix.

    The first three entries reuse already switch-level evaluated actors.  The
    remaining entries are gap cases that are allowed to fail; their value is to
    map the boundary for the next specialist iteration.
    """

    return [
        SpecialistCase(
            name="topology1_lvrt090_80ms",
            topology="topology1",
            fault_pu=0.90,
            duration_s=0.08,
            preset="constant",
            action=(0.55, 0.0, 0.60, 0.0),
            safe_target=(0.55, 0.0, 0.60, 0.0),
            existing_run_id="hpt_traj_specialist_topo1_lvrt090_20260718",
            notes="Existing topology1 LVRT voltage-survival specialist.",
            tags=("known_voltage_survival", "lvrt"),
        ),
        SpecialistCase(
            name="topology2_lvrt095_80ms",
            topology="topology2",
            fault_pu=0.95,
            duration_s=0.08,
            preset="constant",
            action=(0.172, 0.0, 0.022, 0.002),
            safe_target=(0.172, 0.0, 0.014, 0.002),
            existing_run_id="hpt_traj_specialist_topo2_lvrt095_smoke2_20260718",
            notes="Existing topology2 shallow-LVRT voltage-survival specialist.",
            tags=("known_voltage_survival", "lvrt"),
        ),
        SpecialistCase(
            name="topology2_lvrt090_80ms",
            topology="topology2",
            fault_pu=0.90,
            duration_s=0.08,
            preset="two_stage",
            action=(0.25, -0.40, -0.02, 0.002),
            start_action=(0.25, 0.0, -0.02, 0.002),
            safe_target=(0.25, -0.40, -0.02, 0.002),
            step_time=0.055,
            ramp_start=0.035,
            ramp_end=0.095,
            vdc_feedback_gain=0.08,
            q_gate_mode="continuous",
            q_gate_lv_min_pu=0.60,
            q_gate_lv_full_pu=0.90,
            q_gate_time_min_s=0.055,
            q_gate_time_full_s=0.105,
            q_gate_vdc_min_pu=0.80,
            q_gate_vdc_max_pu=1.25,
            epochs=40,
            existing_run_id="hpt_traj_specialist_topo2_lvrt090_rd025_qm04_contq_20260719",
            notes="Existing topology2 0.90-pu dynamic LVRT specialist.",
            tags=("known_voltage_survival", "lvrt", "dynamic_q_gate"),
        ),
        SpecialistCase(
            name="topology1_lvrt075_80ms_probe",
            topology="topology1",
            fault_pu=0.75,
            duration_s=0.08,
            preset="constant",
            action=(0.62, 0.0, 0.45, 0.0),
            safe_target=(0.62, 0.0, 0.45, 0.0),
            vdc_feedback_gain=0.03,
            epochs=45,
            notes="Probe deeper topology1 LVRT boundary with a conservative energy command.",
            tags=("probe", "lvrt", "deep_lvrt"),
        ),
        SpecialistCase(
            name="topology2_hvrt110_80ms_probe",
            topology="topology2",
            fault_pu=1.10,
            duration_s=0.08,
            preset="two_stage_window",
            action=(0.0, 0.0, 0.0, 0.002),
            start_action=(0.0, 0.0, 0.0, 0.002),
            safe_target=(0.0, 0.0, 0.0, 0.002),
            step_time=0.055,
            ramp_start=0.035,
            ramp_end=0.075,
            down_start=0.115,
            down_end=0.155,
            vdc_feedback_gain=0.10,
            epochs=45,
            notes="HVRT probe: current evidence says fixed actions improve score but collapse DC link.",
            tags=("probe", "hvrt"),
        ),
    ]


def safe_token(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(text)).strip("_")


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def case_summary_path(case: SpecialistCase, run_id: str) -> Path:
    if case.existing_run_id:
        return RESULTS / case.existing_run_id / "summary.json"
    return RESULTS / run_id / "summary.json"


def classify(summary: dict[str, Any]) -> str:
    best = summary.get("best_actor_evaluation", {})
    if truthy(best.get("policy_full_frt_pass", False)):
        return "full_frt"
    if truthy(summary.get("promoted_voltage_survival", False)) and truthy(
        summary.get("promoted_beats_baseline", False)
    ):
        return "voltage_survival"
    return "diagnostic"


def row_from_summary(case: SpecialistCase, run_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    best = summary.get("best_actor_evaluation", {})
    trajectory = summary.get("trajectory_summary", {})
    train_summaries = summary.get("train_summaries", [])
    model_path = best.get("model_path") or ""
    if not model_path and best.get("label"):
        suffix = "_" + str(best["label"])
        for item in train_summaries:
            if str(item.get("run_id", "")).endswith(suffix):
                model_path = str(item.get("model_path", ""))
                break
    if not model_path:
        model_path = summary.get("final_model", "")
    actor_path = summary.get("final_actor_mat", "")
    return {
        "case": case.name,
        "run_id": summary.get("run_id", run_id),
        "source": "existing" if case.existing_run_id else "new",
        "topology": case.topology,
        "fault_type": "HVRT" if case.fault_pu > 1.0 else "LVRT",
        "fault_pu": case.fault_pu,
        "duration_s": case.duration_s,
        "promotion_level": classify(summary),
        "voltage_survival_pass": truthy(summary.get("promoted_voltage_survival", False)),
        "beats_conventional": truthy(summary.get("promoted_beats_baseline", False)),
        "full_frt_pass": truthy(best.get("policy_full_frt_pass", False)),
        "policy_score": to_float(best.get("policy_score")),
        "baseline_score": to_float(best.get("baseline_score")),
        "policy_lv_mean": to_float(best.get("policy_lv_mean")),
        "policy_lv_recovery_mean": to_float(best.get("policy_lv_recovery_mean")),
        "policy_vdc_min": to_float(best.get("policy_vdc_min")),
        "policy_vdc_max": to_float(best.get("policy_vdc_max")),
        "policy_cmd_action_max_abs": to_float(best.get("policy_cmd_action_max_abs")),
        "policy_cmd_m_reg_d_mean": to_float(best.get("policy_cmd_m_reg_d_mean")),
        "policy_cmd_m_energy_d_mean": to_float(best.get("policy_cmd_m_energy_d_mean")),
        "voltage_reason": best.get("policy_voltage_reason", ""),
        "full_frt_reason": best.get("policy_full_frt_reason", ""),
        "trajectory_voltage_pass": truthy(trajectory.get("trajectory_voltage_pass", False)),
        "trajectory_reason": trajectory.get("trajectory_reason", ""),
        "best_label": best.get("label", ""),
        "model_path": model_path,
        "actor_mat": actor_path,
        "train_iterations": len(train_summaries),
        "notes": case.notes,
        "tags": ";".join(case.tags),
    }


def build_command(case: SpecialistCase, run_id: str, args: argparse.Namespace) -> list[str]:
    safe_target = case.target()
    cmd = [
        sys.executable,
        "-m",
        "version_2.sac.run_hpt_trajectory_specialist_campaign",
        "--run-id",
        run_id,
        "--topology",
        case.topology,
        "--fault-pu",
        f"{case.fault_pu:.12g}",
        "--duration-s",
        f"{case.duration_s:.12g}",
        "--preset",
        case.preset,
        "--base-action",
        *[f"{x:.12g}" for x in case.base_action],
        "--start-action",
        *[f"{x:.12g}" for x in case.start_action],
        "--action",
        *[f"{x:.12g}" for x in case.action],
        "--safe-target",
        *[f"{x:.12g}" for x in safe_target],
        "--step-time",
        f"{case.step_time:.12g}",
        "--ramp-start",
        f"{case.ramp_start:.12g}",
        "--ramp-end",
        f"{case.ramp_end:.12g}",
        "--dagger-iters",
        str(case.dagger_iters),
        "--vdc-feedback-gain",
        f"{case.vdc_feedback_gain:.12g}",
        "--q-gate-mode",
        case.q_gate_mode,
        "--q-gate-lv-min-pu",
        f"{case.q_gate_lv_min_pu:.12g}",
        "--q-gate-lv-full-pu",
        f"{case.q_gate_lv_full_pu:.12g}",
        "--q-gate-time-min-s",
        f"{case.q_gate_time_min_s:.12g}",
        "--q-gate-time-full-s",
        f"{case.q_gate_time_full_s:.12g}",
        "--q-gate-vdc-min-pu",
        f"{case.q_gate_vdc_min_pu:.12g}",
        "--q-gate-vdc-max-pu",
        f"{case.q_gate_vdc_max_pu:.12g}",
        "--switch-trace-repeat",
        str(case.switch_trace_repeat),
        "--epochs",
        str(case.epochs),
        "--bc-obs-noise-repeat",
        str(case.bc_obs_noise_repeat),
        "--matlab-cmd",
        args.matlab_cmd,
        "--matlab-timeout-s",
        str(args.matlab_timeout_s),
        "--train-timeout-s",
        str(args.train_timeout_s),
    ]
    if case.down_start is not None:
        cmd += ["--down-start", f"{case.down_start:.12g}"]
    if case.down_end is not None:
        cmd += ["--down-end", f"{case.down_end:.12g}"]
    return cmd


def run_case(case: SpecialistCase, run_id: str, run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    summary_path = case_summary_path(case, run_id)
    if summary_path.exists():
        return read_json(summary_path)
    cmd = build_command(case, run_id, args)
    log_path = run_dir / "case_logs" / f"{safe_token(case.name)}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        log_path.write_text("DRY RUN:\n" + " ".join(cmd), encoding="utf-8")
        return {
            "schema": "hpt-trajectory-specialist-campaign-v1",
            "run_id": run_id,
            "topology": case.topology,
            "fault_pu": case.fault_pu,
            "duration_s": case.duration_s,
            "promoted_voltage_survival": False,
            "promoted_beats_baseline": False,
            "best_actor_evaluation": {"policy_full_frt_pass": False},
            "dry_run": True,
        }
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.case_timeout_s,
    )
    log_path.write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return {
            "schema": "hpt-trajectory-specialist-campaign-v1",
            "run_id": run_id,
            "topology": case.topology,
            "fault_pu": case.fault_pu,
            "duration_s": case.duration_s,
            "promoted_voltage_survival": False,
            "promoted_beats_baseline": False,
            "best_actor_evaluation": {
                "policy_full_frt_pass": False,
                "policy_voltage_reason": "case_command_failed",
                "policy_full_frt_reason": f"returncode={proc.returncode}",
            },
            "error": f"returncode={proc.returncode}",
            "log_path": str(log_path),
        }
    if not summary_path.exists():
        raise FileNotFoundError(f"Case completed but summary not found: {summary_path}")
    return read_json(summary_path)


def write_report(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    full = [row for row in rows if row["promotion_level"] == "full_frt"]
    voltage = [row for row in rows if row["promotion_level"] == "voltage_survival"]
    diagnostic = [row for row in rows if row["promotion_level"] == "diagnostic"]
    lines = [
        "# HPT Specialist SAC Matrix Campaign",
        "",
        "## Summary",
        "",
        f"- Cases: `{len(rows)}`",
        f"- Full-FRT promoted: `{len(full)}`",
        f"- Voltage-survival promoted: `{len(voltage)}`",
        f"- Diagnostic / failed: `{len(diagnostic)}`",
        "",
        "## Case Matrix",
        "",
        "| Case | Topology | Fault | Level | Beat | Score | Baseline | LV mean/recovery | Vdc min/max | Full-FRT reason |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case']}` | {row['topology']} | {row['fault_pu']} pu / "
            f"{int(round(1000 * row['duration_s']))} ms | `{row['promotion_level']}` | "
            f"{row['beats_conventional']} | {row['policy_score']:.3f} | "
            f"{row['baseline_score']:.3f} | {row['policy_lv_mean']:.2f}/"
            f"{row['policy_lv_recovery_mean']:.2f} | {row['policy_vdc_min']:.2f}/"
            f"{row['policy_vdc_max']:.2f} | `{row['full_frt_reason']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `full_frt` is the only level that can be claimed as complete FRT certification.",
            "- `voltage_survival` is useful for voltage-regulation research, but its failure reasons must remain visible.",
            "- `diagnostic` cases define the boundary for the next action-sweep or controller-design iteration.",
        ]
    )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def select_cases(cases: list[SpecialistCase], names: set[str], max_cases: int) -> list[SpecialistCase]:
    selected = [case for case in cases if not names or case.name in names]
    if max_cases > 0:
        selected = selected[:max_cases]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", default=f"hpt_specialist_matrix_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--case", action="append", default=[], help="Run only named case(s).")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--matlab-timeout-s", type=int, default=1200)
    parser.add_argument("--train-timeout-s", type=int, default=600)
    parser.add_argument("--case-timeout-s", type=int, default=3600)
    args = parser.parse_args()

    run_dir = RESULTS / args.campaign_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cases = select_cases(default_cases(), set(args.case), args.max_cases)
    if not cases:
        raise ValueError("No specialist cases selected")

    write_csv_rows(run_dir / "case_manifest.csv", [asdict(case) for case in cases])
    rows: list[dict[str, Any]] = []
    status_path = run_dir / "status.json"
    for idx, case in enumerate(cases, 1):
        run_id = f"{args.campaign_id}_{safe_token(case.name)}"
        write_json(
            status_path,
            {
                "campaign_id": args.campaign_id,
                "stage": "running",
                "current_case": case.name,
                "completed_cases": idx - 1,
                "total_cases": len(cases),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        print(f"[{idx}/{len(cases)}] {case.name}", flush=True)
        summary = run_case(case, run_id, run_dir, args)
        rows.append(row_from_summary(case, run_id, summary))
        write_csv_rows(run_dir / "specialist_matrix_results.csv", rows)
        write_json(
            status_path,
            {
                "campaign_id": args.campaign_id,
                "stage": "running",
                "completed_cases": idx,
                "total_cases": len(cases),
                "last_case": case.name,
                "last_level": rows[-1]["promotion_level"],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )

    summary = {
        "schema": "hpt-specialist-matrix-campaign-v1",
        "campaign_id": args.campaign_id,
        "case_count": len(rows),
        "full_frt_promoted": sum(row["promotion_level"] == "full_frt" for row in rows),
        "voltage_survival_promoted": sum(row["promotion_level"] == "voltage_survival" for row in rows),
        "diagnostic": sum(row["promotion_level"] == "diagnostic" for row in rows),
        "results_csv": str(run_dir / "specialist_matrix_results.csv"),
        "report": str(run_dir / "REPORT.md"),
        "rows": rows,
        "config": vars(args),
    }
    write_json(run_dir / "summary.json", summary)
    write_json(
        status_path,
        {
            "campaign_id": args.campaign_id,
            "stage": "complete",
            "summary": {
                "full_frt_promoted": summary["full_frt_promoted"],
                "voltage_survival_promoted": summary["voltage_survival_promoted"],
                "diagnostic": summary["diagnostic"],
            },
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    write_report(run_dir, rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_specialist_matrix_campaign",
        config=summary["config"],
        dataset_manifest=run_dir / "case_manifest.csv",
        extra={"summary_path": str(run_dir / "summary.json")},
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
