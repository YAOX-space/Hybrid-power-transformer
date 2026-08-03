"""Summarize the 2026-07-26 promoted specialist recheck for paper evidence.

This script is intentionally read-only with respect to experiment outputs.  It
does not run Simulink or re-score trajectories; it converts the validated
switch-level boundary summary into compact CSV/Markdown artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "lab/results/hpt_promoted_recheck_20260726_round1/boundary_case_summary.csv"
DEFAULT_SUMMARY = ROOT / "lab/results/hpt_promoted_recheck_20260726_round1/summary.json"
DEFAULT_OUT_DIR = ROOT / "paper/evidence"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def as_float(value: str) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return math.nan


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "topology",
        "fault_family",
        "phase_mode",
        "fault_pu",
        "fault_duration_s",
        "conventional_pass",
        "sac_pass",
        "sac_beats_conventional",
        "conventional_score",
        "sac_score",
        "score_delta_sac_minus_conventional",
        "conventional_reason",
        "sac_reason",
        "sac_envelope_violation_max_pu",
        "sac_recovery_violation_max_pu",
        "sac_vdc_min",
        "sac_vdc_max",
        "evidence_label",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def classify(row: Dict[str, str]) -> str:
    conv_pass = as_bool(row["conventional_voltage_survival_pass"])
    sac_pass = as_bool(row["sac_voltage_survival_pass"])
    beats = as_bool(row["sac_beats_conventional"])
    if sac_pass and not conv_pass:
        return "traditional_fail_sac_pass"
    if sac_pass and beats:
        return "sac_quality_win"
    if sac_pass:
        return "survival_only_not_quality_win"
    return "not_promoted"


def build_rows(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for row in rows:
        case_id = f"{row['topology']}:{row['case_name']}"
        out.append(
            {
                "case_id": case_id,
                "topology": row["topology"],
                "fault_family": row["fault_family"],
                "phase_mode": row["phase_mode"],
                "fault_pu": row["fault_pu"],
                "fault_duration_s": row["fault_duration_s"],
                "conventional_pass": as_bool(row["conventional_voltage_survival_pass"]),
                "sac_pass": as_bool(row["sac_voltage_survival_pass"]),
                "sac_beats_conventional": as_bool(row["sac_beats_conventional"]),
                "conventional_score": as_float(row["conventional_score"]),
                "sac_score": as_float(row["sac_score"]),
                "score_delta_sac_minus_conventional": as_float(row["sac_minus_conventional_score"]),
                "conventional_reason": row["conventional_reason"],
                "sac_reason": row["sac_reason"],
                "sac_envelope_violation_max_pu": as_float(row["sac_envelope_violation_max_pu"]),
                "sac_recovery_violation_max_pu": as_float(row["sac_recovery_violation_max_pu"]),
                "sac_vdc_min": as_float(row["sac_vdc_min"]),
                "sac_vdc_max": as_float(row["sac_vdc_max"]),
                "evidence_label": classify(row),
            }
        )
    return out


def markdown_table(rows: List[Dict[str, object]]) -> str:
    headers = [
        "case",
        "fault",
        "phase",
        "conv pass",
        "SAC pass",
        "SAC beats",
        "conv score",
        "SAC score",
        "label",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append(
            "| {case_id} | {fault_family} {fault_pu} pu/{fault_duration_s}s | {phase_mode} | "
            "{conventional_pass} | {sac_pass} | {sac_beats_conventional} | "
            "{conventional_score:.3f} | {sac_score:.3f} | {evidence_label} |".format(**row)
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    source_rows = read_csv(args.input)
    rows = build_rows(source_rows)
    out_csv = args.out_dir / "stage3_voltage_survival_summary.csv"
    out_md = args.out_dir / "stage3_voltage_survival_summary.md"
    write_csv(out_csv, rows)

    if args.summary_json.exists():
        summary = json.loads(args.summary_json.read_text(encoding="utf-8"))
    else:
        summary = {
            "case_count": len(rows),
            "conventional_voltage_survival_pass_count": sum(r["conventional_pass"] for r in rows),
            "sac_voltage_survival_pass_count": sum(r["sac_pass"] for r in rows),
            "sac_beats_conventional_count": sum(r["sac_beats_conventional"] for r in rows),
            "traditional_fail_sac_pass_count": sum(
                r["evidence_label"] == "traditional_fail_sac_pass" for r in rows
            ),
        }

    weak_rows = [r for r in rows if r["sac_pass"] and not r["sac_beats_conventional"]]
    md = [
        "# Stage-3 Switch-Level Voltage-Survival Summary",
        "",
        f"Source CSV: `{args.input}`",
        "",
        "## Counts",
        "",
        f"- Cases: {summary.get('case_count', len(rows))}",
        f"- Conventional voltage-survival pass: {summary.get('conventional_voltage_survival_pass_count')}/{summary.get('case_count', len(rows))}",
        f"- SAC voltage-survival pass: {summary.get('sac_voltage_survival_pass_count')}/{summary.get('case_count', len(rows))}",
        f"- SAC beats conventional by score: {summary.get('sac_beats_conventional_count')}/{summary.get('case_count', len(rows))}",
        f"- Traditional fail / SAC pass: {summary.get('traditional_fail_sac_pass_count')}/{summary.get('case_count', len(rows))}",
        "",
        "## Per-Case Table",
        "",
        markdown_table(rows),
        "",
        "## Current Limitations",
        "",
        "- These rows are switch-level voltage-survival evidence, not full FRT certification.",
        "- Grid current limit, reactive current support, and full GBT recovery gates are intentionally deferred.",
        "- Weak rows that survive but do not beat conventional: "
        + ", ".join(str(r["case_id"]) for r in weak_rows),
        "",
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()
