# HPT family-specialist matrix summary

This run evaluates one existing actor across the family matrix; no training occurs in this run.

## Configuration

- family_label: `t2_a_lvrt_joint_support_r6`
- topology: `topology2`
- category: `LVRT`
- phase_key: `a`
- train_depths: `None`
- train_durations_ms: `None`
- eval_depths: `[0.5, 0.6, 0.625]`
- eval_durations_ms: `[160, 200, 240]`

## Controller Summary

| controller | rows | pass | active Vdc pass | GBT Vdc survive | pass while dq fails | score < dq | score < seed | score mean | grid I max | env max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| family_sac_after_finetune | 9 | 8 | 8 | 9 | 4 | 9 | 3 | 118.587 | 1.314 | 0.00000 |
| family_seed_before_sac | 9 | 4 | 4 | 9 | 3 | 9 | 0 | 118.616 | 1.313 | 0.00000 |
| strong_dq | 9 | 4 | 4 | 5 | 0 | 0 | 0 | 125.350 | 1.402 | 0.00000 |

## Per-case rows

| case | controller | pass | reason | score | grid I | env | recovery | Vdc min | actor model |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| t2_a_lvrt_joint_support_r6_pu0500_d160ms | strong_dq | 1 |  | 122.357 | 1.402 | 0.00000 | 0.00000 | 677.1 |  |
| t2_a_lvrt_joint_support_r6_pu0500_d160ms | family_seed_before_sac | 1 |  | 120.443 | 1.313 | 0.00000 | 0.00000 | 681.4 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0500_d200ms | strong_dq | 0 | dc_link_bounds | 134.640 | 1.402 | 0.00000 | 0.00000 | 548.9 |  |
| t2_a_lvrt_joint_support_r6_pu0500_d200ms | family_seed_before_sac | 1 |  | 120.321 | 1.313 | 0.00000 | 0.00000 | 663.7 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0500_d240ms | strong_dq | 0 | dc_link_bounds | 136.787 | 1.402 | 0.00000 | 0.00000 | 526.9 |  |
| t2_a_lvrt_joint_support_r6_pu0500_d240ms | family_seed_before_sac | 0 | dc_link_bounds | 121.698 | 1.313 | 0.00000 | 0.00000 | 634.3 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d160ms | strong_dq | 1 |  | 120.049 | 1.373 | 0.00000 | 0.00000 | 713.2 |  |
| t2_a_lvrt_joint_support_r6_pu0600_d160ms | family_seed_before_sac | 0 | dc_link_bounds | 119.986 | 1.294 | 0.00000 | 0.00000 | 619.7 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d200ms | strong_dq | 1 |  | 120.577 | 1.373 | 0.00000 | 0.00000 | 701.9 |  |
| t2_a_lvrt_joint_support_r6_pu0600_d200ms | family_seed_before_sac | 0 | dc_link_bounds | 117.226 | 1.294 | 0.00000 | 0.00000 | 646.2 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d240ms | strong_dq | 1 |  | 120.719 | 1.373 | 0.00000 | 0.00000 | 696.2 |  |
| t2_a_lvrt_joint_support_r6_pu0600_d240ms | family_seed_before_sac | 0 | dc_link_bounds | 118.273 | 1.294 | 0.00000 | 0.00000 | 633.7 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d160ms | strong_dq | 0 | dc_link_bounds | 125.185 | 1.402 | 0.00000 | 0.00000 | 577.0 |  |
| t2_a_lvrt_joint_support_r6_pu0625_d160ms | family_seed_before_sac | 1 |  | 116.200 | 1.292 | 0.00000 | 0.00000 | 658.9 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d200ms | strong_dq | 0 | dc_link_bounds | 121.888 | 1.402 | 0.00000 | 0.00000 | 612.8 |  |
| t2_a_lvrt_joint_support_r6_pu0625_d200ms | family_seed_before_sac | 1 |  | 115.959 | 1.292 | 0.00000 | 0.00000 | 657.4 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d240ms | strong_dq | 0 | dc_link_bounds | 125.952 | 1.402 | 0.00000 | 0.00000 | 568.5 |  |
| t2_a_lvrt_joint_support_r6_pu0625_d240ms | family_seed_before_sac | 0 | dc_link_bounds | 117.437 | 1.292 | 0.00000 | 0.00000 | 634.3 | hpt_t2_a_lvrt_joint_support_family_sac_r5_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0500_d160ms | family_sac_after_finetune | 1 |  | 120.522 | 1.314 | 0.00000 | 0.00000 | 674.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0500_d200ms | family_sac_after_finetune | 1 |  | 120.415 | 1.314 | 0.00000 | 0.00000 | 665.6 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0500_d240ms | family_sac_after_finetune | 1 |  | 120.254 | 1.314 | 0.00000 | 0.00000 | 659.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d160ms | family_sac_after_finetune | 1 |  | 118.047 | 1.298 | 0.00000 | 0.00000 | 666.1 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d200ms | family_sac_after_finetune | 1 |  | 117.905 | 1.298 | 0.00000 | 0.00000 | 668.2 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0600_d240ms | family_sac_after_finetune | 1 |  | 117.667 | 1.298 | 0.00000 | 0.00000 | 655.3 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d160ms | family_sac_after_finetune | 1 |  | 116.969 | 1.295 | 0.00000 | 0.00000 | 654.9 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d200ms | family_sac_after_finetune | 1 |  | 116.782 | 1.295 | 0.00000 | 0.00000 | 668.7 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
| t2_a_lvrt_joint_support_r6_pu0625_d240ms | family_sac_after_finetune | 0 | dc_link_bounds | 118.722 | 1.295 | 0.00000 | 0.00000 | 626.5 | hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip |
