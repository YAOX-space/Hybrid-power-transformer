# Topology2 Simulink Fault Control Plot Gallery

Scope: topology2 only; LVRT/HVRT representative fault depth with balanced, single-phase, and two-phase phase modes.

These plots are generated from Simulink-exported control-step trace CSVs using `eval_hpt_v2_sac_single_case.m`.

## Fault Matrix

| Family | Depth | Duration | Phase modes |
| --- | ---: | ---: | --- |
| LVRT | 0.90 pu | 60 ms | balanced, A, B, C, AB, BC, CA |
| HVRT | 1.10 pu | 60 ms | balanced, A, B, C, AB, BC, CA |

## Generated Plots

| Scenario | Trace CSV | PNG | PDF |
| --- | --- | --- | --- |
| topology2 BALANCED LVRT 0.90 pu / 60 ms | `topology2_balanced_lvrt_0p90pu_60ms_trace.csv` | `topology2_balanced_lvrt_0p90pu_60ms.png` | `topology2_balanced_lvrt_0p90pu_60ms.pdf` |
| topology2 A LVRT 0.90 pu / 60 ms | `topology2_a_lvrt_0p90pu_60ms_trace.csv` | `topology2_a_lvrt_0p90pu_60ms.png` | `topology2_a_lvrt_0p90pu_60ms.pdf` |
| topology2 B LVRT 0.90 pu / 60 ms | `topology2_b_lvrt_0p90pu_60ms_trace.csv` | `topology2_b_lvrt_0p90pu_60ms.png` | `topology2_b_lvrt_0p90pu_60ms.pdf` |
| topology2 C LVRT 0.90 pu / 60 ms | `topology2_c_lvrt_0p90pu_60ms_trace.csv` | `topology2_c_lvrt_0p90pu_60ms.png` | `topology2_c_lvrt_0p90pu_60ms.pdf` |
| topology2 AB LVRT 0.90 pu / 60 ms | `topology2_ab_lvrt_0p90pu_60ms_trace.csv` | `topology2_ab_lvrt_0p90pu_60ms.png` | `topology2_ab_lvrt_0p90pu_60ms.pdf` |
| topology2 BC LVRT 0.90 pu / 60 ms | `topology2_bc_lvrt_0p90pu_60ms_trace.csv` | `topology2_bc_lvrt_0p90pu_60ms.png` | `topology2_bc_lvrt_0p90pu_60ms.pdf` |
| topology2 CA LVRT 0.90 pu / 60 ms | `topology2_ca_lvrt_0p90pu_60ms_trace.csv` | `topology2_ca_lvrt_0p90pu_60ms.png` | `topology2_ca_lvrt_0p90pu_60ms.pdf` |
| topology2 BALANCED HVRT 1.10 pu / 60 ms | `topology2_balanced_hvrt_1p10pu_60ms_trace.csv` | `topology2_balanced_hvrt_1p10pu_60ms.png` | `topology2_balanced_hvrt_1p10pu_60ms.pdf` |
| topology2 A HVRT 1.10 pu / 60 ms | `topology2_a_hvrt_1p10pu_60ms_trace.csv` | `topology2_a_hvrt_1p10pu_60ms.png` | `topology2_a_hvrt_1p10pu_60ms.pdf` |
| topology2 B HVRT 1.10 pu / 60 ms | `topology2_b_hvrt_1p10pu_60ms_trace.csv` | `topology2_b_hvrt_1p10pu_60ms.png` | `topology2_b_hvrt_1p10pu_60ms.pdf` |
| topology2 C HVRT 1.10 pu / 60 ms | `topology2_c_hvrt_1p10pu_60ms_trace.csv` | `topology2_c_hvrt_1p10pu_60ms.png` | `topology2_c_hvrt_1p10pu_60ms.pdf` |
| topology2 AB HVRT 1.10 pu / 60 ms | `topology2_ab_hvrt_1p10pu_60ms_trace.csv` | `topology2_ab_hvrt_1p10pu_60ms.png` | `topology2_ab_hvrt_1p10pu_60ms.pdf` |
| topology2 BC HVRT 1.10 pu / 60 ms | `topology2_bc_hvrt_1p10pu_60ms_trace.csv` | `topology2_bc_hvrt_1p10pu_60ms.png` | `topology2_bc_hvrt_1p10pu_60ms.pdf` |
| topology2 CA HVRT 1.10 pu / 60 ms | `topology2_ca_hvrt_1p10pu_60ms_trace.csv` | `topology2_ca_hvrt_1p10pu_60ms.png` | `topology2_ca_hvrt_1p10pu_60ms.pdf` |

## QA Notes

- `_topology2_fault_gallery_contact_sheet.png` gives a visual overview of all 14 traces.
- `trace_gallery_qa_summary.csv` summarizes LV/DC-link window rates and energy-branch action magnitude.
- Review result: this gallery is diagnostic, not final paper-pass evidence. The current active actor shows useful voltage support in several windows, but many cases still show DC-link overvoltage/collapse and near-zero energy-branch action.

Note: these are SAC actor traces only. Conventional-vs-SAC raw waveform overlays require a separate multi-mode trace evaluator.
