"""Run grouped switch-level voltage-survival boundary comparisons.

The runner consumes the 2026-07-25 boundary manifest and evaluates the tuned
traditional controller and, optionally, the nearest Stage-2 SAC specialist on
the same switch-level scenarios.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from version_2.sac.experiment_metadata import write_experiment_metadata
from version_2.sac.export_hpt_sac_actor import export_hpt_actor


ROOT = Path(__file__).resolve().parents[3]
SIMULINK_DIR = ROOT / "version_2" / "simulink"
CONTROL_DIR = ROOT / "lab" / "results" / "hpt_v2_control_comparison"
RESULTS = ROOT / "lab" / "results"
DEFAULT_MANIFEST = (
    ROOT
    / "version_2"
    / "sac"
    / "experiments"
    / "voltage_survival_boundary_manifest_20260725.csv"
)


@dataclass(frozen=True)
class ScenarioRow:
    raw: dict[str, str]

    @property
    def case_id(self) -> str:
        return self.raw["case_id"]

    @property
    def case_name(self) -> str:
        return self.raw["case_name"]

    @property
    def topology(self) -> str:
        return self.raw["topology"]

    @property
    def fault_pu(self) -> float:
        return float(self.raw["fault_pu"])

    @property
    def duration_s(self) -> float:
        return float(self.raw["duration_s"])

    @property
    def phase_mode(self) -> str:
        return self.raw["phase_mode"]

    @property
    def fault_phase_pu(self) -> list[float]:
        return parse_float_vector(self.raw.get("fault_phase_pu", ""))

    @property
    def is_balanced(self) -> bool:
        return not self.fault_phase_pu

    @property
    def model_path(self) -> str:
        return self.raw["model_path"]

    @property
    def fault_start_s(self) -> float:
        return float(self.raw["fault_start_s"])

    @property
    def fault_stop_margin_s(self) -> float:
        return float(self.raw["fault_stop_margin_s"])

    @property
    def fault_settle_s(self) -> float:
        return float(self.raw["fault_settle_s"])

    @property
    def chopper_threshold(self) -> float:
        return float(self.raw["chopper_threshold"])

    @property
    def rchop_scale(self) -> float:
        return float(self.raw["rchop_scale"])

    @property
    def actor_filter_tau(self) -> float:
        return float(self.raw["actor_filter_tau"])

    @property
    def phase_override(self) -> bool:
        return parse_bool(self.raw.get("phase_override", "false"))


def safe_token(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def matlab_vector(values: list[float]) -> str:
    return "[" + " ".join(f"{value:.12g}" for value in values) + "]"


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def parse_float_vector(text: str) -> list[float]:
    value = (text or "").strip()
    if not value:
        return []
    value = value.strip("[]()")
    return [float(part) for part in value.replace(",", " ").split() if part]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


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
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout_s: int,
    allow_nonzero: bool = False,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
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
    if proc.returncode != 0 and not allow_nonzero:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def latest_new_file(directory: Path, pattern: str, before: set[Path]) -> Path | None:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    return None


def fault_cell(rows: list[ScenarioRow]) -> str:
    if not rows:
        return "{}"
    has_phase = any(not row.is_balanced for row in rows)
    row_text: list[str] = []
    for row in rows:
        items = [
            matlab_string(row.case_name),
            f"{row.fault_pu:.12g}",
            f"{row.duration_s:.12g}",
        ]
        if has_phase:
            phase = row.fault_phase_pu or [row.fault_pu, row.fault_pu, row.fault_pu]
            items.append(matlab_vector(phase))
        row_text.append(", ".join(items))
    return "{ " + "; ".join(row_text) + " }"


def model_params_struct(row: ScenarioRow) -> str:
    base_rchop = (800.0**2) / 120e3
    items = [
        ("hpt_chopper_threshold", row.chopper_threshold),
        ("hpt_rchop", base_rchop * row.rchop_scale),
    ]
    if row.phase_override:
        fault_clear = row.fault_start_s + row.duration_s
        items.extend(
            [
                ("hpt_sac_phase_override_enable", 1.0),
                ("hpt_sac_phase_fault_start_s", row.fault_start_s),
                ("hpt_sac_phase_fault_clear_s", fault_clear),
                ("hpt_sac_phase_recovery_end_s", fault_clear + row.fault_stop_margin_s),
            ]
        )
    return "struct(" + ",".join(f"'{key}',{value:.12g}" for key, value in items) + ")"


def group_key(row: ScenarioRow, *, include_sac: bool) -> tuple[Any, ...]:
    # Phase-override rows depend on fault clear/recovery times, so keep each
    # duration separate there.  Non-phase-override rows can batch all durations.
    duration_key = row.duration_s if row.phase_override else -1.0
    actor_key = row.model_path if include_sac else ""
    return (
        row.topology,
        "balanced" if row.is_balanced else "phase",
        row.fault_start_s,
        row.fault_stop_margin_s,
        row.fault_settle_s,
        row.chopper_threshold,
        row.rchop_scale,
        row.actor_filter_tau if include_sac else 0.0,
        row.phase_override if include_sac else False,
        duration_key,
        actor_key,
    )


def export_actor_for_group(model_path: str, run_dir: Path) -> Path:
    source = ROOT / model_path
    if not source.exists():
        raise FileNotFoundError(source)
    out = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"
    export_hpt_actor(source, out)
    (run_dir / f"export_{safe_token(source.stem)}.json").write_text(
        json.dumps({"source": str(source), "out": str(out)}, indent=2),
        encoding="utf-8",
    )
    return out


def run_group(
    *,
    group_rows: list[ScenarioRow],
    group_index: int,
    run_dir: Path,
    matlab_cmd: str,
    timeout_s: int,
    include_sac: bool,
) -> Path:
    first = group_rows[0]
    if include_sac:
        export_actor_for_group(first.model_path, run_dir)
        modes = "string({'conventional_dq','sac_actor_always_raw'})"
    else:
        modes = "string({'conventional_dq'})"

    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    label = (
        f"{run_dir.name}_g{group_index:03d}_"
        f"{first.topology}_{'balanced' if first.is_balanced else 'phase'}"
    )
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(first.topology)}",
        "hpt_compare_scenario_type='fault'",
        f"hpt_compare_modes={modes}",
        f"hpt_compare_faults={fault_cell(group_rows)}",
        f"hpt_compare_model_params={model_params_struct(first)}",
        f"hpt_compare_fault_start={first.fault_start_s:.12g}",
        f"hpt_compare_fault_stop_margin={first.fault_stop_margin_s:.12g}",
        f"hpt_compare_fault_settle_s={first.fault_settle_s:.12g}",
        f"hpt_compare_actor_filter_tau={first.actor_filter_tau:.12g}",
        f"hpt_compare_run_label={matlab_string(label)}",
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
    ]
    proc = run_command(
        [matlab_cmd, "-batch", "; ".join(statements)],
        cwd=ROOT,
        log_path=run_dir / "logs" / f"group_{group_index:03d}_{safe_token(label)}.log",
        timeout_s=timeout_s,
        allow_nonzero=True,
    )
    csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
    if proc.returncode != 0 and csv_path is None:
        raise RuntimeError(
            f"MATLAB group {group_index} failed ({proc.returncode}) and produced no CSV"
        )
    if csv_path is None:
        raise RuntimeError(f"MATLAB group {group_index} produced no CSV")
    if proc.returncode != 0:
        (run_dir / "logs" / f"group_{group_index:03d}_nonzero.warning.txt").write_text(
            f"MATLAB returned {proc.returncode}, but produced {csv_path}\n",
            encoding="utf-8",
        )
    copy_path = run_dir / "group_csv" / f"group_{group_index:03d}.csv"
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(csv_path, copy_path)
    return copy_path


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        value = row.get(key, default)
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def b(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"1", "1.0", "true", "yes"}


def merge_group_outputs(csv_paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in csv_paths:
        for row in read_csv(path):
            row["source_group_csv"] = str(path)
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]], include_sac: bool) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (row.get("topology", ""), row.get("case_name", ""))
        groups[key][row.get("mode", "")] = row

    paired: list[dict[str, Any]] = []
    for (topology, case_name), by_mode in sorted(groups.items()):
        conv = by_mode.get("conventional_dq", {})
        sac = by_mode.get("sac_actor_always_raw", {}) if include_sac else {}
        conv_pass = b(conv, "voltage_survival_pass")
        sac_pass = b(sac, "voltage_survival_pass") if sac else False
        conv_score = f(conv, "control_score")
        sac_score = f(sac, "control_score") if sac else float("nan")
        sac_beat = bool(
            include_sac
            and sac
            and sac_pass
            and (
                (not conv_pass)
                or (
                    math.isfinite(sac_score)
                    and math.isfinite(conv_score)
                    and sac_score < conv_score
                )
            )
        )
        paired.append(
            {
                "topology": topology,
                "case_name": case_name,
                "fault_pu": f(conv or sac, "fault_pu"),
                "fault_duration_s": f(conv or sac, "fault_duration_s"),
                "phase_mode": phase_mode_from_case(case_name),
                "fault_family": "HVRT" if f(conv or sac, "fault_pu") > 1.0 else "LVRT",
                "conventional_voltage_survival_pass": conv_pass,
                "conventional_score": conv_score,
                "conventional_reason": conv.get("voltage_survival_reason", ""),
                "sac_voltage_survival_pass": sac_pass if include_sac else "",
                "sac_score": sac_score if include_sac else "",
                "sac_reason": sac.get("voltage_survival_reason", "") if sac else "",
                "sac_beats_conventional": sac_beat if include_sac else "",
                "sac_minus_conventional_score": sac_score - conv_score
                if include_sac and math.isfinite(sac_score) and math.isfinite(conv_score)
                else "",
                "conventional_vdc_min": f(conv, "vdc_min"),
                "conventional_vdc_max": f(conv, "vdc_max"),
                "sac_vdc_min": f(sac, "vdc_min") if sac else "",
                "sac_vdc_max": f(sac, "vdc_max") if sac else "",
                "conventional_envelope_violation_max_pu": f(conv, "envelope_violation_max_pu"),
                "sac_envelope_violation_max_pu": f(sac, "envelope_violation_max_pu")
                if sac
                else "",
                "conventional_recovery_violation_max_pu": f(conv, "recovery_violation_max_pu"),
                "sac_recovery_violation_max_pu": f(sac, "recovery_violation_max_pu")
                if sac
                else "",
            }
        )

    conv_pass_n = sum(1 for row in paired if row["conventional_voltage_survival_pass"])
    sac_pass_n = sum(1 for row in paired if row["sac_voltage_survival_pass"] is True)
    sac_beat_n = sum(1 for row in paired if row["sac_beats_conventional"] is True)
    conv_fail_sac_pass = sum(
        1
        for row in paired
        if row["conventional_voltage_survival_pass"] is False
        and row["sac_voltage_survival_pass"] is True
    )
    conv_pass_sac_fail = sum(
        1
        for row in paired
        if row["conventional_voltage_survival_pass"] is True
        and row["sac_voltage_survival_pass"] is False
    )
    return {
        "case_count": len(paired),
        "raw_row_count": len(rows),
        "conventional_voltage_survival_pass_count": conv_pass_n,
        "sac_voltage_survival_pass_count": sac_pass_n if include_sac else None,
        "sac_beats_conventional_count": sac_beat_n if include_sac else None,
        "traditional_fail_sac_pass_count": conv_fail_sac_pass if include_sac else None,
        "traditional_pass_sac_fail_count": conv_pass_sac_fail if include_sac else None,
        "paired_rows": paired,
    }


def phase_mode_from_case(case_name: str) -> str:
    for prefix in ("balanced", "ab", "bc", "ca", "a", "b", "c"):
        if case_name.startswith(prefix + "_"):
            return prefix
    return ""


def write_report(run_dir: Path, summary: dict[str, Any], include_sac: bool) -> None:
    lines = [
        "# HPT Voltage-Survival Boundary Matrix",
        "",
        f"- Run ID: `{run_dir.name}`",
        f"- Cases: `{summary['case_count']}`",
        f"- Raw rows: `{summary['raw_row_count']}`",
        f"- Conventional voltage-survival pass: `{summary['conventional_voltage_survival_pass_count']} / {summary['case_count']}`",
    ]
    if include_sac:
        lines.extend(
            [
                f"- SAC voltage-survival pass: `{summary['sac_voltage_survival_pass_count']} / {summary['case_count']}`",
                f"- SAC beats conventional: `{summary['sac_beats_conventional_count']} / {summary['case_count']}`",
                f"- Traditional fail / SAC pass: `{summary['traditional_fail_sac_pass_count']} / {summary['case_count']}`",
                f"- Traditional pass / SAC fail: `{summary['traditional_pass_sac_fail_count']} / {summary['case_count']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Boundary Rows",
            "",
            "| Topology | Case | Conv pass | SAC pass | SAC beat | Conv score | SAC score | Conv reason | SAC reason |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in summary["paired_rows"]:
        lines.append(
            f"| {row['topology']} | `{row['case_name']}` | "
            f"{row['conventional_voltage_survival_pass']} | "
            f"{row['sac_voltage_survival_pass']} | "
            f"{row['sac_beats_conventional']} | "
            f"{float(row['conventional_score']):.3f} | "
            f"{float(row['sac_score']):.3f}" if include_sac else ""
        )
        if include_sac:
            lines[-1] += (
                f" | `{row['conventional_reason']}` | `{row['sac_reason']}` |"
            )
        else:
            lines[-1] += f"| | | `{row['conventional_reason']}` | |"
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def filter_rows(rows: list[ScenarioRow], args: argparse.Namespace) -> list[ScenarioRow]:
    out = rows
    if args.topology != "all":
        out = [row for row in out if row.topology == args.topology]
    if args.phase_modes:
        wanted = {mode.strip().lower() for mode in args.phase_modes.split(",") if mode.strip()}
        out = [row for row in out if row.phase_mode in wanted]
    if args.depths:
        wanted_depths = {round(float(x), 6) for x in args.depths.split(",") if x.strip()}
        out = [row for row in out if round(row.fault_pu, 6) in wanted_depths]
    if args.durations_ms:
        wanted_ms = {int(round(float(x))) for x in args.durations_ms.split(",") if x.strip()}
        out = [row for row in out if int(round(1000.0 * row.duration_s)) in wanted_ms]
    if args.max_cases > 0:
        out = out[: args.max_cases]
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--controller-mode",
        choices=["conventional", "current-sac"],
        default="current-sac",
        help="current-sac runs conventional_dq and nearest SAC actor together.",
    )
    parser.add_argument("--topology", choices=["all", "topology1", "topology2"], default="all")
    parser.add_argument("--phase-modes", default="", help="Comma list such as balanced,a,ab.")
    parser.add_argument("--depths", default="", help="Comma list of pu values for smoke runs.")
    parser.add_argument("--durations-ms", default="", help="Comma list of durations in ms.")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=2400)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def jsonable_args(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in vars(args).items():
        if isinstance(value, Path):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def main() -> int:
    args = parse_args()
    include_sac = args.controller_mode == "current-sac"
    run_id = args.run_id or f"hpt_voltage_survival_boundary_{args.controller_mode}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = [ScenarioRow(row) for row in read_csv(args.manifest)]
    rows = filter_rows(rows, args)
    if not rows:
        raise ValueError("No rows selected from manifest")

    groups: dict[tuple[Any, ...], list[ScenarioRow]] = defaultdict(list)
    for row in rows:
        groups[group_key(row, include_sac=include_sac)].append(row)
    grouped = list(groups.values())

    selected_manifest = run_dir / "selected_manifest.csv"
    write_csv(selected_manifest, [row.raw for row in rows])
    plan = {
        "schema": "hpt-voltage-survival-boundary-run-plan-v1",
        "run_id": run_id,
        "controller_mode": args.controller_mode,
        "selected_cases": len(rows),
        "group_count": len(grouped),
        "manifest": str(args.manifest),
        "selected_manifest": str(selected_manifest),
        "dry_run": args.dry_run,
    }
    (run_dir / "run_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_voltage_survival_boundary_matrix",
        config=jsonable_args(args),
        dataset_manifest=args.manifest,
        extra=plan,
    )
    if args.dry_run:
        print(json.dumps(plan, indent=2), flush=True)
        return 0

    csv_paths: list[Path] = []
    for idx, group_rows in enumerate(grouped, start=1):
        csv_paths.append(
            run_group(
                group_rows=group_rows,
                group_index=idx,
                run_dir=run_dir,
                matlab_cmd=args.matlab_cmd,
                timeout_s=args.timeout_s,
                include_sac=include_sac,
            )
        )

    raw_rows = merge_group_outputs(csv_paths)
    raw_csv = run_dir / "boundary_raw_rows.csv"
    write_csv(raw_csv, raw_rows)
    summary = summarize(raw_rows, include_sac=include_sac)
    summary["schema"] = "hpt-voltage-survival-boundary-summary-v1"
    summary["run_id"] = run_id
    summary["controller_mode"] = args.controller_mode
    summary["raw_csv"] = str(raw_csv)
    paired_csv = run_dir / "boundary_case_summary.csv"
    write_csv(paired_csv, summary["paired_rows"])
    summary_json = {k: v for k, v in summary.items() if k != "paired_rows"}
    summary_json["paired_csv"] = str(paired_csv)
    (run_dir / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")
    write_report(run_dir, summary, include_sac)
    print(json.dumps(summary_json, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
