"""Validate offline full-action proxy candidates in switch-level Simulink.

The offline boundary runner produces proxy-gate case results.  This script
promotes only selected rows (by default AWAC rows that beat conventional in the
proxy gate) to switch-level validation.  Each candidate is run through
``eval_hpt_v2_control_comparison.m`` using the model's fixed-action mode:

    hpt_sac_policy_mode = -1
    hpt_compare_fixed_action = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

The Simulink comparison still runs ``conventional_dq`` in the same case so the
switch-level result can be compared against the real traditional baseline.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
SIMULINK_DIR = ROOT / "version_2" / "simulink"
DEFAULT_SOURCE = RESULTS / "hpt_offline_full_action_group_boundary" / "case_results.csv"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def truthy_value(value: Any) -> bool:
    """Parse MATLAB/Python/CSV boolean-like values consistently."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "1.0", "true", "yes", "y"}


def b(row: dict[str, str], key: str) -> bool:
    return truthy_value(row.get(key, ""))


def f(row: dict[str, str], key: str, default: float = float("nan")) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def fmt_float(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def latest_control_csv(before: set[Path]) -> Path:
    after = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    all_files = sorted(after, key=lambda p: p.stat().st_mtime)
    if not all_files:
        raise FileNotFoundError(f"No control comparison CSVs under {CONTROL_DIR}")
    return all_files[-1]


def select_candidates(
    rows: list[dict[str, str]],
    *,
    topology: str,
    category: str,
    algorithm_contains: str,
    only_proxy_beats: bool,
    max_cases: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        if topology != "all" and row.get("topology") != topology:
            continue
        if category != "all" and row.get("category") != category:
            continue
        if algorithm_contains and algorithm_contains not in row.get("algorithm", ""):
            continue
        if only_proxy_beats and not b(row, "beat"):
            continue
        selected.append(row)
    selected = sorted(
        selected,
        key=lambda row: (
            row.get("topology", ""),
            row.get("category", ""),
            int(round(f(row, "duration_ms", 0))),
            f(row, "fault_pu", 1.0),
            row.get("algorithm", ""),
        ),
    )
    return selected[:max_cases] if max_cases > 0 else selected


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def recompute_switch_flags(row: dict[str, Any]) -> dict[str, Any]:
    """Recompute beat flags from switch-level pass fields and scores."""
    baseline_pass = truthy_value(row.get("switch_baseline_voltage_survival_pass", ""))
    fixed_pass = truthy_value(row.get("switch_fixed_voltage_survival_pass", ""))
    try:
        baseline_score = float(row.get("switch_baseline_control_score", "nan"))
        fixed_score = float(row.get("switch_fixed_control_score", "nan"))
    except (TypeError, ValueError):
        baseline_score = float("nan")
        fixed_score = float("nan")
    row["switch_beat"] = bool(
        (fixed_pass and not baseline_pass)
        or (fixed_pass and baseline_pass and math.isfinite(fixed_score) and fixed_score < baseline_score)
    )
    row["switch_improved_score"] = bool(
        math.isfinite(fixed_score) and math.isfinite(baseline_score) and fixed_score < baseline_score
    )
    return row


def run_switch_case(row: dict[str, str], *, run_dir: Path, matlab_cmd: str) -> dict[str, Any]:
    action = [
        f(row, "action_m_reg_d", 0.0),
        f(row, "action_m_reg_q", 0.0),
        f(row, "action_m_energy_d", 0.0),
        f(row, "action_m_energy_q", 0.0),
    ]
    topology = row["topology"]
    case_name = row["case_name"]
    fault_pu = f(row, "fault_pu")
    duration_s = f(row, "duration_ms") / 1000.0
    label = safe_token(f"offline_fixed_{row['algorithm']}_{case_name}")
    statement = "; ".join(
        [
            f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
            f"hpt_compare_topology={matlab_string(topology)}",
            "hpt_compare_scenario_type='fault'",
            "hpt_compare_modes=string({'conventional_dq','fixed_action'})",
            f"hpt_compare_faults={{ {matlab_string(case_name)}, {fault_pu:.12g}, {duration_s:.12g} }}",
            "hpt_compare_fault_start=0.035",
            "hpt_compare_fault_stop_margin=0.125",
            f"hpt_compare_run_label={matlab_string(label)}",
            "hpt_compare_fixed_action=[" + " ".join(f"{x:.12g}" for x in action) + "]",
            "eval_hpt_v2_control_comparison",
        ]
    )
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    proc = subprocess.run(
        [matlab_cmd, "-batch", statement],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=900,
    )
    log_path = run_dir / f"{label}_matlab.log"
    log_path.write_text(
        "STDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )
    result: dict[str, Any] = {
        "candidate_algorithm": row["algorithm"],
        "topology": topology,
        "category": row.get("category", ""),
        "duration_ms": int(round(f(row, "duration_ms", 0))),
        "case_name": case_name,
        "fault_pu": fault_pu,
        "proxy_baseline_pass": b(row, "baseline_pass"),
        "proxy_policy_pass": b(row, "policy_pass"),
        "proxy_beat": b(row, "beat"),
        "proxy_policy_score": f(row, "policy_score"),
        "action_m_reg_d": action[0],
        "action_m_reg_q": action[1],
        "action_m_energy_d": action[2],
        "action_m_energy_q": action[3],
        "matlab_returncode": proc.returncode,
        "matlab_log": str(log_path),
    }
    if proc.returncode != 0:
        result["switch_error"] = "matlab_failed"
        result["switch_csv"] = ""
        return result

    csv_path = latest_control_csv(before)
    result["switch_csv"] = str(csv_path)
    sim_rows = read_csv(csv_path)
    by_mode = {r.get("mode", ""): r for r in sim_rows}
    for prefix, mode in [("switch_baseline", "conventional_dq"), ("switch_fixed", "fixed_action")]:
        sim = by_mode.get(mode)
        if not sim:
            result[f"{prefix}_present"] = False
            continue
        result[f"{prefix}_present"] = True
        for key in [
            "voltage_survival_pass",
            "full_frt_pass",
            "voltage_survival_reason",
            "full_frt_reason",
            "control_score",
            "lv_mean",
            "lv_recovery_mean",
            "lv_peak",
            "lv_min",
            "vdc_min",
            "vdc_max",
            "action_max_abs",
            "reg_d_mean",
            "reg_q_mean",
            "energy_d_mean",
            "energy_q_mean",
            "grid_iq_shortfall_max_pu",
            "grid_current_peak_pu",
            "gbt_reactive_status",
        ]:
            result[f"{prefix}_{key}"] = sim.get(key, "")
    return recompute_switch_flags(result)


def write_report(run_dir: Path, rows: list[dict[str, Any]], source_csv: Path) -> None:
    total = len(rows)
    completed = sum(int(int(row.get("matlab_returncode", 1)) == 0) for row in rows)
    beat = sum(int(truthy_value(row.get("switch_beat", False))) for row in rows)
    fixed_pass = sum(int(truthy_value(row.get("switch_fixed_voltage_survival_pass", ""))) for row in rows)
    baseline_pass = sum(int(truthy_value(row.get("switch_baseline_voltage_survival_pass", ""))) for row in rows)
    lines = [
        "# HPT Offline Full-Action Switch-Level Validation",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Source proxy CSV: `{source_csv}`",
        f"- Candidates: `{total}`",
        f"- MATLAB completed: `{completed} / {total}`",
        f"- Switch-level conventional voltage-survival pass: `{baseline_pass} / {total}`",
        f"- Switch-level fixed-action voltage-survival pass: `{fixed_pass} / {total}`",
        f"- Switch-level fixed-action beats conventional: `{beat} / {total}`",
        "",
        "| Candidate | Baseline Pass | Fixed Pass | Beat | Fixed Score | Reason | Action |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        action = (
            f"[{float(row['action_m_reg_d']):.3f}, {float(row['action_m_reg_q']):.3f}, "
            f"{float(row['action_m_energy_d']):.3f}, {float(row['action_m_energy_q']):.3f}]"
        )
        lines.append(
            f"| `{row['candidate_algorithm']} / {row['case_name']}` | "
            f"{row.get('switch_baseline_voltage_survival_pass', '')} | "
            f"{row.get('switch_fixed_voltage_survival_pass', '')} | "
            f"{row.get('switch_beat', '')} | "
            f"{row.get('switch_fixed_control_score', '')} | "
            f"`{row.get('switch_fixed_voltage_survival_reason', '')}` | `{action}` |"
        )
    lines.extend(
        [
            "",
            "## Action-Transfer Diagnosis",
            "",
            "| Candidate | Req reg_d | Sim reg_d | Req energy_d | Sim energy_d | LV recovery | Vdc min/max |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['candidate_algorithm']} / {row['case_name']}` | "
            f"{fmt_float(row.get('action_m_reg_d'))} | "
            f"{fmt_float(row.get('switch_fixed_reg_d_mean'))} | "
            f"{fmt_float(row.get('action_m_energy_d'))} | "
            f"{fmt_float(row.get('switch_fixed_energy_d_mean'))} | "
            f"{fmt_float(row.get('switch_fixed_lv_recovery_mean'))} | "
            f"{fmt_float(row.get('switch_fixed_vdc_min'))}/{fmt_float(row.get('switch_fixed_vdc_max'))} |"
        )
    lines.extend(
        [
            "",
            "Interpretation aid:",
            "",
            "- `Req reg_d` should roughly match `Sim reg_d` in fixed-action mode.",
            "- A large sign or magnitude mismatch between `Req energy_d` and `Sim energy_d` means the offline proxy action semantics do not yet match the switch-level energy branch.",
        ]
    )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-results-csv", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--recompute-run-dir",
        type=Path,
        default=None,
        help="Recompute beat flags, summary, and report from an existing run directory.",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology1")
    parser.add_argument("--category", default="HVRT")
    parser.add_argument("--algorithm-contains", default="awac_style")
    parser.add_argument("--only-proxy-beats", action="store_true", default=True)
    parser.add_argument("--max-cases", type=int, default=8)
    parser.add_argument("--matlab-cmd", default="matlab")
    args = parser.parse_args()

    if args.recompute_run_dir is not None:
        run_dir = args.recompute_run_dir
        result_csv = run_dir / "switch_validation_results.csv"
        if not result_csv.exists():
            raise FileNotFoundError(result_csv)
        result_rows = [recompute_switch_flags(row) for row in read_csv(result_csv)]
        write_csv(result_csv, result_rows)
        write_report(run_dir, result_rows, args.case_results_csv)
        summary = {
            "schema": "hpt-offline-full-action-switch-validation-v1",
            "run_id": run_dir.name,
            "source_csv": str(args.case_results_csv),
            "result_csv": str(result_csv),
            "report": str(run_dir / "REPORT.md"),
            "candidate_count": len(result_rows),
            "matlab_completed": sum(int(int(row.get("matlab_returncode", 1)) == 0) for row in result_rows),
            "switch_baseline_voltage_survival_pass_count": sum(
                int(truthy_value(row.get("switch_baseline_voltage_survival_pass", ""))) for row in result_rows
            ),
            "switch_fixed_voltage_survival_pass_count": sum(
                int(truthy_value(row.get("switch_fixed_voltage_survival_pass", ""))) for row in result_rows
            ),
            "switch_beat_count": sum(int(truthy_value(row.get("switch_beat", False))) for row in result_rows),
            "recomputed_from_existing_results": True,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return 0

    run_id = args.run_id or f"hpt_offline_full_action_switch_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_rows = read_csv(args.case_results_csv)
    candidates = select_candidates(
        source_rows,
        topology=args.topology,
        category=args.category,
        algorithm_contains=args.algorithm_contains,
        only_proxy_beats=args.only_proxy_beats,
        max_cases=args.max_cases,
    )
    if not candidates:
        raise RuntimeError("No proxy candidates selected for switch-level validation")
    write_csv(run_dir / "selected_candidates.csv", candidates)

    result_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(candidates, 1):
        print(
            f"[{idx}/{len(candidates)}] switch validate {row['algorithm']} {row['case_name']} "
            f"action=[{row['action_m_reg_d']},{row['action_m_reg_q']},"
            f"{row['action_m_energy_d']},{row['action_m_energy_q']}]",
            flush=True,
        )
        result_rows.append(run_switch_case(row, run_dir=run_dir, matlab_cmd=args.matlab_cmd))
        write_csv(run_dir / "switch_validation_results.csv", result_rows)

    write_report(run_dir, result_rows, args.case_results_csv)
    summary = {
        "schema": "hpt-offline-full-action-switch-validation-v1",
        "run_id": run_id,
        "source_csv": str(args.case_results_csv),
        "result_csv": str(run_dir / "switch_validation_results.csv"),
        "report": str(run_dir / "REPORT.md"),
        "candidate_count": len(candidates),
        "matlab_completed": sum(int(int(row.get("matlab_returncode", 1)) == 0) for row in result_rows),
        "switch_baseline_voltage_survival_pass_count": sum(
            int(truthy_value(row.get("switch_baseline_voltage_survival_pass", ""))) for row in result_rows
        ),
        "switch_fixed_voltage_survival_pass_count": sum(
            int(truthy_value(row.get("switch_fixed_voltage_survival_pass", ""))) for row in result_rows
        ),
        "switch_beat_count": sum(int(truthy_value(row.get("switch_beat", False))) for row in result_rows),
        "config": {
            "topology": args.topology,
            "category": args.category,
            "algorithm_contains": args.algorithm_contains,
            "only_proxy_beats": args.only_proxy_beats,
            "max_cases": args.max_cases,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_offline_full_action_switch_validation",
        config=summary["config"],
        dataset_manifest=args.case_results_csv,
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
