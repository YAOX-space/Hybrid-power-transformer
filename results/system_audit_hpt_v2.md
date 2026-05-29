# HPT v2 System Audit And Cleanup

更新日期：2026-05-25

## 审计结论

项目当前主线已经收敛到正确的 HPT v2 开关级 Simulink 模型。早期平均模型、ODE 模型、合成数据、旧拓扑数据和旧结果报告已经清理。

当前所有保留的主线测试都基于：

```text
simulink/hpt_switching_model.slx
```

必要拓扑块已由 MATLAB 检查确认存在：

```text
Energy_Extraction_VSC
Regulation_VSC_phase_1
Regulation_VSC_phase_2
Regulation_VSC_phase_3
Series_Injection_Transformer_1
Series_Injection_Transformer_2
Series_Injection_Transformer_3
Main_Line_Frequency_Transformer
LV_Load
LV_AC_Fault
DC_Link_Capacitor
```

## 当前保留的数据

```text
data/raw_switching_hpt_v2
data/raw_switching_hpt_v2_dnn
data/raw_switching_hpt_v2_dq_smoke
data_collection/scenario_table_hpt_v2.csv
data_collection/scenario_table_hpt_v2_smoke.csv
data/processed/fault_windows_raw_switching_hpt_v2.npz
data/processed/fault_scaler_raw_switching_hpt_v2.pkl
data/models/lstm_fault_detector_raw_switching_hpt_v2.pt
data/models/lstm_fault_detector_raw_switching_hpt_v2_tcn.pt
data/models/lstm_fault_detector_raw_switching_hpt_v2_cnn_lstm.pt
data/models/ppo_hpt_v2_dry_run.pt
```

## 当前保留的核心程序

```text
simulink/build_hpt_switching_model.m
simulink/hpt_switching_model.slx
simulink/parameters.m
simulink/dnn_frt_policy.m
simulink/test_switching_quick.m
simulink/validate_switching_model.m

data_collection/run_switching_scenarios.m
data_collection/generate_hpt_v2_scenario_table.py

ai/data_loader.py
ai/lstm_fault_detector.py
ai/traditional_fault_baselines.py
ai/fault_method_comparison.py
ai/lvrt_metrics.py
ai/control_method_comparison.py
ai/train_dnn_frt_imitation.py
ai/ppo_hpt_v2.py
```

## 已删除内容

已删除不再属于主线的早期程序：

```text
data_collection/run_scenarios.m
simulink/build_hpt_model.m
simulink/build_hpt_ee.m
simulink/hpt_ode_model.m
simulink/run_ode_scenarios.m
simulink/test_ode_quick.m
simulink/test_ode_v2.m
simulink/test_sim_batch.m
simulink/design_pi_controller.m
ai/generate_synthetic_mat.py
ai/dnn_controller.py
ai/drl_trainer.m
ai/frt_controller.py
ai/cwt_cnn_localizer.py
ai/evaluate.py
```

已删除旧数据目录：

```text
data/raw
data/raw_ode
data/raw_switching
data/raw_switching_closed_loop
data/raw_switching_frt_*
data/raw_control_*
```

已删除旧模型和旧缓存：

```text
data/models/*raw_switching*.pt, except hpt_v2
data/models/dnn_frt_imitation.pt
data/processed/*raw_switching*.npz/pkl, except hpt_v2
```

已删除旧报告，只保留 HPT v2 报告。

## 验证结果

MATLAB 拓扑检查：

```text
HPT v2 topology blocks verified: 11 required blocks found.
```

快速仿真：

```text
normal: samples=401  Vdc_final=775.66  P1_final=319130.46
3ph fault: samples=401  Vdc_final=1085.15  P1_final=4397759.48
```

多工况 sanity 验证：

```text
normal   Vdc_final=819.8   V2_LL_rms=379.0
igbt_sh  Vdc_final=879.7   V2_LL_rms=379.4
igbt_se  Vdc_final=872.0   V2_LL_rms=375.1
cap      Vdc_final=0.1     V2_LL_rms=369.7
sc_1ph   Vdc_final=513.1   V2_LL_rms=367.4
sc_3ph   Vdc_final=1057.5  V2_LL_rms=309.5
cascade  Vdc_final=914.9   V2_LL_rms=376.1
```

HPT v2 控制对比：

```text
Rule-based FRT: pass=56.43% VdcMin=0.488 VdcMax=1.154 I2Max=2.764
DNN-FRT: pass=0.71% VdcMin=0.227 VdcMax=1.091 I2Max=2.852
dq double-loop baseline: pass=71.43% VdcMin=0.654 VdcMax=1.127 I2Max=2.525
PPO/DRL controller: planned; not yet trained in Simulink loop
```

说明：dq double-loop baseline 当前仅为固定场景表 smoke 结果，不能与 140 文件旧随机批次作论文级排名。正式竞争需要用 `scenario_table_hpt_v2.csv` 对所有控制器重新跑完整 350 场景。

HPT v2 故障识别对比：

```text
ELM: 88.10% accuracy, 82.66% macro F1
SVM-RBF: 86.19% accuracy, 82.05% macro F1
Random Forest: 86.19% accuracy, 80.13% macro F1
AI-CNN: 75.71% accuracy, 67.86% macro F1
AI-CNN-LSTM: 80.48% accuracy, 72.39% macro F1
AI-TCN: 75.71% accuracy, 69.23% macro F1
Threshold centroid: 60.00% accuracy, 38.10% macro F1
```

说明：TCN/CNN-LSTM 已完成当前旧随机批次数据上的 60 epoch 训练，但仍不是固定场景表的最终论文结果。

固定场景表：

```text
scenario_table_hpt_v2.csv: 350 scenarios, seed=20260525
scenario_table_hpt_v2_smoke.csv: 7 scenarios
```

PPO/DRL：

```text
ppo_hpt_v2.py dry-run passed, reward includes LVRT pass, VdcMin, VdcMax, I2Max, recovery time, and V2 error integral.
Real Simulink-in-the-loop PPO is not enabled yet.
```

## 后续方向

当前结论仍然是：AI 尚未超过传统方法。

下一步应集中在三条线：

1. 正常运行控制：实现完整 dq 双闭环传统基线，再让 AI 在 V2 RMS error、Vdc ripple、I2 peak 上竞争。
2. 故障检测：训练 TCN/CNN-LSTM/Transformer，目标超过 ELM 的 88.10% accuracy 和 82.66% macro F1。
3. 故障穿越：用 Simulink-in-the-loop PPO/DRL 直接优化 `VdcMin/VdcMax/I2Max/recovery time`，目标超过 rule-based FRT 的 56.43% 平均 pass rate。
