# HPT Specialist Policy Ablation Ladder Protocol

Date: 2026-07-25

Purpose: answer the reviewer question "is the result really SAC, or mostly teacher/DAgger/BC?"  The experiment must compare the same switch-level case under the same validator using a ladder:

1. `teacher_replay`
2. `bc_actor`
3. `bc_dagger_actor`
4. `bc_dagger_sac_finetune_actor`

The claim "SAC contributes" is allowed only when step 4 improves over step 3 under the same switch-level evaluator.

## 1. Selected Cases

Use two cases:

| case_key | reason |
| --- | --- |
| `topology2_a_hvrt105_60ms` | strongest reduced-boundary probe: traditional fail / specialist pass, topology2 energy branch active |
| `topology1_balanced_lvrt090_80ms` | balanced LVRT boundary case where DAgger trajectory actor is already used |

## 2. Common Gate

Use the current L1 voltage-survival validator only:

```text
fault_lv_band_violation_max_pu <= 1e-3
envelope_violation_max_pu <= 1e-3
recovery_violation_max_pu <= 1e-3
650 V <= vdc_min and vdc_max <= 1000 V
action_max_abs <= 0.9501
```

Also report but do not gate:

- grid_current_peak_pu;
- grid_iq_shortfall_max_pu;
- full_frt_reason;
- Vdc margin to lower/upper bounds.

## 3. Variant Definitions

### 3.1 Teacher replay

Run the switch-level model with the trajectory action schedule directly.  This proves the handcrafted/search teacher itself is feasible.

Output:

```text
control_comparison_* mode=trajectory_action or fixed_action
```

### 3.2 BC actor

Run `run_hpt_trajectory_specialist_campaign.py` with:

```text
--dagger-iters 0
```

The final actor is a pure behavior-cloned SAC-compatible actor.

### 3.3 BC + DAgger actor

Run the same campaign with:

```text
--dagger-iters 1
```

The final actor is a state-distribution-corrected SAC-compatible actor.

### 3.4 BC + DAgger + SAC fine-tune

Warm-start from the BC+DAgger actor using:

```text
py -3 -m version_2.sac.offline.train_hpt_fault_specialists_vs_baseline ^
  --init-model <bc_dagger_actor.zip> ^
  --steps <small-to-medium SAC steps> ^
  --behavior-anchor-epochs <positive> ^
  --controller-heads split
```

Then export and validate in switch-level Simulink using the same evaluator.

This is the only variant that can be used to argue that SAC policy improvement adds value beyond imitation.

## 4. Concrete Starting Commands

### 4.1 topology2 A-HVRT 1.05 pu / 60 ms

BC actor:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign `
  --run-id hpt_ablation_t2_a_hvrt105_bc_20260725 `
  --topology topology2 `
  --case-name ablation_t2_a_hvrt105_60ms `
  --fault-pu 1.05 `
  --fault-phase-pu 1.05 1.0 1.0 `
  --duration-s 0.060 `
  --fault-start 0.035 `
  --chopper-threshold 780 `
  --rchop-scale 0.65 `
  --actor-filter-tau 0.001 `
  --preset fault_recovery `
  --base-action 0.30 0.0 0.05 0.0 `
  --safe-target 0.12 0.0 0.02 0.0 `
  --dagger-iters 0 `
  --epochs 220
```

BC + DAgger actor:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign `
  --run-id hpt_ablation_t2_a_hvrt105_dagger_20260725 `
  --topology topology2 `
  --case-name ablation_t2_a_hvrt105_60ms `
  --fault-pu 1.05 `
  --fault-phase-pu 1.05 1.0 1.0 `
  --duration-s 0.060 `
  --fault-start 0.035 `
  --chopper-threshold 780 `
  --rchop-scale 0.65 `
  --actor-filter-tau 0.001 `
  --preset fault_recovery `
  --base-action 0.30 0.0 0.05 0.0 `
  --safe-target 0.12 0.0 0.02 0.0 `
  --dagger-iters 1 `
  --epochs 220
```

### 4.2 topology1 balanced LVRT 0.90 pu / 80 ms

BC actor:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign `
  --run-id hpt_ablation_t1_lvrt090_80ms_bc_20260725 `
  --topology topology1 `
  --case-name ablation_t1_lvrt090_80ms `
  --fault-pu 0.90 `
  --duration-s 0.080 `
  --fault-start 0.080 `
  --chopper-threshold 850 `
  --rchop-scale 1.0 `
  --actor-filter-tau 0.001 `
  --preset fault_recovery `
  --base-action 0.50 0.0 -0.05 0.0 `
  --safe-target 0.18 0.0 -0.02 0.0 `
  --dagger-iters 0 `
  --epochs 220
```

BC + DAgger actor:

```powershell
py -3 -m version_2.sac.run_hpt_trajectory_specialist_campaign `
  --run-id hpt_ablation_t1_lvrt090_80ms_dagger_20260725 `
  --topology topology1 `
  --case-name ablation_t1_lvrt090_80ms `
  --fault-pu 0.90 `
  --duration-s 0.080 `
  --fault-start 0.080 `
  --chopper-threshold 850 `
  --rchop-scale 1.0 `
  --actor-filter-tau 0.001 `
  --preset fault_recovery `
  --base-action 0.50 0.0 -0.05 0.0 `
  --safe-target 0.18 0.0 -0.02 0.0 `
  --dagger-iters 1 `
  --epochs 220
```

## 5. Evidence Status

Completed this turn:

- MATLAB command-line interface smoke passed:
  `test_hpt_v2_sac_interface.m`
- Paper evidence package generated:
  `paper/evidence/per_case_metrics.csv`
  `paper/evidence/paired_case_comparison.csv`
  `paper/evidence/score_sensitivity.csv`
  `paper/evidence/reproducibility_manifest.csv`

Not completed yet:

- Fresh teacher replay for the two ablation cases.
- Fresh BC actor switch-level validation.
- Fresh BC+DAgger actor switch-level validation.
- Fresh BC+DAgger+SAC fine-tune switch-level validation.

These must be run before claiming SAC fine-tuning adds value over DAgger.
