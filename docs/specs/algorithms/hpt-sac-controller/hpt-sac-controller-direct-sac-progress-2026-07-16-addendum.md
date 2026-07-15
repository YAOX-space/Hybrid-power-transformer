# HPT Direct SAC Progress Addendum - 2026-07-16

## Completed

1. Added scenario-aware filtering to `version_2/sac/pretrain_hpt_actor_bc.py`.
   - `--switch-trace-scenario-types {all,steady,fault}`
   - `--raw-smoke-correction-scenario-types {all,steady,fault}`
   - `--energy-teacher-trace-scenario-types {all,steady,fault}`
   - `--energy-teacher-min-time`

2. Extended `version_2/simulink/collect_hpt_v2_sac_energy_teacher_traces.m`.
   - The conventional `VoltageRegulator` is now recorded as a teacher.
   - The trace now includes equivalent `target_action_01/02 = m_reg_d/m_reg_q`.
   - The trace still includes `target_action_03/04 = i_energy_d/q_ref_pu`.

3. Generated a full conventional teacher trace.
   - CSV: `lab/results/hpt_v2_sac_energy_teacher_traces/energy_teacher_traces_20260716_025657.csv`
   - Samples: 1584
   - Coverage: topology1/topology2, 3 steady grid voltages, 0.2/0.5/0.75/0.85/0.9 pu sag, and 1.1/1.2/1.25/1.3 pu swell.

4. Trained and tested these additional actors:
   - `steady_fullteacher_settled`
   - `dynamic_fullteacher_settled`
   - `steady_rawdominant`
   - `dynamic_teacheronly_settled`
   - `dynamic_fulltrace_teacher`

## Best Current Candidate

The exported Simulink weights were restored to the best candidate found in this round:

- steady actor: `data/models/hpt_voltage_sac_currentref_steady_fullteacher_settled.zip`
- dynamic actor: `data/models/hpt_voltage_sac_currentref_dynamic_fullteacher_settled.zip`
- Simulink weights:
  - `version_2/simulink/hpt_sac_actor_weights.mat`
  - `version_2/simulink/hpt_sac_actor_weights_dynamic.mat`

Best raw guard=0 smoke result:

- CSV: `lab/results/hpt_v2_sac_raw_switchlevel_smoke/raw_sac_switchlevel_smoke_20260716_023932.csv`
- Passed: 5 / 10
- Passed cases:
  - topology1 fault sag_0p90
  - topology1 fault swell_1p10
  - topology2 steady 9000 V
  - topology2 steady 10000 V
  - topology2 steady 11000 V
- Failed cases:
  - topology1 steady 9000 V: DC-link steady window is low.
  - topology1 steady 10000 V / 11000 V: LV is over-regulated.
  - topology2 sag/swell fault: LV peak/min constraints fail during the fault window.

## Failed Attempts And Findings

1. `steady_rawdominant` did not fix topology1 steady over-regulation.
   - The raw smoke correction is aggregated per case.
   - The actor sees time-varying `HPTSAC_obs`, last action, and detector flags.
   - A single aggregate correction row is not enough to repair the full trajectory.

2. `dynamic_teacheronly_settled` degraded topology1 fault.
   - Conventional teacher-only labels under-compensated the low-voltage fault window once projected through the switch-level controller.

3. `dynamic_fulltrace_teacher` was worse and caused topology2 fault DC-link collapse.
   - Mixing deep LVRT/HVRT and shallow faults into one dynamic BC actor pulled the policy toward extreme-fault behavior.
   - This argues for a fault-depth classifier and specialist actors instead of one undifferentiated dynamic actor.

4. The `sqrt(2)` difference between `reg_m_amp` and `m_reg_d` was checked.
   - This is expected: `reg_m_amp` is three-phase RMS modulation amplitude, while SAC action uses peak modulation amplitude.
   - The main remaining problem is data alignment and fault-class mixing, not a simple scaling error.

## Next Step

Move from one dynamic actor to classifier-routed specialist actors:

1. Add a fault condition classifier:
   - steady
   - shallow LVRT/HVRT
   - deep LVRT
   - asymmetric fault
   - topology2 dynamic special case

2. Collect switch-level state-action traces instead of aggregate smoke rows:
   - `obs24` at every SAC step
   - raw actor action
   - conventional teacher action
   - LV/Vdc window status

3. Train specialist actors and only promote a candidate after raw guard=0 smoke reaches at least 8 / 10.
