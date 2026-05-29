# PPO/DRL HPT v2 Training Curve

更新日期：2026-05-26

## 设置

真实 Simulink-in-the-loop PPO，使用 `ControllerMode=5`，从固定场景表三相短路段开始：

```text
scenario_table_hpt_v2.csv
start_row=250
epochs=3
steps_per_epoch=8, 16, 32
```

每个 epoch 使用 batch rollout：Python 写出 action table，MATLAB 单次启动后连续运行该 epoch 的多个 Simulink 场景。

奖励为 dense physical reward，包含：

```text
LVRT pass
V2min
VdcMin
VdcMax
I2Max
recovery time
V2 error
```

## 曲线结果

| steps/epoch | epoch | reward | pass | V2min | VdcMin | VdcMax | I2Max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 1 | 2.362 | 12.5% | 0.388 | 0.542 | 1.030 | 2.572 |
| 8 | 2 | 2.946 | 12.5% | 0.380 | 0.605 | 1.079 | 2.486 |
| 8 | 3 | 1.243 | 0.0% | 0.391 | 0.476 | 0.991 | 2.587 |
| 16 | 1 | 1.725 | 0.0% | 0.384 | 0.545 | 1.059 | 2.571 |
| 16 | 2 | 1.474 | 0.0% | 0.376 | 0.525 | 1.022 | 2.663 |
| 16 | 3 | 1.742 | 0.0% | 0.381 | 0.549 | 1.051 | 2.569 |
| 32 | 1 | 1.473 | 0.0% | 0.380 | 0.522 | 1.033 | 2.631 |
| 32 | 2 | 5.249 | 40.6% | 0.578 | 0.648 | 1.075 | 2.073 |
| 32 | 3 | 9.175 | 78.1% | 0.831 | 0.796 | 1.123 | 1.437 |

## 结论

`steps_per_epoch=32` 是当前第一个有效 PPO 训练设置。它在三相短路场景段上出现清晰改善：

```text
pass:   0.0% -> 40.6% -> 78.1%
V2min:  0.380 -> 0.578 -> 0.831
VdcMin: 0.522 -> 0.648 -> 0.796
I2Max:  2.631 -> 2.073 -> 1.437
```

`steps_per_epoch=8` 波动较大，`steps_per_epoch=16` 较稳定但没有学出 pass。当前判断是：真实 Simulink PPO 至少需要 32 个 rollout/epoch 才有足够批量信号。

## 下一步

## 10 Epoch 扩展训练

从 `ppo_hpt_v2_real_spe32.pt` 继续训练，设置：

```text
steps_per_epoch=32
epochs=10
start_row=250
```

| epoch | reward | pass | V2min | VdcMin | VdcMax | I2Max |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2.147 | 9.4% | 0.380 | 0.552 | 1.037 | 2.623 |
| 2 | 5.295 | 37.5% | 0.581 | 0.661 | 1.077 | 2.053 |
| 3 | 9.250 | 78.1% | 0.833 | 0.801 | 1.121 | 1.435 |
| 4 | 10.518 | 96.9% | 0.919 | 0.886 | 1.071 | 1.383 |
| 5 | 10.675 | 100.0% | 0.931 | 0.866 | 1.076 | 1.370 |
| 6 | 9.723 | 81.2% | 0.930 | 0.786 | 1.089 | 1.415 |
| 7 | 9.840 | 87.5% | 0.850 | 0.852 | 1.106 | 1.337 |
| 8 | 9.240 | 81.2% | 0.843 | 0.849 | 1.107 | 1.406 |
| 9 | 4.788 | 9.4% | 0.928 | 0.610 | 1.125 | 1.428 |
| 10 | 5.706 | 21.9% | 0.864 | 0.648 | 1.066 | 1.563 |

Best checkpoint:

```text
data/models/ppo_hpt_v2_real_spe32_10ep_best.pt
best_epoch=5
best_reward=10.675
```

## 350 场景完整评估

使用 best checkpoint 对完整固定场景表 350 个场景评估：

```text
results/ppo_hpt_v2_eval_spe32_10ep_best.json
results/lvrt_metrics_ppo_hpt_v2_spe32_10ep_best.json
```

总体：

```text
PPO/DRL pass=59.43%
mean reward=7.724
V2min mean=0.809
VdcMin mean=0.755
VdcMax mean=1.078
I2Max mean=1.615
```

按场景 pass：

```text
normal       100%
igbt_oc_sh    90%
igbt_oc_se   100%
cap_fault     20%
sc_1ph        16%
sc_3ph         2%
cascade       88%
```

与传统控制固定场景对比：

```text
dq double-loop  pass=64.00%
Rule-based FRT  pass=60.57%
PPO/DRL         pass=59.43%
DNN-FRT         pass=0.29%
```

结论：PPO 在训练段三相短路上能学出明显改善，但泛化到完整 350 场景后尚未超过 dq double-loop 或 Rule-based FRT。

## 下一步

1. 训练场景从单一三相短路段扩展到 `sc_1ph + sc_3ph + cap_fault + cascade` 混合段。
2. 加入 best checkpoint early stopping，避免 10 epoch 后半段退化。
3. 在奖励中提高 `VdcMin < 0.75` 的惩罚，当前完整评估的主要失败来自 DC link 欠压。
4. 用固定 350 场景完整评估每个候选 best checkpoint，再与 dq double-loop 和 Rule-based FRT 排名。
