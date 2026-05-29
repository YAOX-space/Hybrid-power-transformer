# HPT v2 重建进度报告

更新日期：2026-05-25

## 为什么重做

旧数据和旧结论基于拓扑表达不清的模型，不能作为论文级结论继续使用。旧工作现在只保留为工具链验证：证明 Simulink 批量仿真、MATLAB 数据保存、Python 数据读取、GPU/DirectML 训练、传统/AI 对比脚本和 LVRT 指标脚本都能跑通。

以下旧结论已降级为 legacy，不再作为主结果：

- 基于旧拓扑生成的训练数据。
- 旧故障识别准确率。
- 旧传统方法与 AI 方法对比。
- 旧 DNN-FRT 控制效果。
- 旧 LVRT/FRT pass rate。
- 任何“击败文献”的判断。

## 已完成的新工作

### 1. 新拓扑模型

当前主模型：

```text
simulink/hpt_switching_model.slx
```

当前拓扑已经明确为混合式电力变压器结构：

```text
主功率通道:
Grid -> Series_Injection_Transformer_* -> Main_Line_Frequency_Transformer -> LV_Load

取能换流器:
400 V LV bus -> Energy_Filter_* -> Energy_Extraction_VSC -> DC_Link_Capacitor

调控换流器:
DC_Link_Capacitor -> Regulation_VSC_phase_* -> Series_Injection_Transformer_* -> main AC path
```

布局图：

```text
results/hpt_switching_model_layout.png
```

### 2. 新数据集

已基于当前 HPT v2 拓扑重新生成数据：

```text
data/raw_switching_hpt_v2
```

规模：

```text
7 类场景
每类 20 个开关级仿真文件
总计 140 个 .mat 文件
窗口数 1400
训练/验证/测试 = 980 / 210 / 210
采样率 20 kHz
窗口长度 100 samples = 5 ms
ControllerMode=2，传统规则 FRT
```

另生成 DNN-FRT 控制数据：

```text
data/raw_switching_hpt_v2_dnn
```

规模同样为 140 个 `.mat` 文件，`ControllerMode=3`。

## 新 LVRT/FRT 结果

### 传统规则 FRT，HPT v2

结果文件：

```text
results/lvrt_metrics_raw_switching_hpt_v2.json
results/lvrt_metrics_raw_switching_hpt_v2.csv
```

汇总：

| 场景 | 样本数 | Pass rate | V2min | VdcMax | I2Max |
|---|---:|---:|---:|---:|---:|
| normal | 20 | 100.00% | 0.925 | 1.105 | 1.577 |
| igbt_oc_sh | 20 | 65.00% | 0.926 | 1.123 | 1.565 |
| igbt_oc_se | 20 | 100.00% | 0.819 | 1.132 | 1.584 |
| cap_fault | 20 | 20.00% | 0.922 | 1.154 | 1.626 |
| sc_1ph | 20 | 25.00% | 0.686 | 1.103 | 1.922 |
| sc_3ph | 20 | 0.00% | 0.341 | 1.101 | 2.764 |
| cascade | 20 | 85.00% | 0.824 | 1.153 | 1.714 |

总体平均 pass rate：56.43%。

当前主要短板：三相短路、单相短路和电容故障。

### DNN-FRT，HPT v2

结果文件：

```text
results/lvrt_metrics_raw_switching_hpt_v2_dnn.json
results/lvrt_metrics_raw_switching_hpt_v2_dnn.csv
```

汇总：

| 场景 | 样本数 | Pass rate | V2min | VdcMax | I2Max |
|---|---:|---:|---:|---:|---:|
| normal | 20 | 0.00% | 0.934 | 0.981 | 1.695 |
| igbt_oc_sh | 20 | 5.00% | 0.914 | 1.091 | 1.713 |
| igbt_oc_se | 20 | 0.00% | 0.823 | 1.058 | 1.671 |
| cap_fault | 20 | 0.00% | 0.918 | 0.983 | 1.678 |
| sc_1ph | 20 | 0.00% | 0.706 | 0.987 | 1.842 |
| sc_3ph | 20 | 0.00% | 0.343 | 0.983 | 2.852 |
| cascade | 20 | 0.00% | 0.816 | 1.088 | 1.835 |

总体平均 pass rate：0.71%。

当前结论：DNN-FRT 在新拓扑上明显失败，不能作为有效控制结果。它需要重新训练或改成真正 Simulink-in-the-loop PPO/DRL，而不是沿用旧 surrogate/imitation 策略。

## 新故障识别结果

新 AI 模型：

```text
data/models/lstm_fault_detector_raw_switching_hpt_v2.pt
```

统一对比报告：

```text
results/fault_method_comparison_raw_switching_hpt_v2.md
results/fault_method_comparison_raw_switching_hpt_v2.json
```

排名：

| Rank | Method | Family | Accuracy | Macro F1 |
|---:|---|---|---:|---:|
| 1 | ELM | Traditional | 88.10% | 82.66% |
| 2 | SVM-RBF | Traditional | 86.19% | 82.05% |
| 3 | Random Forest | Traditional | 86.19% | 80.13% |
| 4 | AI-CNN | AI | 75.71% | 67.86% |
| 5 | Threshold centroid | Traditional | 60.00% | 38.10% |

当前诚实结论：在 HPT v2 的 140 文件数据集上，AI 故障识别没有超过传统方法。传统 ELM 暂时最强。

AI-CNN 分类短板：

- `cascade` 识别很差，F1 约 0.33。
- `igbt_oc_sh` 和 `igbt_oc_se` 仍有混淆。
- 正常类和串联侧开路、电容故障存在误判。

## 当前项目状态

项目已经从“旧拓扑工具链验证”推进到“正确 HPT 拓扑上的第一轮真实重建实验”。

已经完成：

- 正确 HPT 拓扑建模。
- 新拓扑 Simulink 模型重建。
- 新拓扑布局图导出。
- HPT v2 传统规则 FRT 数据集生成。
- HPT v2 DNN-FRT 数据集生成。
- 新 LVRT/FRT 指标计算。
- 新传统故障识别基线。
- 新 AI/CNN 故障识别训练。
- 新传统 vs AI 诊断对比。

尚未完成：

- 完整 dq 双闭环传统控制器。
- 同场景固定随机种子的严格控制器公平对比。
- PPO/DRL 在线闭环训练。
- AI 控制器在新拓扑上的有效超越。
- 论文级结论。

## 下一步优先级

1. 把取能换流器升级成 PLL + dq 电流内环 + Vdc 外环。
2. 把调控换流器升级成负载电压外环 + 串联注入电流/电压限幅。
3. 建立同一随机场景表，让传统规则 FRT、DNN-FRT、后续 PPO/DRL 在完全相同故障上比较。
4. 针对短路和电容故障重新设计 LVRT 控制目标，尤其关注 `VdcMin`、`VdcMax`、`I2Max` 和恢复时间。
5. 扩大 HPT v2 数据规模到每类 80-100 个文件，再训练 TCN/CNN-LSTM/Transformer。
6. 只有当 AI 在相同场景、相同指标下超过传统控制和传统诊断基线，才可以写“优于传统方法”。
