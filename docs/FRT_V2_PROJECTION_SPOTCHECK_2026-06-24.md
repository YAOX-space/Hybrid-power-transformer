# frt-v2 Reactive Safety-Projection — Small Switching Spotcheck (2026-06-24)

> **Scope & honesty banner.** This is a **small switching-level spotcheck of 8 scenarios**, NOT a
> full-320 run and **NOT a pass rate**. It does **not** modify `lab/results/p3_full320_sw_mi14.mat`,
> `p3_full320_sw_mi7.mat`, or any certified result. **No retraining. No full-320 re-run.** All outputs are
> written to **new files only**. `NOT_EVALUATED` is never counted as PASS; "no-fail / effective" is **not**
> a strict grid-code pass rate.
>
> **Certified result of record — UNCHANGED:** residual SAC mi=14 **strict_pass = 53.1 %**,
> no-fail/effective = 89.4 %, fail = 10.6 % (True/False/NE = 170/34/116). See
> [FRT_V2_RESULTS_2026-06-23.md](FRT_V2_RESULTS_2026-06-23.md).

## What was run

For each selected reactive=FAIL scenario the **same calibrated fault** was simulated twice in the full
switching model (`hpt_frt_full`, Simscape Specialized Power Systems, Ts = 20 µs):

- **baseline** = `mode 14` (deployed residual SAC, the certified controller — byte-identical path);
- **projected** = `mode 16` = `mode 14` **+ deployment-side reactive sign-consistent dead-band** applied
  to the final per-unit reactive command inside the HLC (`build_hpt_frt_full.m`, early remap `mode 16 →
  mode 14` sets `proj_en`; mirrors `src/hpt_frt/device/safety_projection.py`):

  ```
  V+ < 0.9 (under-volt):  if iq < −1e-3  →  iq = 0     % forbid absorbing while sagging
  V+ > 1.1 (over-volt):   if iq > +1e-3  →  iq = 0     % forbid sourcing while swelling
  then |iq| ≤ 0.27  (never grows |iq|; mse_d / mse_q untouched; action stays 3-D)
  ```

Both runs are scored by the single authoritative evaluator `frt_v2_evaluate.m` with the validated
measurement pipeline (cold-start trim, 1-cycle RMS smoothing, retained-min residual, i2 from Ish).
The `mode 14` path is **unchanged**: the projection block executes only when `proj_en` is set (mode 16).

**Scenarios (8 sids, all 4 reactive-FAIL clusters):**

| sid | fault | grid | V+ (Vg_p) | cluster |
|---|---|---|---|---|
| 161, 162 | 2ph | scr10 (strong) | 0.875 | under-volt, symmetric |
| 171, 174 | 2ph | scr3 (weak) | 0.875 | under-volt, weak grid |
| 224, 227 | 2ph_g | scr10 (strong) | 0.833 | under-volt, asymmetric (V2n>0) |
| 311, 312 | swell_1ph | scr3 (weak) | 1.100 | over-volt, exactly at HVRT threshold |

**Baseline reproduces the certified failures:** all 8 scored `reactive = FAIL`, `frt = False` under
`mode 14` — consistent with the full-320 record (these 8 are reactive-FAIL there). This validates that the
spotcheck harness reconstructs the certified scenarios faithfully.

## Per-scenario result (baseline → projected)

Outputs: `lab/results/projection_spotcheck_reactive.{mat,json,csv}`.

| sid | fault / grid | base reactive | proj reactive | base frt | proj frt | wrong-sign base→proj | reactive cleared? | new fails |
|---|---|---|---|---|---|:---:|:---:|:---:|
| 161 | 2ph scr10 | FAIL | **NOT_EVALUATED** | False | None | 1 → **0** | **yes** | none |
| 162 | 2ph scr10 | FAIL | **NOT_EVALUATED** | False | None | 1 → **0** | **yes** | none |
| 171 | 2ph scr3 | FAIL | FAIL | False | False | 1 → 1 | no | none |
| 174 | 2ph scr3 | FAIL | FAIL | False | False | 1 → 1 | no | none |
| 224 | 2ph_g scr10 | FAIL | FAIL | False | False | 1 → 1 | no | none |
| 227 | 2ph_g scr10 | FAIL | FAIL | False | False | 1 → 1 | no | none |
| 311 | swell_1ph scr3 | FAIL | FAIL | False | False | 1 → 1 | no | none |
| 312 | swell_1ph scr3 | FAIL | FAIL | False | False | 1 → 1 | no | none |

**Headline (stated plainly, no spin):**
- The projection **eliminated switching-level reactive wrong-sign in 2 / 8** scenarios (161, 162 —
  strong-grid symmetric 2ph). Even there it converts `FAIL → None`, **not a strict PASS**: with the
  command floored at 0 the tiny droop demand falls below the criterion's support threshold, so reactive
  becomes `NOT_EVALUATED` ("no sustained reactive demand after the response delay").
- **6 / 8 still score `reactive = FAIL`** at switching level (171, 174, 224, 227, 311, 312).
- **No new failures** were introduced anywhere: `connect`, `limit`, `recover`, `survive` stayed `PASS`
  in every scenario (the dead-band never grows |iq| and leaves `mse_d`/`mse_q` untouched).
- The offline static "24/24 would be intercepted" predicate-equivalence does **not** translate into
  switching-level wrong-sign elimination — exactly the caveat the plan flagged.

## Why 6 / 8 are not cleared (trace-level diagnosis)

A focused re-run logging in-window traces (`lab/results/projection_spotcheck_diag.mat`; assessment window
t ∈ [t_f+0.06, t_f+dur]) shows the projection **does fire and does change the command** in every case
(`max|cmd_base − cmd_proj|` = 0.006–0.014 pu) and **sharply cuts wrong-sign occurrences** — but not to the
hard zero the criterion demands. Wrong-sign sample counts (MEASURED iq / COMMANDED iq, in-window):

| sid | base measured / commanded | proj measured / commanded |
|---|---|---|
| 161 (strong 2ph) | 8 / 8 | **0 / 0** |
| 171 (weak 2ph) | 1317 / 1401 | 1048 / 914 |
| 224 (strong 2ph_g) | 5186 / 5467 | 450 / 668 |
| 311 (HVRT swell_1ph) | 5582 / 5527 | 2268 / 664 |

> Note: this **corrects** an earlier hypothesis that "the command is already correct-sign / the dead-band
> never triggers." It does trigger — heavily (sid224 commanded-wrong 5467→668; sid311 5527→664). The
> failure is not inaction; it is that a command-only clip can't reach zero wrong-sign here.

Three mechanisms, all fundamental to a *command-only* post-processing dead-band:

1. **The criterion FAILs on _any_ single wrong-sign sample** (`any(V+<0.9 & iq<−ε)` …). Projection removes
   ~80–90 % of wrong-sign samples, but one survivor still trips `FAIL`. Only sid161/162 reach an exact zero.

2. **Filtered V+ (gate) vs evaluator V1 (score) disagree at the boundary.** The projection gate keys on the
   HLC's heavily **filtered positive-sequence V2p** (`af = 0.005`); the evaluator scores against a
   **1-cycle-RMS V1**. At near-boundary V+ (0.875, 0.833, and especially **1.10 — exactly the HVRT
   threshold**) the two straddle 0.9 / 1.1 differently instant-to-instant, so the gate is *open* on samples
   the evaluator counts as in-region → residual commanded wrong-sign survives (sid171 914, sid224 668,
   sid311 664).

3. **Measured-vs-commanded gap (plant dynamics / ripple).** The criterion scores the **measured** dq-axis
   current; converter + PLL dynamics and asymmetric-fault 2ω ripple push measured iq to the wrong side even
   where the *command* is corrected. This dominates the HVRT case: sid311 measured-wrong (2268) ≫
   commanded-wrong (664). A command dead-band cannot remove these.

4. **Why 161/162 succeed:** the strong symmetric grid holds V+ steadily and clearly below 0.9, so filtered
   V2p and the evaluator's V1 agree throughout → the gate stays closed on every wrong-sign instant → the
   small baseline violation (8 samples) is fully removed; the residual demand is then so small that reactive
   becomes `NOT_EVALUATED`.

## Honest conclusion

The deployment-side reactive dead-band is **correctly implemented, active, and safe** (it fires, never
grows |iq|, touches nothing else, introduces no new failures) and **fully clears the clean strong-grid
symmetric under-volt case**. But as a *command-only* projection keyed on the controller's filtered V+, it
is **necessary-but-insufficient** at switching level for the weak-grid, asymmetric, and exact-boundary
(V+ = 1.10) clusters, because (i) the reactive criterion has zero tolerance for wrong-sign samples,
(ii) the gate's filtered V+ disagrees with the evaluator's 1-cycle V1 near the threshold, and (iii) the
*measured* current can violate the sign even when the command is correct.

This spotcheck therefore makes **no** claim of any improvement to the full-320 pass rate.

## Is a projected full-320 worth it? — Not yet.

A command-side projection clears only 2/8 of the spotchecked reactive FAILs, so a projected full-320 is
**not** justified at this stage. Suggested next steps (NOT done here — each needs validation, possibly
retraining):

1. **Align gate to the score:** engage the projection on V+ within a hysteresis margin of the thresholds,
   using the same 1-cycle V1 the evaluator uses, so the gate closes on every in-region instant.
2. **Fix the measured-current sign, not just the command:** a small droop-proportional positive-iq *floor*
   during under-volt (negative floor during over-volt), or negative-sequence-aware reactive control —
   beyond a pure post-processing dead-band.
3. **Targeted retraining** over-weighting these clusters (weak-grid 2ph V+0.875, asymmetric 2ph_g V+0.833,
   boundary swell_1ph V+1.10) — only if the cheaper controller-side fixes prove insufficient.
4. Only if a revised projection clears the spotcheck would a clearly-labelled projected-vs-baseline
   full-320 (separate result file, **never** overwriting `p3_full320_sw_mi14.mat`) be warranted.

The HVRT deep-swell `survive` cluster (10 sids, swell_3ph V+1.30) is **not** addressed here — it is a
DC-bus survival issue, unrelated to the reactive sign projection (plan-only, see
[FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md](FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md)).

## Provenance / governance

- **Files added/changed (new files only):** `lab/simulink/frt_v2_projected_spotcheck.m` (spotcheck driver
  + JSON/CSV writer), `lab/results/projection_spotcheck_reactive.{mat,json,csv}`,
  `lab/results/projection_spotcheck_diag.mat`, this document. The `mode 16 / proj_en` projection path in
  `lab/simulink/build_hpt_frt_full.m` is an additive branch; the `mode 14` certified path is byte-identical.
- **Untouched:** `lab/results/p3_full320_sw_mi14.mat`, `p3_full320_sw_mi7.mat`,
  `p3_full320_switching_summary.json`, and every certified result/value.
- **Tests:** `pytest tests -p no:cacheprovider -q` → **134 passed** (incl. the 10 `safety_projection` unit
  tests), run in the project `.venv`.
