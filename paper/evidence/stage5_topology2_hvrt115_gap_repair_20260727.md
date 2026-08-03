# Stage-5 Topology2 HVRT 1.15 pu Gap Repair

Date: 2026-07-27

## Scope

This evidence note records the targeted repair of the remaining topology2 HVRT
`1.15 pu` voltage-survival gaps after the first Stage-5 batch.  The claim is
limited to switch-level voltage-survival and beat-conventional evidence.  Full
FRT certification is not claimed because the full-FRT evaluator still reports
grid-current and, for AB `80 ms`, GBT recovery violations.

## Previous Failure Modes

The retry run
`lab/results/hpt_stage5_t2_hvrt115_retry_20260727` showed two distinct failure
modes:

| Case | Previous failure | Interpretation |
|---|---|---|
| topology2 balanced HVRT 1.15 pu / 80 ms | `dc_link_bounds`, `Vdc_max ~= 1103 V` | The LV envelope was not the limiting factor; the DC link required stronger energy/chopper shaping. |
| topology2 balanced HVRT 1.15 pu / 120 ms | `dc_link_bounds`, `Vdc_max ~= 1103 V` | Same as the 80 ms balanced row. |
| topology2 AB HVRT 1.15 pu / 80 ms | `timestep_recovery_envelope`, recovery violation about `0.011 pu` | DC survival was acceptable; the action needed recovery-window damping. |

## Diagnostic Chopper Sweep

Manifest:
`version_2/sac/experiments/stage5_t2_hvrt115_balanced_chopper_sweep_20260727.csv`

Command:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt115_balanced_chopper_sweep_20260727.csv --run-id hpt_stage5_t2_hvrt115_balanced_chopper_sweep_20260727 --controller-mode current-sac --timeout-s 2400
```

The sweep was intentionally diagnostic.  It confirmed that lowering the chopper
threshold to `760 V` prevents the previous `~1103 V` DC-link overvoltage, but
the old actor then fails LV/recovery voltage-survival.  Therefore the balanced
repair cannot be a chopper-only change; it requires a matched regulating action.

## Targeted Trajectory Repairs

The following constant action trajectories were tested directly in the
switch-level Simulink model before converting them to neural actors:

| Case | Trajectory action `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]` | Chopper threshold | Rchop scale | Trajectory voltage-survival | Trajectory score | Baseline score |
|---|---:|---:|---:|---:|---:|---:|
| balanced HVRT 1.15 pu / 80 ms | `[0.60, 0.00, 0.00, 0.00]` | `760 V` | `0.55` | pass | `131.977` | `269.359` |
| balanced HVRT 1.15 pu / 120 ms | `[0.60, 0.00, 0.00, 0.00]` | `760 V` | `0.55` | pass | `132.210` | `271.334` |
| AB HVRT 1.15 pu / 80 ms | `[0.45, 0.00, 0.26, 0.00]` | `780 V` | `0.65` | pass | `131.036` | `232.840` |

These smoke tests show that the three previously unresolved cases are
physically controllable under the current switch-level model and validator.

## Actor Conversion

Each trajectory was converted into a state-feedback actor using the existing
BC/DAgger trajectory-specialist pipeline.  The final promoted models are:

| Case | Run directory | Final actor model | Final stage | Voltage-survival | Full-FRT status |
|---|---|---|---|---:|---|
| balanced HVRT 1.15 pu / 80 ms | `lab/results/hpt_stage5_t2_bal_hvrt115_80ms_const060_actor_retry_20260727` | `data/models/hpt_stage5_t2_bal_hvrt115_80ms_const060_actor_retry_20260727_dagger1.zip` | `dagger1` | pass | fail: `grid_current_limit` |
| balanced HVRT 1.15 pu / 120 ms | `lab/results/hpt_stage5_t2_bal_hvrt115_120ms_const060_actor_20260727` | `data/models/hpt_stage5_t2_bal_hvrt115_120ms_const060_actor_20260727_dagger1.zip` | `dagger1` | pass | fail: `grid_current_limit` |
| AB HVRT 1.15 pu / 80 ms | `lab/results/hpt_stage5_t2_ab_hvrt115_80ms_reg045_energy026_actor_20260727` | `data/models/hpt_stage5_t2_ab_hvrt115_80ms_reg045_energy026_actor_20260727_dagger1.zip` | `dagger1` | pass | fail: `gbt_recover;grid_current_limit` |

For the AB case, the initial BC actor still failed recovery by
`0.00435 pu`.  One DAgger iteration repaired the switch-level recovery envelope,
reducing the recovery violation to zero.

## Exact Recheck

Balanced recheck manifest:
`version_2/sac/experiments/stage5_t2_hvrt115_balanced_const060_recheck_20260727.csv`

AB recheck manifest:
`version_2/sac/experiments/stage5_t2_ab_hvrt115_80ms_reg045_energy026_recheck_20260727.csv`

Commands:

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_hvrt115_balanced_const060_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt115_balanced_const060_recheck_20260727 --controller-mode current-sac --timeout-s 1800
```

```powershell
py -3 -m version_2.sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest version_2/sac/experiments/stage5_t2_ab_hvrt115_80ms_reg045_energy026_recheck_20260727.csv --run-id hpt_stage5_t2_ab_hvrt115_80ms_reg045_energy026_recheck_20260727 --controller-mode current-sac --timeout-s 1800
```

Exact recheck result:

| Case | Conventional voltage-survival | SAC voltage-survival | SAC beats conventional | Conventional score | SAC score | SAC minus conventional | SAC envelope violation max pu | SAC recovery violation max pu | SAC Vdc min/max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| balanced HVRT 1.15 pu / 80 ms | fail | pass | yes | `269.359` | `131.686` | `-137.673` | `0.000` | `0.000` | `739.37 / 800.02 V` |
| balanced HVRT 1.15 pu / 120 ms | fail | pass | yes | `271.334` | `132.057` | `-139.277` | `0.000` | `0.000` | `738.76 / 800.02 V` |
| AB HVRT 1.15 pu / 80 ms | fail | pass | yes | `232.840` | `129.976` | `-102.863` | `0.000` | `0.000` | `761.54 / 831.85 V` |

The promoted specialist manifest was updated:
`version_2/sac/experiments/stage4_promoted_specialists_20260727.csv`.

## Interpretation

The targeted repair converts the remaining topology2 HVRT `1.15 pu` gaps into
three exact-rechecked voltage-survival specialists.  The key mechanism is not
blind SAC fine-tuning.  It is:

1. identify the switch-level failure mode;
2. construct a feasible trajectory in the switch-level model;
3. convert the trajectory into a state-feedback actor with BC/DAgger;
4. recheck the actor through the same boundary-matrix validator.

This is useful paper evidence because the repaired rows are all cases where the
strong conventional baseline fails voltage-survival, while the SAC-format actor
passes and obtains a lower survival score.

## Remaining Limitations

These rows are not full-FRT certified.  The voltage-survival gate checks LV
fault/recovery envelope, DC-link survival, and action limits.  The full-FRT
gate additionally requires grid-current and reactive-current behavior.  The
balanced rows still fail `grid_current_limit`; the AB 80 ms row still fails
`gbt_recover;grid_current_limit`.

The next research step should therefore remain focused on voltage-survival
boundary expansion unless the project explicitly resumes full-FRT certification.
The most natural next voltage-survival targets are:

- topology2 HVRT `1.20 pu`, `80/120 ms`;
- topology1 unbalanced score optimization, especially cases where SAC passes
  but does not yet beat the conventional dq baseline;
- a compact exact recheck matrix containing all newly promoted Stage-5 actors.
