# HPT SAC Experiment Registry

This folder documents how version 2 SAC experiments should be launched and
interpreted.  The actual generated outputs stay in `lab/results/`; trained
actors stay in `data/models/`.

## Result Locations

- `lab/results/hpt_v2_frt_calibration_matrix/`
  - switch-level FRT calibration matrix and 2 ms traces.
- `lab/results/hpt_v2_frt_proxy_gap/`
  - proxy-vs-switch-level error summaries.
- `lab/results/hpt_v2_frt_teacher_traces/`
  - selected teacher actions and per-step FRT teacher traces.
- `lab/results/hpt_case_specialists_<timestamp>/`
  - per-case specialist training logs, exported actors, status JSON, and report.
- `data/models/hpt_case_specialists/`
  - trained specialist policy ZIP files.

## Campaign Naming

Use this naming pattern in reports and commits:

```text
<topology>_<scenario-type>_<case>_<purpose>
```

Examples:

- `topology1_fault_sag_0p75_teacher_bc`
- `topology2_fault_swell_1p20_joint_proxy_gap`
- `topology1_steady_grid_9000V_switch_promotion`

## Current Campaigns

### FRT Proxy Calibration Matrix

Canonical command:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_calib_mode='full'; hpt_calib_topology='all'; collect_hpt_v2_frt_calibration_matrix;"
```

Latest accepted source:

- `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_full_all_20260717_005608.csv`
- `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_traces_full_all_20260717_005608.csv`

### FRT Specialist Training

Canonical command:

```powershell
py -3.8 -m version_2.sac.train_hpt_case_specialists --all-cases --scenario-type fault --max-specialists 999 --epochs 60 --repeat 128 --energy-enable 1.0
```

Interrupted diagnostic run:

- `lab/results/hpt_case_specialists_20260717_011726`
- reached 11 fault specialist records before interruption
- no actor was promoted
- several LVRT candidates improved score and Vdc survival, but still failed
  full FRT criteria

## Promotion Standard

A model can be called a switch-level success only if all are true:

1. The candidate is evaluated in the switch-level Simulink model, not only the
   averaged proxy.
2. The case evaluator returns `passed = true`.
3. The report includes LV metrics, Vdc metrics, action bounds, and failure
   reasons.
4. For fault cases, the report must include grid-side `Igrid_abc` derived dq
   metrics, reactive-current support/response status, and grid-current limit
   status.  A case with missing or failed current metrics is not promotable.
5. Proxy-only SAC results are not promotable unless the active proxy
   calibration JSON was generated from an FRT matrix containing those same
   grid-current fields.
6. Proxy training runs must pass rollout alignment with
   `verify_hpt_proxy_rollout_alignment.py`; this checks the actual SAC
   environment, not only the static lookup tables.

## Cleanup Policy

Interrupted runs should be stopped explicitly and documented in the next progress
report.  Do not delete partial diagnostic results unless they are known to be
corrupt or the user asks for cleanup.
