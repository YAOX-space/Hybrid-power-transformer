"""Generate a fixed scenario table for fair HPT v2 controller comparison."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
S_RATED = 400e3

SCENARIOS = [
    (0, 'normal'),
    (3, 'igbt_oc_sh'),
    (4, 'igbt_oc_se'),
    (5, 'cap_fault'),
    (6, 'sc_1ph'),
    (7, 'sc_3ph'),
    (8, 'cascade'),
]


def choose_fault_variant(rng: np.random.Generator, sc_id: int) -> int:
    if sc_id in (3, 8):
        return int(rng.integers(1, 7))
    if sc_id == 4:
        return int(rng.integers(1, 5))
    if sc_id == 6:
        return int(rng.integers(1, 4))
    return 1


def choose_fault_magnitude(rng: np.random.Generator, sc_id: int) -> float:
    if sc_id in (3, 4):
        return float(rng.uniform(0.75, 1.0))
    if sc_id == 8:
        return float(rng.uniform(0.90, 1.0))
    if sc_id == 5:
        return 1.0
    return float(rng.uniform(0.80, 1.0))


def fault_resistance(rng: np.random.Generator, sc_id: int) -> tuple[float, float]:
    if sc_id == 6:
        r = float(rng.uniform(0.25, 0.50))
        return r, r
    if sc_id == 7:
        r = float(rng.uniform(0.18, 0.38))
        return r, r
    return 0.01, 0.01


def build_rows(runs_per_scenario: int, seed: int):
    rng = np.random.default_rng(seed)
    rows = []
    scenario_id = 0
    for sc_id, label in SCENARIOS:
        for run_idx in range(1, runs_per_scenario + 1):
            scenario_id += 1
            p_load = float(S_RATED * rng.uniform(0.70, 0.90))
            pf = float(rng.uniform(0.85, 0.95))
            q_load = float(p_load * np.tan(np.arccos(pf)))
            t_fault = float(rng.uniform(0.012, 0.030))
            r_fault, r_ground = fault_resistance(rng, sc_id)
            rows.append({
                'scenario_id': scenario_id,
                'sc_id': sc_id,
                'sc_label': label,
                'run_idx': run_idx,
                'T_sim': 0.05,
                'P_load': round(p_load, 6),
                'Q_load': round(q_load, 6),
                'power_factor': round(pf, 6),
                't_fault': round(t_fault, 8),
                'fault_variant': choose_fault_variant(rng, sc_id),
                'fault_mag': round(choose_fault_magnitude(rng, sc_id), 6),
                'fault_resistance': round(r_fault, 6),
                'ground_resistance': round(r_ground, 6),
                'random_seed': seed,
            })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs-per-scenario', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20260525)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rows = build_rows(args.runs_per_scenario, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f'Wrote {len(rows)} fixed HPT v2 scenarios to {args.out}')


if __name__ == '__main__':
    main()
