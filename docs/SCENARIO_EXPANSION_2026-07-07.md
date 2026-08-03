# FRT scenario expansion - 2026-07-07

## Why expand beyond 320

The 320-scenario baseline is good for certified comparison, but it is sparse:

- LVRT only covers 0.20, 0.50, 0.75 pu;
- HVRT only covers 1.20 and 1.30 pu;
- grid strength only covers SCR 3 and 10;
- fault impedance angle is fixed at X/R = 3;
- duration is randomized, not an explicit family dimension.

FRT literature and standards commonly define scenarios by voltage-against-time
profiles, balanced and unbalanced fault types, positive/negative sequence
response, grid strength, impedance, and current-limiting behavior.

## Sources used

- IEEE 2800 guidance: voltage ride-through thresholds include LVRT levels around
  0.90, 0.70, 0.50, 0.25/0.10 and HVRT levels above 1.05/1.10/1.20, with
  minimum ride-through times.
- NREL IEEE-2800 compliant algorithm work: stresses current management under
  diverse grid fault conditions and positive/negative sequence handling.
- NERC/IEEE 2800 presentation material: uses voltage-versus-time envelopes as
  the template for ride-through trajectories.
- ENTSO-E/EirGrid-style FRT material: emphasizes voltage-against-time profiles
  and symmetric/asymmetric voltage dips.

## Expanded matrix

Generated file:

`lab/frt_scenarios_expanded.csv`

Generator:

`python -m hpt_frt.device.gen_frt_scenarios --profile expanded`

The default command still preserves the original baseline:

`python -m hpt_frt.device.gen_frt_scenarios --profile base`

The base output was hash-checked against the existing `lab/frt_scenarios.csv`.

### Expanded dimensions

LVRT:

- fault types: `sym3ph`, `1ph_g`, `2ph`, `2ph_g`
- target voltage: `0.10`, `0.20`, `0.35`, `0.50`, `0.70`, `0.85`
- duration bins: `0.16 s`, `0.50 s`

HVRT:

- fault types: `swell_3ph`, `swell_1ph`
- target voltage: `1.10`, `1.15`, `1.20`, `1.25`, `1.30`
- duration bins: `0.50 s`, `1.00 s`

Grid:

- SCR: `2`, `3`, `5`, `10`, `15`
- X/R: `1.5`, `3`, `6`
- randomized load and power factor retained

### Size

- total scenarios: `2040`
- families: `1020`
- runs per family: `2`
- LVRT: `1440`
- HVRT: `600`

## Important limitation

The current Simulink switching harness uses `dur = min(fault_dur, 0.5)`. That
means the `1.0 s` HVRT duration bin is useful for ODE/training immediately, but
will not be faithfully certified in switching until the switching harness is
deliberately extended.

For the next training round, use the expanded set for ODE pretraining or
stress-testing first, then choose a smaller targeted switching subset to keep
runtime manageable.
