"""Re-validate accepted HPT specialist actors in switch-level Simulink.

The input manifest is a small CSV with one checkpoint per topology/fault case.
For each row this script:

1. exports the SAC actor checkpoint into ``hpt_sac_actor_weights_dynamic.mat``;
2. runs ``eval_hpt_v2_control_comparison`` against ``conventional_dq``;
3. writes a compact pass/fail CSV and Markdown report.

This is a regression gate for accepted voltage-survival specialists.  It does
not turn voltage-survival specialists into full-FRT-certified controllers.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .experiment_metadata import write_experiment_metadata
from .run_hpt_trajectory_specialist_campaign import (
    CONTROL_DIR,
    RESULTS,
    ROOT,
    SIMULINK_DIR,
    latest_new_file,
    matlab_string,
    read_csv,
    safe_token,
    summarize_control_csv,
)


DEFAULT_MANIFEST = Path(__file__).resolve().parent / "experiments" / "accepted_specialists_20260719.csv"


def run_command(cmd: list[str], *, cwd: Path, timeout_s: int, log_path: Path) -> None:
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
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_actor(model_path: Path, run_dir: Path, matlab_actor_path: Path, timeout_s: int) -> None:
    run_command(
        [
            "py",
            "-3",
            "-m",
            "version_2.sac.export_hpt_sac_actor",
            "--model",
            str(model_path),
            "--out",
            str(matlab_actor_path),
        ],
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / f"export_{safe_token(model_path.stem)}.log",
    )


def row_float(row: dict[str, str], key: str, default: float) -> float:
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        return float(default)
    return float(value)


def row_bool(row: dict[str, str], key: str, default: bool = False) -> bool:
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        return bool(default)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def row_float_vector(row: dict[str, str], key: str) -> list[float]:
    value = row.get(key, "")
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    text = text.strip("[]()")
    parts = [part for part in text.replace(",", " ").split() if part]
    return [float(part) for part in parts]


def matlab_vector(values: list[float]) -> str:
    return "[" + " ".join(f"{value:.12g}" for value in values) + "]"


def run_switch_validation(
    row: dict[str, str],
    run_dir: Path,
    matlab_cmd: str,
    timeout_s: int,
    *,
    default_fault_start: float,
    default_fault_stop_margin: float,
    default_fault_settle_s: float,
) -> dict[str, Any]:
    case_id = row["case_id"]
    topology = row["topology"]
    fault_pu = float(row["fault_pu"])
    duration_s = float(row["duration_s"])
    fault_start = row_float(row, "fault_start_s", default_fault_start)
    fault_stop_margin = row_float(row, "fault_stop_margin_s", default_fault_stop_margin)
    fault_settle_s = row_float(row, "fault_settle_s", default_fault_settle_s)
    chopper_threshold = row_float(row, "chopper_threshold", 850.0)
    rchop_scale = row_float(row, "rchop_scale", 1.0)
    actor_filter_tau = row_float(row, "actor_filter_tau", 0.0)
    comparison_mode = str(row.get("comparison_mode", "") or "").strip() or "sac_actor_always_raw"
    phase_override = row_bool(row, "phase_override", False)
    fault_phase_key = str(row.get("fault_phase_key", "") or "").strip()
    fault_phase_pu = row_float_vector(row, "fault_phase_pu")
    base_rchop = (800.0**2) / 120e3
    case_name = f"{'hvrt' if fault_pu > 1.0 else 'lvrt'}_{int(round(duration_s * 1000)):03d}ms_{fault_pu:.3f}pu".replace(".", "p")
    if fault_phase_key:
        case_name = f"{fault_phase_key}_{'hvrt' if fault_pu > 1.0 else 'lvrt'}{int(round(fault_pu * 100)):03d}"
    fault_args = f"{matlab_string(case_name)}, {fault_pu:.12g}, {duration_s:.12g}"
    if len(fault_phase_pu) == 3:
        fault_args += ", " + matlab_vector(fault_phase_pu)
    model_param_items = [
        f"'hpt_chopper_threshold',{chopper_threshold:.12g}",
        f"'hpt_rchop',{base_rchop * rchop_scale:.12g}",
    ]
    if phase_override:
        fault_clear = fault_start + duration_s
        recovery_end = fault_clear + fault_stop_margin
        model_param_items.extend(
            [
                "'hpt_sac_phase_override_enable',1",
                f"'hpt_sac_phase_fault_start_s',{fault_start:.12g}",
                f"'hpt_sac_phase_fault_clear_s',{fault_clear:.12g}",
                f"'hpt_sac_phase_recovery_end_s',{recovery_end:.12g}",
            ]
        )
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(topology)}",
        "hpt_compare_scenario_type='fault'",
        f"hpt_compare_modes=string({{'conventional_dq',{matlab_string(comparison_mode)}}})",
        f"hpt_compare_faults={{ {fault_args} }}",
        "hpt_compare_model_params=struct(" + ",".join(model_param_items) + ")",
        f"hpt_compare_fault_start={fault_start:.12g}",
        f"hpt_compare_fault_stop_margin={fault_stop_margin:.12g}",
        f"hpt_compare_fault_settle_s={fault_settle_s:.12g}",
        f"hpt_compare_actor_filter_tau={actor_filter_tau:.12g}",
        f"hpt_compare_run_label={matlab_string('accepted_' + safe_token(case_id))}",
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
    ]
    run_command(
        [matlab_cmd, "-batch", "; ".join(statements)],
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / f"validate_{safe_token(case_id)}.log",
    )
    csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
    summary = summarize_control_csv(csv_path, comparison_mode)
    return {
        "case_id": case_id,
        "comparison_mode": comparison_mode,
        "topology": topology,
        "fault_family": row["fault_family"],
        "fault_phase_key": fault_phase_key,
        "fault_phase_pu": matlab_vector(fault_phase_pu) if len(fault_phase_pu) == 3 else "",
        "fault_pu": fault_pu,
        "duration_s": duration_s,
        "fault_start_s": fault_start,
        "fault_stop_margin_s": fault_stop_margin,
        "fault_settle_s": fault_settle_s,
        "chopper_threshold": chopper_threshold,
        "rchop_scale": rchop_scale,
        "actor_filter_tau": actor_filter_tau,
        "phase_override": phase_override,
        "model_path": row["model_path"],
        "base_model_path": row.get("base_model_path", ""),
        "dynamic_model_path": row.get("dynamic_model_path", ""),
        "control_csv": str(csv_path),
        "voltage_survival_pass": summary["policy_voltage_pass"],
        "beats_conventional": summary["policy_beats_baseline"],
        "full_frt_pass": summary["policy_full_frt_pass"],
        "policy_score": summary["policy_score"],
        "baseline_score": summary["baseline_score"],
        "lv_mean": summary["policy_lv_mean"],
        "lv_recovery_mean": summary["policy_lv_recovery_mean"],
        "fault_lv_min": summary["policy_fault_lv_min"],
        "fault_lv_max": summary["policy_fault_lv_max"],
        "fault_lv_band_violation_max_pu": summary[
            "policy_fault_lv_band_violation_max_pu"
        ],
        "envelope_violation_max_pu": summary["policy_envelope_violation_max_pu"],
        "recovery_violation_max_pu": summary["policy_recovery_violation_max_pu"],
        "vdc_min": summary["policy_vdc_min"],
        "vdc_max": summary["policy_vdc_max"],
        "voltage_reason": summary["policy_voltage_reason"],
        "full_frt_reason": summary["policy_full_frt_reason"],
    }


def unsupported_checkpoint_row(
    row: dict[str, str],
    *,
    default_fault_start: float,
    default_fault_stop_margin: float,
    default_fault_settle_s: float,
    reason: str,
) -> dict[str, Any]:
    fault_pu = float(row["fault_pu"])
    duration_s = float(row["duration_s"])
    return {
        "case_id": row["case_id"],
        "comparison_mode": str(row.get("comparison_mode", "") or "").strip() or "sac_actor_always_raw",
        "topology": row["topology"],
        "fault_family": row["fault_family"],
        "fault_pu": fault_pu,
        "duration_s": duration_s,
        "fault_start_s": row_float(row, "fault_start_s", default_fault_start),
        "fault_stop_margin_s": row_float(row, "fault_stop_margin_s", default_fault_stop_margin),
        "fault_settle_s": row_float(row, "fault_settle_s", default_fault_settle_s),
        "actor_filter_tau": row_float(row, "actor_filter_tau", 0.0),
        "phase_override": row_bool(row, "phase_override", False),
        "model_path": row["model_path"],
        "base_model_path": row.get("base_model_path", ""),
        "dynamic_model_path": row.get("dynamic_model_path", ""),
        "control_csv": "",
        "voltage_survival_pass": False,
        "beats_conventional": False,
        "full_frt_pass": False,
        "policy_score": float("inf"),
        "baseline_score": float("inf"),
        "lv_mean": float("nan"),
        "lv_recovery_mean": float("nan"),
        "fault_lv_min": float("nan"),
        "fault_lv_max": float("nan"),
        "fault_lv_band_violation_max_pu": float("nan"),
        "envelope_violation_max_pu": float("nan"),
        "recovery_violation_max_pu": float("nan"),
        "vdc_min": float("nan"),
        "vdc_max": float("nan"),
        "voltage_reason": reason,
        "full_frt_reason": reason,
    }


def write_report(run_dir: Path, rows: list[dict[str, Any]], manifest: Path) -> None:
    lines = [
        "# Accepted HPT Specialist Validation",
        "",
        f"- Manifest: `{manifest}`",
        f"- Cases: `{len(rows)}`",
        "",
        "| Case | Voltage | Beat | Full FRT | Score SAC / conventional | Fault LV min/max | Violations pu | Vdc min/max | Reason |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | {row['voltage_survival_pass']} | "
            f"{row['beats_conventional']} | {row['full_frt_pass']} | "
            f"{row['policy_score']:.3f} / {row['baseline_score']:.3f} | "
            f"{row['fault_lv_min']:.2f} / {row['fault_lv_max']:.2f} | "
            f"{row['fault_lv_band_violation_max_pu']:.4g} / "
            f"{row['envelope_violation_max_pu']:.4g} / "
            f"{row['recovery_violation_max_pu']:.4g} | "
            f"{row['vdc_min']:.2f} / {row['vdc_max']:.2f} | "
            f"`{row['voltage_reason'] or row['full_frt_reason']}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--case-id", default="", help="Optional case_id filter for targeted re-validation.")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.0)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument(
        "--post-export-delay-s",
        type=float,
        default=2.0,
        help="Delay after writing the actor MAT file before starting MATLAB.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_csv(args.manifest)
    if args.case_id:
        rows = [row for row in rows if row.get("case_id") == args.case_id]
        if not rows:
            raise ValueError(f"case_id not found in {args.manifest}: {args.case_id}")
    if args.max_cases > 0:
        rows = rows[: args.max_cases]
    run_id = args.run_id or f"hpt_accepted_specialist_validation_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    base_actor_path = SIMULINK_DIR / "hpt_sac_actor_weights.mat"
    dynamic_actor_path = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        base_model_text = str(row.get("base_model_path", "") or "").strip()
        dynamic_model_text = str(row.get("dynamic_model_path", "") or "").strip()
        if base_model_text and dynamic_model_text:
            base_model_path = ROOT / base_model_text
            dynamic_model_path = ROOT / dynamic_model_text
            if not base_model_path.exists():
                raise FileNotFoundError(base_model_path)
            if not dynamic_model_path.exists():
                raise FileNotFoundError(dynamic_model_path)
            if base_model_path.suffix.lower() != ".zip" or dynamic_model_path.suffix.lower() != ".zip":
                out_rows.append(
                    unsupported_checkpoint_row(
                        row,
                        default_fault_start=args.fault_start,
                        default_fault_stop_margin=args.fault_stop_margin,
                        default_fault_settle_s=args.fault_settle_s,
                        reason=(
                            "unsupported_dual_checkpoint_suffix:"
                            f"{base_model_path.suffix},{dynamic_model_path.suffix}"
                        ),
                    )
                )
                continue
            export_actor(base_model_path, run_dir, base_actor_path, args.timeout_s)
            export_actor(dynamic_model_path, run_dir, dynamic_actor_path, args.timeout_s)
        else:
            model_path = ROOT / row["model_path"]
            if not model_path.exists():
                raise FileNotFoundError(model_path)
            if model_path.suffix.lower() != ".zip":
                out_rows.append(
                    unsupported_checkpoint_row(
                        row,
                        default_fault_start=args.fault_start,
                        default_fault_stop_margin=args.fault_stop_margin,
                        default_fault_settle_s=args.fault_settle_s,
                        reason=f"unsupported_checkpoint_suffix:{model_path.suffix}",
                    )
                )
                continue
            export_actor(model_path, run_dir, dynamic_actor_path, args.timeout_s)
        if args.post_export_delay_s > 0.0:
            time.sleep(args.post_export_delay_s)
        out_rows.append(
            run_switch_validation(
                row,
                run_dir,
                args.matlab_cmd,
                args.timeout_s,
                default_fault_start=args.fault_start,
                default_fault_stop_margin=args.fault_stop_margin,
                default_fault_settle_s=args.fault_settle_s,
            )
        )

    write_csv(run_dir / "accepted_specialist_validation.csv", out_rows)
    write_report(run_dir, out_rows, args.manifest)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema": "hpt-accepted-specialist-validation-v1",
                "run_id": run_id,
                "manifest": str(args.manifest),
                "case_count": len(out_rows),
                "voltage_survival_pass_count": sum(1 for row in out_rows if row["voltage_survival_pass"]),
                "beats_conventional_count": sum(1 for row in out_rows if row["beats_conventional"]),
                "full_frt_pass_count": sum(1 for row in out_rows if row["full_frt_pass"]),
                "results_csv": str(run_dir / "accepted_specialist_validation.csv"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_accepted_specialist_validation",
        config={
            **vars(args),
            "manifest": str(args.manifest),
        },
        dataset_manifest=args.manifest,
        extra={"results_csv": str(run_dir / "accepted_specialist_validation.csv")},
    )
    print(json.dumps(json.loads((run_dir / "summary.json").read_text(encoding="utf-8")), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
