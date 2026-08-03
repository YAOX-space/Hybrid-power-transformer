# Stage-5 Reviewer Evidence Refresh, 2026-07-27

This note records a fresh reviewer-evidence campaign for the current
Stage-5 voltage-survival workflow. It supplements, but does not replace, the
main manuscript. The evidence below supports a bounded claim: selected
switch-level-promoted, case-specialized policies can achieve load-side
voltage survival and beat the tested conventional baseline in specific
boundary cases. It does not support full FRT certification.

## Campaign

- Run id: `hpt_reviewer_evidence_stage5_20260727`
- Run directory: `lab/results/hpt_reviewer_evidence_stage5_20260727`
- Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_reviewer_evidence_campaign --run-id hpt_reviewer_evidence_stage5_20260727 --stage all --ablation-epochs 120 --max-ablation-cases 2 --max-baseline-param-sets 3 --max-proxy-matrices 2 --max-robustness-cases 4 --max-robustness-variants 4 --matlab-timeout-s 2400 --ablation-timeout-s 3000 --proxy-timeout-s 1200 --robustness-timeout-s 3000
```

- Subprocesses: `15`
- Nonzero subprocesses: `0`
- Campaign index: `lab/results/hpt_reviewer_evidence_stage5_20260727/campaign_results.csv`

The campaign runner was updated so robustness variants default to
`version_2/sac/experiments/stage4_promoted_specialists_20260727.csv` rather
than the older 20260722 accepted manifest. A proxy-summary parsing bug was
also fixed and verified with:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_reviewer_evidence_campaign --run-id hpt_reviewer_evidence_stage5_proxyfix_20260727 --stage proxy --max-proxy-matrices 2 --proxy-timeout-s 1200
```

## Ablation

| Case | Teacher replay | BC actor | BC + DAgger actor | Interpretation |
| --- | ---: | ---: | ---: | --- |
| topology2 A-HVRT 1.05 pu / 60 ms | pass, beat, score `126.275` | pass, beat, score `126.052` | pass, beat, score `125.846` | The neural actor reproduces and slightly improves the feasible trajectory under switch-level validation. |
| topology1 balanced LVRT 0.90 pu / 80 ms | pass, beat, score `160.680` | fail, score `166.176` | fail, score `157.561` | The teacher trajectory is feasible, but BC/DAgger imitation still violates timestep gates. |

The topology1 BC failure reason was
`timestep_fault_lv_band;timestep_voltage_envelope`. The topology1 DAgger
failure reason was `timestep_recovery_envelope`. This is important because the
continuous score can improve while the hard timestep voltage-survival gate
still fails.

## Conventional Baseline Tuning

| Scale label | Reg scale | Energy scale | Cases | Voltage-survival pass | Full FRT pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| scale045 | 0.45 | 0.45 | 12 | 0 | 0 |
| scale055 | 0.55 | 0.55 | 12 | 0 | 0 |
| scale070 | 0.70 | 0.70 | 12 | 0 | 0 |

Dominant voltage-survival failure modes were combinations of:

- `timestep_voltage_envelope`
- `timestep_fault_lv_band`
- `timestep_recovery_envelope`
- `dc_link_bounds`

This does not yet prove a fully tuned strong conventional baseline. It does
provide a reproducible negative tuning sweep under the current strict
timestep validator.

## Proxy Holdout Alignment

Proxy-only evidence remains bounded. The proxy can reproduce its local support
domain nearly exactly, but it still has non-trivial error on broader matrices.

| Matrix | Rows | LV mean MAE | Vdc mean MAE | Grid iq MAE | Envelope max MAE | Fault-band max MAE | Recovery max MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pilot_all_20260721_175951` | 52 | `4.75e-11` | `2.21e-11` | `7.75e-10` | `1.88e-10` | `4.21e-10` | `6.12e-10` |
| `pilot_all_20260721_193807` | 104 | `0.0307` | `0.0262` | `0.0442` | `0.00488` | `0.0198` | `0.00589` |

The safe interpretation is unchanged: use the proxy for screening, warm start,
and local search, but require switch-level promotion for accepted claims.

## Reduced Robustness Matrix

Robustness was rerun on four current promoted specialists from the Stage-5
manifest.

| Variant | Cases | Voltage-survival pass | Beat conventional | Full FRT pass |
| --- | ---: | ---: | ---: | ---: |
| fault start +5 ms | 4 | 3 | 3 | 0 |
| fault start -5 ms | 4 | 2 | 2 | 0 |
| Rchop +10% | 4 | 3 | 3 | 0 |
| actor filter tau = 2 ms | 4 | 2 | 2 | 0 |

Failure examples:

- `topology2 balanced LVRT 0.90 / 60 ms` is sensitive to fault-start shifts
  and Rchop changes, with failures including `dc_link_bounds`,
  `timestep_recovery_envelope`, and `timestep_voltage_envelope`.
- `topology1 balanced LVRT 0.90 / 60 ms` fails when actor filter tau is
  increased to 2 ms because recovery-envelope tracking degrades.
- Full FRT remains failed in all robustness variants, mainly due to
  `grid_current_limit`, `gbt_recover`, and reactive-current diagnostics.

## Stage-5 Topology1 Score-Optimization Diagnostic

Two topology1 A-phase LVRT 0.85 pu / 80 ms diagnostics were run before the
reviewer-evidence campaign:

- Protected proxy-SAC fine-tune preserved voltage survival but did not improve
  the accepted score.
- A refined two-stage trajectory sweep over `fault_reg_d` and
  `recovery_reg_d` found no valid point that beat conventional.

Best voltage-survival point in the refined sweep:

- `fault_reg_d = 0.55`, `recovery_reg_d = 0.28`
- trajectory score: `148.131`
- conventional score: `146.777`
- voltage-survival pass: `true`
- full-FRT reason: `gbt_recover;grid_current_limit;reactive_wrong_sign`

The lower-score `fault_reg_d = 0.60` candidates were rejected by the hard gate
because they violated `dc_link_bounds`. This case remains a genuine boundary
where the current simple trajectory family cannot beat the tested
conventional controller.

## Evidence Boundary After This Refresh

Completed:

- Fresh ablation for two representative cases.
- Fresh conventional-scale sweep under the current strict timestep validator.
- Fresh proxy holdout alignment with corrected summary extraction.
- Fresh four-variant reduced robustness check on the latest promoted manifest.
- Additional topology1 unbalanced score-optimization diagnostics.

Still not completed:

- A broad mixed pass/fail conventional boundary from a fully tuned dq/PI
  controller.
- Global proxy alignment reliable enough for final policy selection.
- Robustness across inception angle, load perturbation, SCR/XR, noise, and
  solver tolerance.
- Full FRT certification with grid-current limits, reactive-current support,
  and complete recovery criteria.
