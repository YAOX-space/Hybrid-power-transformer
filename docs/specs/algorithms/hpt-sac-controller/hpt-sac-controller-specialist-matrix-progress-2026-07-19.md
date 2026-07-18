# HPT Specialist SAC Matrix Progress - 2026-07-19

## Goal

Build usable specialist SAC controllers split by topology and fault family, and
evaluate them against the switch-level Simulink models and the conventional DQ
baseline.

## What Was Added

- Added `version_2.sac.run_hpt_specialist_matrix_campaign`.
- The runner reuses completed switch-level specialist campaigns when available,
  launches missing cases, and writes:
  - `case_manifest.csv`
  - `specialist_matrix_results.csv`
  - `summary.json`
  - `REPORT.md`
- Promotion levels are explicit:
  - `full_frt`: full switch-level FRT pass.
  - `voltage_survival`: switch-level voltage-survival pass and better score than
    conventional DQ, but full-FRT blockers remain.
  - `diagnostic`: not a usable specialist.
- Fixed campaign metadata so the recorded policy checkpoint points to the best
  actor instead of the last trained actor.
- Added continuous q-gating support in the BC/DAgger teacher path before this
  matrix run, so topology2 LVRT can gradually introduce reactive action instead
  of applying an abrupt q command.

## Matrix Run

Command:

```powershell
py -3 -m version_2.sac.run_hpt_specialist_matrix_campaign --campaign-id hpt_specialist_matrix_20260719 --case-timeout-s 3600 --matlab-timeout-s 1200 --train-timeout-s 600
```

Output:

- Result directory:
  `lab/results/hpt_specialist_matrix_20260719`
- Matrix CSV:
  `lab/results/hpt_specialist_matrix_20260719/specialist_matrix_results.csv`

## Current Promoted Specialist Controllers

| Case | Level | Result |
| --- | --- | --- |
| `topology1_lvrt090_80ms` | `voltage_survival` | Passes voltage-survival and slightly beats conventional DQ. Full FRT still fails: `gbt_recover;grid_current_limit;reactive_wrong_sign`. |
| `topology2_lvrt095_80ms` | `voltage_survival` | Passes voltage-survival and strongly beats conventional DQ. Full FRT still fails: voltage envelope/recovery, grid current, reactive sign. |
| `topology2_lvrt090_80ms` | `voltage_survival` | Passes voltage-survival and beats conventional DQ after DAgger with continuous q-gate. Full FRT still fails: voltage envelope/recovery, grid current, reactive sign. |

No actor currently passes full FRT certification.

## Failed Boundary Probes

### topology1 / LVRT / 0.75 pu / 80 ms

- New specialist probe:
  `hpt_specialist_matrix_20260719_topology1_lvrt075_80ms_probe`
- Result: `diagnostic`
- Failure:
  - `lv_fault_mean_bounds`
  - `dc_link_bounds`
  - `reactive_wrong_sign`
- Interpretation:
  A fixed high `m_reg_d` plus energy command is not enough for this deeper sag.
  The conventional DQ controller survives voltage in this case, but the current
  hand-made teacher action drains the DC link and undershoots the LV fault mean.

Additional sweep:

```powershell
py -3 -m version_2.sac.run_hpt_dynamic_trajectory_sweep --run-id hpt_boundary_sweep_topo1_lvrt075_ramp5_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --reg-d-grid 0.45,0.55,0.62,0.70 --reg-q-grid 0 --energy-d-grid 0,0.10,0.20,0.35 --energy-q-grid 0 --d-ramp-ms-grid 5 --q-ramp-ms-grid 5 --down-ms-grid 0 --max-cases 16 --timeout-s 1200
```

Result:

- Completed: `16 / 16`
- Voltage-survival pass: `0 / 16`
- Best score still failed due `lv_fault_mean_bounds;dc_link_bounds`.

Rule-teacher follow-up:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign --run-id hpt_rule_teacher_topo1_lvrt075_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --teacher-source rule --dagger-iters 0 --switch-trace-repeat 64 --epochs 60 --bc-obs-noise-repeat 3 --matlab-timeout-s 1200 --train-timeout-s 600
```

Result:

- BC loss was low, but the switch-level actor still failed voltage-survival.
- Failure reason: `lv_fault_mean_bounds`.
- Interpretation:
  matching the teacher action at sampled states is not enough, because the actor
  creates its own closed-loop state trajectory after being inserted into
  Simulink.  This is a rollout-alignment problem, not only an action-label MSE
  problem.

### topology2 / HVRT / 1.10 pu / 80 ms

- New specialist probe:
  `hpt_specialist_matrix_20260719_topology2_hvrt110_80ms_probe`
- Result: `diagnostic`
- Failure:
  - `dc_link_bounds`
  - `grid_current_limit`
  - reactive-current demand was not evaluated after the delay because the
    trajectory collapsed into a no-demand region.

Additional sweep:

```powershell
py -3 -m version_2.sac.run_hpt_dynamic_trajectory_sweep --run-id hpt_boundary_sweep_topo2_hvrt110_energy_20260719 --topology topology2 --fault-pu 1.10 --duration-s 0.08 --reg-d-grid=0,-0.05 --reg-q-grid 0 --energy-d-grid=-0.30,-0.20,-0.10,-0.05 --energy-q-grid 0.002 --d-ramp-ms-grid 5 --q-ramp-ms-grid 20 --down-ms-grid 40 --max-cases 8 --timeout-s 1200
```

Result:

- Completed: `8 / 8`
- Voltage-survival pass: `0 / 8`
- Best trajectories lower the score relative to conventional but fail DC-link
  bounds, so they cannot be used as SAC teachers yet.

Rule-teacher follow-up:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign --run-id hpt_rule_teacher_topo2_hvrt110_20260719 --topology topology2 --fault-pu 1.10 --duration-s 0.08 --teacher-source rule --dagger-iters 0 --switch-trace-repeat 64 --epochs 60 --bc-obs-noise-repeat 3 --matlab-timeout-s 1200 --train-timeout-s 600
```

Result:

- The actor almost reproduced the conventional score, but did not pass.
- Failure reason: `dc_link_bounds`.
- Interpretation:
  topology2/HVRT needs an explicit DC-link/energy-loop safe rollout objective.
  Pure BC from rule/DQ traces is not enough.

## Technical Interpretation

The useful progress is not a universal FRT controller yet.  It is a reliable
pipeline that can promote per-case switch-level voltage-survival actors and
separate them from diagnostic failures.

The main blocker is now clear:

1. LVRT voltage regulation can be learned for shallow and mid sag cases.
2. Full FRT fails mostly because grid-side reactive-current support and current
   limits are not satisfied.
3. Deeper LVRT and HVRT need a dynamic teacher derived from the conventional DQ
   controller or a redesigned energy/DC-link loop; fixed full-action teachers
   are not physically safe enough.

## Next Plan

1. Add conventional-trace teacher collection for failed boundary cases.
   Instead of fixed action labels, collect `policy_mode=0` rule/DQ action traces
   during `topology1_lvrt075` and `topology2_hvrt110`.
   This was implemented and tested; both cases still failed after insertion into
   the closed-loop switch-level model.
2. Add rollout-alignment evaluation for rule-teacher BC:
   compare teacher trace, actor trace, LV/Vdc waveforms, and action error along
   actor-visited states, not just static sampled states.
3. Train BC warm-start actors from those conventional traces, then apply small
   residual action targets only inside switch-level validated safe regions.
4. Add a dynamic energy/DC-link constraint to the teacher label generator:
   reduce regulating action when `Vdc < 0.80 pu`, and prefer energy current
   recovery before voltage/recovery-window aggressiveness.
5. Re-run the specialist matrix with:
   - topology1: LVRT 0.75/0.85/0.90
   - topology2: LVRT 0.90/0.95 and HVRT 1.10
6. Only if the conventional-trace actor survives the switch-level gate, train a
   residual/SAC specialist to beat conventional score without violating DC link
   or grid-current constraints.
