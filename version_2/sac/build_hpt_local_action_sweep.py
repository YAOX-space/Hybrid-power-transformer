"""Build fixed-action candidate CSVs for local switch-level sweeps.

The output schema intentionally mirrors ``train_hpt_offline_full_action_baselines``
case_results.csv enough for ``validate_hpt_offline_actions_switchlevel`` to run
the candidates in Simulink fixed-action mode.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from .experiment_metadata import write_experiment_metadata


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"


def parse_grid(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Grid must contain at least one value")
    return values


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2")
    parser.add_argument("--category", default="LVRT")
    parser.add_argument("--case-name", default="lvrt_080ms_0p950pu")
    parser.add_argument("--fault-pu", type=float, default=0.95)
    parser.add_argument("--duration-ms", type=int, default=80)
    parser.add_argument("--reg-d-grid", type=parse_grid, default=parse_grid("0.145,0.172,0.200"))
    parser.add_argument("--energy-d-grid", type=parse_grid, default=parse_grid("0.017,0.022,0.027"))
    parser.add_argument("--reg-q", type=float, default=0.0)
    parser.add_argument("--energy-q", type=float, default=0.002)
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_local_action_sweep_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = RESULTS / run_id
    rows: list[dict[str, object]] = []
    for reg_d in args.reg_d_grid:
        for energy_d in args.energy_d_grid:
            token = f"r{reg_d:.3f}_e{energy_d:.3f}".replace(".", "p").replace("-", "m")
            rows.append(
                {
                    "algorithm": f"local_sweep/{token}",
                    "topology": args.topology,
                    "category": args.category,
                    "duration_ms": args.duration_ms,
                    "case_name": args.case_name,
                    "fault_pu": args.fault_pu,
                    "baseline_pass": True,
                    "baseline_score": "",
                    "baseline_reason": "",
                    "policy_pass": True,
                    "policy_score": "",
                    "policy_reason": "",
                    "beat": True,
                    "improved": True,
                    "action_m_reg_d": reg_d,
                    "action_m_reg_q": args.reg_q,
                    "action_m_energy_d": energy_d,
                    "action_m_energy_q": args.energy_q,
                    "action_max_abs": max(abs(reg_d), abs(args.reg_q), abs(energy_d), abs(args.energy_q)),
                }
            )

    csv_path = run_dir / "case_results.csv"
    write_csv(csv_path, rows)
    summary = {
        "schema": "hpt-local-action-sweep-v1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "case_results_csv": str(csv_path),
        "candidate_count": len(rows),
        "config": {
            "topology": args.topology,
            "category": args.category,
            "case_name": args.case_name,
            "fault_pu": args.fault_pu,
            "duration_ms": args.duration_ms,
            "reg_d_grid": args.reg_d_grid,
            "energy_d_grid": args.energy_d_grid,
            "reg_q": args.reg_q,
            "energy_q": args.energy_q,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_local_action_sweep",
        config=summary["config"],
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
