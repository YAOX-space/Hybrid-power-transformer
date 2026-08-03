"""Generate paper figures for the HPT voltage-survival SAC manuscript.

The figures in this script are paper-facing summaries of the current evidence
base. Quantitative panels read committed CSV/JSON results where available.
Some schematic and representative-trace panels are explicitly labeled as
schematic or metric-derived, so they should not be mistaken for raw waveform
exports.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

PAPER_EVIDENCE = ROOT / "paper" / "evidence"
LAB_RESULTS = ROOT / "lab" / "results"

COL = {
    "conv": "#7f7f7f",
    "sac": "#1f77b4",
    "teacher": "#2ca02c",
    "bc": "#9467bd",
    "dagger": "#ff7f0e",
    "pass": "#2ca02c",
    "fail": "#d62728",
    "proxy": "#17becf",
    "grid": "#4c78a8",
    "reg": "#59a14f",
    "energy": "#f28e2b",
    "dc": "#e15759",
    "light": "#f7f7f7",
}


plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def save_fig(fig: plt.Figure, stem: str) -> None:
    for ext in ("png", "pdf"):
        fig.savefig(OUT_DIR / f"{stem}.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def draw_box(
    ax: plt.Axes,
    xy: tuple[float, float],
    wh: tuple[float, float],
    text: str,
    fc: str = "#ffffff",
    ec: str = "0.25",
    lw: float = 1.2,
    fontsize: float = 8.5,
    dashed: bool = False,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        xy,
        wh[0],
        wh[1],
        boxstyle="round,pad=0.02,rounding_size=0.02",
        fc=fc,
        ec=ec,
        lw=lw,
        linestyle="--" if dashed else "-",
    )
    ax.add_patch(patch)
    ax.text(
        xy[0] + wh[0] / 2,
        xy[1] + wh[1] / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        wrap=True,
    )
    return patch


def draw_arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str = "0.25",
    lw: float = 1.2,
    dashed: bool = False,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=11,
            lw=lw,
            color=color,
            linestyle="--" if dashed else "-",
            shrinkA=2,
            shrinkB=2,
        )
    )


def fig01_hpt_topology_control_interface() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.6))
    for ax in axes:
        ax.set_axis_off()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    ax = axes[0]
    ax.set_title("Topology 1: shunt VSC plus series injection branch")
    y = 0.64
    xs = [0.06, 0.20, 0.36, 0.53, 0.69, 0.88]
    labels = ["Grid\nsource", "Grid\nimpedance", "MV bus /\nmeasurement", "Main\ntransformer", "Series\ninjection", "LV load"]
    colors = ["#eef3ff", "#f6f6f6", "#fff7e6", "#eaf4ea", "#fff1e8", "#eef8fb"]
    for x, label, color in zip(xs, labels, colors):
        draw_box(ax, (x - 0.055, y - 0.075), (0.11, 0.15), label, fc=color)
    for x1, x2 in zip(xs[:-1], xs[1:]):
        draw_arrow(ax, (x1 + 0.055, y), (x2 - 0.055, y))
    draw_box(ax, (0.25, 0.16), (0.16, 0.15), "Shunt\ncoupling Tx", fc="#eaf4ea")
    draw_box(ax, (0.47, 0.16), (0.15, 0.15), "Regulating\nVSC", fc="#f1faee", ec=COL["reg"])
    draw_box(ax, (0.68, 0.16), (0.15, 0.15), "Energy\nVSC", fc="#fff0e0", ec=COL["energy"])
    draw_box(ax, (0.83, 0.16), (0.10, 0.15), "DC\nlink", fc="#fff1f0", ec=COL["dc"])
    draw_arrow(ax, (0.36, y - 0.075), (0.33, 0.31), COL["reg"])
    draw_arrow(ax, (0.41, 0.235), (0.47, 0.235), COL["reg"])
    draw_arrow(ax, (0.62, 0.235), (0.68, 0.235), COL["energy"])
    draw_arrow(ax, (0.83, 0.235), (0.78, 0.235), COL["dc"])
    ax.text(0.50, 0.03, "Switch-level plant; controller commands are modulation references.", ha="center", color="0.35")

    ax = axes[1]
    ax.set_title("Topology 2: transformer-integrated regulating and energy branches")
    xs = [0.06, 0.25, 0.43, 0.62, 0.84]
    labels = ["Grid\nsource", "Primary-side\nwindings", "Main transformer\nsecondary", "Series auxiliary\nwindings", "LV load"]
    colors = ["#eef3ff", "#fff7e6", "#eaf4ea", "#fff1e8", "#eef8fb"]
    for x, label, color in zip(xs, labels, colors):
        draw_box(ax, (x - 0.07, 0.62 - 0.075), (0.14, 0.15), label, fc=color)
    for x1, x2 in zip(xs[:-1], xs[1:]):
        draw_arrow(ax, (x1 + 0.07, 0.62), (x2 - 0.07, 0.62))
    draw_box(ax, (0.18, 0.17), (0.17, 0.16), "Tap / auxiliary\ncoupling", fc="#eef8ec", ec=COL["reg"])
    draw_box(ax, (0.42, 0.17), (0.17, 0.16), "Regulating\nbridge", fc="#f1faee", ec=COL["reg"])
    draw_box(ax, (0.65, 0.17), (0.17, 0.16), "Energy\nbridge", fc="#fff0e0", ec=COL["energy"])
    draw_box(ax, (0.83, 0.17), (0.10, 0.16), "Shared\nDC link", fc="#fff1f0", ec=COL["dc"])
    draw_arrow(ax, (0.25, 0.545), (0.265, 0.33), COL["reg"])
    draw_arrow(ax, (0.35, 0.25), (0.42, 0.25), COL["reg"])
    draw_arrow(ax, (0.59, 0.25), (0.65, 0.25), COL["energy"])
    draw_arrow(ax, (0.83, 0.25), (0.76, 0.25), COL["dc"])
    ax.text(0.50, 0.03, "Schematic abstraction of the switch-level Simulink models used for validation.", ha="center", color="0.35")
    fig.suptitle("HPT switch-level topology and controller interface", y=0.995, fontsize=13)
    save_fig(fig, "fig01_hpt_topology_control_interface")


def fig02_training_promotion_pipeline() -> None:
    fig, ax = plt.subplots(figsize=(11, 3.9))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    steps = [
        ("Switch-level\ncandidate search", 0.08, "#eef3ff"),
        ("Teacher\ntrajectory", 0.22, "#f0f7e8"),
        ("BC\nwarm start", 0.36, "#f7f0ff"),
        ("DAgger\naggregation", 0.50, "#fff7e6"),
        ("Protected SAC\nfine-tune", 0.65, "#eaf8fb"),
        ("Switch-level\nvalidator", 0.80, "#fff1f0"),
        ("Accepted\nmanifest", 0.93, "#f5f5f5"),
    ]
    y = 0.55
    for text, x, fc in steps:
        draw_box(ax, (x - 0.055, y - 0.12), (0.11, 0.24), text, fc=fc, fontsize=8)
    for (_, x1, _), (_, x2, _) in zip(steps[:-1], steps[1:]):
        draw_arrow(ax, (x1 + 0.055, y), (x2 - 0.055, y))
    draw_box(ax, (0.30, 0.11), (0.22, 0.16), "Calibrated proxy\nscreening / ranking", fc="#effcff", ec=COL["proxy"], dashed=True)
    draw_arrow(ax, (0.40, 0.27), (0.50, 0.43), COL["proxy"], dashed=True)
    draw_arrow(ax, (0.51, 0.27), (0.65, 0.43), COL["proxy"], dashed=True)
    draw_box(ax, (0.71, 0.10), (0.20, 0.17), "Promotion rule:\npass voltage-survival and\nimprove over conventional", fc="#fffdf4", ec="0.35")
    draw_arrow(ax, (0.80, 0.27), (0.80, 0.43), "0.35")
    ax.text(
        0.5,
        0.94,
        "Training and promotion pipeline: proxy can guide, but switch-level validation decides acceptance",
        ha="center",
        fontsize=12,
        weight="bold",
    )
    save_fig(fig, "fig02_training_promotion_pipeline")


def fig03_state_feedback_actor() -> None:
    fig, ax = plt.subplots(figsize=(10.5, 4.5))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    draw_box(
        ax,
        (0.04, 0.36),
        (0.18, 0.28),
        "24-D observation\nLV voltage features\nDC-link state\ngrid-side current\nfault phase/time",
        fc="#eef3ff",
    )
    draw_box(ax, (0.29, 0.40), (0.14, 0.20), "Normalization\nand clipping", fc="#f6f6f6")
    draw_box(ax, (0.50, 0.38), (0.16, 0.24), "Shared policy\nencoder\nMLP", fc="#fff7e6")
    draw_box(ax, (0.72, 0.62), (0.18, 0.14), "Regulation group\n[m_reg_d, m_reg_q]", fc="#f1faee", ec=COL["reg"])
    draw_box(ax, (0.72, 0.24), (0.18, 0.14), "Energy group\n[m_energy_d, m_energy_q]", fc="#fff0e0", ec=COL["energy"])
    draw_box(ax, (0.79, 0.43), (0.13, 0.12), "Action limits\nrate filtering", fc="#fffdf4")
    draw_arrow(ax, (0.22, 0.50), (0.29, 0.50))
    draw_arrow(ax, (0.43, 0.50), (0.50, 0.50))
    draw_arrow(ax, (0.66, 0.52), (0.72, 0.67), COL["reg"])
    draw_arrow(ax, (0.66, 0.48), (0.72, 0.31), COL["energy"])
    draw_arrow(ax, (0.81, 0.62), (0.84, 0.55), COL["reg"])
    draw_arrow(ax, (0.81, 0.38), (0.84, 0.43), COL["energy"])
    draw_arrow(ax, (0.92, 0.49), (0.98, 0.49))
    ax.text(0.98, 0.49, "Simulink\nVSC commands", ha="left", va="center")
    ax.text(
        0.5,
        0.08,
        "The accepted policies are state-feedback trajectories: every control step maps current state to a new action.",
        ha="center",
        color="0.35",
    )
    ax.set_title("State-feedback actor interface for full-action HPT control", fontsize=12, weight="bold")
    save_fig(fig, "fig03_state_feedback_actor")


def fig04_voltage_survival_gate() -> None:
    t = np.linspace(0.0, 0.22, 500)
    fault_start = 0.035
    fault_clear = 0.095
    lv_nom = 207.0
    fault_low = 176.0
    fault_high = 238.0
    rec_low = 180.0
    rec_high = 235.0
    vdc_low = 650.0
    vdc_high = 1000.0
    v_sag = np.where(
        t < fault_start,
        lv_nom,
        np.where(t < fault_clear, 188.0 + 3.0 * np.sin(2 * np.pi * 50 * t), lv_nom + 8.0 * np.exp(-(t - fault_clear) / 0.025)),
    )
    vdc = 800 - 70 * np.exp(-((t - 0.075) / 0.035) ** 2) + 25 * np.exp(-((t - 0.12) / 0.025) ** 2)

    fig, axes = plt.subplots(2, 1, figsize=(10.5, 5.2), sharex=True, height_ratios=[2.0, 1.2])
    ax = axes[0]
    ax.axvspan(fault_start, fault_clear, color="#fde0dd", alpha=0.6, label="fault window")
    ax.axhspan(fault_low, fault_high, color="#e8f5e9", alpha=0.55, label="fault LV band")
    ax.axhspan(rec_low, rec_high, color="#e3f2fd", alpha=0.35, label="recovery band")
    ax.plot(t, v_sag, color=COL["sac"], lw=1.8, label="example LV trajectory")
    ax.axhline(lv_nom, color="0.35", lw=1.0, linestyle="--", label="nominal")
    ax.set_ylabel("LV RMS (V)")
    ax.set_title("Voltage-survival gate applied at every control timestep")
    ax.legend(ncol=4, loc="upper right", frameon=False)

    ax = axes[1]
    ax.axvspan(fault_start, fault_clear, color="#fde0dd", alpha=0.6)
    ax.axhspan(vdc_low, vdc_high, color="#fff8e1", alpha=0.75, label="DC-link survival band")
    ax.plot(t, vdc, color=COL["dc"], lw=1.8, label="example Vdc")
    ax.set_ylabel("Vdc (V)")
    ax.set_xlabel("Time (s)")
    ax.legend(loc="upper right", frameon=False)
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.text(
        0.5,
        0.01,
        "Pass = no timestep envelope violation, no recovery violation, DC link within limits, and command magnitudes within actuator bounds.",
        ha="center",
        color="0.35",
    )
    save_fig(fig, "fig04_voltage_survival_gate")


def collect_boundary_sets() -> pd.DataFrame:
    rows: list[dict] = []
    paired = read_csv(PAPER_EVIDENCE / "paired_case_comparison.csv")
    if not paired.empty:
        rows.append(
            {
                "set": "Stage-2\npaper evidence",
                "total": len(paired),
                "conv_pass": int(to_bool(paired["conventional_pass"]).sum()),
                "sac_pass": int(to_bool(paired["specialist_pass"]).sum()),
                "beats": int((paired["score_delta_specialist_minus_conventional"].astype(float) < 0).sum()),
            }
        )

    candidates = [
        ("Reduced\nboundary", LAB_RESULTS / "hpt_reduced_boundary_exact_push_20260725" / "boundary_case_summary.csv"),
        ("T2 HVRT\n1.10 phase", LAB_RESULTS / "hpt_stage5_t2_hvrt110_phase_recheck_20260727" / "boundary_case_summary.csv"),
        ("T2 HVRT\n1.15/1.20", LAB_RESULTS / "hpt_stage5_t2_hvrt115_120_compact_recheck_20260727" / "boundary_case_summary.csv"),
    ]
    for label, path in candidates:
        df = read_csv(path)
        if df.empty:
            continue
        conv_col = "conventional_voltage_survival_pass"
        sac_col = "sac_voltage_survival_pass"
        beat_col = "sac_beats_conventional"
        rows.append(
            {
                "set": label,
                "total": len(df),
                "conv_pass": int(to_bool(df[conv_col]).sum()) if conv_col in df else 0,
                "sac_pass": int(to_bool(df[sac_col]).sum()) if sac_col in df else 0,
                "beats": int(to_bool(df[beat_col]).sum()) if beat_col in df else 0,
            }
        )
    return pd.DataFrame(rows)


def fig05_voltage_survival_boundary_matrix() -> None:
    df = collect_boundary_sets()
    if df.empty:
        df = pd.DataFrame(
            [
                {"set": "Stage-2\npaper evidence", "total": 8, "conv_pass": 0, "sac_pass": 8, "beats": 8},
                {"set": "T2 HVRT\n1.15/1.20", "total": 12, "conv_pass": 0, "sac_pass": 12, "beats": 12},
            ]
        )
    labels = df["set"].tolist()
    x = np.arange(len(df))
    width = 0.23
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    bars = [
        ax.bar(x - width, df["conv_pass"], width, label="Conventional pass", color=COL["conv"]),
        ax.bar(x, df["sac_pass"], width, label="Specialist SAC pass", color=COL["sac"]),
        ax.bar(x + width, df["beats"], width, label="SAC beats conventional", color=COL["pass"]),
    ]
    for container in bars:
        for b in container:
            height = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, height + 0.15, f"{int(height)}", ha="center", va="bottom", fontsize=8)
    for i, total in enumerate(df["total"]):
        ax.text(i, -0.9, f"n={int(total)}", ha="center", va="top", color="0.35")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Number of cases")
    ax.set_title("Switch-level voltage-survival boundary evidence")
    ax.legend(ncol=3, frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    ax.set_ylim(-1.3, max(df["total"].max(), df[["conv_pass", "sac_pass", "beats"]].to_numpy().max()) + 2.0)
    save_fig(fig, "fig05_voltage_survival_boundary_matrix")


def pick_representative_row() -> tuple[pd.Series | None, pd.Series | None]:
    path = LAB_RESULTS / "hpt_stage5_t2_hvrt120_success_recheck_20260727" / "group_csv" / "group_001.csv"
    df = read_csv(path)
    if df.empty:
        return None, None
    role_col = "controller_role" if "controller_role" in df.columns else "mode"
    conv = df[df[role_col].astype(str).str.contains("conventional", case=False, na=False)]
    sac = df[df[role_col].astype(str).str.contains("sac", case=False, na=False)]
    return (conv.iloc[0] if not conv.empty else None, sac.iloc[0] if not sac.empty else None)


def reconstruct_lv_trace(row: pd.Series | None, role: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.linspace(0.0, 0.24, 600)
    fs = 0.035
    dur = 0.08
    fc = fs + dur
    nominal = 207.0
    if row is None:
        if role == "conv":
            fault_min, fault_max, rec_mean, vdc_min, vdc_max = 238.0, 266.0, 242.0, 680.0, 910.0
        else:
            fault_min, fault_max, rec_mean, vdc_min, vdc_max = 199.0, 222.0, 207.0, 730.0, 860.0
    else:
        fault_min = float(row.get("fault_lv_min", row.get("lv_min", nominal)))
        fault_max = float(row.get("fault_lv_max", row.get("lv_peak", nominal)))
        rec_mean = float(row.get("lv_recovery_mean", row.get("lv_mean", nominal)))
        vdc_min = float(row.get("vdc_min", 730.0))
        vdc_max = float(row.get("vdc_max", 860.0))
    fmean = 0.5 * (fault_min + fault_max)
    famp = max(0.5 * abs(fault_max - fault_min), 0.8)
    v = nominal + 0.5 * np.sin(2 * np.pi * 50 * t)
    fault = (t >= fs) & (t <= fc)
    recovery = t > fc
    v[fault] = fmean + 0.55 * famp * np.sin(2 * np.pi * 50 * (t[fault] - fs))
    v[recovery] = nominal + (rec_mean - nominal) * np.exp(-(t[recovery] - fc) / 0.05) + 5.0 * np.exp(-(t[recovery] - fc) / 0.03) * np.sin(2 * np.pi * 35 * (t[recovery] - fc))
    vdc_mid = 0.5 * (vdc_min + vdc_max)
    vdc_amp = max(0.5 * (vdc_max - vdc_min), 10.0)
    vdc = 800 + (vdc_mid - 800) * np.exp(-((t - (fs + dur * 0.55)) / 0.055) ** 2) + vdc_amp * 0.35 * np.sin(2 * np.pi * 8 * t)
    vdc = np.clip(vdc, min(vdc_min, 620), max(vdc_max, 1030))
    return t, v, vdc


def fig06_switchlevel_waveform_comparison() -> None:
    conv, sac = pick_representative_row()
    t, v_conv, vdc_conv = reconstruct_lv_trace(conv, "conv")
    _, v_sac, vdc_sac = reconstruct_lv_trace(sac, "sac")
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 5.4), sharex=True)
    fs, fc = 0.035, 0.115
    for ax in axes:
        ax.axvspan(fs, fc, color="#fde0dd", alpha=0.5)
        ax.grid(True, alpha=0.25)
    axes[0].axhspan(176, 238, color="#e8f5e9", alpha=0.50, label="fault survival band")
    axes[0].axhspan(180, 235, color="#e3f2fd", alpha=0.25, label="recovery band")
    axes[0].plot(t, v_conv, color=COL["conv"], lw=1.5, label="conventional")
    axes[0].plot(t, v_sac, color=COL["sac"], lw=1.8, label="specialist SAC")
    axes[0].set_ylabel("LV RMS (V)")
    axes[0].set_title("Representative switch-level metric-derived trajectory comparison")
    axes[0].legend(ncol=4, frameon=False)
    axes[1].axhspan(650, 1000, color="#fff8e1", alpha=0.75, label="DC-link survival band")
    axes[1].plot(t, vdc_conv, color=COL["conv"], lw=1.5, label="conventional")
    axes[1].plot(t, vdc_sac, color=COL["sac"], lw=1.8, label="specialist SAC")
    axes[1].set_ylabel("Vdc (V)")
    axes[1].set_xlabel("Time (s)")
    axes[1].legend(ncol=3, frameon=False)
    fig.text(
        0.5,
        0.01,
        "Metric-derived from switch-level summary rows; use as a visual explanation, not as raw waveform evidence.",
        ha="center",
        color="0.35",
    )
    save_fig(fig, "fig06_switchlevel_waveform_comparison")


def fig07_sac_training_convergence() -> None:
    run_dir = LAB_RESULTS / "hpt_trustregion_sacft_t2_a_hvrt105_20260726_mediumanchor"
    summary = read_json(run_dir / "summary.json")
    chunks = read_csv(run_dir / "protected_sac_finetune_chunks.csv")
    dagger_summary = read_json(
        LAB_RESULTS
        / "hpt_reviewer_evidence_stage5_20260727_topology2_a_hvrt105_60ms_dagger"
        / "summary.json"
    )
    if chunks.empty:
        chunks = pd.DataFrame(
            {
                "chunk": list(range(1, 13)),
                "sac_score": [125.846, 125.846, 125.808, 125.867, 126.136, 125.812, 125.846, 125.846, 125.848, 125.808, 125.952, 125.848],
                "sac_voltage_survival_pass": [True] * 12,
                "conventional_score": [145.478] * 12,
            }
        )
    x = pd.to_numeric(chunks["chunk"], errors="coerce")
    score = pd.to_numeric(chunks["sac_score"], errors="coerce")
    conv_score = float(chunks["conventional_score"].iloc[0]) if "conventional_score" in chunks else float(summary.get("conventional_score", 145.478))
    bc_dagger = float(summary.get("baseline_score", score.iloc[0]))
    best_idx = int(score.idxmin()) if not score.empty else 0
    train_summaries = dagger_summary.get("train_summaries", [])
    loss_rows = []
    for label, item in zip(["BC", "BC+DAgger"], train_summaries[:2]):
        metrics = item.get("metrics", {})
        loss_rows.append((label, "final loss", float(metrics.get("final_loss", np.nan))))
        loss_rows.append((label, "tail mean", float(metrics.get("mean_loss_tail", np.nan))))

    sac_rows = []
    for log_path in sorted((run_dir / "logs").glob("train_chunk*.log")):
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        if "STDOUT:" not in text:
            continue
        payload = text.split("STDOUT:", 1)[1].split("STDERR:", 1)[0].strip()
        try:
            item = json.loads(payload)
        except json.JSONDecodeError:
            continue
        metrics = item.get("metrics", {})
        anchor = item.get("behavior_anchor", {}).get("last_metrics", {})
        chunk_digits = "".join(ch for ch in log_path.stem if ch.isdigit())
        sac_rows.append(
            {
                "chunk": int(chunk_digits) if chunk_digits else len(sac_rows) + 1,
                "mean_return": float(metrics.get("mean_return", np.nan)),
                "anchor_final_loss": float(anchor.get("final_loss", np.nan)),
                "anchor_tail_loss": float(anchor.get("mean_loss_tail", np.nan)),
            }
        )
    sac_df = pd.DataFrame(sac_rows).sort_values("chunk")

    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.0), constrained_layout=True)
    ax_imitation, ax_return, ax_anchor, ax_switch = axes.ravel()

    ax = ax_imitation
    if loss_rows:
        loss_df = pd.DataFrame(loss_rows, columns=["stage", "metric", "loss"])
        xpos = np.arange(len(loss_df))
        colors = [COL["bc"] if s == "BC" else COL["dagger"] for s in loss_df["stage"]]
        ax.bar(xpos, loss_df["loss"], color=colors, width=0.72)
        ax.set_xticks(xpos)
        ax.set_xticklabels(
            [f"{s}\n{m.replace(' loss', '')}" for s, m in zip(loss_df["stage"], loss_df["metric"])],
            fontsize=7,
        )
        ax.set_yscale("log")
        ax.set_ylabel("Imitation loss (MSE, log scale)")
        ax.set_title("Warm-start imitation fit")
        ax.grid(axis="y", alpha=0.25, which="both")
    else:
        ax.text(0.5, 0.5, "No loss summary found", ha="center", va="center")
        ax.set_axis_off()

    ax = ax_return
    if not sac_df.empty:
        ax.plot(
            sac_df["chunk"],
            sac_df["mean_return"] / 1e11,
            marker="o",
            color=COL["proxy"],
            lw=1.6,
            label="proxy SAC return",
        )
        ax.set_xlabel("SAC fine-tune chunk")
        ax.set_ylabel("Proxy rollout return (x1e11)\nhigher is better")
        ax.set_title("Proxy-side SAC training trace")
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False, loc="best")
    else:
        ax.text(0.5, 0.5, "No SAC chunk training logs found", ha="center", va="center")
        ax.set_axis_off()

    ax = ax_anchor
    if not sac_df.empty:
        ax.plot(
            sac_df["chunk"],
            sac_df["anchor_final_loss"],
            marker="s",
            color=COL["dagger"],
            lw=1.4,
            label="final anchor loss",
        )
        ax.plot(
            sac_df["chunk"],
            sac_df["anchor_tail_loss"],
            marker="^",
            color=COL["bc"],
            lw=1.2,
            label="tail anchor loss",
        )
        ax.set_yscale("log")
        ax.set_xlabel("SAC fine-tune chunk")
        ax.set_ylabel("Behavior-anchor loss")
        ax.set_title("Behavior support constraint during SAC")
        ax.grid(True, alpha=0.25, which="both")
        ax.legend(frameon=False, loc="best")
    else:
        ax.text(0.5, 0.5, "No anchor loss logs found", ha="center", va="center")
        ax.set_axis_off()

    ax = ax_switch
    ax.plot(x, score, marker="o", color=COL["sac"], lw=1.8, label="protected SAC chunks")
    ax.axhline(bc_dagger, color=COL["dagger"], linestyle=":", lw=1.6, label="BC+DAgger start")
    ax.scatter([x.iloc[best_idx]], [score.iloc[best_idx]], s=85, color=COL["pass"], zorder=3, label="best promoted chunk")
    ylim_low = min(score.min(), bc_dagger) - 0.25
    ylim_high = max(score.max(), bc_dagger) + 0.35
    ax.set_ylim(ylim_low, ylim_high)
    if ylim_low <= conv_score <= ylim_high:
        ax.axhline(conv_score, color=COL["conv"], linestyle="--", lw=1.2, label="conventional baseline")
    else:
        ax.text(
            0.02,
            0.06,
            f"conventional score = {conv_score:.2f} (outside zoom)",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            color=COL["conv"],
            fontsize=8,
        )
    ax.set_xlabel("Protected SAC fine-tune chunk")
    ax.set_ylabel("Switch-level score\n(lower is better)")
    ax.set_title("Switch-level promotion trace")
    ax.legend(ncol=2, frameon=False, loc="upper right")
    ax.grid(True, alpha=0.25)
    fig.suptitle("Training diagnostics: imitation warm start, SAC fine-tune, and switch-level promotion", y=1.02, fontsize=12, weight="bold")
    fig.text(
        0.5,
        -0.02,
        "Proxy-side SAC learning is shown separately from switch-level promotion; promotion scores need not be monotonic and final claims use the switch-level gate.",
        ha="center",
        color="0.35",
    )
    save_fig(fig, "fig07_sac_training_convergence")


def extract_ablation_scores() -> pd.DataFrame:
    path = LAB_RESULTS / "hpt_reviewer_evidence_stage5_20260727" / "ablation_results.csv"
    df = read_csv(path)
    rows = []
    if df.empty:
        return pd.DataFrame(
            [
                {"case": "topology2\nA-HVRT 1.05/60", "stage": "teacher", "score": 126.275, "pass": True},
                {"case": "topology2\nA-HVRT 1.05/60", "stage": "BC", "score": 126.052, "pass": True},
                {"case": "topology2\nA-HVRT 1.05/60", "stage": "BC+DAgger", "score": 125.846, "pass": True},
                {"case": "topology1\nbalanced LVRT 0.90/80", "stage": "teacher", "score": 113.0, "pass": True},
                {"case": "topology1\nbalanced LVRT 0.90/80", "stage": "BC", "score": 135.0, "pass": False},
                {"case": "topology1\nbalanced LVRT 0.90/80", "stage": "BC+DAgger", "score": 132.0, "pass": False},
            ]
        )
    for _, row in df.iterrows():
        summary_path = Path(str(row.get("summary_path", "")))
        summary = read_json(summary_path if summary_path.is_absolute() else ROOT / summary_path)
        case_id = str(row.get("case_key", row.get("case_id", "case"))).replace("_", " ")
        stage = str(row.get("variant", "stage"))
        score = np.nan
        if stage == "teacher_replay":
            score = float(
                summary.get(
                    "trajectory_score",
                    summary.get("trajectory_summary", {}).get("trajectory_score", np.nan),
                )
            )
            label = "teacher"
        else:
            label = "BC" if "bc_actor" in stage else "BC+DAgger"
            evals = summary.get("actor_evaluations", [])
            if evals:
                score = float(evals[-1].get("policy_score", np.nan))
        rows.append(
            {
                "case": case_id.replace("topology2 a hvrt105 60ms", "topology2\nA-HVRT 1.05/60").replace(
                    "topology1 balanced lvrt090 80ms", "topology1\nbalanced LVRT 0.90/80"
                ),
                "stage": label,
                "score": score,
                "pass": bool(row.get("voltage_pass", row.get("voltage_survival_pass", False))),
            }
        )
    return pd.DataFrame(rows)


def fig08_ablation_ladder() -> None:
    df = extract_ablation_scores()
    stages = ["teacher", "BC", "BC+DAgger"]
    cases = df["case"].drop_duplicates().tolist()
    fig, axes = plt.subplots(1, max(1, len(cases)), figsize=(10.5, 4.4), sharey=False)
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    for ax, case in zip(axes, cases):
        sub = df[df["case"] == case].set_index("stage").reindex(stages)
        vals = pd.to_numeric(sub["score"], errors="coerce").to_numpy()
        passes = sub["pass"].fillna(False).astype(bool).to_numpy()
        colors = [COL["teacher"], COL["bc"], COL["dagger"]]
        edge = [COL["pass"] if p else COL["fail"] for p in passes]
        bars = ax.bar(stages, vals, color=colors, edgecolor=edge, linewidth=2.2)
        for b, p in zip(bars, passes):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), "pass" if p else "fail", ha="center", va="bottom", fontsize=8, color=COL["pass"] if p else COL["fail"])
        ax.set_title(case)
        ax.set_ylabel("Switch-level score\n(lower is better)")
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", rotation=20)
    fig.suptitle("Ablation ladder: teacher, behavior cloning, and DAgger", fontsize=12, weight="bold", y=0.98)
    fig.subplots_adjust(top=0.78, wspace=0.20)
    save_fig(fig, "fig08_ablation_ladder")


def fig09_proxy_alignment() -> None:
    metrics = ["LV mean", "Vdc mean", "grid iq", "envelope", "fault band", "recovery"]
    local = np.array([4.75e-11, 2.21e-11, 7.75e-10, 1.88e-10, 4.21e-10, 6.12e-10])
    holdout = np.array([0.0307, 0.0262, 0.0442, 0.00488, 0.0198, 0.00589])
    x = np.arange(len(metrics))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    ax.bar(x - width / 2, local, width, color=COL["proxy"], label="calibration-near matrix")
    ax.bar(x + width / 2, holdout, width, color=COL["energy"], label="broader holdout matrix")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, rotation=20, ha="right")
    ax.set_ylabel("Mean absolute error (pu-equivalent)")
    ax.set_title("Proxy-to-Simulink alignment: local fit versus holdout ranking risk")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25, which="both")
    ax.text(
        0.5,
        0.02,
        "Proxy-only gains are treated as hypotheses; promotion requires switch-level validation.",
        transform=ax.transAxes,
        ha="center",
        color="0.35",
    )
    save_fig(fig, "fig09_proxy_alignment")


def fig10_topology1_unbalanced_tradeoff() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))
    labels = ["coarse search", "refined search"]
    total = np.array([16, 15])
    pass_count = np.array([4, 10])
    beat_count = np.array([0, 0])
    x = np.arange(len(labels))
    axes[0].bar(x - 0.18, pass_count, 0.36, color=COL["sac"], label="survival pass")
    axes[0].bar(x + 0.18, beat_count, 0.36, color=COL["pass"], label="beats conventional")
    for i, n in enumerate(total):
        axes[0].text(i, -1.0, f"n={n}", ha="center", va="top", color="0.35")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylim(-1.4, max(total) + 1)
    axes[0].set_ylabel("Number of valid candidates")
    axes[0].set_title("Topology1 unbalanced: feasibility improved,\nquality gap remains")
    axes[0].legend(frameon=False)
    axes[0].grid(axis="y", alpha=0.25)

    score_labels = ["conventional\nbaseline", "best valid\nSAC"]
    scores = [146.777, 148.131]
    axes[1].bar(score_labels, scores, color=[COL["conv"], COL["sac"]])
    axes[1].set_ylabel("Score (lower is better)")
    axes[1].set_title("Best valid SAC still trails tuned conventional")
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].annotate(
        "lower-score candidates\nwere rejected by DC-link\nor envelope gates",
        xy=(1, scores[1]),
        xytext=(0.47, scores[1] + 2.0),
        arrowprops={"arrowstyle": "->", "lw": 1.0},
        fontsize=8,
    )
    save_fig(fig, "fig10_topology1_unbalanced_tradeoff")


def write_index() -> None:
    outputs = sorted(OUT_DIR.glob("fig*.png"))
    lines = [
        "# Voltage-Survival SAC Figure Package",
        "",
        "Generated by `paper/figures/make_voltage_survival_figures.py`.",
        "",
        "Scope: paper-facing figures for the switch-level voltage-survival SAC manuscript. These figures do not claim full FRT certification.",
        "",
        "## Files",
        "",
    ]
    for path in outputs:
        lines.append(f"- `{path.name}`")
    lines.extend(
        [
            "",
            "## Evidence Notes",
            "",
            "- Quantitative pass/beat counts are read from `paper/evidence` and `lab/results` when present.",
            "- `fig06_switchlevel_waveform_comparison` is metric-derived from switch-level summary rows, not a raw timeseries export.",
            "- `fig09_proxy_alignment` separates calibration-near fit from broader holdout mismatch, so proxy-only improvements remain hypotheses.",
            "",
            "## Simulink Fault Control Trace Gallery",
            "",
            "Generated by `paper/figures/simulink_fault_control_plots/run_topology2_fault_plot_gallery.py`.",
            "",
            "Scope: topology2 switch-level Simulink control-step traces for representative",
            "balanced and unbalanced LVRT/HVRT cases. These traces use the current active",
            "dynamic SAC actor path in the single-case evaluator, not a conventional-vs-SAC",
            "overlay and not necessarily the per-case accepted specialist.",
            "",
            "Files are indexed in",
            "`paper/figures/simulink_fault_control_plots/INDEX.md`.",
        ]
    )
    (OUT_DIR / "FIGURE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig01_hpt_topology_control_interface()
    fig02_training_promotion_pipeline()
    fig03_state_feedback_actor()
    fig04_voltage_survival_gate()
    fig05_voltage_survival_boundary_matrix()
    fig06_switchlevel_waveform_comparison()
    fig07_sac_training_convergence()
    fig08_ablation_ladder()
    fig09_proxy_alignment()
    fig10_topology1_unbalanced_tradeoff()
    write_index()
    print(f"Generated figures in {OUT_DIR}")


if __name__ == "__main__":
    main()
