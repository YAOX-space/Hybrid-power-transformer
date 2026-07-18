# HPT Specialist SAC Matrix Addendum - 2026-07-19

## Current Gate

The current promotion gate is the switch-level `voltage_survival_pass` in
`version_2/simulink/eval_hpt_v2_control_comparison.m`:

- LV fault-window mean: 176-238 V phase RMS.
- LV recovery-window mean: 180-235 V phase RMS.
- DC link: 650-1000 V.
- Switch modulation/action response: `<= 0.9501`.

`full_frt_pass` is still stricter and currently fails for all promoted
specialists because grid-current/reactive-current requirements are not yet
met.  Therefore the rows below are promoted as voltage-survival specialists,
not final grid-code-certified FRT controllers.

## Important Fix

`version_2/sac/pretrain_hpt_actor_bc.py` now maps the CLI limits into the
actual Gym action space:

- `reg_d_limit = reg_limit`
- `reg_q_limit = reg_limit`
- `energy_d_limit = energy_limit`
- `energy_q_limit = energy_limit`

Before this fix, `--energy-limit 0.95` did not change the actor action space:
`m_energy_d` was still limited to +/-0.40.  This explained why topology1
actors could not reproduce teacher actions such as `m_energy_d = 0.55-0.60`.

## Promoted Specialists

| Case | Topology | Fault | Model | Voltage pass | Beats conventional | Score SAC / conventional | LV mean / recovery | Vdc min / max | Notes |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `topology1_lvrt075_80ms` | topology1 | 0.750 pu / 80 ms | `data/models/hpt_traj_specialist_topo1_lvrt075_delayed_daggertraj_clean_20260719_dagger2.zip` | yes | no | 163.877 / 162.763 | 177.13 / 205.99 | 764.85 / 870.96 | Deep LVRT survives; conventional still slightly better on total score due grid-current/reactive penalties. |
| `topology1_lvrt090_80ms` | topology1 | 0.900 pu / 80 ms | `data/models/hpt_traj_specialist_topo1_lvrt090_rd050_ed055_currentgate_20260719_bc0.zip` | yes | no | 153.133 / 152.692 | 203.42 / 229.99 | 767.55 / 879.80 | Uses fixed teacher `[0.50, 0, 0.55, 0]`; passes current voltage/DC gate but does not yet beat tuned DQ. |
| `topology2_lvrt095_80ms` | topology2 | 0.950 pu / 80 ms | `data/models/hpt_traj_specialist_topo2_lvrt095_currentgate_energyw_20260719_dagger1.zip` | yes | yes | 126.719 / 239.881 | 194.85 / 221.38 | 663.98 / 997.85 | DAgger fixed the BC0 DC-link dip and produced a clear switch-level win. |
| `topology2_lvrt0925_80ms` | topology2 | 0.925 pu / 80 ms | `data/models/hpt_traj_specialist_topo2_lvrt0925_const_currentgate_20260719_dagger1.zip` | yes | yes | 142.522 / 279.629 | 181.92 / 225.81 | 662.16 / 978.45 | More meaningful than 0.95 because conventional voltage-survival fails while SAC passes. |

## Non-Promoted Boundary Findings

| Case | Finding |
| --- | --- |
| `topology2_lvrt090_80ms` | Two-stage q-injection trajectories improved score but repeatedly hit `dc_link_bounds` with a ~1005.6 V DC peak.  This needs topology2 energy-branch transient calibration before actor training. |
| `topology2_hvrt110_80ms` | Existing rule-teacher and energy sweep did not find a voltage-survival pass.  Main failure is DC-link bounds, with several trajectories also exceeding grid-current or lacking sustained reactive demand. |
| `topology1_lvrt090_80ms` high-energy teachers | After the action-space fix, actors can reproduce `m_energy_d=0.55-0.60`, but high-energy targets over-drive recovery voltage and/or lower Vdc below 650 V.  The promoted target is the lower `[0.50, 0, 0.55, 0]` version. |

## Next Work

1. Add reactive-current-aware teacher targets.  All promoted specialists still
   fail `full_frt_pass` mainly through `grid_current_limit` and
   `reactive_wrong_sign`.
2. Calibrate topology2 transient DC-link behavior for dynamic trajectories.
   The repeated ~1005 V peak blocks 0.90 pu LVRT and HVRT attempts.
3. Build a small automatic matrix runner that only promotes rows satisfying
   the current gate and writes a stable `accepted_specialists.csv`.
4. Train the next round per-case specialists from these accepted teachers,
   then re-test only the promoted checkpoints in switch-level Simulink.
