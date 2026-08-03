# Figure Plan and Goal for the HPT Voltage-Survival Paper

Date: 2026-07-27

## Goal

Generate a reproducible, paper-facing figure package for
`paper/hpt_sac_voltage_survival_manuscript.md`.  The figures support only the
current bounded claim:

> Switch-level-promoted, case-specialized SAC-compatible policies can achieve
> load-side voltage survival and beat the tested conventional baseline in
> selected HPT fault boundary cases.

The figures must not imply full grid-code FRT certification, a unified SAC
controller, or proxy-only validation.

## Output Folder

All generated figures live under:

```text
paper/figures/
```

For each figure, the generator should write both `.png` and `.pdf` when
possible.  Source code is:

```text
paper/figures/make_voltage_survival_figures.py
```

## Planned Figures

| ID | File stem | Main message | Evidence / source |
| --- | --- | --- | --- |
| Fig. 1 | `fig01_hpt_topology_control_interface` | The task is a switch-level HPT control problem with two topologies and a four-action learning interface. | Manuscript topology description and `version_2/simulink` model names. |
| Fig. 2 | `fig02_training_promotion_pipeline` | Proxy is only a screening/training aid; switch-level Simulink promotion is final evidence. | Method section and HPT evidence rules. |
| Fig. 3 | `fig03_state_feedback_actor` | The deployed actor is state-feedback, not a fixed action table. | 24-D observation / 4-D action contract in the manuscript. |
| Fig. 4 | `fig04_voltage_survival_gate` | Pass/fail is checked at every control step using envelope, fault band, recovery band, DC link, and action limits. | `version_2/sac/frt_envelope.py` concept and manuscript gate definition. |
| Fig. 5 | `fig05_voltage_survival_boundary_matrix` | Specialist policies extend selected switch-level voltage-survival boundaries beyond the tested conventional baseline. | `paper/evidence/paired_case_comparison.csv`, Stage-5 compact recheck summaries. |
| Fig. 6 | `fig06_switchlevel_waveform_comparison` | Representative switch-level time response shows the specialist staying inside the L1 voltage-survival limits while conventional fails. | Control CSVs referenced by `paper/evidence/per_case_metrics.csv` when available; otherwise metric-derived representative trace reconstruction is marked as schematic. |
| Fig. 7 | `fig07_sac_training_convergence` | Training evidence is better shown as imitation-loss reduction plus protected SAC promotion trace, not as a monotonic plain-SAC reward curve. | `lab/results/hpt_reviewer_evidence_stage5_20260727/ablation_results.csv` and Stage-5 protected SAC notes. |
| Fig. 8 | `fig08_ablation_ladder` | Teacher, BC, and DAgger have different switch-level outcomes across cases; actor promotion is necessary. | `lab/results/hpt_reviewer_evidence_stage5_20260727/ablation_results.csv` and associated summary JSON files. |
| Fig. 9 | `fig09_proxy_alignment` | Proxy alignment is strong near local support but weaker on broader holdout, so proxy cannot replace switch-level validation. | `paper/evidence/stage5_reviewer_evidence_refresh_20260727.md` and proxy holdout summaries. |
| Fig. 10 | `fig10_topology1_unbalanced_tradeoff` | Topology1 unbalanced LVRT is an honest hard case: survival is possible but score improvement over conventional remains difficult. | `paper/evidence/stage5_reviewer_evidence_refresh_20260727.md` and topology1 score optimization diagnostics. |

## Caption Policy

- Figure labels and in-figure text are English.
- Captions can be inserted into the manuscript in Chinese for now.
- Every quantitative figure must name the evidence file or result directory in
  either the caption or manuscript text.
- Any schematic or reconstructed trace must be labeled as schematic rather than
  switch-level measured waveform.
