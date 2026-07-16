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

## Per-Case Specialist Update

After the repeated step-trace specialist loop reached about 60 iterations without
improving the `5 / 10` raw guard=0 smoke score, the unified/single dynamic actor
search was stopped.  The working direction is now closer to the previous SAC
version: train separate actors for topology/case families first, then build a
router only after individual actors pass switch-level validation.

New tooling added:

- `version_2/simulink/eval_hpt_v2_sac_single_case.m`
  - Runs exactly one raw guard=0 switch-level case.
  - Supports topology/scenario/case filters.
  - Supports `hpt_eval_energy_enable`, so regulating-bridge SAC can be tested
    while the energy bridge stays on the physical DC-link loop.
- `version_2/sac/train_hpt_case_specialists.py`
  - Trains one actor per topology/case from filtered switch-level step traces.
  - Exports the candidate to the steady or dynamic MAT slot only for that case.
  - Restores the previous best MAT files after each trial.
- `version_2/sac/pretrain_hpt_actor_bc.py`
  - Now supports `--episodes-per-scenario 0`, allowing pure switch-trace BC
    without mixed proxy curriculum data.
  - Now supports `--zero-energy-targets`.
  - Now supports configurable BC action weights via `--action-weights`.

First focused case:

- Case: `topology1 steady grid_9000V`
- Baseline active actor with SAC energy disabled:
  - LV mean about `213.49 V`
  - Vdc min about `657.64 V`
  - Fails `steady_lv;steady_vdc`
- Per-case switch-trace BC actor:
  - LV mean improved in some trials, e.g. `207.54 V`, but Vdc collapsed to
    about `394 V`.
  - With SAC energy disabled, Vdc still stayed too low in actor mode because
    the regulating action drifted into a high-gain region.
- DAgger-style aggregate correction:
  - Reduced effective `reg_d_mean` in one trial from about `0.73` to `0.61`.
  - Still failed: LV remained about `212 V`, Vdc min about `593 V`.

Action-sweep finding:

- Fixed-action switch-level sweep says topology1 `grid_9000V` can be healthy:
  - fixed raw `m_reg_d = 0.8`, `m_reg_q = 0`, SAC energy disabled
  - LV mean about `207.00 V`
  - Vdc mean about `823.30 V`
  - Vdc min about `727.64 V`
- Therefore the plant and regulating bridge can solve this case.
- The current actor failure is a policy/trajectory-distribution problem, not a
  topology impossibility.

Interpretation:

- Single-step BC from conventional trace is not enough.  Once the actor pushes
  the plant into a different observation region, it outputs high `reg_d`,
  nonzero `reg_q`, and sometimes energy commands that were not present in the
  safe fixed-action sweep.
- Aggregate smoke-row corrections are too weak because they contain only mean
  observations.  The next useful DAgger data must be per-step actor rollout
  traces from the failed switch-level case.
- The first `energy disabled` specialist loop was not enough.  It improved LV
  voltage but did not preserve the DC link.

## July 16 Per-Case DAgger Run

The current target is no longer a unified SAC.  The active research loop now
trains separate SAC actors for topology/fault families, following the previous
version's expert-routing idea.

New additions:

- `eval_hpt_v2_sac_single_case.m` now also writes per-step actor rollout traces:
  `lab/results/hpt_v2_sac_single_case_actor_traces/*.csv`
- `pretrain_hpt_actor_bc.py` can filter switch traces by:
  - topology
  - scenario type
  - condition class
  - case name
  - window zone
- `pretrain_hpt_actor_bc.py` can use a fixed physical target with
  `--switch-trace-fixed-target`.
- `sweep_hpt_v2_reg_energy_response.m` sweeps regulating and energy commands
  together, instead of treating them independently.
- `overnight_hpt_case_specialists.py` runs a closed-loop DAgger loop:
  evaluate actor on switch-level Simulink, collect failed rollout trace, train
  a per-case specialist, export it, and test it again on switch-level Simulink.

Topology1 `grid_9000V` findings:

- `m_reg_d = 0.8` can recover LV voltage but can deplete the DC link when the
  actor drifts into the same high-gain region.
- Joint fixed-action sweep found a healthier region around
  `[reg_d, reg_q, energy_d, energy_q] = [0.55, 0, 0.4, 0]`.
- A trained actor still drifted in closed-loop:
  - actual `reg_d_mean` around `0.62`
  - actual `reg_q_mean` around `-0.10`
  - actual `energy_d_mean` around `0.34`
  - LV entered the desired window, but VdcMean was still too low.

Interpretation:

- The physical switch-level topology can regulate the case, but the actor has
  not internalized the joint regulating/energy law.
- The current failure is mainly a closed-loop distribution shift problem:
  the actor sees states outside its BC trace and produces non-physical q-axis
  and energy-channel deviations.
- Therefore the 8-hour loop is now doing DAgger-style trace refresh, not proxy
  residual correction.

Current 8-hour run:

- Script: `version_2/sac/overnight_hpt_case_specialists.py`
- Status pointer: `lab/results/.hpt_case_specialists_8h_current.json`
- Active run at launch:
  `lab/results/hpt_case_specialists_8h_20260716_125417`
- Promotion rule: only a candidate with `within_window=true` in switch-level
  single-case validation is kept under `promoted/`.

Final result of this run:

- Status: complete at `2026-07-16T20:54:32`
- Iterations: `350`
- Passing switch-level candidates: `148`
- Best case: iteration `108`
- Best physical target used for training: `[0.55, 0, 0.6, 0]`
- Best switch-level metrics:
  - LV mean: `206.990 V`
  - LV unbalance: `0.428 V`
  - Vdc mean: `806.706 V`
  - Vdc min: `725.755 V`
  - action max: `0.934`
  - mean action: `reg_d=0.567`, `reg_q=-0.107`,
    `energy_d=0.242`, `energy_q=-0.039`
- Best files:
  - `lab/results/hpt_case_specialists_8h_20260716_125417/best/topology1_grid9000.mat`
  - `lab/results/hpt_case_specialists_8h_20260716_125417/best/hpt_case_specialists_8h_20260716_125417_topology1_grid9000_it108.zip`

Important limitation:

- This is a successful specialist for `topology1 / steady / grid_9000V`.
- It is not yet a full HPT controller for topology1 all steady points, topology2,
  sag, swell, or fault-transition cases.
- The next step is to repeat the same per-case loop for the remaining cases and
  then build a router that selects the correct specialist.
