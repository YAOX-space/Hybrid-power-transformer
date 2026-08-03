"""Evaluate a fixed topology2 balanced-LVRT SAC actor on a boundary matrix.

The script does not train, tune, or select profiles at run time.  It exports one
given SAC actor once, then evaluates strong conventional dq and that same actor
on every switch-level Simulink case.  The output is a compact boundary table
that makes the pass/fail regions for dq and SAC directly comparable.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path

from version_2.sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ROOT,
    SIMULINK,
    BoundaryCase,
    export_actor_for_simulink,
    matlab_evaluate_actor,
    read_comparison_rows,
    write_csv,
)
from version_2.sac.experiment_metadata import write_experiment_metadata


RESULTS = ROOT / "lab" / "results"
DEFAULT_ACTOR = (
    ROOT
    / "data"
    / "models"
    / "hpt_t2_bal_lvrt_family_distilled_gate_sac_"
    "hpt_t2_bal_lvrt_family_distill_gate_sac_2x2_20260731_r2_rawteacher.zip"
)


def parse_float_list(raw: str) -> list[float]:
    return [float(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def as_bool(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "1.0", "true", "yes", "pass", "passed"}


def as_float(row: dict[str, str], *names: str, default: float = math.nan) -> float:
    for name in names:
        value = row.get(name, "")
        if value not in ("", None):
            try:
                return float(value)
            except ValueError:
                return default
    return default


def field(row: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name, "")
        if value not in ("", None):
            return str(value)
    return default


def make_cases(depths: list[float], durations_ms: list[int]) -> list[BoundaryCase]:
    return [
        BoundaryCase(fault_pu=depth, duration_s=duration_ms / 1000.0)
        for depth in depths
        for duration_ms in durations_ms
    ]


def compact_by_case(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return one dq and one SAC row per case.

    Each Simulink comparison CSV has a conventional dq row and a SAC row.  If an
    evaluation gets repeated, keep the latest row inserted into ``rows``.
    """

    latest: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        label = field(row, "family_eval_label", "boundary_label", "case_name")
        controller = field(row, "controller", "mode")
        latest[(label, controller)] = row
    compact = list(latest.values())
    compact.sort(
        key=lambda row: (
            as_float(row, "family_fault_pu", "boundary_fault_pu", "fault_pu"),
            as_float(row, "family_duration_ms", "boundary_duration_ms", default=as_float(row, "fault_duration_s") * 1000.0),
            0 if field(row, "controller") == "strong_dq" else 1,
        )
    )
    return compact


def relation(dq_row: dict[str, str] | None, sac_row: dict[str, str] | None) -> str:
    dq_pass = as_bool(dq_row.get("voltage_survival_pass")) if dq_row else False
    sac_pass = as_bool(sac_row.get("voltage_survival_pass")) if sac_row else False
    if dq_pass and sac_pass:
        return "both_pass"
    if sac_pass and not dq_pass:
        return "sac_only"
    if dq_pass and not sac_pass:
        return "dq_only"
    return "both_fail"


def short_reason(row: dict[str, str] | None) -> str:
    if row is None:
        return "missing"
    if as_bool(row.get("voltage_survival_pass")):
        return "pass"
    reason = field(row, "voltage_survival_reason", "full_frt_reason", default="-")
    if not reason:
        return "-"
    return reason


def case_rows(compact: list[dict[str, str]]) -> list[dict[str, object]]:
    by_case: dict[str, dict[str, dict[str, str]]] = {}
    for row in compact:
        label = field(row, "family_eval_label", "boundary_label", "case_name")
        by_case.setdefault(label, {})[field(row, "controller")] = row

    out: list[dict[str, object]] = []
    for label, controllers in sorted(
        by_case.items(),
        key=lambda item: (
            as_float(next(iter(item[1].values())), "family_fault_pu", "boundary_fault_pu", "fault_pu"),
            as_float(next(iter(item[1].values())), "family_duration_ms", "boundary_duration_ms", default=as_float(next(iter(item[1].values())), "fault_duration_s") * 1000.0),
        ),
    ):
        dq = controllers.get("strong_dq")
        sac = controllers.get("fixed_family_gate_sac")
        base = dq or sac or {}
        out.append(
            {
                "case": label,
                "fault_pu": as_float(base, "family_fault_pu", "boundary_fault_pu", "fault_pu"),
                "duration_ms": as_float(base, "family_duration_ms", "boundary_duration_ms", default=as_float(base, "fault_duration_s") * 1000.0),
                "strong_dq_pass": int(as_bool(dq.get("voltage_survival_pass")) if dq else False),
                "sac_pass": int(as_bool(sac.get("voltage_survival_pass")) if sac else False),
                "relation": relation(dq, sac),
                "strong_dq_reason": short_reason(dq),
                "sac_reason": short_reason(sac),
                "strong_dq_score": as_float(dq or {}, "survival_score", "control_score"),
                "sac_score": as_float(sac or {}, "survival_score", "control_score"),
                "strong_dq_grid_current_peak_pu": as_float(dq or {}, "grid_current_peak_pu"),
                "sac_grid_current_peak_pu": as_float(sac or {}, "grid_current_peak_pu"),
                "strong_dq_vdc_min": as_float(dq or {}, "vdc_min"),
                "sac_vdc_min": as_float(sac or {}, "vdc_min"),
                "strong_dq_envelope_violation_max_pu": as_float(dq or {}, "envelope_violation_max_pu"),
                "sac_envelope_violation_max_pu": as_float(sac or {}, "envelope_violation_max_pu"),
                "strong_dq_recovery_violation_max_pu": as_float(dq or {}, "recovery_violation_max_pu"),
                "sac_recovery_violation_max_pu": as_float(sac or {}, "recovery_violation_max_pu"),
                "strong_dq_fault_lv_band_violation_max_pu": as_float(dq or {}, "fault_lv_band_violation_max_pu"),
                "sac_fault_lv_band_violation_max_pu": as_float(sac or {}, "fault_lv_band_violation_max_pu"),
            }
        )
    return out


def summarize_cases(rows: list[dict[str, object]]) -> dict[str, object]:
    n = len(rows)
    sac_pass = sum(int(row["sac_pass"]) for row in rows)
    dq_pass = sum(int(row["strong_dq_pass"]) for row in rows)
    relation_counts: dict[str, int] = {}
    for row in rows:
        relation_name = str(row["relation"])
        relation_counts[relation_name] = relation_counts.get(relation_name, 0) + 1
    return {
        "case_count": n,
        "strong_dq_pass_count": dq_pass,
        "sac_pass_count": sac_pass,
        "strong_dq_pass_rate": dq_pass / n if n else 0.0,
        "sac_pass_rate": sac_pass / n if n else 0.0,
        "relation_counts": relation_counts,
        "sac_only_count": relation_counts.get("sac_only", 0),
        "dq_only_count": relation_counts.get("dq_only", 0),
        "both_pass_count": relation_counts.get("both_pass", 0),
        "both_fail_count": relation_counts.get("both_fail", 0),
    }


def pass_map(rows: list[dict[str, object]], *, controller_key: str) -> list[dict[str, object]]:
    depths = sorted({float(row["fault_pu"]) for row in rows})
    durations = sorted({float(row["duration_ms"]) for row in rows})
    by_pair = {
        (float(row["fault_pu"]), float(row["duration_ms"])): row for row in rows
    }
    table: list[dict[str, object]] = []
    for duration in durations:
        row_out: dict[str, object] = {"duration_ms": int(duration)}
        for depth in depths:
            row = by_pair.get((depth, duration))
            if row is None:
                value = ""
            else:
                value = "P" if int(row[controller_key]) else "F"
            row_out[f"{depth:.3f}pu"] = value
        table.append(row_out)
    return table


def relation_map(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    depths = sorted({float(row["fault_pu"]) for row in rows})
    durations = sorted({float(row["duration_ms"]) for row in rows})
    by_pair = {
        (float(row["fault_pu"]), float(row["duration_ms"])): row for row in rows
    }
    table: list[dict[str, object]] = []
    labels = {
        "both_pass": "BOTH",
        "sac_only": "SAC",
        "dq_only": "DQ",
        "both_fail": "FAIL",
    }
    for duration in durations:
        row_out: dict[str, object] = {"duration_ms": int(duration)}
        for depth in depths:
            row = by_pair.get((depth, duration))
            row_out[f"{depth:.3f}pu"] = labels.get(str(row["relation"]), "") if row else ""
        table.append(row_out)
    return table


def markdown_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    fields = list(rows[0].keys())
    lines = [
        "| " + " | ".join(fields) + " |\n",
        "| " + " | ".join("---" for _ in fields) + " |\n",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(field, "")) for field in fields) + " |\n")
    return "".join(lines)


def write_report(run_dir: Path, summary: dict[str, object], cases: list[dict[str, object]]) -> None:
    dq_map = pass_map(cases, controller_key="strong_dq_pass")
    sac_map = pass_map(cases, controller_key="sac_pass")
    rel_map = relation_map(cases)
    lines = [
        "# Topology2 Balanced LVRT Fixed-Actor Boundary\n\n",
        f"Run directory: `{run_dir}`\n\n",
        "## Aggregate\n\n",
        f"- strong dq voltage-survival pass: `{summary['strong_dq_pass_count']}/{summary['case_count']}`\n",
        f"- fixed family SAC voltage-survival pass: `{summary['sac_pass_count']}/{summary['case_count']}`\n",
        f"- SAC-only boundary points: `{summary['sac_only_count']}`\n",
        f"- dq-only boundary points: `{summary['dq_only_count']}`\n",
        f"- both-pass points: `{summary['both_pass_count']}`\n",
        f"- both-fail points: `{summary['both_fail_count']}`\n\n",
        "## Relation Map\n\n",
        "`SAC` means SAC passes and strong dq fails; `DQ` means the opposite; ",
        "`BOTH` means both pass; `FAIL` means both fail.\n\n",
        markdown_table(rel_map),
        "\n## Strong DQ Pass Map\n\n",
        markdown_table(dq_map),
        "\n## Fixed Family SAC Pass Map\n\n",
        markdown_table(sac_map),
        "\n## Per-Case Table\n\n",
        markdown_table(cases),
        "\n## Scope\n\n",
        "- The controller is one fixed exported SAC actor; no profile selection is used.\n",
        "- The evidence is switch-level Simulink voltage-survival, not full FRT certification.\n",
        "- Reactive-current support is intentionally not promoted as passed in this run.\n",
    ]
    (run_dir / "BOUNDARY_REPORT.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=f"hpt_t2_bal_lvrt_fixed_actor_boundary_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--actor-model", type=Path, default=DEFAULT_ACTOR)
    parser.add_argument("--depths", default="0.85,0.875,0.90,0.925,0.95")
    parser.add_argument("--durations-ms", default="60,80,100,120,160")
    parser.add_argument("--fault-start-s", type=float, default=0.08)
    parser.add_argument("--case-limit", type=int, default=0)
    args = parser.parse_args()

    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    actor_model = Path(args.actor_model)
    if not actor_model.exists():
        raise FileNotFoundError(actor_model)

    depths = parse_float_list(args.depths)
    durations_ms = parse_int_list(args.durations_ms)
    cases = make_cases(depths, durations_ms)
    if args.case_limit > 0:
        cases = cases[: args.case_limit]

    config = {
        "run_id": args.run_id,
        "topology": "topology2",
        "fault_family": "balanced_lvrt",
        "depths": depths,
        "durations_ms": durations_ms,
        "case_limit": args.case_limit,
        "case_count": len(cases),
        "fault_start_s": args.fault_start_s,
        "actor_model": str(actor_model),
        "controller_label": "fixed_family_gate_sac",
        "no_training": True,
        "no_profile_selection": True,
    }
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_t2_balanced_lvrt_fixed_actor_boundary",
        config=config,
        topology_models={
            "topology2": SIMULINK / "topology2" / "hpt_v2_topology2_paper.slx",
        },
        policy_checkpoint=actor_model,
    )
    (run_dir / "campaign_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    export_actor_for_simulink(actor_model, run_dir, "fixed_family_gate_sac")
    raw_rows: list[dict[str, str]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] evaluating {case.label}", flush=True)
        csv_path = matlab_evaluate_actor(
            case,
            run_dir,
            tag=f"fixed_family_gate_sac_{case.label}",
            fault_start_s=args.fault_start_s,
        )
        for row in read_comparison_rows(csv_path, controller_label="fixed_family_gate_sac"):
            row["boundary_label"] = case.label
            row["boundary_fault_pu"] = f"{case.fault_pu:.6g}"
            row["boundary_duration_ms"] = str(case.duration_ms)
            raw_rows.append(row)
        write_csv(run_dir / "boundary_raw_rows.csv", raw_rows)
        compact = compact_by_case(raw_rows)
        write_csv(run_dir / "boundary_compact_controller_rows.csv", compact)
        per_case = case_rows(compact)
        write_csv(run_dir / "boundary_case_table.csv", per_case)
        summary = summarize_cases(per_case)
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        write_csv(run_dir / "boundary_strong_dq_pass_map.csv", pass_map(per_case, controller_key="strong_dq_pass"))
        write_csv(run_dir / "boundary_fixed_sac_pass_map.csv", pass_map(per_case, controller_key="sac_pass"))
        write_csv(run_dir / "boundary_relation_map.csv", relation_map(per_case))
        write_report(run_dir, summary, per_case)

    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
