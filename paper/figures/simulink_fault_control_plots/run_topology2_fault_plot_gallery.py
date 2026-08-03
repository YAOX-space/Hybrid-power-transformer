"""Run topology2 Simulink fault traces and generate control plots.

This script intentionally reuses the existing switch-level single-case
evaluator:

    version_2/simulink/evaluators/eval_hpt_v2_sac_single_case.m

The evaluator writes 2-ms control-step trace CSVs.  The plots generated here
are therefore based on real Simulink-exported control traces, not metric-derived
reconstructions.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "version_2" / "simulink"
TRACE_DIR = ROOT / "lab" / "results" / "hpt_v2_sac_single_case_actor_traces"
OUT_DIR = ROOT / "paper" / "figures" / "simulink_fault_control_plots"
MATLAB = "matlab"

FAULT_START = 0.035
FAULT_DURATION = 0.060
FAULT_CLEAR = FAULT_START + FAULT_DURATION
TARGET_LV_RMS = 207.0
VDC_LOW = 650.0
VDC_HIGH = 1000.0


@dataclass(frozen=True)
class FaultScenario:
    family: str
    phase_mode: str
    fault_pu: float
    phase_pu: tuple[float, float, float]

    @property
    def case_name(self) -> str:
        if self.family == "LVRT":
            return "sag_0p90"
        return "swell_1p10"

    @property
    def slug(self) -> str:
        return f"topology2_{self.phase_mode}_{self.family.lower()}_{self.fault_pu:.2f}pu_60ms".replace(
            ".", "p"
        )

    @property
    def title(self) -> str:
        return f"topology2 {self.phase_mode.upper()} {self.family} {self.fault_pu:.2f} pu / 60 ms"


def build_scenarios() -> list[FaultScenario]:
    phase_modes = {
        "balanced": lambda pu: (pu, pu, pu),
        "a": lambda pu: (pu, 1.0, 1.0),
        "b": lambda pu: (1.0, pu, 1.0),
        "c": lambda pu: (1.0, 1.0, pu),
        "ab": lambda pu: (pu, pu, 1.0),
        "bc": lambda pu: (1.0, pu, pu),
        "ca": lambda pu: (pu, 1.0, pu),
    }
    scenarios: list[FaultScenario] = []
    for family, pu in [("LVRT", 0.90), ("HVRT", 1.10)]:
        for mode, fn in phase_modes.items():
            scenarios.append(FaultScenario(family, mode, pu, fn(pu)))
    return scenarios


def latest_trace_files() -> set[Path]:
    if not TRACE_DIR.exists():
        return set()
    return set(TRACE_DIR.glob("single_actor_trace_*.csv"))


def matlab_vec(values: Iterable[float]) -> str:
    return "[" + " ".join(f"{float(v):.12g}" for v in values) + "]"


def run_simulink_trace(scenario: FaultScenario, timeout_s: int = 900) -> Path:
    before = latest_trace_files()
    phase = matlab_vec(scenario.phase_pu)
    statement = (
        f"cd('{SIM_DIR.as_posix()}'); "
        "hpt_eval_topology='topology2'; "
        "hpt_eval_scenario_type='fault'; "
        f"hpt_eval_case_name='{scenario.case_name}'; "
        f"hpt_eval_fault_phase_pu={phase}; "
        "hpt_eval_energy_enable=1.0; "
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_sac_single_case.m'));"
    )
    cmd = [MATLAB, "-batch", statement]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
    )
    log_path = OUT_DIR / f"{scenario.slug}_matlab.log"
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
        raise RuntimeError(f"MATLAB failed for {scenario.slug}; see {log_path}")
    after = latest_trace_files()
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if not new_files:
        raise RuntimeError(f"No new trace CSV found for {scenario.slug}; see {log_path}")
    trace = new_files[-1]
    copied = OUT_DIR / f"{scenario.slug}_trace.csv"
    shutil.copy2(trace, copied)
    return copied


def safe_numeric(df: pd.DataFrame, col: str, default: float = 0.0) -> np.ndarray:
    if col not in df.columns:
        return np.full(len(df), default, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default).to_numpy(dtype=float)


def plot_trace(scenario: FaultScenario, trace_csv: Path) -> Path:
    df = pd.read_csv(trace_csv)
    t = safe_numeric(df, "t")
    lv = safe_numeric(df, "lv_rms_inst")
    vdc = safe_numeric(df, "vdc_inst")
    vpos = safe_numeric(df, "obs_02")
    vneg = safe_numeric(df, "obs_03")
    actions = [safe_numeric(df, f"actor_action_{i:02d}") for i in range(1, 5)]
    window_ok = safe_numeric(df, "window_ok", default=np.nan)

    fig, axes = plt.subplots(4, 1, figsize=(10.8, 7.4), sharex=True)
    fig.suptitle(f"Simulink switch-level control trace: {scenario.title}", fontsize=12, weight="bold")

    for ax in axes:
        ax.axvspan(FAULT_START, FAULT_CLEAR, color="#fde0dd", alpha=0.45)
        ax.axvline(FAULT_START, color="0.35", lw=0.9, linestyle="--")
        ax.axvline(FAULT_CLEAR, color="0.35", lw=0.9, linestyle="--")
        ax.grid(True, alpha=0.25)

    if scenario.family == "LVRT":
        axes[0].axhspan(176.0, 238.0, color="#e8f5e9", alpha=0.35, label="fault survival band")
    else:
        axes[0].axhspan(176.0, 238.0, color="#e8f5e9", alpha=0.20, label="voltage-survival band")
    axes[0].plot(t, lv, color="#1f77b4", lw=1.7, label="LV RMS")
    axes[0].axhline(TARGET_LV_RMS, color="0.35", lw=0.9, linestyle=":")
    axes[0].set_ylabel("LV RMS (V)")
    axes[0].legend(loc="upper right", frameon=False)

    axes[1].plot(t, vpos, color="#4c78a8", lw=1.6, label="grid Vpos obs")
    axes[1].plot(t, vneg, color="#e15759", lw=1.2, label="grid Vneg obs")
    axes[1].set_ylabel("Grid seq. (pu)")
    axes[1].legend(loc="upper right", frameon=False, ncol=2)

    axes[2].axhspan(VDC_LOW, VDC_HIGH, color="#fff8e1", alpha=0.65, label="DC-link survival band")
    axes[2].plot(t, vdc, color="#d62728", lw=1.5, label="Vdc")
    axes[2].set_ylabel("Vdc (V)")
    axes[2].legend(loc="upper right", frameon=False)

    labels = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]
    colors = ["#2ca02c", "#98df8a", "#ff7f0e", "#ffbb78"]
    for action, label, color in zip(actions, labels, colors):
        axes[3].plot(t, action, lw=1.4, label=label, color=color)
    axes[3].axhline(0.0, color="0.25", lw=0.7)
    axes[3].set_ylabel("Actor action")
    axes[3].set_xlabel("Time (s)")
    axes[3].legend(loc="upper right", frameon=False, ncol=4)

    if np.isfinite(window_ok).any():
        pass_rate = float(np.nanmean(window_ok) * 100.0)
        axes[0].text(
            0.01,
            0.05,
            f"control-step window-ok rate: {pass_rate:.1f}%",
            transform=axes[0].transAxes,
            ha="left",
            va="bottom",
            color="0.25",
            fontsize=8,
        )
    fig.text(
        0.5,
        0.01,
        "Trace exported from Simulink single-case evaluator at 2-ms control-step stride; shaded region is the injected fault window.",
        ha="center",
        color="0.35",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    out_png = OUT_DIR / f"{scenario.slug}.png"
    out_pdf = OUT_DIR / f"{scenario.slug}.pdf"
    fig.savefig(out_png, dpi=300)
    fig.savefig(out_pdf)
    plt.close(fig)
    return out_png


def write_index(results: list[dict[str, str]]) -> None:
    lines = [
        "# Topology2 Simulink Fault Control Plot Gallery",
        "",
        "Scope: topology2 only; LVRT/HVRT representative fault depth with balanced, single-phase, and two-phase phase modes.",
        "",
        "These plots are generated from Simulink-exported control-step trace CSVs using `eval_hpt_v2_sac_single_case.m`.",
        "",
        "## Fault Matrix",
        "",
        "| Family | Depth | Duration | Phase modes |",
        "| --- | ---: | ---: | --- |",
        "| LVRT | 0.90 pu | 60 ms | balanced, A, B, C, AB, BC, CA |",
        "| HVRT | 1.10 pu | 60 ms | balanced, A, B, C, AB, BC, CA |",
        "",
        "## Generated Plots",
        "",
        "| Scenario | Trace CSV | PNG | PDF |",
        "| --- | --- | --- | --- |",
    ]
    for row in results:
        lines.append(
            f"| {row['title']} | `{Path(row['trace']).name}` | `{Path(row['png']).name}` | `{Path(row['pdf']).name}` |"
        )
    lines.append("")
    lines.append("Note: these are SAC actor traces only. Conventional-vs-SAC raw waveform overlays require a separate multi-mode trace evaluator.")
    (OUT_DIR / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    smoke = "--smoke" in argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    if smoke:
        scenarios = [scenarios[0]]

    results: list[dict[str, str]] = []
    started = time.time()
    for idx, scenario in enumerate(scenarios, start=1):
        print(f"[{idx}/{len(scenarios)}] running {scenario.slug}", flush=True)
        trace = run_simulink_trace(scenario)
        png = plot_trace(scenario, trace)
        results.append(
            {
                "title": scenario.title,
                "trace": str(trace),
                "png": str(png),
                "pdf": str(png.with_suffix(".pdf")),
            }
        )
    write_index(results)
    summary = {
        "topology": "topology2",
        "scenario_count": len(results),
        "elapsed_s": time.time() - started,
        "output_dir": str(OUT_DIR),
        "results": results,
    }
    (OUT_DIR / ("SUMMARY_smoke.json" if smoke else "SUMMARY.json")).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
