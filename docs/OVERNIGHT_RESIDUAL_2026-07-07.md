# Overnight residual SAC experiment - 2026-07-07

## Goal

Train the residual SAC policy, export the best available candidate, run ODE and
switching verification, and keep the project on the best certified switching
artifact.

## Changes tested

- ODE-visible instrumentation was added to the mi14 error-analysis loop.
- The ODE environment now uses the same effective fault-duration cap as the
  switching script for long faults.
- Residual SAC received asymmetric LVRT V2n feed-forward for the blind
  measured-iq wrong-sign cluster.
- Export selection can evaluate raw/EMA checkpoints on the full-320 ODE proxy.
- The switching script now loads the residual MAT policy for mi14 instead of
  the generic actor MAT.

## Training result

Run directory:

`lab/results/overnight_residual_20260707_023134`

Best validation proxy checkpoints:

| candidate | checkpoint | validation proxy |
|---|---:|---:|
| raw best | 125000 | 100.0% |
| EMA best | 25000 | 100.0% |

Full-320 ODE proxy candidate scores:

| candidate | partial proxy | Vdc proxy | decided FAIL |
|---|---:|---:|---:|
| sac_residual_best.zip | 93.8% | 93.8% | 20 |
| sac_residual_ema_best.zip | 93.8% | 93.8% | 20 |
| sac_residual_final.zip | 78.1% | 93.8% | 70 |
| sac_residual_ema_final.zip | 87.5% | 93.8% | 40 |

## Switching verification

The new checkpoints did not beat the existing certified switching baseline.

| artifact | true | false | none | no-fail pct | status |
|---|---:|---:|---:|---:|---|
| baseline restored active | 170 | 34 | 116 | 89.4% | best certified |
| overnight EMA best | 130 | 36 | 154 | 88.8% | archived |
| overnight raw best | 120 | 50 | 150 | 84.4% | archived |

Active restored artifact:

`lab/results/p3_full320_sw_mi14.mat`

Archived failed experiments:

- `lab/results/overnight_residual_20260707_023134/switching_ema_best_result/`
- `lab/results/overnight_residual_20260707_023134/switching_raw_best_result/`

## Error analysis of raw-best switching result

Raw-best switching result had 50 FAIL out of 320:

- survive: 30
- reactive: 20
- sym3ph: 20
- swell_3ph: 10
- swell_1ph: 20
- ODE visibility: 40 BLIND, 10 VISIBLE

This is the main conclusion: the ODE improvements made the ODE proxy look much
better, but did not close the switching-level gap. The next optimization step
should target the ODE-blind switching dynamics before spending more SAC training
budget.

## Current project state

The active mi14 switching artifact and Simulink residual MAT weights were
restored to the best certified baseline. The overnight SAC checkpoints remain in
`data/models` and the run directory for later analysis.
