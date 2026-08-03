# HPT family-specialist matrix summary

This run evaluates one existing actor across the family matrix; no training occurs in this run.

## Configuration

- family_label: `t2_a_lvrt_r6_square60`
- topology: `topology2`
- category: `LVRT`
- phase_key: `a`
- train_depths: `None`
- train_durations_ms: `None`
- eval_depths: `[0.2, 0.5, 0.575, 0.65, 0.7, 0.75, 0.8, 0.825, 0.85, 0.875]`
- eval_durations_ms: `[80, 120, 160, 200, 240, 300]`

## Controller Summary

| controller | rows | pass | active Vdc pass | GBT Vdc survive | pass while dq fails | score < dq | score < seed | score mean | grid I max | env max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| family_sac_after_finetune | 60 | 46 | 52 | 60 | 3 | 45 | 0 | 115.571 | 1.369 | 0.00000 |
| strong_dq | 60 | 48 | 48 | 48 | 0 | 0 | 0 | 123.600 | 1.494 | 0.00000 |

## Per-case rows

| case | controller | pass | reason | score | grid I | env | recovery | Vdc min | actor model |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| t2_a_lvrt_r6_square60_pu0200_d080ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 171.361 | 1.494 | 0.00000 | 0.08584 | 581.0 |  |
| t2_a_lvrt_r6_square60_pu0200_d080ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.018 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0200_d120ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 166.829 | 1.494 | 0.00000 | 0.08645 | 581.0 |  |
| t2_a_lvrt_r6_square60_pu0200_d120ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.078 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0200_d160ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 226.750 | 1.494 | 0.00000 | 0.15112 | 0.2 |  |
| t2_a_lvrt_r6_square60_pu0200_d160ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.164 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0200_d200ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 180.039 | 1.494 | 0.00000 | 0.12248 | 460.0 |  |
| t2_a_lvrt_r6_square60_pu0200_d200ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.103 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0200_d240ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 182.898 | 1.494 | 0.00000 | 0.13778 | 448.8 |  |
| t2_a_lvrt_r6_square60_pu0200_d240ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.133 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0200_d300ms | strong_dq | 0 | timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope | 183.211 | 1.494 | 0.00000 | 0.12933 | 448.8 |  |
| t2_a_lvrt_r6_square60_pu0200_d300ms | family_sac_after_finetune | 0 | timestep_fault_lv_band | 132.240 | 1.369 | 0.00000 | 0.00000 | 688.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d080ms | strong_dq | 1 |  | 118.164 | 1.392 | 0.00000 | 0.00000 | 677.1 |  |
| t2_a_lvrt_r6_square60_pu0500_d080ms | family_sac_after_finetune | 1 |  | 120.101 | 1.314 | 0.00000 | 0.00000 | 793.8 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d120ms | strong_dq | 1 |  | 120.477 | 1.392 | 0.00000 | 0.00000 | 677.1 |  |
| t2_a_lvrt_r6_square60_pu0500_d120ms | family_sac_after_finetune | 1 |  | 120.812 | 1.314 | 0.00000 | 0.00000 | 688.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d160ms | strong_dq | 1 |  | 122.357 | 1.402 | 0.00000 | 0.00000 | 677.1 |  |
| t2_a_lvrt_r6_square60_pu0500_d160ms | family_sac_after_finetune | 1 |  | 120.522 | 1.314 | 0.00000 | 0.00000 | 674.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d200ms | strong_dq | 0 | dc_link_bounds | 134.640 | 1.402 | 0.00000 | 0.00000 | 548.9 |  |
| t2_a_lvrt_r6_square60_pu0500_d200ms | family_sac_after_finetune | 1 |  | 120.415 | 1.314 | 0.00000 | 0.00000 | 665.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d240ms | strong_dq | 0 | dc_link_bounds | 136.787 | 1.402 | 0.00000 | 0.00000 | 526.9 |  |
| t2_a_lvrt_r6_square60_pu0500_d240ms | family_sac_after_finetune | 1 |  | 120.254 | 1.314 | 0.00000 | 0.00000 | 659.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0500_d300ms | strong_dq | 0 | dc_link_bounds | 142.825 | 1.402 | 0.00000 | 0.00000 | 466.5 |  |
| t2_a_lvrt_r6_square60_pu0500_d300ms | family_sac_after_finetune | 0 | dc_link_bounds | 124.005 | 1.314 | 0.00000 | 0.00000 | 609.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d080ms | strong_dq | 1 |  | 116.123 | 1.409 | 0.00000 | 0.00000 | 706.3 |  |
| t2_a_lvrt_r6_square60_pu0575_d080ms | family_sac_after_finetune | 1 |  | 118.866 | 1.298 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d120ms | strong_dq | 1 |  | 118.825 | 1.409 | 0.00000 | 0.00000 | 706.3 |  |
| t2_a_lvrt_r6_square60_pu0575_d120ms | family_sac_after_finetune | 1 |  | 118.759 | 1.298 | 0.00000 | 0.00000 | 711.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d160ms | strong_dq | 1 |  | 122.095 | 1.409 | 0.00000 | 0.00000 | 706.3 |  |
| t2_a_lvrt_r6_square60_pu0575_d160ms | family_sac_after_finetune | 1 |  | 118.459 | 1.298 | 0.00000 | 0.00000 | 696.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d200ms | strong_dq | 0 | dc_link_bounds | 129.167 | 1.409 | 0.00000 | 0.00000 | 576.5 |  |
| t2_a_lvrt_r6_square60_pu0575_d200ms | family_sac_after_finetune | 0 | dc_link_bounds | 118.355 | 1.298 | 0.00000 | 0.00000 | 648.0 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d240ms | strong_dq | 0 | dc_link_bounds;timestep_recovery_envelope | 142.880 | 1.409 | 0.00000 | 0.00120 | 451.1 |  |
| t2_a_lvrt_r6_square60_pu0575_d240ms | family_sac_after_finetune | 0 | dc_link_bounds | 121.213 | 1.298 | 0.00000 | 0.00000 | 616.0 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0575_d300ms | strong_dq | 0 | dc_link_bounds;timestep_recovery_envelope | 145.211 | 1.409 | 0.00000 | 0.00671 | 434.9 |  |
| t2_a_lvrt_r6_square60_pu0575_d300ms | family_sac_after_finetune | 1 |  | 117.885 | 1.298 | 0.00000 | 0.00000 | 661.5 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d080ms | strong_dq | 1 |  | 115.560 | 1.341 | 0.00000 | 0.00000 | 733.5 |  |
| t2_a_lvrt_r6_square60_pu0650_d080ms | family_sac_after_finetune | 1 |  | 116.527 | 1.292 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d120ms | strong_dq | 1 |  | 116.149 | 1.341 | 0.00000 | 0.00000 | 733.5 |  |
| t2_a_lvrt_r6_square60_pu0650_d120ms | family_sac_after_finetune | 1 |  | 116.279 | 1.292 | 0.00000 | 0.00000 | 677.5 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d160ms | strong_dq | 1 |  | 116.423 | 1.341 | 0.00000 | 0.00000 | 733.5 |  |
| t2_a_lvrt_r6_square60_pu0650_d160ms | family_sac_after_finetune | 0 | dc_link_bounds | 117.978 | 1.292 | 0.00000 | 0.00000 | 625.8 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d200ms | strong_dq | 1 |  | 116.479 | 1.341 | 0.00000 | 0.00000 | 733.5 |  |
| t2_a_lvrt_r6_square60_pu0650_d200ms | family_sac_after_finetune | 0 | dc_link_bounds | 117.344 | 1.292 | 0.00000 | 0.00000 | 629.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d240ms | strong_dq | 1 |  | 120.777 | 1.341 | 0.00000 | 0.00000 | 685.4 |  |
| t2_a_lvrt_r6_square60_pu0650_d240ms | family_sac_after_finetune | 1 |  | 115.251 | 1.292 | 0.00000 | 0.00000 | 650.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0650_d300ms | strong_dq | 1 |  | 120.814 | 1.341 | 0.00000 | 0.00000 | 733.5 |  |
| t2_a_lvrt_r6_square60_pu0650_d300ms | family_sac_after_finetune | 1 |  | 115.250 | 1.292 | 0.00000 | 0.00000 | 653.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d080ms | strong_dq | 1 |  | 115.681 | 1.364 | 0.00000 | 0.00000 | 781.4 |  |
| t2_a_lvrt_r6_square60_pu0700_d080ms | family_sac_after_finetune | 1 |  | 115.327 | 1.281 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d120ms | strong_dq | 1 |  | 115.791 | 1.364 | 0.00000 | 0.00000 | 781.4 |  |
| t2_a_lvrt_r6_square60_pu0700_d120ms | family_sac_after_finetune | 1 |  | 115.369 | 1.281 | 0.00000 | 0.00000 | 772.5 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d160ms | strong_dq | 1 |  | 115.890 | 1.364 | 0.00000 | 0.00000 | 777.1 |  |
| t2_a_lvrt_r6_square60_pu0700_d160ms | family_sac_after_finetune | 0 | dc_link_bounds | 115.219 | 1.281 | 0.00000 | 0.00000 | 644.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d200ms | strong_dq | 1 |  | 115.777 | 1.364 | 0.00000 | 0.00000 | 767.0 |  |
| t2_a_lvrt_r6_square60_pu0700_d200ms | family_sac_after_finetune | 0 | dc_link_bounds | 116.353 | 1.281 | 0.00000 | 0.00000 | 628.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d240ms | strong_dq | 1 |  | 115.727 | 1.364 | 0.00000 | 0.00000 | 761.2 |  |
| t2_a_lvrt_r6_square60_pu0700_d240ms | family_sac_after_finetune | 0 | dc_link_bounds | 114.602 | 1.281 | 0.00000 | 0.00000 | 644.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0700_d300ms | strong_dq | 1 |  | 115.871 | 1.364 | 0.00000 | 0.00000 | 761.2 |  |
| t2_a_lvrt_r6_square60_pu0700_d300ms | family_sac_after_finetune | 1 |  | 114.140 | 1.281 | 0.00000 | 0.00000 | 659.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d080ms | strong_dq | 1 |  | 112.508 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d080ms | family_sac_after_finetune | 1 |  | 112.836 | 1.276 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d120ms | strong_dq | 1 |  | 112.674 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d120ms | family_sac_after_finetune | 1 |  | 112.875 | 1.276 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d160ms | strong_dq | 1 |  | 113.762 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d160ms | family_sac_after_finetune | 1 |  | 112.426 | 1.276 | 0.00000 | 0.00000 | 664.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d200ms | strong_dq | 1 |  | 113.623 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d200ms | family_sac_after_finetune | 1 |  | 111.897 | 1.276 | 0.00000 | 0.00000 | 651.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d240ms | strong_dq | 1 |  | 113.618 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d240ms | family_sac_after_finetune | 1 |  | 111.783 | 1.276 | 0.00000 | 0.00000 | 657.8 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0750_d300ms | strong_dq | 1 |  | 114.795 | 1.285 | 0.00000 | 0.00000 | 797.7 |  |
| t2_a_lvrt_r6_square60_pu0750_d300ms | family_sac_after_finetune | 1 |  | 111.774 | 1.276 | 0.00000 | 0.00000 | 657.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d080ms | strong_dq | 1 |  | 110.468 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d080ms | family_sac_after_finetune | 1 |  | 111.360 | 1.268 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d120ms | strong_dq | 1 |  | 110.838 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d120ms | family_sac_after_finetune | 1 |  | 111.814 | 1.268 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d160ms | strong_dq | 1 |  | 113.878 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d160ms | family_sac_after_finetune | 1 |  | 111.740 | 1.268 | 0.00000 | 0.00000 | 666.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d200ms | strong_dq | 1 |  | 113.752 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d200ms | family_sac_after_finetune | 1 |  | 111.165 | 1.268 | 0.00000 | 0.00000 | 676.8 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d240ms | strong_dq | 1 |  | 113.702 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d240ms | family_sac_after_finetune | 1 |  | 111.104 | 1.268 | 0.00000 | 0.00000 | 680.4 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0800_d300ms | strong_dq | 1 |  | 113.709 | 1.294 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0800_d300ms | family_sac_after_finetune | 1 |  | 110.999 | 1.268 | 0.00000 | 0.00000 | 658.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d080ms | strong_dq | 1 |  | 110.337 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d080ms | family_sac_after_finetune | 1 |  | 110.576 | 1.260 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d120ms | strong_dq | 1 |  | 110.451 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d120ms | family_sac_after_finetune | 1 |  | 110.600 | 1.260 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d160ms | strong_dq | 1 |  | 112.735 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d160ms | family_sac_after_finetune | 1 |  | 110.835 | 1.260 | 0.00000 | 0.00000 | 735.0 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d200ms | strong_dq | 1 |  | 112.593 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d200ms | family_sac_after_finetune | 1 |  | 110.038 | 1.260 | 0.00000 | 0.00000 | 656.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d240ms | strong_dq | 1 |  | 112.539 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d240ms | family_sac_after_finetune | 1 |  | 109.914 | 1.260 | 0.00000 | 0.00000 | 698.5 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0825_d300ms | strong_dq | 1 |  | 112.485 | 1.260 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0825_d300ms | family_sac_after_finetune | 1 |  | 109.975 | 1.260 | 0.00000 | 0.00000 | 670.4 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d080ms | strong_dq | 1 |  | 109.232 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d080ms | family_sac_after_finetune | 1 |  | 109.906 | 1.256 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d120ms | strong_dq | 1 |  | 110.194 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d120ms | family_sac_after_finetune | 1 |  | 109.735 | 1.256 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d160ms | strong_dq | 1 |  | 110.875 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d160ms | family_sac_after_finetune | 1 |  | 110.023 | 1.256 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d200ms | strong_dq | 1 |  | 110.918 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d200ms | family_sac_after_finetune | 1 |  | 109.414 | 1.256 | 0.00000 | 0.00000 | 666.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d240ms | strong_dq | 1 |  | 110.869 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d240ms | family_sac_after_finetune | 1 |  | 109.048 | 1.256 | 0.00000 | 0.00000 | 677.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0850_d300ms | strong_dq | 1 |  | 110.821 | 1.285 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0850_d300ms | family_sac_after_finetune | 1 |  | 109.217 | 1.256 | 0.00000 | 0.00000 | 671.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d080ms | strong_dq | 1 |  | 109.818 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d080ms | family_sac_after_finetune | 1 |  | 108.664 | 1.252 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d120ms | strong_dq | 1 |  | 110.064 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d120ms | family_sac_after_finetune | 1 |  | 108.521 | 1.252 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d160ms | strong_dq | 1 |  | 110.003 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d160ms | family_sac_after_finetune | 1 |  | 108.803 | 1.252 | 0.00000 | 0.00000 | 799.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d200ms | strong_dq | 1 |  | 111.106 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d200ms | family_sac_after_finetune | 1 |  | 108.926 | 1.252 | 0.00000 | 0.00000 | 717.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d240ms | strong_dq | 1 |  | 111.061 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d240ms | family_sac_after_finetune | 1 |  | 108.266 | 1.252 | 0.00000 | 0.00000 | 663.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_r6_square60_pu0875_d300ms | strong_dq | 1 |  | 111.014 | 1.256 | 0.00000 | 0.00000 | 799.7 |  |
| t2_a_lvrt_r6_square60_pu0875_d300ms | family_sac_after_finetune | 1 |  | 107.995 | 1.252 | 0.00000 | 0.00000 | 678.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
