# Reviewer Evidence Experiment Report, 2026-07-25

This document records the newly executed evidence experiments for the reviewer critique items: ablation, baseline tuning, proxy holdout alignment, and robustness. The conclusions below are based only on fresh runs from this campaign. Older CSV files are not treated as completed reviewer evidence unless they were rechecked by the current validator.

## 1. Campaign Runner

New unified entry point:

- `version_2/sac/campaigns/run_hpt_reviewer_evidence_campaign.py`

Purpose:

- fix run IDs, commands, logs, and output directories;
- avoid mixing stale results into paper evidence;
- keep the reviewer evidence runs reproducible.

Syntax check passed:

```powershell
py -3 -m compileall version_2/sac/campaigns/run_hpt_reviewer_evidence_campaign.py
```

## 2. Ablation Evidence

Run directory:

- `lab/results/hpt_reviewer_evidence_20260725_ablation_v2`

Representative cases:

- topology2 A-phase HVRT 1.05 pu / 60 ms
- topology1 balanced LVRT 0.90 pu / 80 ms

Fresh stages:

- teacher replay
- BC actor
- BC+DAgger actor
- naive BC+DAgger+SAC fine-tune
- trust-region protected SAC fine-tune

Summary:

| Case | Teacher replay | BC actor | BC+DAgger actor | Naive SAC fine-tune | Trust-region protected SAC fine-tune | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| topology2 A-HVRT 1.05/60 ms | pass, beat conventional | pass, beat conventional | pass, beat conventional | fail | pass, improves over BC+DAgger | BC/DAgger is the feasible warm start; unconstrained proxy SAC breaks it, while local trust-region SAC gives a small switch-level policy-improvement result. |
| topology1 balanced LVRT 0.90/80 ms | pass, beat conventional | fail | fail | not run | not run | The teacher trajectory is feasible, but the promoted BC/DAgger actor does not reproduce it reliably. |

Key values:

- topology2 teacher trajectory score: 126.2748; conventional score: 145.4778.
- topology2 BC+DAgger actor score: 125.8460; conventional score: 145.4778.
- topology2 naive BC+DAgger+SAC fine-tune score: 294.7297; conventional score: 145.4778.
- topology2 trust-region protected SAC fine-tune best score: 125.8084; BC+DAgger baseline score: 125.8460; switch-level improvement: 0.0376.
- topology1 teacher trajectory score: 160.6802; conventional score: 169.1727.
- topology1 BC/DAgger promoted actor failed voltage survival; therefore imitation alone is not enough for that case.

Naive SAC fine-tune result:

- The topology2 fine-tuned actor failed switch-level voltage survival.
- Failure details: LV mean/recovery were 78.98/80.85 V, Vdc max was 1066.92 V, and action max was 1.131.
- The fine-tune run is therefore diagnostic negative evidence against unconstrained proxy SAC.  It does not support a claim that naive proxy SAC fine-tune improves over DAgger.
- topology1 fine-tune was not run because the BC/DAgger actor already failed; imitation must be fixed before a SAC fine-tune ablation is meaningful.

Protected SAC fine-tune follow-up:

- A chunked, switch-level-gated runner was added at
  `version_2/sac/campaigns/run_hpt_protected_sac_finetune.py`.
- Run `hpt_protected_sacft_t2_a_hvrt105_20260725` used 100 proxy-SAC steps
  per chunk.  Chunk 1 preserved voltage survival but did not improve over
  BC+DAgger; chunk 2 failed the recovery-envelope gate.
- Run `hpt_protected_sacft_t2_a_hvrt105_20260725_tinyanchor` used 20 proxy-SAC
  steps per chunk, stronger behavior anchoring, and lower exploration.  It ran
  8/8 chunks without voltage-survival failure, but the best score delta versus
  BC+DAgger was only 2.68e-9, below the 1e-3 meaningful-improvement threshold.
  Later chunks degraded the score from 125.8460 to 126.4266.
- Run `hpt_trustregion_sacft_t2_a_hvrt105_20260726_seedsearch` added an
  `advance-policy=improve` local trust-region gate.  All 10 candidates passed
  voltage survival, but none improved over BC+DAgger; the strong anchor mostly
  froze the policy.
- Run `hpt_trustregion_sacft_t2_a_hvrt105_20260726_mediumanchor` relaxed the
  anchor and kept switch-level rollback.  Chunk 3 passed voltage survival with
  zero timestep-envelope, recovery, and fault-band violations.  It improved
  the switch-level score from 125.8460 to 125.8084.  The improvement is 0.0376,
  above the 1e-3 meaningful-improvement threshold.
- Conclusion: switch-level chunk gating is useful as a safety mechanism, and
  local trust-region SAC can provide a small but real policy-improvement
  contribution on the topology2 A-HVRT representative case.  This remains a
  voltage-survival result only; full FRT still fails on
  `gbt_recover;grid_current_limit`.

## 3. Baseline Tuning Evidence

Run directory:

- `lab/results/hpt_reviewer_evidence_20260725_baseline`

Conventional dq parameter sweep:

| Label | reg scale | energy scale | Cases | Voltage-survival pass | Full FRT pass |
|---|---:|---:|---:|---:|---:|
| scale045 | 0.45 | 0.45 | 12 | 0 | 0 |
| scale055 | 0.55 | 0.55 | 12 | 0 | 0 |
| scale070 | 0.70 | 0.70 | 12 | 0 | 0 |

Additional shallow sanity sweep:

- LVRT: 0.995 / 0.990 / 0.980 pu
- HVRT: 1.005 / 1.010 / 1.020 pu
- duration: 60 ms
- reg scale = 0.55
- energy scale = 0.55

The shallow sweep also produced 0/12 voltage-survival pass.

Dominant failure reasons:

- timestep recovery envelope;
- timestep fault LV band;
- DC-link bounds;
- timestep voltage envelope.

Interpretation:

- Under the current strict validator, this conventional dq sweep did not produce a mixed pass/fail boundary.
- This should not be written as "SAC beats a strong conventional baseline" yet.
- A stronger conventional tuning protocol is still required, including PI/dq gains, sag/swell scale, recovery damping, energy scale, and chopper/DC parameters.

## 4. Proxy Holdout Alignment Evidence

Run directory:

- `lab/results/hpt_reviewer_evidence_20260725_proxy_v2`

The old 20260718 holdout matrices were not used as current paper evidence because they do not contain the current validator fields:

- `envelope_violation_max_pu`
- `fault_lv_band_violation_max_pu`
- `recovery_violation_max_pu`

Envelope-aware matrices were used instead.

Summary:

| Matrix | Rows | LV mean MAE | Vdc mean MAE | Envelope max MAE | Fault-band max MAE | Recovery max MAE | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| pilot_all_20260721_175951 | 52 | ~4.75e-11 | ~2.21e-11 | ~1.88e-10 | ~4.21e-10 | ~6.12e-10 | Near-exact replay inside the calibration support domain. |
| pilot_all_20260721_193807 | 104 | 0.0307 pu | 0.0262 pu | 0.00488 pu | 0.0198 pu | 0.00589 pu | Non-trivial mismatch on the broader matrix, especially Vdc and recovery tail behavior. |

Interpretation:

- The proxy is reliable in the local support domain.
- The proxy is not yet globally trustworthy as the only training/evaluation environment.
- The current safe usage is proxy-based screening, warm start, and trajectory search, followed by switch-level validation for promotion.

## 5. Robustness Evidence

Run directory:

- `lab/results/hpt_reviewer_evidence_20260725_robustness`

Reduced matrix: two accepted specialists.

| Variant | Cases | Voltage-survival pass | Beat conventional | Full FRT pass |
|---|---:|---:|---:|---:|
| fault_start +5 ms | 2 | 2 | 2 | 0 |
| fault_start -5 ms | 2 | 2 | 2 | 0 |
| Rchop +10% | 2 | 2 | 2 | 0 |
| actor filter tau = 2 ms | 2 | 1 | 1 | 0 |

Interpretation:

- The two accepted specialists are robust to small fault-timing shifts and Rchop +10% under the voltage-survival gate.
- The actor output filter time constant is sensitive: tau = 2 ms breaks one of two cases.
- Full FRT pass remains zero; this is not a full FRT certification result.

## 6. Evidence Status

Completed in this run:

- new reviewer evidence campaign runner;
- fresh ablation recheck for teacher / BC / BC+DAgger, plus a topology2 BC+DAgger+SAC fine-tune negative row;
- first systematic conventional baseline scale sweep;
- envelope-aware proxy alignment check;
- reduced robustness matrix.

Still missing:

- a successful BC+DAgger+SAC fine-tune ablation row with meaningful
  switch-level score improvement;
- a convincing strong conventional baseline tuning protocol;
- strict calibration / validation / holdout split for proxy alignment;
- expanded robustness matrix;
- full FRT certification including reactive current, grid current limit, and recovery criteria.

## 7. Immediate Next Work

1. Redesign SAC fine-tune before re-running: naive proxy fine-tune failed
   switch-level validation, while protected tiny-step fine-tune preserved
   voltage survival but produced no meaningful improvement.
2. Expand conventional baseline tuning to PI/dq gains, sag/swell scale, recovery damping, energy scale, and chopper/DC parameters.
3. Regenerate a stratified proxy matrix split into calibration, validation, and holdout sets by topology, fault type, balanced/unbalanced class, action group, and trajectory rollout.
4. Expand robustness from the reduced check to fault inception angle, load perturbation, SCR/XR, measurement noise, and solver tolerance.
5. Keep the paper claim bounded: the current evidence supports switch-level voltage-survival specialist behavior, not a full FRT-certified controller.
