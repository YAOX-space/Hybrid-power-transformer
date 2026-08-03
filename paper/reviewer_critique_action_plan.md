# HPT Voltage-Survival Paper: Reviewer-Critique Action Plan

Date: 2026-07-25

This note converts the pasted critique into a paper-hardening plan. It is not a research log and should not be cited as evidence. Its purpose is to prevent the manuscript from overclaiming and to define the minimum evidence package needed before submission or defense.

## 1. Claim Boundary Fixes

### 1.1 Rename the contribution

Current risk:

The phrase "Specialist SAC FRT controller" can be read as a full grid-code FRT controller trained mainly by SAC.

Required manuscript position:

```text
switch-level-promoted, case-specialized load-side voltage-survival policy
using a SAC-compatible actor architecture with BC/DAgger and limited SAC fine-tuning
```

Allowed claims:

- The accepted actors are case-specialized policies.
- The current pass gate is load-side voltage survival.
- Some local boundary probes show traditional fail / specialist pass.
- The final evidence is switch-level Simulink validation, not proxy reward.

Disallowed claims:

- Unified HPT FRT controller.
- Full GB/T or grid-code FRT certification.
- General boundary surface over all 630 scenarios.
- Plain SAC trained from scratch solved the task.

### 1.2 Separate four validation layers

| Layer | Name | Required metrics | Current status |
| --- | --- | --- | --- |
| L1 | Load-side voltage survival | timestep LV envelope, fault band, recovery band, DC link survival, action limit | current paper evidence |
| L2 | Current-safe survival | L1 + grid/converter current limit | diagnostic only |
| L3 | Reactive-support FRT | L2 + reactive current support and response delay | not completed |
| L4 | Full FRT certification | L3 + complete GB/T recovery and robustness | not claimed |

Every result table must state which layer it supports.

## 2. Minimum Evidence Package Before Stronger Claims

### 2.1 Per-case metric table

For every accepted and rejected case, report:

- LV fault-window min / max / mean.
- LV recovery min / max / mean.
- Maximum timestep envelope violation.
- Fault-band violation and duration.
- Recovery-band violation and duration.
- Vdc min / max and margin to bounds.
- Grid current peak.
- Reactive-current shortfall if evaluated.
- Action max and action slew.
- Chopper threshold / rchop_scale / actor_filter_tau.
- Pass/fail reason.

This prevents pass/fail results from hiding current or recovery problems.

### 2.2 Feasibility versus quality

Report two different comparisons:

```text
feasibility improvement:
  conventional fails gate, specialist passes gate

quality improvement:
  both pass gate, specialist has lower continuous score
```

Do not use `+100 fail penalty` to imply better control quality. It only encodes feasibility.

### 2.3 Conventional baseline protocol

Add a reproducible baseline section:

- Physical controller path for topology1.
- Conventional-like fallback path for topology2.
- Why topology2 physical conventional cannot be used as-is.
- Parameter table.
- Search range or manual tuning process.
- Tuning budget.
- Objective function.
- Whether conventional receives topology/fault specialist tuning.
- Failure matrix for conventional.

### 2.4 Ablation for the "SAC" name

Required ablation:

| Variant | Purpose |
| --- | --- |
| Teacher trajectory direct replay | Shows whether neural policy adds anything beyond replay |
| BC actor | Shows actor approximation of teacher |
| BC + DAgger | Shows state-distribution correction |
| BC + DAgger + SAC fine-tune | Shows marginal SAC contribution |

Report each variant on the same switch-level cases and same validator.

## 3. Observability and Deployment Questions

### 3.1 Remove oracle ambiguity

For every observation channel, classify it as:

- Direct measurement.
- Filtered estimate.
- Known plant configuration.
- Fault detector output.
- Simulation-only input.

Current risky channels:

- fault/recovery flag.
- fault elapsed time.
- recovery elapsed time.
- fault min/max.

Required future test:

Replace simulation-schedule flags with a measurement-only detector and report:

- detection delay;
- false trigger behavior;
- noise robustness;
- actor performance with delayed flags.

### 3.2 Specialist selector

Current specialist results do not answer deployment selection. Add a future section:

- How topology is known.
- How LVRT/HVRT and phase mode are identified.
- How fault depth and duration are estimated online.
- What happens for 0.87 pu / 95 ms / BC-phase cases.
- How actor switching avoids bumps.
- Safe fallback if specialist confidence is low.

## 4. Gate and Score Robustness

### 4.1 Gate definitions needing justification

Explain or revise:

- 1e-3 pu tolerance.
- "Every timestep" means evaluator timestep, not necessarily switching solver micro-step.
- Fault-window band 176-238 V.
- Recovery band and 35 ms settle delay.
- Episode length 0.22 s versus GB/T envelopes that extend longer.
- Use of GB/T 19963.1-2021 as inspiration, not direct certification standard for load-side HPT voltage survival.

### 4.2 Score sensitivity

Run score sensitivity on accepted and boundary cases:

- current weight: 25 / 50 / 100.
- recovery weight: 60 / 120 / 240.
- fail penalty: 50 / 100 / 200.
- continuous score without fail penalty.

Expected output:

- whether "beat conventional" is stable under score weights;
- which cases are feasibility-only wins.

## 5. Proxy Evidence Upgrade

### 5.1 Split proxy alignment into four levels

Do not report only calibration-point MAE.

Required proxy alignment categories:

| Category | Meaning |
| --- | --- |
| Calibration replay error | table or interpolation point reproduction |
| Hold-out fixed-action error | unseen fixed action in same topology/fault family |
| Hold-out trajectory rollout error | dynamic trajectory prediction |
| Ranking correlation | Spearman / top-k overlap for candidate selection |

### 5.2 Energy branch warning

The energy sweep ranking is weak. Any training or search using energy action must include:

- command-to-measured response mapping;
- support-domain distance;
- action cloud versus calibration support;
- rejected OOD candidate log.

## 6. Reproducibility Package

For each accepted actor, record:

- Git commit.
- Dirty-state flag.
- actor zip/MAT SHA256.
- training dataset SHA256.
- teacher trajectory SHA256.
- exact training command.
- exact MATLAB validation command.
- MATLAB/Simulink version.
- solver settings.
- result run id.
- accepted/rejected manifest row.

Historical accepted CSVs without these hashes should be treated as preliminary evidence, not final paper artifact.

## 7. Robustness Matrix

Before claiming robustness, run at least:

- 3-5 random seeds for training or BC initialization.
- fault inception angle variation.
- PWM initial phase variation.
- measurement noise.
- solver tolerance variation.
- small load perturbation.
- SCR/XR perturbation.

For the current paper stage, this can be a reduced robustness matrix on the strongest 4-6 cases.

## 8. Immediate Edits Already Applied

Applied to `paper/hpt_sac_voltage_survival_manuscript.md`:

- Title downgraded to load-side voltage survival.
- Abstract changed from "Specialist SAC FRT controller" to SAC-compatible case-specialized policy.
- Explicit note added that current accepted policies are mainly BC/DAgger with limited SAC fine-tuning.
- 630 scenario matrix marked as planned, not completed.
- Observability risk of fault/recovery flags stated.
- Specialist selector and bumpless transfer left as future work.
- Baseline fairness caveat added.
- Feasibility improvement separated from quality improvement.
- Four-layer validation boundary added.

## 9. Next Experimental Priorities

1. Generate the per-case metric table for the existing 8 + 6 cases. **Status: done for available CSV metrics in `paper/evidence/per_case_metrics.csv`.**
2. Add actor/data/Git hash manifest for all accepted specialists. **Status: partial; actor and control CSV hashes are recorded in `paper/evidence/reproducibility_manifest.csv`, but training dataset hashes, teacher trajectory hashes, exact training commands, MATLAB version, and solver settings remain missing.**
3. Re-run conventional baseline tuning documentation or create a conventional tuning appendix. **Status: first fresh tuning sweep completed in `lab/results/hpt_reviewer_evidence_20260725_baseline`, but the tested conventional scale sweep produced `0/12` voltage-survival pass for each scale and does not yet establish a strong mixed pass/fail baseline.**
4. Run teacher / BC / BC+DAgger / BC+DAgger+SAC ablation on the best topology2 A-HVRT and one topology1 LVRT case. **Status: fresh switch-level teacher / BC / BC+DAgger recheck completed in `lab/results/hpt_reviewer_evidence_20260725_ablation_v2`. topology2 A-HVRT 1.05 pu / 60 ms passes for teacher, BC, and BC+DAgger; topology1 balanced LVRT 0.90 pu / 80 ms passes for teacher replay but fails for promoted BC and BC+DAgger actors. A naive topology2 BC+DAgger+SAC fine-tune row in `lab/results/hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_sacft` failed switch-level validation: score `294.7297`, LV mean/recovery `78.98/80.85 V`, Vdc max `1066.92 V`, action max `1.131`. Follow-up protected SAC fine-tune runs show why the mechanism matters: `hpt_protected_sacft_t2_a_hvrt105_20260725_tinyanchor` was stable but effectively frozen (`2.68e-9` score delta), while `hpt_trustregion_sacft_t2_a_hvrt105_20260726_mediumanchor` produced a valid trust-region SAC improvement on topology2 A-HVRT: score `125.8084` versus BC+DAgger `125.8460`, delta `0.0376`, zero voltage-survival envelope violations. This is now positive evidence for local protected SAC fine-tuning on one representative case, but still not full FRT certification.**
5. Run score sensitivity on all accepted and reduced-boundary cases. **Status: done for current reconstructed score variants in `paper/evidence/score_sensitivity.csv`.**
6. Add current peak and Vdc margin columns to all result tables. **Status: done in `paper/evidence/per_case_metrics.csv` and `paper/evidence/paired_case_comparison.csv` where source CSV fields exist.**

Additional completed infrastructure check:

- MATLAB command-line interface smoke passed for topology1/topology2 24-D observation and 4-D action contract using `test_hpt_v2_sac_interface.m`.

Additional reviewer-evidence runs completed on 2026-07-25:

- Proxy holdout alignment: completed in `lab/results/hpt_reviewer_evidence_20260725_proxy_v2`. One local support-domain matrix aligns near exactly; one broader envelope-aware matrix shows non-trivial LV/Vdc/recovery mismatch. Proxy is therefore usable for screening and warm-start, but not as final evidence.
- Reduced robustness matrix: completed in `lab/results/hpt_reviewer_evidence_20260725_robustness`. The reduced two-specialist set passes voltage survival for fault-start +/-5 ms and Rchop +10%; actor filter tau = 2 ms passes only 1/2 cases. Full FRT pass remains zero.
- Paper-facing addendum: summarized in `paper/evidence/REPORT.md` and detailed in `paper/evidence/reviewer_evidence_experiment_report_2026-07-25.md`.

Only after these steps should the paper move from "internal report" toward submission-grade manuscript.
