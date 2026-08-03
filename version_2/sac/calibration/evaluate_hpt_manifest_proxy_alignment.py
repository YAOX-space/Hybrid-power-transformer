"""Evaluate accepted HPT specialist actors inside the averaged proxy.

This is a lightweight governance check for the question:

    Do the accepted switch-level specialist actors have matching proxy behavior?

It does not replace Simulink validation.  It rolls each manifest actor through
``HPTVoltageSACEnv`` and optionally joins a switch-level validation CSV so that
false-positive/false-negative proxy cases are visible in one table.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from hpt_frt.device.model_io import load_sac

from version_2.sac.experiment_metadata import write_experiment_metadata
from version_2.sac.hpt_voltage_sac_env import HPTVoltageEnvConfig, HPTVoltageSACEnv
from version_2.sac.offline.train_hpt_voltage_sac import scenario_from_manifest_row


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = repo_root()
DEFAULT_MANIFEST = (
    ROOT
    / "version_2"
    / "sac"
    / "experiments"
    / "stage6_recheck_manifest_current12_repaired_sac_20260728.csv"
)
DEFAULT_SWITCH_CSV = (
    ROOT
    / "lab"
    / "results"
    / "hpt_stage6_recheck_current12_repaired_sac_20260728"
    / "accepted_specialist_validation.csv"
)
DEFAULT_OUT = ROOT / "lab" / "results"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: Any, default: float = float("nan")) -> float:
    if value in ("", None):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def git_metadata() -> dict[str, str]:
    def run(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, cwd=ROOT, text=True).strip()
        except Exception:
            return ""

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "commit": run(["git", "rev-parse", "HEAD"]),
        "status_short": run(["git", "status", "--short"]),
    }


def finite_mean(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.mean(arr))


def finite_max(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.max(arr))


def finite_min(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.min(arr))


def rollout_actor(row: dict[str, str], config: HPTVoltageEnvConfig, seed: int) -> dict[str, Any]:
    scenario = scenario_from_manifest_row(row)
    model_path = Path(row["model_path"])
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    model = load_sac(model_path, device="cpu")
    env = HPTVoltageSACEnv([scenario], config=config, seed=seed, train_mode=False)
    obs, _ = env.reset()

    ret = 0.0
    steps = 0
    lv_values: list[float] = []
    vdc_values: list[float] = []
    envelope_values: list[float] = []
    fault_values: list[float] = []
    recovery_values: list[float] = []
    support_values: list[float] = []
    action_values: list[float] = []
    raw_action_values: list[float] = []
    grid_current_values: list[float] = []
    terminated = False
    truncated = False
    info: dict[str, Any] = {}
    while not (terminated or truncated):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        ret += float(reward)
        steps += 1
        lv_values.append(float(info["v_lv_pu"]))
        vdc_values.append(float(info["vdc_pu"]))
        envelope_values.append(float(info["envelope_violation_max_pu"]))
        fault_values.append(float(info["fault_band_violation_max_pu"]))
        recovery_values.append(float(info["recovery_violation_max_pu"]))
        support_values.append(float(info["calibration_support_violation"]))
        action_values.append(float(info["action_max_abs"]))
        raw_action_values.append(float(info["raw_action_max_abs"]))
        grid_current_values.append(float(info["grid_current_peak_pu"]))

    tol = float(config.envelope_tolerance_pu)
    lv_min = finite_min(lv_values)
    lv_max = finite_max(lv_values)
    vdc_min = finite_min(vdc_values)
    vdc_max = finite_max(vdc_values)
    envelope_max = finite_max(envelope_values)
    fault_max = finite_max(fault_values)
    recovery_max = finite_max(recovery_values)
    action_max = finite_max(action_values)
    proxy_voltage_survival_pass = bool(
        lv_min >= 180.0 / config.v_ref_phase_rms - 1e-9
        and lv_max <= 238.0 / config.v_ref_phase_rms + 1e-9
        and vdc_min >= 650.0 / config.vdc_ref - 1e-9
        and vdc_max <= 1000.0 / config.vdc_ref + 1e-9
        and envelope_max <= tol
        and fault_max <= tol
        and recovery_max <= tol
        and action_max <= 0.9501
    )

    return {
        "case_id": row.get("case_id", ""),
        "topology": row.get("topology", ""),
        "fault_family": row.get("fault_family", ""),
        "fault_phase_key": row.get("fault_phase_key", "") or "balanced",
        "fault_pu": row.get("fault_pu", ""),
        "duration_s": row.get("duration_s", ""),
        "model_path": row.get("model_path", ""),
        "proxy_episode_return": ret,
        "proxy_steps": steps,
        "proxy_terminated": terminated,
        "proxy_truncated": truncated,
        "proxy_lv_min_pu": lv_min,
        "proxy_lv_max_pu": lv_max,
        "proxy_lv_mean_pu": finite_mean(lv_values),
        "proxy_vdc_min_pu": vdc_min,
        "proxy_vdc_max_pu": vdc_max,
        "proxy_vdc_mean_pu": finite_mean(vdc_values),
        "proxy_envelope_violation_max_pu": envelope_max,
        "proxy_fault_lv_band_violation_max_pu": fault_max,
        "proxy_recovery_violation_max_pu": recovery_max,
        "proxy_support_violation_max": finite_max(support_values),
        "proxy_action_max_abs": action_max,
        "proxy_raw_action_max_abs": finite_max(raw_action_values),
        "proxy_grid_current_peak_pu": finite_max(grid_current_values),
        "proxy_voltage_survival_pass": proxy_voltage_survival_pass,
        "proxy_final_condition": info.get("condition", ""),
    }


def join_switch_rows(
    proxy_rows: list[dict[str, Any]], switch_csv: Path | None
) -> list[dict[str, Any]]:
    if switch_csv is None or not switch_csv.exists():
        return proxy_rows
    switch_by_case = {row["case_id"]: row for row in read_csv(switch_csv)}
    out: list[dict[str, Any]] = []
    for row in proxy_rows:
        sw = switch_by_case.get(str(row["case_id"]), {})
        switch_pass = as_bool(sw.get("voltage_survival_pass", ""))
        proxy_pass = bool(row["proxy_voltage_survival_pass"])
        item = dict(row)
        item.update(
            {
                "switch_voltage_survival_pass": switch_pass,
                "switch_beats_conventional": as_bool(sw.get("beats_conventional", "")),
                "switch_full_frt_pass": as_bool(sw.get("full_frt_pass", "")),
                "switch_policy_score": as_float(sw.get("policy_score")),
                "switch_baseline_score": as_float(sw.get("baseline_score")),
                "switch_lv_min_pu": as_float(sw.get("fault_lv_min")) / 207.0,
                "switch_lv_max_pu": as_float(sw.get("fault_lv_max")) / 207.0,
                "switch_vdc_min_pu": as_float(sw.get("vdc_min")) / 800.0,
                "switch_vdc_max_pu": as_float(sw.get("vdc_max")) / 800.0,
                "switch_envelope_violation_max_pu": as_float(
                    sw.get("envelope_violation_max_pu")
                ),
                "switch_fault_lv_band_violation_max_pu": as_float(
                    sw.get("fault_lv_band_violation_max_pu")
                ),
                "switch_recovery_violation_max_pu": as_float(
                    sw.get("recovery_violation_max_pu")
                ),
                "proxy_switch_pass_agree": proxy_pass == switch_pass,
            }
        )
        out.append(item)
    return out


def write_report(path: Path, rows: list[dict[str, Any]], manifest: Path) -> None:
    total = len(rows)
    proxy_pass = sum(1 for row in rows if row["proxy_voltage_survival_pass"])
    switch_joined = any("switch_voltage_survival_pass" in row for row in rows)
    switch_pass = sum(1 for row in rows if row.get("switch_voltage_survival_pass"))
    agree = sum(1 for row in rows if row.get("proxy_switch_pass_agree"))
    lines = [
        "# HPT Manifest Proxy Alignment",
        "",
        f"- Manifest: `{manifest}`",
        f"- Cases: `{total}`",
        f"- Proxy voltage-survival pass: `{proxy_pass} / {total}`",
    ]
    if switch_joined:
        lines.extend(
            [
                f"- Switch-level voltage-survival pass: `{switch_pass} / {total}`",
                f"- Proxy/switch pass agreement: `{agree} / {total}`",
                "",
                "> This report is a proxy governance diagnostic. Switch-level Simulink remains the source of record.",
            ]
        )
    lines.extend(
        [
            "",
            "| Case | Topology | Fault | Proxy pass | Switch pass | Agree | Proxy LV min/max | Proxy Vdc min/max | Proxy violations | Support |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        fault = (
            f"{row['fault_family']} {row['fault_phase_key']} "
            f"{float(row['fault_pu']):.3g}pu/{float(row['duration_s']) * 1000:.0f}ms"
        )
        lines.append(
            f"| `{row['case_id']}` | {row['topology']} | {fault} | "
            f"{row['proxy_voltage_survival_pass']} | "
            f"{row.get('switch_voltage_survival_pass', '')} | "
            f"{row.get('proxy_switch_pass_agree', '')} | "
            f"{row['proxy_lv_min_pu']:.3f}/{row['proxy_lv_max_pu']:.3f} | "
            f"{row['proxy_vdc_min_pu']:.3f}/{row['proxy_vdc_max_pu']:.3f} | "
            f"{row['proxy_fault_lv_band_violation_max_pu']:.4g}/"
            f"{row['proxy_envelope_violation_max_pu']:.4g}/"
            f"{row['proxy_recovery_violation_max_pu']:.4g} | "
            f"{row['proxy_support_violation_max']:.3f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--switch-csv", type=Path, default=DEFAULT_SWITCH_CSV)
    parser.add_argument("--calibration", type=Path, default=ROOT / "version_2" / "sac" / "hpt_proxy_calibration.json")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--case-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_csv(args.manifest)
    if args.case_id:
        rows = [row for row in rows if row.get("case_id") == args.case_id]
        if not rows:
            raise ValueError(f"case_id not found: {args.case_id}")
    if args.max_cases > 0:
        rows = rows[: args.max_cases]

    run_id = args.run_id or f"hpt_proxy_manifest_alignment_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = DEFAULT_OUT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    config = HPTVoltageEnvConfig(calibration_path=str(args.calibration))
    proxy_rows = [
        rollout_actor(row, config, seed=idx)
        for idx, row in enumerate(rows)
    ]
    joined = join_switch_rows(proxy_rows, args.switch_csv)
    detail_csv = out_dir / "proxy_manifest_alignment.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "REPORT.md"
    write_csv(detail_csv, joined)
    summary = {
        "schema": "hpt-proxy-manifest-alignment-v1",
        "run_id": run_id,
        "manifest": str(args.manifest),
        "switch_csv": str(args.switch_csv) if args.switch_csv else "",
        "calibration": str(args.calibration),
        "case_count": len(joined),
        "proxy_voltage_survival_pass_count": sum(
            1 for row in joined if row["proxy_voltage_survival_pass"]
        ),
        "switch_voltage_survival_pass_count": sum(
            1 for row in joined if row.get("switch_voltage_survival_pass")
        ),
        "proxy_switch_pass_agreement_count": sum(
            1 for row in joined if row.get("proxy_switch_pass_agree")
        ),
        "git": git_metadata(),
        "detail_csv": str(detail_csv),
        "report_md": str(report_md),
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(report_md, joined, args.manifest)
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_proxy_manifest_alignment",
        config={
            "manifest": str(args.manifest),
            "switch_csv": str(args.switch_csv),
            "calibration": str(args.calibration),
            "max_cases": args.max_cases,
            "case_id": args.case_id,
        },
        dataset_manifest=args.manifest,
        extra={"detail_csv": str(detail_csv), "summary_json": str(summary_json)},
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
