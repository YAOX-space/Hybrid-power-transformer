# Expanded scenario run - 2026-07-07

## Scope

Started the expanded-scenario loop without replacing the certified 320-scenario
baseline.

Expanded scenario file:

`lab/frt_scenarios_expanded.csv`

Run directory:

`lab/results/expanded_residual_20260707_120235`

## Current champion stress test

Command:

`python -m hpt_frt.device.eval_full320_ode --scenarios lab/frt_scenarios_expanded.csv --out lab/results/p3_expanded_ode_proxy.json`

Result:

- scenarios: 2040
- overall ODE proxy: 86.7%
- LVRT proxy: 93.3%
- HVRT proxy: 70.7%

By fault type:

| fault type | n | proxy |
|---|---:|---:|
| `1ph_g` | 360 | 100.0% |
| `2ph` | 360 | 100.0% |
| `2ph_g` | 360 | 100.0% |
| `sym3ph` | 360 | 73.3% |
| `swell_3ph` | 300 | 61.3% |
| `swell_1ph` | 300 | 80.0% |

Detailed failure export:

- `lab/results/p3_expanded_ode_failures.csv`
- `lab/results/p3_expanded_ode_failure_summary.json`

Failure count:

- 272 / 2040 proxy failures

Failure criteria occurrences:

- `vdc_survive_proxy`: 156
- `reactive`: 116
- `connect`: 112
- `recover`: 47

Failure types:

- `sym3ph`: 96
- `swell_3ph`: 116
- `swell_1ph`: 60

## First expanded residual-SAC training

Training command used `HPT_SCENARIO_CSV=lab/frt_scenarios_expanded.csv`.

Steps:

- 200k

Train/validation split:

- train: 1632
- validation: 408

Best validation proxy:

| candidate | proxy | step |
|---|---:|---:|
| raw best | 83.8% | 125000 |
| EMA best | 85.0% | 25000 |

This did not clearly beat the pre-expanded champion. On a deterministic 500
scenario sample:

| candidate | proxy |
|---|---:|
| old raw best | 86% |
| old EMA best | 88% |
| new raw best | 88% |
| new EMA best | 87% |
| new final | 86% |
| new EMA final | 88% |

Because the improvement is not decisive, the expanded checkpoints were archived
under the run directory and the pretrain residual checkpoints were restored to
`data/models`.

## Next step

The expanded failures are not uniform. The next training round should not train
blindly on all 2040 scenarios. Better options:

1. curriculum/oversampling for `sym3ph`, `swell_3ph`, and `swell_1ph`;
2. reward shaping focused on HVRT reactive at 1.10/1.15 and Vdc survival;
3. targeted ODE evaluation subsets before full 2040 evaluation;
4. only after ODE improvement, select a smaller switching subset for Simulink.
