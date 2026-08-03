"""Run the DC-safe dq-seeded SAC pipeline on the 12 HPT fault families.

This is the expansion entry point after the topology2 balanced-LVRT 3x3
debug run.  It intentionally starts with one center case per family so the
topology/category/phase interfaces are verified before launching expensive
family matrices.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
EXPERIMENTS = ROOT / "version_2" / "sac" / "experiments"


@dataclass(frozen=True)
class Family:
    topology: str
    category: str
    phase_key: str

    @property
    def label(self) -> str:
        top = "t1" if self.topology == "topology1" else "t2"
        cat = "hvrt" if self.category == "HVRT" else "lvrt"
        phase = "bal" if self.phase_key == "abc" else self.phase_key
        return f"{top}_{phase}_{cat}"

    @property
    def center_pu(self) -> float:
        return 1.10 if self.category == "HVRT" else 0.90


FAMILIES = [
    Family(topology, category, phase)
    for topology in ("topology1", "topology2")
    for category in ("LVRT", "HVRT")
    for phase in ("abc", "a", "ab")
]


def run_logged(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    return int(proc.returncode)


def summarize_campaign(run_dir: Path, family: Family) -> dict:
    path = run_dir / "boundary_comparison_rows.csv"
    base = {
        "family": family.label,
        "topology": family.topology,
        "category": family.category,
        "phase_key": family.phase_key,
        "run_dir": str(run_dir),
        "csv": str(path),
        "status": "missing_csv",
    }
    if not path.exists():
        return base
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    out = dict(base)
    out["status"] = "ok"
    for row in rows:
        ctrl = row.get("controller", "")
        prefix = {
            "strong_dq": "dq",
            "dq_seeded_actor_before_sac": "seed",
            "dq_seeded_actor_after_sac": "sac",
        }.get(ctrl)
        if not prefix:
            continue
        for key in (
            "voltage_survival_pass",
            "control_score",
            "vdc_min",
            "vdc_max",
            "grid_current_peak_pu",
            "envelope_violation_max_pu",
            "recovery_violation_max_pu",
            "fault_lv_band_violation_max_pu",
            "voltage_survival_reason",
        ):
            out[f"{prefix}_{key}"] = row.get(key, "")
    return out


def write_rows(path: Path, rows: list[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--families", default="all", help="Comma-separated labels or all.")
    parser.add_argument("--duration-ms", type=int, default=60)
    parser.add_argument("--bc-epochs", type=int, default=180)
    parser.add_argument("--sac-steps", type=int, default=40)
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    selected = FAMILIES
    if args.families.strip().lower() != "all":
        wanted = {x.strip() for x in args.families.split(",") if x.strip()}
        selected = [family for family in FAMILIES if family.label in wanted]
        missing = sorted(wanted - {family.label for family in selected})
        if missing:
            raise ValueError(f"Unknown family labels: {missing}")

    run_id = args.run_id or f"hpt_dcsafe_12family_center_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "hpt-dcsafe-12-family-center-smoke-v1",
        "run_id": run_id,
        "families": [
            {**asdict(family), "label": family.label}
            for family in selected
        ],
        "duration_ms": args.duration_ms,
        "bc_epochs": args.bc_epochs,
        "sac_steps": args.sac_steps,
        "profile": "dc_safe_topology2_balanced_lvrt_debug_profile",
    }
    (run_dir / "campaign_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    rows: list[dict] = []
    for family in selected:
        child_run_id = f"{run_id}_{family.label}"
        case_pair = f"{family.center_pu:.3f}:{int(args.duration_ms)}"
        cmd = [
            sys.executable,
            "-m",
            "version_2.sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary",
            "--run-id",
            child_run_id,
            "--topology",
            family.topology,
            "--category",
            family.category,
            "--phase-key",
            family.phase_key,
            "--case-pairs",
            case_pair,
            "--bc-epochs",
            str(args.bc_epochs),
            "--sac-steps",
            str(args.sac_steps),
            "--fault-start-s",
            "0.08",
            "--anchor-min-time-s",
            "0.02",
            "--actor-filter-tau",
            "0.001",
            "--sac-learning-rate",
            "5e-9",
            "--sac-support-weight",
            "80000",
            "--sac-vdc-bounds-weight",
            "120000",
            "--sac-vdc-margin-weight",
            "180000",
            "--sac-vdc-margin-pu",
            "0.06",
            "--sac-proxy-vdc-downshift-pu",
            "0.04",
            "--sac-behavior-anchor-interval-steps",
            "20",
        ]
        child_dir = RESULTS / child_run_id
        row = {
            "family": family.label,
            "topology": family.topology,
            "category": family.category,
            "phase_key": family.phase_key,
            "child_run_id": child_run_id,
            "case_pair": case_pair,
            "command": " ".join(cmd),
        }
        rc = run_logged(cmd, run_dir / f"{family.label}.log")
        row["returncode"] = rc
        if rc != 0 and not args.continue_on_error:
            rows.append(row)
            write_rows(run_dir / "family_center_summary.csv", rows)
            raise RuntimeError(f"Family {family.label} failed with return code {rc}")
        row.update(summarize_campaign(child_dir, family))
        rows.append(row)
        write_rows(run_dir / "family_center_summary.csv", rows)

    write_rows(run_dir / "family_center_summary.csv", rows)
    manifest_path = EXPERIMENTS / f"{run_id}_manifest.csv"
    write_rows(manifest_path, rows)
    (run_dir / "family_center_summary.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"run_dir": str(run_dir), "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
