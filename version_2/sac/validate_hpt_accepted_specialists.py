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


def run_switch_validation(row: dict[str, str], run_dir: Path, matlab_cmd: str, timeout_s: int) -> dict[str, Any]:
    case_id = row["case_id"]
    topology = row["topology"]
    fault_pu = float(row["fault_pu"])
    duration_s = float(row["duration_s"])
    case_name = f"{'hvrt' if fault_pu > 1.0 else 'lvrt'}_{int(round(duration_s * 1000)):03d}ms_{fault_pu:.3f}pu".replace(".", "p")
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(topology)}",
        "hpt_compare_scenario_type='fault'",
        "hpt_compare_modes=string({'conventional_dq','sac_actor_always_raw'})",
        f"hpt_compare_faults={{ {matlab_string(case_name)}, {fault_pu:.12g}, {duration_s:.12g} }}",
        "hpt_compare_fault_start=0.035",
        "hpt_compare_fault_stop_margin=0.125",
        f"hpt_compare_run_label={matlab_string('accepted_' + safe_token(case_id))}",
        "eval_hpt_v2_control_comparison",
    ]
    run_command(
        [matlab_cmd, "-batch", "; ".join(statements)],
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / f"validate_{safe_token(case_id)}.log",
    )
    csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
    summary = summarize_control_csv(csv_path, "sac_actor_always_raw")
    return {
        "case_id": case_id,
        "topology": topology,
        "fault_family": row["fault_family"],
        "fault_pu": fault_pu,
        "duration_s": duration_s,
        "model_path": row["model_path"],
        "control_csv": str(csv_path),
        "voltage_survival_pass": summary["policy_voltage_pass"],
        "beats_conventional": summary["policy_beats_baseline"],
        "full_frt_pass": summary["policy_full_frt_pass"],
        "policy_score": summary["policy_score"],
        "baseline_score": summary["baseline_score"],
        "lv_mean": summary["policy_lv_mean"],
        "lv_recovery_mean": summary["policy_lv_recovery_mean"],
        "vdc_min": summary["policy_vdc_min"],
        "vdc_max": summary["policy_vdc_max"],
        "voltage_reason": summary["policy_voltage_reason"],
        "full_frt_reason": summary["policy_full_frt_reason"],
    }


def write_report(run_dir: Path, rows: list[dict[str, Any]], manifest: Path) -> None:
    lines = [
        "# Accepted HPT Specialist Validation",
        "",
        f"- Manifest: `{manifest}`",
        f"- Cases: `{len(rows)}`",
        "",
        "| Case | Voltage | Beat | Full FRT | Score SAC / conventional | LV mean / recovery | Vdc min / max | Reason |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | {row['voltage_survival_pass']} | "
            f"{row['beats_conventional']} | {row['full_frt_pass']} | "
            f"{row['policy_score']:.3f} / {row['baseline_score']:.3f} | "
            f"{row['lv_mean']:.2f} / {row['lv_recovery_mean']:.2f} | "
            f"{row['vdc_min']:.2f} / {row['vdc_max']:.2f} | "
            f"`{row['voltage_reason'] or row['full_frt_reason']}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_csv(args.manifest)
    if args.max_cases > 0:
        rows = rows[: args.max_cases]
    run_id = args.run_id or f"hpt_accepted_specialist_validation_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    actor_path = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"

    out_rows: list[dict[str, Any]] = []
    for row in rows:
        model_path = ROOT / row["model_path"]
        if not model_path.exists():
            raise FileNotFoundError(model_path)
        export_actor(model_path, run_dir, actor_path, args.timeout_s)
        out_rows.append(run_switch_validation(row, run_dir, args.matlab_cmd, args.timeout_s))

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
