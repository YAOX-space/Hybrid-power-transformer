# ODE blind-model fixes - 2026-07-07

## Problem

The overnight raw-best residual SAC switching run produced 50 FAIL scenarios:

- 20 `sym3ph/SCR=10` LVRT survive failures (`Vdc<0.75`)
- 10 `swell_3ph/SCR=3` HVRT survive failures
- 20 `swell_1ph/SCR=3` HVRT reactive wrong-sign failures

Before this change, ODE replay saw only 10/50 failures. The missing 40 were
ODE-blind:

- balanced stiff-grid LVRT DC-link under-voltage was too smooth in ODE;
- weak-grid single-phase HVRT sequence/measurement coupling was absent.

## Model changes

File: `src/hpt_frt/device/frt_env.py`

1. Added a narrow stiff-grid balanced-LVRT DC-link starvation term:

   - active only for `category=LVRT`, `fault_type=sym3ph`, `SCR>=8`, `Vg_p<=0.55`
   - proportional to the voltage depression below 0.9 pu
   - exposes the switching `Vdc<0.75` failure for deep/mid stiff-grid sym3ph faults

2. Added a narrow weak-grid single-phase-HVRT sequence measurement term:

   - active only for `category=HVRT`, `fault_type=swell_1ph`, `SCR<=4`
   - adds a V2n-proportional positive-sequence measurement lift
   - adds a V2n-proportional measured-iq positive bias
   - exposes the switching reactive wrong-sign failure near the 1.1-pu boundary

The existing `swell_3ph` HVRT DC undershoot model was unchanged.

## Verification

Targeted replay of the archived raw-best switching FAIL list:

| group | before | after |
|---|---:|---:|
| `sym3ph/survive` | 0/20 visible | 20/20 visible |
| `swell_1ph/reactive` | 0/20 visible | 20/20 visible |
| `swell_3ph/survive` | 10/10 visible | 10/10 visible |
| total | 10/50 visible | 50/50 visible |

Full-320 ODE proxy after the fix:

- overall proxy: 81.2%
- LVRT proxy: 91.7%
- HVRT proxy: 50.0%
- `swell_1ph`: 50.0% after restricting the sequence bias to weak grid only

Regression tests:

`144 passed in 7.56s`

## Notes

This does not mean switching certification is improved yet. It means the ODE
training environment can now see the two switching failure families that were
previously blind, so retraining SAC is now meaningful again.
