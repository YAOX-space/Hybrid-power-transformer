# HPT v2 Current Progress

更新日期：2026-05-26

## 当前状态

项目已经收敛到正确的 HPT v2 开关级 Simulink 模型：

```text
simulink/hpt_switching_model.slx
```

拓扑包含主工频变压器、取能换流器、直流母线、三相串联调控换流器和串联注入变压器。当前保留测试均围绕该模型展开。

## 已完成

1. 建立固定随机场景表：

```text
data_collection/scenario_table_hpt_v2.csv        # 350 scenarios, 7 classes x 50
data_collection/scenario_table_hpt_v2_smoke.csv  # 7 scenarios
```

2. 批量仿真脚本已支持固定场景表：

```text
data_collection/run_switching_scenarios.m
```

3. 传统控制基线已扩展：

```text
ControllerMode=2  rule-based FRT
ControllerMode=4  dq double-loop baseline v1
ControllerMode=5  PPO/DRL action-controlled baseline
```

4. AI 故障检测已扩展：

```text
CNN
TCN
CNN-LSTM
```

5. PPO/DRL 已建立训练框架和奖励函数：

```text
ai/ppo_hpt_v2.py
```

奖励已经包含：

```text
LVRT pass
VdcMin
VdcMax
I2Max
recovery time
V2 error integral
```

当前 PPO 已完成 dry-run 和真实 Simulink-in-the-loop smoke。真实 smoke 会调用 Simulink、写入 RL 动作、读取 LVRT 指标并更新 PPO 网络；完整 350 场景训练尚未完成。

PPO 已完成两项优化：

```text
1. 批量 rollout：Python 每个 epoch 写出 PPO action table，MATLAB 单次启动后连续运行多个 Simulink 场景。
2. Dense reward：奖励不再只依赖 pass/fail，而是连续使用 V2min、VdcMin、VdcMax、I2Max、recovery time 和 V2 error。
```

6. 完整固定场景数据已生成：

```text
data/raw_switching_hpt_v2_fixed_rule  # 350 files
data/raw_switching_hpt_v2_fixed_dq    # 350 files
data/raw_switching_hpt_v2_fixed_dnn   # 350 files
data/raw_switching_hpt_v2_fixed_all   # 1050 files
```

## 当前验证结果

Simulink 快速测试通过：

```text
normal: samples=401  Vdc_final=775.66  P1_final=319130.46
3ph fault: samples=401  Vdc_final=1085.15  P1_final=4397759.48
```

多工况 sanity 测试通过：

```text
normal   Vdc_final=819.8   V2_LL_rms=379.0
igbt_sh  Vdc_final=879.7   V2_LL_rms=379.4
igbt_se  Vdc_final=872.0   V2_LL_rms=375.1
cap      Vdc_final=0.1     V2_LL_rms=369.7
sc_1ph   Vdc_final=513.1   V2_LL_rms=367.4
sc_3ph   Vdc_final=1057.5  V2_LL_rms=309.5
cascade  Vdc_final=914.9   V2_LL_rms=376.1
```

故障识别当前排名：

```text
Random Forest        acc=95.68%  macroF1=94.74%
ELM                  acc=88.83%  macroF1=86.21%
SVM-RBF              acc=87.68%  macroF1=86.12%
AI-TCN               acc=83.37%  macroF1=80.48%
AI-CNN-LSTM          acc=82.79%  macroF1=79.85%
AI-CNN               acc=79.75%  macroF1=76.53%
Threshold centroid   acc=58.48%  macroF1=36.37%
```

控制方法当前结果：

```text
dq double-loop        pass=64.00%  VdcMin=0.470  VdcMax=1.155  I2Max=3.435
Rule-based FRT        pass=60.57%  VdcMin=0.469  VdcMax=1.155  I2Max=3.431
DNN-FRT               pass=0.29%   VdcMin=0.213  VdcMax=1.120  I2Max=3.474
```

PPO/DRL 真实闭环 smoke：

```text
old single-step interface: epoch=001 reward=-1.586 pass=0.0% Vdc=[0.570,1.041] I2=2.763
new batch+dense-reward:   epoch=001 reward=4.477  pass=50.0% V2min=0.319 Vdc=[0.629,1.049] I2=2.740
checkpoint=data/models/ppo_hpt_v2_real.pt
report=results/ppo_hpt_v2_real.json
```

PPO/DRL 训练曲线已开始：

```text
steps_per_epoch=8:  reward 2.362 -> 2.946 -> 1.243, pass 12.5% -> 12.5% -> 0.0%
steps_per_epoch=16: reward 1.725 -> 1.474 -> 1.742, pass 0.0% -> 0.0% -> 0.0%
steps_per_epoch=32: reward 1.473 -> 5.249 -> 9.175, pass 0.0% -> 40.6% -> 78.1%
```

PPO/DRL 10 epoch 扩展训练：

```text
best epoch=5
best training reward=10.675
best training pass=100.0%
checkpoint=data/models/ppo_hpt_v2_real_spe32_10ep_best.pt
```

完整 350 场景评估：

```text
PPO/DRL pass=59.43%
dq double-loop pass=64.00%
Rule-based FRT pass=60.57%
DNN-FRT pass=0.29%
```

结论：PPO 在三相短路训练段能明显学到穿越动作，但完整固定表泛化还没有超过 dq 双闭环和 Rule-based FRT。

详细报告：

```text
results/ppo_hpt_v2_training_curve.md
```

## 当前诚实结论

AI 还没有击败传统方法。

旧拓扑生成的训练数据、旧故障识别准确率、旧 DNN-FRT 控制效果、旧 LVRT/FRT pass rate 和任何“击败文献”的判断，都只能作为工具链验证，不是主结果。

## 下一步

1. 继续训练 PPO/DRL：以 `steps_per_epoch=32` 作为当前有效设置，扩展到 10-20 epoch。
2. 针对 AI 检测继续做更强模型：multi-task TCN/Transformer、控制器域标签、故障位置/严重度辅助任务。
3. 针对 dq 双闭环继续调参，重点提升 `sc_1ph` 和 `sc_3ph` 的 pass rate，同时控制 I2Max。
4. 只有完整固定场景结果超过传统控制/传统诊断后，才可写入论文级结论。
