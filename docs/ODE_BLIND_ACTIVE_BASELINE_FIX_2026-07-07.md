# Active-baseline ODE-blind fix - 2026-07-07

## Problem

Current certified mi14 switching result has 34 FAIL scenarios. Before this fix,
error analysis classified 14 LVRT asymmetric reactive failures as ODE-blind:

- `2ph`, target `0.75`, SCR `3` and `10`: 12 FAIL
- `2ph_g`, target `0.75`, SCR `10`: 2 FAIL

All 14 are reactive wrong-sign failures in switching.

## Cause

The ODE already had a negative-sequence measured-iq bias, but the residual prior
also applied a V2n feed-forward floor. In the shallow `target=0.75` asymmetric
LVRT cases, the feed-forward kept ODE measured `iq` slightly positive, while the
switching sequence extraction/filtering still measured wrong-sign current.

## Fix

File:

`src/hpt_frt/device/frt_env.py`

Added a narrow extra measured-iq ripple term for shallow asymmetric LVRT:

- applies only inside the existing boundary band;
- applies to `2ph` target >= 0.70 when fault duration >= 0.37 s;
- applies to `2ph_g` target >= 0.70 only for strong grid SCR >= 8 and duration >= 0.45 s;
- affects measured `iq` for reward/evaluation only, not plant dynamics.

## Verification

Current switching FAIL visibility:

- before: 20 visible / 14 blind
- after: 34 visible / 0 blind

Targeted ODE hit list for `2ph/2ph_g` now matches the switching FAIL ids exactly:

`161, 162, 163, 166, 169, 170, 171, 174, 176, 178, 179, 180, 224, 227`

Full-320 ODE proxy after the fix:

- overall: 76.9%
- LVRT: 85.8%
- HVRT: 50.0%

Tests:

`145 passed in 7.29s`

## Interpretation

This is not a certified switching improvement yet. It means the ODE layer now
sees every current certified switching failure, so the next SAC/curriculum
training round has the right error signal.
