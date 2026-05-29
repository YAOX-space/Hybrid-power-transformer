# AI Strategy on Correct HPT v2 Model

更新日期：2026-05-25

## 原则

所有 AI 方法必须在当前正确 HPT v2 开关级模型上验证：

```text
simulink/hpt_switching_model.slx
```

旧拓扑、ODE、平均模型和合成数据不能用于主结论。

## 竞争对象

| 任务 | AI 方法 | 必须击败的传统基线 | 主要指标 |
|---|---|---|---|
| 正常运行 | supervised policy / RL policy | dq PI / rule control | V2 RMS error, Vdc ripple, I2 peak, P/Q tracking |
| 故障检测 | CNN, TCN, CNN-LSTM, Transformer | ELM, SVM-RBF, Random Forest | Accuracy, macro F1, confusion matrix, 5 ms latency |
| 故障穿越 | PPO/DRL, hybrid imitation+RL | Rule-based FRT | LVRT pass, VdcMin, VdcMax, I2Max, recovery time |
| 综合策略 | fault-aware controller | traditional multi-mode control | 同场景综合得分 |

## 当前基线

### 故障检测

当前 HPT v2 数据集：

```text
data/raw_switching_hpt_v2
```

当前结果：

| Method | Family | Accuracy | Macro F1 |
|---|---|---:|---:|
| ELM | Traditional | 88.10% | 82.66% |
| SVM-RBF | Traditional | 86.19% | 82.05% |
| Random Forest | Traditional | 86.19% | 80.13% |
| AI-CNN-LSTM | AI | 80.48% | 72.39% |
| AI-TCN | AI | 75.71% | 69.23% |
| AI-CNN | AI | 75.71% | 67.86% |

结论：AI 诊断尚未超过传统方法。

### 故障穿越

| Controller | Family | Mean LVRT Pass | VdcMin | VdcMax | I2Max |
|---|---|---:|---:|---:|---:|
| Rule-based FRT | Traditional | 56.43% | 0.4877 | 1.1537 | 2.7640 |
| DNN-FRT | AI | 0.71% | 0.2270 | 1.0907 | 2.8515 |
| dq double-loop smoke | Traditional | 71.43% | 0.6537 | 1.1270 | 2.5249 |

结论：当前 DNN-FRT 失败，不能作为有效 AI 控制结果。

说明：dq double-loop 当前只跑了 `scenario_table_hpt_v2_smoke.csv` 的 7 个固定场景，不能和 Rule-based FRT/DNN-FRT 的 140 文件旧随机批次直接做最终排名。

## 策略 1：正常运行 AI 控制

目标：

- 稳定低压侧电压。
- 减小 DC link 波动。
- 限制二次侧电流峰值。
- 保持 P/Q 跟踪或功率因数目标。

建议方法：

1. 先实现完整传统 dq 双闭环，作为强基线。
2. 用传统控制生成正常运行 imitation 数据。
3. 训练轻量策略网络，输入 `V2abc/I2abc/Vdc/P2/Q2`，输出取能换流器和调控换流器调制参考。
4. 用物理指标筛选，不允许只看 MSE。

最低胜出标准：

```text
V2 RMS error <= traditional dq PI
Vdc ripple <= traditional dq PI
I2Max <= traditional dq PI
normal LVRT pass = 100%
```

## 策略 2：故障检测 AI

当前 AI-CNN 弱点：

- `cascade` F1 很低。
- `igbt_oc_sh` 与 `igbt_oc_se` 有混淆。
- 正常窗口占比偏高，容易让 AI 偏向 normal。

下一轮模型：

1. TCN：适合 5 ms 窗口和实时因果推理。
2. CNN-LSTM：用 CNN 抽取开关纹波/暂态特征，再用 LSTM 建模故障演化。
3. Transformer encoder：用于更长窗口或多尺度窗口。
4. Multi-task learning：同时预测故障类别、故障相/开关位置、故障严重度。

最低胜出标准：

```text
Accuracy > 88.10%
Macro F1 > 82.66%
Latency <= 5 ms window
No single fault class F1 < 70%
```

## 策略 3：故障穿越 AI 控制

当前 DNN-FRT 失败原因：

- policy 来自旧拓扑/旧 surrogate。
- 没有在真实 Simulink 闭环中用 LVRT 指标训练。
- `VdcMin`、`I2Max`、recovery time 没有形成真实闭环约束。

建议路线：

1. 先做 hybrid imitation：让 AI 学 rule-based FRT 的保守动作。
2. 再做 Simulink-in-the-loop PPO/DRL：奖励直接使用物理指标。
3. 加入 safety shield：AI 输出必须经过 Vdc/I2/V2 限幅器。
4. 所有控制器使用固定场景表比较。

奖励函数建议：

```text
reward =
  + w1 * LVRT_pass
  - w2 * max(0, 0.75 - VdcMin)
  - w3 * max(0, VdcMax - 1.25)
  - w4 * max(0, I2Max - 3.0)
  - w5 * recovery_time_ms / 100
  - w6 * V2_error_integral
```

最低胜出标准：

```text
Mean LVRT pass > 56.43%
sc_3ph pass > 0%
VdcMin >= rule-based FRT
I2Max <= rule-based FRT
Recovery time <= rule-based FRT
```

## 策略 4：公平竞争框架

必须建立统一 scenario table：

```text
scenario_id
sc_id
t_fault
fault_variant
fault_mag
P_load
Q_load
fault_resistance
controller_mode
random_seed
```

当前已经建立：

```text
data_collection/scenario_table_hpt_v2.csv        # 350 scenarios, seed=20260525
data_collection/scenario_table_hpt_v2_smoke.csv  # 7 scenarios
```

传统控制、AI 控制、PPO/DRL 都跑同一组场景，结果才可比较。

## 已完成的新增实现

1. `run_switching_scenarios.m` 已支持 `HPT_SCENARIO_TABLE`，可以按固定 CSV 场景驱动 Simulink。
2. `ControllerMode=4` 已加入 HPT v2 模型，用于 dq 双闭环传统控制 smoke baseline。
3. `lstm_fault_detector.py` 已加入 TCN 和 CNN-LSTM 架构，并保存架构独立 checkpoint。
4. `fault_method_comparison.py` 已能统一评估传统方法、CNN、TCN、CNN-LSTM。
5. `ppo_hpt_v2.py` 已建立 PPO/DRL 框架和物理奖励；当前通过 dry-run，真实 Simulink 闭环尚未接通。

## 下一步实验顺序

1. 用完整 `scenario_table_hpt_v2.csv` 重跑 Rule-based FRT、dq double-loop、DNN-FRT。
2. 在固定场景数据上重训 CNN/TCN/CNN-LSTM，目标超过 ELM。
3. 做 safe imitation FRT，先追平 rule-based FRT。
4. 将 PPO/DRL 接入真实 Simulink 闭环，用真实 LVRT 指标优化。
5. 写论文前只使用 HPT v2 固定场景结果，不引用 legacy 数值。
