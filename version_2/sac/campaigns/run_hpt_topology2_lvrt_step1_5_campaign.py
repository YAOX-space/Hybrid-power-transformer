"""Run the topology2/LVRT Step 1-5 local-sweep research campaign.

Stages:
1. Dense local sweep around the known successful 80-ms, 0.95-pu island.
2. Small fault-depth and duration sweeps around the same island.
3. Convert switch-level results into calibration rows and recalibrate the proxy.
4. Train topology2/LVRT specialist baselines, including success-weighted BC.
5. Validate proxy-beating specialist actions in switch-level Simulink.

This script is intentionally resumable.  It skips a stage if the expected output
already exists, and writes a status JSON after each stage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
MATRIX_DIR = RESULTS / "hpt_v2_frt_calibration_matrix"
DATA_ROOT = ROOT / "version_2" / "data" / "hpt_boundary_full_action"


BASE_MATRICES = [
    MATRIX_DIR / "frt_calibration_matrix_full_all_20260718_002228.csv",
    MATRIX_DIR / "frt_calibration_matrix_holdout_all_20260718_003007.csv",
    MATRIX_DIR / "frt_calibration_matrix_edgeholdout_all_20260718_003737.csv",
    MATRIX_DIR / "frt_calibration_matrix_switchval_edgecalib_awac_failures_20260718_0128.csv",
    MATRIX_DIR / "frt_calibration_matrix_switchval_failureguard_topology2_lvrt_20260718_0150.csv",
    MATRIX_DIR / "frt_calibration_matrix_switchval_counterexamples_topology2_lvrt_20260718_0156.csv",
    MATRIX_DIR / "frt_calibration_matrix_switchval_counterexamples2_topology2_lvrt_20260718_0205.csv",
    MATRIX_DIR / "frt_calibration_matrix_local_sweep_topology2_lvrt80_095_20260718_0210.csv",
    MATRIX_DIR / "frt_calibration_matrix_success_bc_topology2_lvrt80_095_20260718_0210.csv",
]


@dataclass(frozen=True)
class SweepSpec:
    name: str
    fault_pu: float
    duration_ms: int
    reg_d_grid: str
    energy_d_grid: str
    energy_q: float = 0.002

    @property
    def case_name(self) -> str:
        pu_token = f"{self.fault_pu:.3f}".replace(".", "p")
        return f"lvrt_{self.duration_ms:03d}ms_{pu_token}pu"


def run(cmd: list[str], *, cwd: Path = ROOT, timeout: int | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed with {proc.returncode}: {' '.join(cmd)}")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def matrix_from_augment_run(run_id: str) -> Path:
    return MATRIX_DIR / f"frt_calibration_matrix_{run_id}.csv"


def build_sweep(spec: SweepSpec, campaign_id: str) -> tuple[Path, Path]:
    run_id = f"{campaign_id}_{spec.name}"
    run_dir = RESULTS / run_id
    case_csv = run_dir / "case_results.csv"
    if not case_csv.exists():
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.datasets.build_hpt_local_action_sweep",
                "--run-id",
                run_id,
                "--fault-pu",
                f"{spec.fault_pu:.12g}",
                "--duration-ms",
                str(spec.duration_ms),
                "--case-name",
                spec.case_name,
                "--reg-d-grid",
                spec.reg_d_grid,
                "--energy-d-grid",
                spec.energy_d_grid,
                "--energy-q",
                f"{spec.energy_q:.12g}",
            ],
            timeout=60,
        )
    return run_dir, case_csv


def validate_sweep(spec: SweepSpec, campaign_id: str, case_csv: Path) -> Path:
    run_id = f"{campaign_id}_{spec.name}_switchval"
    run_dir = RESULTS / run_id
    result_csv = run_dir / "switch_validation_results.csv"
    if not result_csv.exists():
        summary = read_json(case_csv.parent / "summary.json")
        max_cases = str(int(summary["candidate_count"]))
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.offline.validate_hpt_offline_actions_switchlevel",
                "--case-results-csv",
                str(case_csv),
                "--run-id",
                run_id,
                "--topology",
                "topology2",
                "--category",
                "LVRT",
                "--only-proxy-beats",
                "--algorithm-contains",
                "local_sweep",
                "--max-cases",
                max_cases,
            ],
            timeout=60 * 60 * 6,
        )
    return result_csv


def augment_switch_results(spec: SweepSpec, campaign_id: str, switch_csv: Path) -> Path:
    augment_id = f"{campaign_id}_{spec.name}"
    matrix_csv = matrix_from_augment_run(augment_id)
    if not matrix_csv.exists():
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.calibration.augment_hpt_matrix_from_switch_validation",
                "--switch-validation-csv",
                str(switch_csv),
                "--run-id",
                augment_id,
            ],
            timeout=120,
        )
    return matrix_csv


def calibrate_and_check(campaign_id: str, matrices: list[Path]) -> None:
    run(
        [
            sys.executable,
            "-m",
            "version_2.sac.calibration.calibrate_hpt_frt_proxy_from_matrix",
            "--matrix-csv",
            *[str(p) for p in matrices],
        ],
        timeout=120,
    )
    for matrix in matrices:
        if campaign_id not in matrix.name:
            continue
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.calibration.measure_hpt_frt_proxy_gap",
                "--matrix-csv",
                str(matrix),
            ],
            timeout=120,
        )
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.calibration.measure_hpt_reward_alignment",
                "--matrix-csv",
                str(matrix),
            ],
            timeout=120,
        )


def build_dataset(campaign_id: str, matrices: list[Path]) -> Path:
    run_id = f"{campaign_id}_dataset"
    dataset_csv = DATA_ROOT / run_id / "dataset.csv"
    if not dataset_csv.exists():
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.datasets.build_hpt_boundary_full_action_dataset",
                "--matrix-csv",
                *[str(p) for p in matrices],
                "--run-id",
                run_id,
                "--selection",
                "near_boundary",
                "--candidate-selection",
                "all",
            ],
            timeout=120,
        )
    return dataset_csv


def train_specialist(campaign_id: str, dataset_csv: Path) -> Path:
    run_id = f"{campaign_id}_success_bc_topo2_lvrt"
    run_dir = RESULTS / run_id
    case_csv = run_dir / "case_results.csv"
    if not case_csv.exists():
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.offline.train_hpt_offline_full_action_baselines",
                "--dataset-csv",
                str(dataset_csv),
                "--run-id",
                run_id,
                "--topology",
                "topology2",
                "--category",
                "LVRT",
                "--duration-ms",
                "all",
                "--max-cases",
                "0",
                "--group-specialists",
                "--algorithms",
                "success_bc_style",
                "--epochs",
                "900",
                "--batch-size",
                "32",
                "--hidden",
                "128",
                "--lr",
                "8e-4",
                "--reg-d-limit",
                "0.8",
                "--reg-q-limit",
                "0.4",
                "--energy-d-limit",
                "0.4",
                "--energy-q-limit",
                "0.2",
            ],
            timeout=60 * 20,
        )
    return case_csv


def validate_specialist(campaign_id: str, case_csv: Path) -> Path:
    run_id = f"{campaign_id}_success_bc_switchval"
    run_dir = RESULTS / run_id
    result_csv = run_dir / "switch_validation_results.csv"
    if not result_csv.exists():
        run(
            [
                sys.executable,
                "-m",
                "version_2.sac.offline.validate_hpt_offline_actions_switchlevel",
                "--case-results-csv",
                str(case_csv),
                "--run-id",
                run_id,
                "--topology",
                "topology2",
                "--category",
                "LVRT",
                "--only-proxy-beats",
                "--algorithm-contains",
                "success_bc_style",
                "--max-cases",
                "24",
            ],
            timeout=60 * 60 * 4,
        )
    return result_csv


def summarize_switch_csv(path: Path) -> dict:
    import csv

    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            rows = [dict(row) for row in csv.DictReader(f)]
    def truth(value: str) -> bool:
        return str(value).strip().lower() in {"1", "1.0", "true", "yes"}
    return {
        "csv": str(path),
        "rows": len(rows),
        "fixed_pass": sum(truth(r.get("switch_fixed_voltage_survival_pass", "")) for r in rows),
        "switch_beat": sum(truth(r.get("switch_beat", "")) for r in rows),
        "baseline_pass": sum(truth(r.get("switch_baseline_voltage_survival_pass", "")) for r in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", default=f"hpt_topo2_lvrt_step1_5_{time.strftime('%Y%m%d_%H%M')}")
    args = parser.parse_args()
    campaign_id = args.campaign_id
    campaign_dir = RESULTS / campaign_id
    status_path = campaign_dir / "status.json"
    campaign_dir.mkdir(parents=True, exist_ok=True)

    dense_grid = SweepSpec(
        name="step1_dense_80ms_095pu",
        fault_pu=0.95,
        duration_ms=80,
        reg_d_grid="0.156,0.164,0.168,0.172,0.176,0.184,0.192",
        energy_d_grid="0.014,0.018,0.022,0.026,0.030",
    )
    small_reg = "0.164,0.172,0.184"
    small_energy = "0.018,0.022,0.026"
    depth_sweeps = [
        SweepSpec(f"step2_depth_80ms_{str(pu).replace('.', 'p')}pu", pu, 80, small_reg, small_energy)
        for pu in [0.92, 0.98, 0.995]
    ]
    duration_sweeps = [
        SweepSpec(f"step2_duration_{dur}ms_095pu", 0.95, dur, small_reg, small_energy)
        for dur in [40, 120, 200]
    ]
    sweeps = [dense_grid, *depth_sweeps, *duration_sweeps]

    augmented: list[Path] = []
    switch_summaries: list[dict] = []
    write_json(
        status_path,
        {
            "campaign_id": campaign_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "stage": "switch_sweeps",
            "sweeps": [asdict(spec) for spec in sweeps],
        },
    )
    for spec in sweeps:
        _, case_csv = build_sweep(spec, campaign_id)
        switch_csv = validate_sweep(spec, campaign_id, case_csv)
        augmented.append(augment_switch_results(spec, campaign_id, switch_csv))
        switch_summaries.append(summarize_switch_csv(switch_csv))
        write_json(
            status_path,
            {
                "campaign_id": campaign_id,
                "stage": "switch_sweeps",
                "completed_sweeps": len(switch_summaries),
                "total_sweeps": len(sweeps),
                "switch_summaries": switch_summaries,
                "augmented_matrices": [str(p) for p in augmented],
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

    matrices = [p for p in BASE_MATRICES if p.exists()] + augmented
    calibrate_and_check(campaign_id, matrices)
    write_json(
        status_path,
        {
            "campaign_id": campaign_id,
            "stage": "proxy_calibrated",
            "switch_summaries": switch_summaries,
            "matrices": [str(p) for p in matrices],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    dataset_csv = build_dataset(campaign_id, matrices)
    case_csv = train_specialist(campaign_id, dataset_csv)
    final_switch_csv = validate_specialist(campaign_id, case_csv)
    final_summary = summarize_switch_csv(final_switch_csv)
    write_json(
        status_path,
        {
            "campaign_id": campaign_id,
            "stage": "complete",
            "switch_summaries": switch_summaries,
            "dataset_csv": str(dataset_csv),
            "specialist_case_csv": str(case_csv),
            "final_switch_summary": final_summary,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    print(json.dumps(read_json(status_path), indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


