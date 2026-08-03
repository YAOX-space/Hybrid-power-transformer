"""Build the final r6 family-boundary paper figures.

The control comparison uses raw 2-ms traces exported from the switch-level
Simulink collector.  Boundary and training-diagnostic panels are rebuilt from
the final r6 CSV evidence so controller labels and episode lengths are handled
explicitly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "paper" / "figures"
TRACE_OUT = OUT / "simulink_control_traces"
TRACE_ROOT = ROOT / "lab" / "results" / "hpt_v2_trajectory_traces"

BOUNDARY_CELLS = (
    ROOT
    / "lab"
    / "results"
    / "hpt_family_specialist_t2_a_lvrt_joint_support_sac_r6_probe9_20260803"
    / "boundary_summary"
    / "t2_a_lvrt_joint_support_sac_r6_probe9_combined_cells.csv"
)
EVALUATOR_ROWS = (
    ROOT
    / "lab"
    / "results"
    / "hpt_family_specialist_t2_a_lvrt_joint_support_sac_r6_probe9_20260803"
    / "family_specialist_comparison_rows.csv"
)
TRAINING_DIR = (
    ROOT
    / "lab"
    / "results"
    / "hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803"
)
REWARD_TRACE = TRAINING_DIR / "sac_training_reward_trace.csv"
DIAGNOSTICS_TRACE = TRAINING_DIR / "sac_training_diagnostics_trace.csv"

FAULT_START = 0.080
FAULT_CLEAR = 0.280


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def latest_trace(token: str) -> Path:
    matches = sorted(
        TRACE_ROOT.glob(f"trajectory_trace_topology2_{token}_*.csv"),
        key=lambda path: path.stat().st_mtime,
    )
    if not matches:
        raise FileNotFoundError(f"No switch-level trace found for {token}")
    return matches[-1]


def save_figure(fig: plt.Figure, stem: str) -> tuple[Path, Path]:
    png = OUT / f"{stem}.png"
    pdf = OUT / f"{stem}.pdf"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    return png, pdf


def numeric(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def plot_boundary_matrix() -> tuple[Path, Path, dict[str, int]]:
    cells = pd.read_csv(BOUNDARY_CELLS)
    controller_order = [
        "strong_dq",
        "family_seed_before_sac",
        "family_sac_after_finetune",
    ]
    display_names = {
        "strong_dq": "strong dq",
        "family_seed_before_sac": "SAC r5 checkpoint\n(before corrected continuation)",
        "family_sac_after_finetune": "family SAC r6\n(final)",
    }
    depths = sorted(pd.to_numeric(cells["depth_pu"], errors="raise").unique())
    durations = sorted(pd.to_numeric(cells["duration_ms"], errors="raise").unique())
    cmap = ListedColormap(["#d95f5f", "#66b266"])
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.7), sharey=True)
    pass_counts: dict[str, int] = {}
    for ax, controller in zip(axes, controller_order):
        subset = cells[cells["controller_label"] == controller].copy()
        lookup = {
            (float(row.depth_pu), int(row.duration_ms)): int(row.pass_int)
            for row in subset.itertuples()
        }
        matrix = np.array(
            [[lookup[(float(depth), int(duration))] for duration in durations] for depth in depths],
            dtype=int,
        )
        pass_counts[controller] = int(matrix.sum())
        ax.imshow(matrix, origin="lower", aspect="auto", vmin=0, vmax=1, cmap=cmap)
        ax.set_xticks(range(len(durations)), labels=[str(int(value)) for value in durations])
        ax.set_yticks(range(len(depths)), labels=[f"{value:.3f}" for value in depths])
        ax.set_xlabel("Fault duration (ms)")
        ax.set_title(f"{display_names[controller]}\npass {matrix.sum()}/{matrix.size}")
        ax.set_xticks(np.arange(-0.5, len(durations), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(depths), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=1.6)
        ax.tick_params(which="minor", bottom=False, left=False)
        for row_index in range(matrix.shape[0]):
            for col_index in range(matrix.shape[1]):
                ax.text(
                    col_index,
                    row_index,
                    "P" if matrix[row_index, col_index] else "F",
                    ha="center",
                    va="center",
                    color="black",
                    fontsize=10,
                )
    axes[0].set_ylabel("A-phase retained voltage (pu)")
    fig.suptitle(
        "Switch-level topology2 A-phase deep-LVRT pass matrix\n"
        "One checkpoint per SAC column; no per-cell actor selection",
        fontsize=13,
        weight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    png, pdf = save_figure(fig, "fig11_t2_a_deep_lvrt_family_boundary_r6")
    return png, pdf, pass_counts


def plot_training_diagnostics() -> tuple[Path, Path, dict[str, float]]:
    rewards = pd.read_csv(REWARD_TRACE)
    diagnostics = pd.read_csv(DIAGNOSTICS_TRACE)
    full = rewards[rewards["condition"] != "partial_chunk"].copy()
    full = full.sort_values(["timesteps", "env_index"]).reset_index(drop=True)
    full["return_per_step"] = full["episode_return"] / full["episode_length"]
    full["rolling_return_per_step"] = full["return_per_step"].rolling(5, min_periods=2).mean()

    diag = diagnostics.dropna(subset=["support_actor_loss"]).copy()
    diag["support_roll"] = diag["support_actor_loss"].rolling(100, min_periods=20).mean()
    diag["replay_support_roll"] = diag["replay_support_actor_loss"].rolling(100, min_periods=20).mean()
    relative_steps = numeric(diag, "timesteps") - float(diag["timesteps"].min())

    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.3))
    episode_index = np.arange(1, len(full) + 1)
    axes[0].scatter(
        episode_index,
        full["return_per_step"],
        s=18,
        color="0.65",
        alpha=0.8,
        label="complete episode",
    )
    axes[0].plot(
        episode_index,
        full["rolling_return_per_step"],
        color="#0072b2",
        lw=2.0,
        label="5-episode mean",
    )
    axes[0].set_xlabel("Completed episode")
    axes[0].set_ylabel("Return per control step\n(higher is better)")
    axes[0].set_title("Proxy return (length normalized)")
    axes[0].legend(frameon=False)

    axes[1].plot(relative_steps, diag["support_roll"], color="#009e73", lw=1.8, label="anchor support")
    axes[1].plot(
        relative_steps,
        diag["replay_support_roll"],
        color="#cc79a7",
        lw=1.5,
        label="replay-nearest support",
    )
    axes[1].set_xlabel("Additional SAC environment steps")
    axes[1].set_ylabel("100-update mean MSE")
    axes[1].set_title("Behavior-support constraint")
    axes[1].legend(frameon=False)

    labels = ["strong dq", "SAC r5", "SAC r6"]
    counts = [4, 4, 8]
    bars = axes[2].bar(labels, counts, color=["#d55e00", "#8c8c8c", "#0072b2"])
    axes[2].axhline(9, color="0.35", lw=0.9, ls=":")
    axes[2].set_ylim(0, 9.6)
    axes[2].set_ylabel("Switch-level pass count (of 9)")
    axes[2].set_title("Final promotion gate")
    for bar, count in zip(bars, counts):
        axes[2].text(bar.get_x() + bar.get_width() / 2, count + 0.18, f"{count}/9", ha="center")

    for ax in axes:
        ax.grid(True, alpha=0.22)
    fig.suptitle(
        "SAC r6 continuation diagnostics and switch-level promotion",
        fontsize=13,
        weight="bold",
    )
    fig.text(
        0.5,
        0.005,
        "Partial end-of-run episodes are excluded. Proxy return is non-monotonic; final acceptance is determined by the switch-level gate.",
        ha="center",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.93))
    png, pdf = save_figure(fig, "fig12_t2_a_deep_lvrt_family_sac_convergence_r6")
    metrics = {
        "complete_episodes": int(len(full)),
        "partial_episodes_excluded": int(len(rewards) - len(full)),
        "support_loss_first_100_mean": float(diag["support_actor_loss"].head(100).mean()),
        "support_loss_last_100_mean": float(diag["support_actor_loss"].tail(100).mean()),
        "return_per_step_first_8_mean": float(full["return_per_step"].head(8).mean()),
        "return_per_step_last_8_mean": float(full["return_per_step"].tail(8).mean()),
    }
    return png, pdf, metrics


def plot_control_trace(dq_path: Path, sac_path: Path) -> tuple[Path, Path, dict[str, float]]:
    dq = pd.read_csv(dq_path)
    sac = pd.read_csv(sac_path)
    evaluation = pd.read_csv(EVALUATOR_ROWS)
    case_rows = evaluation[
        np.isclose(pd.to_numeric(evaluation["family_fault_pu"]), 0.50)
        & (pd.to_numeric(evaluation["family_duration_ms"]) == 200)
    ]
    dq_eval = case_rows[case_rows["controller"] == "strong_dq"].iloc[0]
    sac_eval = case_rows[case_rows["controller"] == "family_sac_after_finetune"].iloc[0]
    styles = {
        "dq": {"color": "#d55e00", "ls": "--", "lw": 1.45, "label": "strong dq"},
        "sac": {"color": "#0072b2", "ls": "-", "lw": 1.65, "label": "family SAC r6"},
    }

    fig, axes = plt.subplots(6, 1, figsize=(10.8, 11.4), sharex=True)
    fig.suptitle(
        "Switch-level boundary case: topology2 A-phase LVRT 0.50 pu / 200 ms",
        fontsize=13,
        weight="bold",
    )
    for ax in axes:
        ax.axvspan(FAULT_START, FAULT_CLEAR, color="#fde0dd", alpha=0.42)
        ax.axvline(FAULT_START, color="0.35", lw=0.8, ls=":")
        ax.axvline(FAULT_CLEAR, color="0.35", lw=0.8, ls=":")
        ax.grid(True, alpha=0.23)

    t_dq = numeric(dq, "t")
    t_sac = numeric(sac, "t")
    axes[0].fill_between(
        [FAULT_START, FAULT_CLEAR],
        [176.0, 176.0],
        [238.0, 238.0],
        color="#e8f5e9",
        alpha=0.60,
        label="fault LV band",
    )
    axes[0].fill_between(
        [FAULT_CLEAR, 0.405],
        [180.0, 180.0],
        [235.0, 235.0],
        color="#e3f2fd",
        alpha=0.40,
        label="recovery LV band",
    )
    axes[0].plot(t_dq, numeric(dq, "obs_01") * 207.0, **styles["dq"])
    axes[0].plot(t_sac, numeric(sac, "obs_01") * 207.0, **styles["sac"])
    axes[0].axhline(207.0, color="0.35", lw=0.8, ls=":")
    axes[0].set_ylabel("Controller LV RMS (V)")
    axes[0].legend(loc="lower right", ncol=4, frameon=False, fontsize=8)

    axes[1].axhspan(650.0, 1000.0, color="#fff3cd", alpha=0.55, label="DC-link band")
    axes[1].plot(t_dq, numeric(dq, "vdc_inst"), **styles["dq"])
    axes[1].plot(t_sac, numeric(sac, "vdc_inst"), **styles["sac"])
    axes[1].axhline(650.0, color="#8c6d1f", lw=0.9, ls=":")
    axes[1].set_ylabel("Vdc (V)")
    axes[1].legend(loc="lower left", ncol=3, frameon=False)

    action_labels = [r"$m_{reg,d}$", r"$m_{reg,q}$", r"$m_{energy,d}$", r"$m_{energy,q}$"]
    for index, (ax, label) in enumerate(zip(axes[2:], action_labels), start=1):
        column = f"actor_action_{index:02d}"
        ax.plot(t_dq, numeric(dq, column), **styles["dq"])
        ax.plot(t_sac, numeric(sac, column), **styles["sac"])
        ax.axhline(0.0, color="0.25", lw=0.65)
        ax.set_ylabel(label)
    axes[2].legend(loc="upper right", ncol=2, frameon=False)
    axes[-1].set_xlabel("Time (s)")
    axes[-1].set_xlim(0.04, 0.405)

    dq_vdc_min = float(np.nanmin(numeric(dq, "vdc_inst")))
    sac_vdc_min = float(np.nanmin(numeric(sac, "vdc_inst")))
    dq_eval_vdc_min = float(dq_eval["vdc_min"])
    sac_eval_vdc_min = float(sac_eval["vdc_min"])
    axes[1].text(
        0.99,
        0.05,
        "20-us evaluator Vdc min: "
        f"dq {dq_eval_vdc_min:.1f} V (fail), SAC {sac_eval_vdc_min:.1f} V (pass)",
        transform=axes[1].transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
    )
    fig.text(
        0.5,
        0.008,
        "Raw Simulink switch-level signals sampled every 2 ms; LV metric is the controller-filtered RMS used by the validator.",
        ha="center",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.025, 1, 0.97))
    png = OUT / "fig13_t2_a_deep_lvrt_r6_control_trace.png"
    pdf = OUT / "fig13_t2_a_deep_lvrt_r6_control_trace.pdf"
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    plt.close(fig)
    return png, pdf, {
        "dq_sampled_2ms_vdc_min_v": dq_vdc_min,
        "sac_sampled_2ms_vdc_min_v": sac_vdc_min,
        "dq_evaluator_20us_vdc_min_v": dq_eval_vdc_min,
        "sac_evaluator_20us_vdc_min_v": sac_eval_vdc_min,
        "dq_voltage_survival_pass": int(dq_eval["voltage_survival_pass"]),
        "sac_voltage_survival_pass": int(sac_eval["voltage_survival_pass"]),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    TRACE_OUT.mkdir(parents=True, exist_ok=True)
    dq_trace = latest_trace("r6_boundary_pu0500_d200ms_strong_dq")
    sac_trace = latest_trace("r6_boundary_pu0500_d200ms_family_sac")

    boundary_png, boundary_pdf, boundary_metrics = plot_boundary_matrix()
    convergence_png, convergence_pdf, training_metrics = plot_training_diagnostics()
    trace_png, trace_pdf, metrics = plot_control_trace(dq_trace, sac_trace)

    manifest = {
        "schema": "hpt-t2-a-deep-lvrt-r6-paper-evidence-v1",
        "case": "topology2 A-phase LVRT 0.50 pu / 200 ms",
        "fault_start_s": FAULT_START,
        "fault_clear_s": FAULT_CLEAR,
        "source_files": {
            "boundary_cells": {"path": str(BOUNDARY_CELLS), "sha256": sha256(BOUNDARY_CELLS)},
            "evaluator_rows": {"path": str(EVALUATOR_ROWS), "sha256": sha256(EVALUATOR_ROWS)},
            "reward_trace": {"path": str(REWARD_TRACE), "sha256": sha256(REWARD_TRACE)},
            "diagnostics_trace": {"path": str(DIAGNOSTICS_TRACE), "sha256": sha256(DIAGNOSTICS_TRACE)},
            "strong_dq_trace": {"path": str(dq_trace), "sha256": sha256(dq_trace)},
            "family_sac_r6_trace": {"path": str(sac_trace), "sha256": sha256(sac_trace)},
        },
        "outputs": [
            str(boundary_png), str(boundary_pdf),
            str(convergence_png), str(convergence_pdf),
            str(trace_png), str(trace_pdf),
        ],
        "boundary_metrics": boundary_metrics,
        "training_metrics": training_metrics,
        "trace_metrics": metrics,
        "notes": [
            "Boundary labels identify the actual r5 and r6 SAC checkpoints; r5 is not described as an untrained seed.",
            "Partial end-of-run episodes are excluded from return comparisons and returns are normalized by episode length.",
            "Control trajectories are raw switch-level Simulink exports at 2-ms stride; pass/fail annotations use 20-us evaluator metrics.",
            "The selected case is strong-dq fail and family-SAC-r6 pass under the active voltage-survival gate.",
        ],
    }
    manifest_path = TRACE_OUT / "fig_t2_a_deep_lvrt_r6_evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
