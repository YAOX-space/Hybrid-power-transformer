# Stage-5 Voltage-Survival Extension Plan

Date: 2026-07-27

## Starting Point

The Stage-4 r3 reduced matrix established:

- Cases: `144`
- Conventional voltage-survival pass: `48/144`
- SAC voltage-survival pass: `93/144`
- SAC beats conventional: `49/144`
- Traditional fail / SAC pass: `45/144`
- Traditional pass / SAC fail: `0/144`

The next objective is not full FRT certification. The current goal remains
switch-level voltage-survival and beat-conventional boundary evidence.

## Workstream A: Topology2 HVRT Expansion

Manifest:
`version_2/sac/experiments/stage5_topology2_hvrt_expansion_targets_20260727.csv`

Target matrix:

- topology: `topology2`
- fault family: HVRT
- phase modes: balanced, A-phase, AB-phase
- voltage levels: `1.10`, `1.15`, `1.20 pu`
- durations: `80 ms`, `120 ms`

Rationale:

- In Stage-4 r3, conventional dq fails all topology2 HVRT rows in this region.
- SAC currently passes only a small subset.
- Successful expansion here directly increases the traditional-fail / SAC-pass
  boundary area, which is the clearest paper-critical claim.

Execution order:

1. Train A-phase and AB-phase `1.10 pu` at `80/120 ms`.
2. Train balanced `1.15 pu` at `80/120 ms`.
3. Recheck the whole topology2 HVRT target matrix.
4. Probe `1.20 pu`; train only if the 1.10/1.15 trend is stable.

## Workstream B: Topology1 Unbalanced Score Optimization

Manifest:
`version_2/sac/experiments/stage5_topology1_unbalanced_scoreopt_targets_20260727.csv`

Target matrix:

- topology: `topology1`
- phase modes: A-phase and AB-phase
- condition: SAC voltage-survival pass and conventional voltage-survival pass
- objective: reduce SAC score below conventional without breaking envelope,
  recovery, DC-link, or action-limit survival.

Rationale:

- Stage-4 r3 already eliminated traditional-pass / SAC-fail holes.
- The remaining weakness is that many topology1 unbalanced rows are survival
  only, not beat-conventional.
- Score optimization is therefore a quality-improvement objective, not a
  feasibility objective.

Execution order:

1. Start with near-miss rows where SAC score is within about 2 points of
   conventional.
2. Use conservative protected fine-tuning with strong behavior anchors.
3. Promote only actors that beat conventional and keep all voltage-survival
   gates clean.

## Workstream C: Reviewer-Grade Evidence Tables

Evidence tables to maintain after each successful run:

1. Ablation table:
   - teacher trajectory
   - BC
   - BC + DAgger
   - protected SAC fine-tune
   - switch-level pass/score for each stage
2. Conventional baseline tuning table:
   - selected dq/PI profile
   - tuning budget
   - best conventional score/pass per target family
3. Robustness matrix:
   - selected actors versus conventional under parameter perturbations
   - keep this after voltage-survival expansion stabilizes
4. Proxy/switch-level alignment table:
   - proxy prediction
   - switch-level result
   - rank agreement
   - failure modes

## Promotion Rule

An actor is promoted only if it passes switch-level validation. Proxy-only
improvements are recorded as hypotheses, not evidence.
