# Evidence And Claim Protocol

## Evidence Passport

Every promoted result or quantitative paper claim must identify:

- claim id and exact wording;
- evidence rung;
- run id and result directory;
- Git commit and dirty status;
- MATLAB/Simulink version and required products;
- topology model path and SHA-256;
- validator path, gate configuration, and SHA-256;
- actor path and SHA-256;
- dataset and proxy-calibration paths and hashes when applicable;
- scenario matrix and train/validation/holdout split;
- baseline identity and tuning budget;
- metrics, pass counts, confidence or seed variation where applicable;
- known limitations and excluded claims.

Use `version_2/sac/experiment_metadata.py` for machine metadata and add missing
passport fields through its `extra` section. A manuscript table or figure must
point to the compact report or manifest carrying this information.

## Claim Ladder

| Rung | Allowed claim |
| ---: | --- |
| 0 | Proposed mechanism or plan only |
| 1 | Proxy behavior or training diagnostic |
| 2 | Proxy aligned on untouched holdout cases for the declared metric |
| 3 | Exact actor validated on one switch-level case |
| 4 | One unchanged actor validated across a declared switch-level family |
| 5 | Boundary expansion, robustness, or statistically supported superiority |
| 6 | Full FRT under every explicitly declared voltage, current, reactive-support, recovery, DC-link, and device gate |

State the rung in promotion reports. A higher rung requires all lower-rung
contracts relevant to the claim; it is not obtained by stronger prose.

## Proxy Alignment Layers

Report these separately:

1. observation and unit alignment;
2. single-step or fixed-action response alignment;
3. reward-component and pass/fail alignment;
4. policy-trajectory rollout ranking on untouched holdout trajectories.

Excellent fixed-action rank correlation does not establish trajectory ranking
near a hard DC-link or current gate. When layer 4 fails, stop proxy-only policy
selection and collect local switch-level trajectories.

## Promotion Decisions

- `promote`: exact checkpoint passes the declared switch-level gate and the
  evidence passport is complete.
- `diagnostic`: valid evidence that does not support promotion.
- `rerun`: environment or transient failure invalidated the result.
- `debug`: implementation, model, or interface defect prevents interpretation.
- `retire`: superseded result retained for provenance.

Do not silently omit failed seeds, failed matrix cells, or baseline wins.

## Academic Review Use

Use an academic-research workflow for source discovery, claim-reference
alignment, and adversarial manuscript review. Do not delegate the scientific
promotion decision to a writing workflow. The switch-level gate and evidence
passport remain authoritative.

The evidence-passport, claim-drift, verification, and staged-review ideas are
adapted for this project from ARS-Codex:
https://github.com/Imbad0202/academic-research-skills-codex

Do not adopt its conservative experiment-run restriction as the HPT execution
policy. This skill is explicitly responsible for editing, debugging, retrying,
and validating project code when the user requests autonomous research.
