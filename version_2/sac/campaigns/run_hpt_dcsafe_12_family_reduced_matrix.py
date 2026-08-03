"""Run reduced depth-duration matrices for the 12 HPT fault families.

This is the next step after the 12-family center smoke.  Each family receives
the same DC-safe dq-seeded SAC pipeline and is evaluated on a small
depth-duration matrix, so we can compare strong dq, the dq-seeded initial
actor, and SAC after fine-tuning under the switch-level voltage-survival gate.
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


FAMILIES = [
    Family(topology, category, phase)
    for topology in ("topology1", "topology2")
    for category in ("LVRT", "HVRT")
    for phase in ("abc", "a", "ab")
]


def parse_float_list(text: str) -> list[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_int_list(text: str) -> list[int]:
    return [int(float(x.strip())) for x in text.split(",") if x.strip()]


def yes(value: object) -> bool:
    return str(value).strip() in {"1", "true", "True"}


def as_float(value: object, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


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


def summarize_child(run_dir: Path, family: Family) -> dict:
    path = run_dir / "boundary_comparison_rows.csv"
    out = {
        "family": family.label,
        "topology": family.topology,
        "category": family.category,
        "phase_key": family.phase_key,
        "run_dir": str(run_dir),
        "csv": str(path),
        "status": "missing_csv",
    }
    if not path.exists():
        return out
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    by_label: dict[str, dict[str, dict]] = {}
    for row in rows:
        label = row.get("boundary_label", "")
        controller = row.get("controller", "")
        if not label or not controller:
            continue
        # Some diagnostic campaigns append rows when a validation is re-run.
        # Keep the last row for each controller/case, which is the freshest
        # switch-level result in the child campaign CSV.
        by_label.setdefault(label, {})[controller] = row
    labels = sorted(by_label)
    out["status"] = "ok"
    out["n_cases"] = len(labels)
    for controller, prefix in (
        ("strong_dq", "dq"),
        ("dq_seeded_actor_before_sac", "seed"),
        ("dq_seeded_actor_after_sac", "sac"),
    ):
        crows = [
            controllers[controller]
            for controllers in by_label.values()
            if controller in controllers
        ]
        out[f"{prefix}_pass_count"] = sum(yes(row.get("voltage_survival_pass")) for row in crows)
        scores = [as_float(row.get("control_score")) for row in crows]
        scores = [score for score in scores if score == score]
        out[f"{prefix}_score_mean"] = sum(scores) / len(scores) if scores else ""
    sac_pass_dq_fail = 0
    sac_score_beats_dq = 0
    sac_score_beats_seed = 0
    for controllers in by_label.values():
        dq = controllers.get("strong_dq", {})
        seed = controllers.get("dq_seeded_actor_before_sac", {})
        sac = controllers.get("dq_seeded_actor_after_sac", {})
        if yes(sac.get("voltage_survival_pass")) and not yes(dq.get("voltage_survival_pass")):
            sac_pass_dq_fail += 1
        if as_float(sac.get("control_score"), 1e99) < as_float(dq.get("control_score"), 1e99):
            sac_score_beats_dq += 1
        if as_float(sac.get("control_score"), 1e99) < as_float(seed.get("control_score"), 1e99):
            sac_score_beats_seed += 1
    out["sac_pass_dq_fail_count"] = sac_pass_dq_fail
    out["sac_score_beats_dq_count"] = sac_score_beats_dq
    out["sac_score_beats_seed_count"] = sac_score_beats_seed
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--families", default="all", help="Comma-separated labels or all.")
    parser.add_argument("--lvrt-depths", default="0.875,0.90")
    parser.add_argument("--hvrt-depths", default="1.10,1.15")
    parser.add_argument("--durations-ms", default="60,100")
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

    lvrt_depths = parse_float_list(args.lvrt_depths)
    hvrt_depths = parse_float_list(args.hvrt_depths)
    durations_ms = parse_int_list(args.durations_ms)
    run_id = args.run_id or f"hpt_dcsafe_12family_matrix_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "hpt-dcsafe-12-family-reduced-matrix-v1",
        "run_id": run_id,
        "families": [{**asdict(family), "label": family.label} for family in selected],
        "lvrt_depths": lvrt_depths,
        "hvrt_depths": hvrt_depths,
        "durations_ms": durations_ms,
        "bc_epochs": args.bc_epochs,
        "sac_steps": args.sac_steps,
        "profile": "dc_safe_dq_seeded_sac",
    }
    (run_dir / "campaign_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    rows: list[dict] = []
    for family in selected:
        child_run_id = f"{run_id}_{family.label}"
        depths = hvrt_depths if family.category == "HVRT" else lvrt_depths
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
            "--depths",
            ",".join(f"{depth:.6g}" for depth in depths),
            "--durations-ms",
            ",".join(str(duration) for duration in durations_ms),
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
            "depths": ",".join(f"{depth:.6g}" for depth in depths),
            "durations_ms": ",".join(str(duration) for duration in durations_ms),
            "command": " ".join(cmd),
        }
        rc = run_logged(cmd, run_dir / f"{family.label}.log")
        row["returncode"] = rc
        if rc != 0 and not args.continue_on_error:
            rows.append(row)
            write_rows(run_dir / "family_matrix_summary.csv", rows)
            raise RuntimeError(f"Family {family.label} failed with return code {rc}")
        row.update(summarize_child(child_dir, family))
        rows.append(row)
        write_rows(run_dir / "family_matrix_summary.csv", rows)

    write_rows(run_dir / "family_matrix_summary.csv", rows)
    manifest_path = EXPERIMENTS / f"{run_id}_manifest.csv"
    write_rows(manifest_path, rows)
    (run_dir / "family_matrix_summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
