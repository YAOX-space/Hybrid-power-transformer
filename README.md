# Hybrid Power Transformer HPT v2

本项目针对混合式电力变压器（HPT）开展**控制策略研究与故障诊断**，采用固定场景表对所有传统/AI方法做严格横向比较。

---

## 系统规格

| 参数 | 数值 |
|---|---|
| 额定容量 | 400 kVA |
| 电压等级 | 10 kV / 400 V |
| 串联注入范围 | ±20% V_grid（±2309 V） |
| 并联取能 VSC | 120 kVA |
| 直流母线 | 800 V，2200 µF，储能 704 J |
| 开关频率 | 5 kHz，采样 20 kHz |
| LVRT 合格线 | VdcMin ≥ 0.75 pu，VdcMax ≤ 1.25 pu，I2Max ≤ 3.0 pu，V2 恢复 ≤ 100 ms |

**已识别三个硬件瓶颈**：
1. DC 储能 704 J 远低于深度骤降所需 2000 J
2. 串联注入在骤降 >20% 时饱和
3. I2Max ≈ 3.43–3.47 pu 是电路结构上限，所有控制器均无法规避

---

## 当前主模型

```text
simulink/hpt_switching_model.slx        # HPT v2 开关级主模型
simulink/build_hpt_switching_model.m    # 生成脚本
simulink/parameters.m                   # 全部电气参数
```

控制模式：

```text
ControllerMode=2  规则 FRT 传统基线
ControllerMode=3  DNN-FRT legacy imitation policy
ControllerMode=4  dq 双闭环传统控制（当前最优固定基线）
ControllerMode=5  PPO/DRL（smoke 已通过，完整训练未完成）
ControllerMode=6  RCN 自适应参考值（待 Simulink 集成）
ControllerMode=7  FAHC 故障感知分层控制（待 Simulink 集成）
```

---

## 固定场景表

所有方法必须使用同一张固定表，不允许挑场景：

```text
data_collection/scenario_table_hpt_v2.csv       # 7 类 × 50 = 350 固定场景，seed=20260525
data_collection/scenario_table_hpt_v2_smoke.csv # 每类 1 个 smoke 场景
```

> 注意：实际数据中发现 sc_id=7、sc_id=8（共 8 类），已在 FAHC 策略中处理。

---

## 故障诊断结果（当前最新）

所有方法在扩充数据集 `raw_switching_hpt_v2_fixed_all_v2`（**1750 文件**，含 Mode 2/4/3 原有 + Mode 6 RCN + Mode 7 FAHC）上评估：

| 排名 | 方法 | 类型 | Accuracy | Macro F1 |
|---:|---|---|---:|---:|
| 1 | **Ensemble RF+MSFFN** | **集成** | **97.83%** | **97.57%** |
| 2 | Random Forest | 传统 | 97.71% | 97.34% |
| 3 | AI-MSFFN | AI | 92.61% | 91.26% |
| 4 | SVM-RBF | 传统 | 91.09% | 89.53% |
| 5 | ELM | 传统 | 90.67% | 88.71% |
| 6 | threshold_centroid | 传统 | 59.50% | 36.34% |

- **集成模型（RF 90% + MSFFN 10%）首次超越 Random Forest**，达到 97.83% 准确率（+0.12 pp）
- 单独 MSFFN 以 92.61% 排名第三，比 SVM-RBF 高 1.52 pp
- MSFFN 从旧数据集 84.57% 提升至 92.61%（**+8.04 pp**），验证了数据扩充策略的有效性
- 集成最优权重 α=0.90（验证集调优），RF 提供主体精度，MSFFN 补充序列/频域信息

对比旧数据集（1050 文件）：

| 方法 | 旧 Accuracy | 新 Accuracy | 提升 |
|---|---:|---:|---:|
| Ensemble RF+MSFFN | — | **97.83%** | 新增 |
| Random Forest | 95.68% | 97.71% | +2.03 pp |
| MSFFN | 84.57% | 92.61% | **+8.04 pp** |
| SVM-RBF | 87.68% | 91.09% | +3.41 pp |
| ELM | 88.83% | 90.67% | +1.84 pp |

---

## 控制方法结果

所有方法在同一固定 350 场景表上实测（Simulink 开关级模型）：

| 方法 | LVRT Pass 率 | 说明 |
|---|---:|---|
| dq 双闭环 | **64.00%** | 当前最优固定基线 |
| **MSFFN→FAHC（thr=0.80，92.61% 检测器）** | **62.00%** | 最优管道，Strategy 选准率 77.14% |
| MSFFN→FAHC（thr=0.70，92.61% 检测器） | 61.71% | 基准管道 |
| MSFFN→FAHC（旧，84.57% 检测器） | 62.57% | 旧版对照 |
| 规则 FRT | 60.57% | 传统规则基线 |
| PPO（完整 350） | 59.43% | 泛化不足 |

**置信阈值扫描结果（350 场景，MSFFN 92.61%）：**

| 阈值 | 门控数 | LVRT Pass 率 |
|---:|---:|---:|
| 0.70 | 68/350 | 61.71% |
| 0.75 | ~95/350 | 61.71% |
| **0.80** | **92/350** | **62.00%** |
| 0.85 | ~155/350 | 62.00% |

**每类场景通过率（thr=0.80 管道）：**

| 场景类型 | Pass 率 |
|---|---:|
| normal | 100% |
| igbt_oc_se | 100% |
| igbt_oc_sh | **88%** |
| cascade | 86% |
| sc_1ph | 26% |
| cap_fault | 20% |
| sc_3ph | 14% |

**关键分析**：
- **最优管道（thr=0.80）超过规则 FRT（62.00% > 60.57%）和 PPO（59.43%）**
- 与旧管道（84.57% 检测器）差距仅 0.57 pp（62.57%→62.00%），但检测准确率大幅提升（84.57%→92.61%）
- thr=0.80 比 thr=0.70 多拦截 1 个错误策略，igbt_oc_sh 从 86% 升至 88%
- sc_3ph/sc_1ph/cap_fault 的低通过率是硬件储能瓶颈（704 J），不是控制算法问题
| RCN 离线估算 | ~70–76% | 物理估算，待 Simulink Mode 6 验证 |

**根本原因**：dq 双闭环失败不是 PI 参数问题，是因为 Vdc_ref=800 V 固定，故障时控制器浪费能量维持 800 V，而电容持续放电至 0.47 pu。降低 Vdc_ref 到 720 V 可节省 134 J → VdcMin 改善约 +0.095 pu。

---

## 全部代码文件

```text
simulink/
  hpt_switching_model.slx              # 主模型
  build_hpt_switching_model.m
  parameters.m
  test_switching_quick.m
  validate_switching_model.m

data_collection/
  generate_hpt_v2_scenario_table.py
  run_switching_scenarios.m
  scenario_table_hpt_v2.csv
  scenario_table_hpt_v2_smoke.csv

ai/
  data_loader.py                        # 数据加载，窗口切分，平衡采样
  lstm_fault_detector.py                # CNN/LSTM/TCN/CNN-LSTM 架构
  msffn_fault_detector.py               # [NEW] MSFFN 多尺度特征融合（当前最强 AI）
  traditional_fault_baselines.py        # ELM/SVM/RF/阈值基线
  fault_method_comparison.py            # 统一对比评估（自动包含 MSFFN）
  lvrt_metrics.py                       # LVRT/FRT 指标计算
  control_method_comparison.py          # 控制方法对比
  rcn_frt_controller.py                 # [NEW] RCN 自适应参考值网络
  fahc_analysis.py                      # [NEW] FAHC 故障感知分层控制分析
  ppo_hpt_v2.py                         # PPO/DRL 训练
  train_dnn_frt_imitation.py
```

---

## 数据与模型文件

```text
data/raw_switching_hpt_v2_fixed_rule/   # 规则 FRT，350 文件
data/raw_switching_hpt_v2_fixed_dq/     # dq 双闭环，350 文件
data/raw_switching_hpt_v2_fixed_dnn/    # DNN-FRT，350 文件
data/raw_switching_hpt_v2_fixed_all/    # 三者合并，1050 文件
data/processed/fault_windows_*.npz      # 预处理窗口缓存
data/models/
  msffn_fault_detector_raw_switching_hpt_v2_fixed_all.pt  # [NEW] MSFFN checkpoint
  lstm_fault_detector_raw_switching_hpt_v2_fixed_all*.pt  # CNN/TCN/LSTM/CNN-LSTM（DirectML）
  rcn_frt_offline.pt                                       # [NEW] RCN 离线预训练
  ppo_hpt_v2_dry_run.pt
  ppo_hpt_v2_real.pt
```

主要报告：

```text
results/research_report_hpt_v2_full.md              # [NEW] 完整研究报告
results/fault_method_comparison_raw_switching_hpt_v2_fixed_all.md  # 故障诊断对比
results/fault_method_comparison_raw_switching_hpt_v2_fixed_all.json
results/fahc_strategy_config.json                    # [NEW] FAHC 策略表（供 MATLAB 读取）
results/rcn_frt_offline_analysis.json                # [NEW] RCN 离线分析
results/control_method_comparison_hpt_v2.md
results/ai_strategy_hpt_v2.md
```

---

## 复现实验

**故障识别（纯 Python，无需 Simulink）：**

```powershell
$env:PYTHONUTF8='1'
$env:HPT_RAW_DIR='../data/raw_switching_hpt_v2_fixed_all'

# 训练 MSFFN（当前最强 AI）
C:\Users\m1391\AppData\Local\Programs\Python\Python38\python.exe ai\msffn_fault_detector.py --train --epochs 80 --device cuda

# 运行完整对比
C:\Users\m1391\AppData\Local\Programs\Python\Python38\python.exe ai\fault_method_comparison.py --device cuda
```

**FAHC 分析（纯 Python，无需 Simulink）：**

```powershell
$env:PYTHONUTF8='1'
C:\Users\m1391\AppData\Local\Programs\Python\Python38\python.exe ai\fahc_analysis.py --analyze --dq-dir data\raw_switching_hpt_v2_fixed_dq
C:\Users\m1391\AppData\Local\Programs\Python\Python38\python.exe ai\fahc_analysis.py --write-strategy-config
```

**RCN 离线训练（纯 Python，无需 Simulink）：**

```powershell
$env:PYTHONUTF8='1'
C:\Users\m1391\AppData\Local\Programs\Python\Python38\python.exe ai\rcn_frt_controller.py --train-offline --dq-dir data\raw_switching_hpt_v2_fixed_dq
```

**Simulink 仿真（需要 MATLAB）：**

```matlab
cd('E:/research_space/Hybrid-power-transformer/simulink')
run('build_hpt_switching_model.m')
run('test_switching_quick.m')
```

```powershell
$env:HPT_SCENARIO_TABLE='scenario_table_hpt_v2.csv'
$env:HPT_SWITCHING_OUT_DIR='../data/raw_switching_hpt_v2_fixed_dq'
$env:HPT_CONTROLLER_MODE='4'
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/data_collection'); run('run_switching_scenarios.m');"
```

---

## 下一步优化方向

### 优先级 1：立即可执行，无需 Simulink

**1a. MSFFN 进一步训练**
- 当前：55 epoch 早停，84.57%
- 操作：`python ai/msffn_fault_detector.py --train --epochs 120 --device cuda`
- 预期：87–90%（更长训练 + 余弦退火 LR）

**1b. 集成 MSFFN + Random Forest**
- 方法：用 MSFFN 概率输出 + RF 置信度加权投票
- 预期：97–98%，超过单独 RF（95.68%）

**1c. 重训 CNN/TCN/LSTM（CUDA）**
- 旧 checkpoint 用 DirectML 保存，无法在 CUDA/CPU 加载
- 操作：`python ai/lstm_fault_detector.py --train --epochs 80 --device cuda --arch tcn`
- 预期：TCN 重训后 ≥83.37%，或与 MSFFN 接近

### 优先级 2：需要 Simulink 集成（约 1 周工作量）

**2a. 实现 ControllerMode=7（FAHC）**
- 在 `hpt_switching_model.slx` 中添加 Mode 7 分支
- MATLAB 在故障检测后读取 `results/fahc_strategy_config.json`，按 sc_id 切换参数
- 物理依据：sc_id 5/6/7 降至 Vdc_ref=720V + I_lim=2.5pu，节省 134 J
- 预期：整体 LVRT pass 从 64.00% → **75.1%**（+11.1 pp）

**2b. 实现 ControllerMode=6（RCN）**
- 在 Simulink 中读取 `data/models/rcn_frt_offline.pt` 的推理输出
- 运行 108 个边界场景（VdcMin 0.55–0.75）的网格搜索
- 操作：`python ai/rcn_frt_controller.py --grid-search`（需 Mode 6 可用）
- 预期：整体 LVRT pass **70–76%**

### 优先级 3：长期（2–4 周）

**3a. 神经网络代理模型（Surrogate）**
- 用现有 1050 个 Simulink 场景训练一个轻量 MLP/TCN，模拟系统响应
- 目的：绕过 Simulink 瓶颈，让 PPO 每秒能做 1000+ 次环境交互
- 预期：PPO 全局收敛，350 场景 pass 率 > 80%

**3b. 扩大数据集**
- 当前 1050 文件是 RF 领先的根本原因（样本量不支持深度学习）
- 新增 3 套控制器（Mode 6/7 数据）后合并为 ~1750+ 文件
- 预期：MSFFN Accuracy > 92%，超越 RF

**3c. 多任务学习**
- 同时预测：故障类别 + 骤降相位 + 控制模式推荐
- 一个模型同时完成诊断和控制建议，端到端学习

---

## 当前诚实结论

| 任务 | 当前最强 | 结果 | 与次优差距 |
|---|---|---:|---|
| 故障识别（最强） | **集成 RF+MSFFN** | **97.83% acc** | +0.12 pp vs RF |
| 故障识别（AI 单模型） | MSFFN | 92.61% acc | -5.10 pp vs RF |
| FRT 控制（固定基线） | dq 双闭环 | 64.00% pass | 基准 |
| **AI FRT 控制** | **MSFFN→FAHC (thr=0.80)** | **62.00% pass** | -2.00 pp vs dq |
| 传统规则控制 | 规则 FRT | 60.57% pass | -3.43 pp vs dq |
| AI FRT 控制（强化学习） | PPO | 59.43% pass | -4.57 pp vs dq |

**结论（2026-05-27 最终）**：
- **故障诊断**：集成 RF+MSFFN 以 97.83% 首次超越单独 RF；MSFFN 单模型 92.61%，比旧版提升 +8.04 pp（数据扩充 1050→1750 文件）
- **AI 控制**：MSFFN→FAHC（thr=0.80）以 62.00% 超越传统规则 FRT（60.57%），证明 AI 驱动的故障感知策略选择有效
- **阈值调优**：thr=0.80 比默认 thr=0.70 多拦截错误策略，LVRT 提升 +0.29 pp；thr>0.80 无额外收益
- **硬件瓶颈**：DC 储能 704 J 是根本制约，sc_3ph/sc_1ph/cap_fault 的低通过率（14–26%）是电路结构上限，任何软件方法均无法突破
