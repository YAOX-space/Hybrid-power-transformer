"""Generate the HPT voltage-survival boundary scenario manifest.

The manifest is the source of truth for the 630-case switch-level boundary
matrix requested on 2026-07-25.  It also maps each scenario to the nearest
currently accepted Stage-2 specialist actor for the first SAC boundary scan.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from version_2.sac.experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACCEPTED = (
    ROOT
    / "version_2"
    / "sac"
    / "experiments"
    / "accepted_specialists_20260722_stage2_voltage_survival.csv"
)
DEFAULT_OUT = (
    ROOT
    / "version_2"
    / "sac"
    / "experiments"
    / "voltage_survival_boundary_manifest_20260725.csv"
)
DEFAULT_RUN_DIR = ROOT / "lab" / "results" / "hpt_voltage_survival_boundary_manifest_20260725"


LVRT_DEPTHS = [0.75, 0.80, 0.85, 0.90, 0.95]
HVRT_DEPTHS = [1.05, 1.10, 1.15, 1.20]
DURATIONS_S = [0.040, 0.060, 0.080, 0.120, 0.200]
TOPOLOGIES = ["topology1", "topology2"]
PHASE_MODES: dict[str, tuple[int, int, int] | None] = {
    "balanced": None,
    "a": (1, 0, 0),
    "b": (0, 1, 0),
    "c": (0, 0, 1),
    "ab": (1, 1, 0),
    "bc": (0, 1, 1),
    "ca": (1, 0, 1),
}


@dataclass(frozen=True)
class AcceptedActor:
    case_id: str
    topology: str
    fault_family: str
    phase_key: str
    fault_pu: float
    duration_s: float
    fault_start_s: float
    fault_stop_margin_s: float
    fault_settle_s: float
    chopper_threshold: float
    rchop_scale: float
    actor_filter_tau: float
    phase_override: bool
    model_path: str


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


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def parse_float(value: str, default: float = float("nan")) -> float:
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def parse_accepted(path: Path) -> list[AcceptedActor]:
    actors: list[AcceptedActor] = []
    for row in read_csv(path):
        actors.append(
            AcceptedActor(
                case_id=row["case_id"],
                topology=row["topology"],
                fault_family=row["fault_family"].upper(),
                phase_key=(row.get("fault_phase_key", "") or "").strip().lower(),
                fault_pu=parse_float(row["fault_pu"]),
                duration_s=parse_float(row["duration_s"]),
                fault_start_s=parse_float(row.get("fault_start_s", ""), 0.080),
                fault_stop_margin_s=parse_float(row.get("fault_stop_margin_s", ""), 0.125),
                fault_settle_s=parse_float(row.get("fault_settle_s", ""), 0.020),
                chopper_threshold=parse_float(row.get("chopper_threshold", ""), 850.0),
                rchop_scale=parse_float(row.get("rchop_scale", ""), 1.0),
                actor_filter_tau=parse_float(row.get("actor_filter_tau", ""), 0.001),
                phase_override=parse_bool(row.get("phase_override", ""), False),
                model_path=row["model_path"],
            )
        )
    return actors


def pu_token(value: float) -> str:
    return f"{value:.3f}".replace(".", "p")


def duration_token(duration_s: float) -> str:
    return f"{int(round(1000.0 * duration_s)):03d}ms"


def phase_vector(mode: str, pu: float) -> str:
    mask = PHASE_MODES[mode]
    if mask is None:
        return ""
    values = [pu if enabled else 1.0 for enabled in mask]
    return "[" + " ".join(f"{value:.3f}" for value in values) + "]"


def phase_rank(mode: str) -> str:
    if mode == "balanced":
        return "balanced"
    return "single" if len(mode) == 1 else "double"


def select_actor(
    actors: list[AcceptedActor],
    *,
    topology: str,
    fault_family: str,
    phase_mode: str,
    fault_pu: float,
    duration_s: float,
) -> tuple[AcceptedActor, str, bool]:
    """Return nearest accepted actor, mapping note, and exactness flag."""

    same = [a for a in actors if a.topology == topology and a.fault_family == fault_family]
    if not same:
        raise ValueError(f"No accepted actor for {topology} {fault_family}")

    exact_phase_key = "" if phase_mode == "balanced" else phase_mode
    exact = [
        a
        for a in same
        if a.phase_key == exact_phase_key
        and abs(a.fault_pu - fault_pu) < 1e-9
        and abs(a.duration_s - duration_s) < 1e-9
    ]
    if exact:
        return exact[0], "exact_case", True

    if phase_mode == "balanced":
        candidates = [a for a in same if a.phase_key == ""]
        note = "nearest_balanced_same_family"
    elif fault_family == "LVRT":
        wanted = "a" if len(phase_mode) == 1 else "ab"
        candidates = [a for a in same if a.phase_key == wanted]
        note = f"nearest_unbalanced_{wanted}_same_family"
        if not candidates:
            candidates = [a for a in same if a.phase_key == ""]
            note = "fallback_balanced_same_family"
    else:
        candidates = [a for a in same if a.phase_key == ""]
        note = "fallback_balanced_hvrt_no_unbalanced_specialist"

    if not candidates:
        candidates = same
        note = "fallback_any_same_topology_family"

    def distance(actor: AcceptedActor) -> tuple[float, float, float]:
        phase_penalty = 0.0
        if phase_mode != "balanced" and actor.phase_key == "":
            phase_penalty = 10.0
        return (
            phase_penalty,
            abs(actor.fault_pu - fault_pu),
            abs(actor.duration_s - duration_s),
        )

    actor = min(candidates, key=distance)
    return actor, note, False


def generate_rows(accepted: list[AcceptedActor]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for topology in TOPOLOGIES:
        for duration_s in DURATIONS_S:
            for family, depths in (("LVRT", LVRT_DEPTHS), ("HVRT", HVRT_DEPTHS)):
                for pu in depths:
                    for phase_mode in PHASE_MODES:
                        actor, note, exact = select_actor(
                            accepted,
                            topology=topology,
                            fault_family=family,
                            phase_mode=phase_mode,
                            fault_pu=pu,
                            duration_s=duration_s,
                        )
                        is_balanced = phase_mode == "balanced"
                        fault_start = 0.080 if is_balanced else 0.035
                        fault_settle = 0.020
                        case_name = (
                            f"{phase_mode}_{family.lower()}_"
                            f"{duration_token(duration_s)}_{pu_token(pu)}pu"
                        )
                        case_id = f"{topology}_{case_name}"
                        rows.append(
                            {
                                "case_id": case_id,
                                "case_name": case_name,
                                "topology": topology,
                                "fault_family": family,
                                "fault_pu": f"{pu:.3f}",
                                "duration_s": f"{duration_s:.3f}",
                                "duration_ms": int(round(1000.0 * duration_s)),
                                "phase_mode": phase_mode,
                                "phase_rank": phase_rank(phase_mode),
                                "fault_phase_key": "" if is_balanced else phase_mode,
                                "fault_phase_pu": phase_vector(phase_mode, pu),
                                "fault_start_s": f"{fault_start:.3f}",
                                "fault_stop_margin_s": "0.125",
                                "fault_settle_s": f"{fault_settle:.3f}",
                                "chopper_threshold": f"{actor.chopper_threshold:.6g}",
                                "rchop_scale": f"{actor.rchop_scale:.6g}",
                                "actor_filter_tau": f"{actor.actor_filter_tau:.6g}",
                                "phase_override": str(actor.phase_override).lower(),
                                "model_path": actor.model_path,
                                "nearest_actor_case_id": actor.case_id,
                                "nearest_actor_note": note,
                                "nearest_actor_exact": str(exact).lower(),
                                "promotion_scope": "voltage_survival_boundary_probe",
                            }
                        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accepted", type=Path, default=DEFAULT_ACCEPTED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    args = parser.parse_args()

    accepted = parse_accepted(args.accepted)
    rows = generate_rows(accepted)
    write_csv(args.out, rows)
    summary = {
        "schema": "hpt-voltage-survival-boundary-manifest-v1",
        "accepted_manifest": str(args.accepted),
        "manifest": str(args.out),
        "case_count": len(rows),
        "topologies": TOPOLOGIES,
        "lvrt_depths": LVRT_DEPTHS,
        "hvrt_depths": HVRT_DEPTHS,
        "durations_s": DURATIONS_S,
        "phase_modes": list(PHASE_MODES),
        "exact_actor_rows": sum(row["nearest_actor_exact"] == "true" for row in rows),
    }
    args.run_dir.mkdir(parents=True, exist_ok=True)
    (args.run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        args.run_dir,
        experiment_name="hpt_voltage_survival_boundary_manifest",
        config={"accepted": str(args.accepted), "out": str(args.out)},
        dataset_manifest=args.accepted,
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

