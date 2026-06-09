# Hybrid Power Transformer (HPT) — SAC 自适应 LVRT 控制

400 kVA 混合式电力变压器，基于 SAC 强化学习实现自适应 LVRT 控制，Simulink 开关模型验证。

---

## 结果

开关级 Simulink 验证（350 场景，统一以 SAC直接调制 运行）。归因消融分离"工程基线"与"强化学习"的贡献：

| 控制策略 | Simulink LVRT | vs 固定基线 |
|---------|--------------|-------|
| 传统 dq 双环 PI | 64.00% | — |
| 固定 m_sh=0.90（无 SAC，仅保护逻辑）| 62.86% | 基线 |
| 原始 SAC（零硬编码）| 63.43% | +0.6 pp |
| SAC + 遗留覆盖（旧）| 71.43% | +8.6 pp |
| **SAC + 智能混合（当前）** | **82.00%** | **+19.1 pp** |

**智能混合**：在 SAC 学有所长的类（normal/igbt_oc_sh/cap_fault/sc_1ph/sc_3ph）直接放行 SAC，
仅对训练 ODE 难以表达、SAC 学不会的两类（igbt_oc_se、cascade）加最小针对性补丁。
相比旧的"遗留覆盖"(71.4%)，提升的 +10.6 pp **完全来自放行 SAC 的真实强项**：
sc_3ph 12%→**66%**、cap_fault 20%→**40%**。即增益归属于 SAC 自身策略，而非硬编码。

**完整正式记录**：[results/HPT_SAC_Control_Report.md](results/HPT_SAC_Control_Report.md)
（建模、方法、消融、优缺点、局限与复现）。

---

## 系统规格

| 参数 | 数值 |
|------|------|
| 额定容量 | 400 kVA |
| 电压等级 | 10 kV / 400 V（Δ-Yg，相移 π/6） |
| PE 容量 | 120 kVA（30%） |
| DC 母线 | 800 V，C = 2200 µF，储能 704 J |
| 开关频率 | 5 kHz，采样 20 kHz |
| 串联 VSC | H 桥，Tse = 8.66，最大注入 ±46.2 V |
| 并联 VSC | 3 相桥，I_sh_max = 173.2 A |
| **LVRT 标准** | VdcMin ≥ 0.75 pu，VdcMax ≤ 1.25 pu，I2Max ≤ 3.0 pu |

---

## 文件结构

```
Hybrid-power-transformer/
├── simulink/                         # 开关级模型与 MATLAB 辅助
│   ├── hpt_switching_model.slx       # 主模型（开关级，5 kHz SPWM）★权威
│   ├── build_hpt_switching_model.m   # 模型构建脚本（含 SAC直接调制）
│   ├── parameters.m                  # 系统参数
│   ├── dnn_frt_policy.m              # Mode 3 存根（保持编译完整性）
│   ├── validate_switching_model.m    # 冒烟测试
│   ├── run_fault_waveforms.m         # 波形数据生成
│   └── probe_series_dc.m            # 串联→直流 诊断探针（标定用）
│
├── ai/                              # 训练 / 推理 / 评估（Python）
│   │  ── SAC LVRT 控制流水线 ──
│   ├── hpt_direct_env.py            # SAC 训练环境（平均值 ODE）
│   ├── train_sac.py                 # SAC 训练（CUDA GPU，500k 步）
│   ├── sac_hpt_controller.py        # 训练/评估封装
│   ├── generate_sac_actions.py      # 部署动作生成（按类策略）
│   ├── validate_sac_simulink.py     # matlab.engine 验证桥
│   ├── lvrt_metrics.py / data_loader.py  # LVRT 指标与数据加载
│   │  ── 归因消融 ──
│   ├── gen_ablation_actions.py      # 生成四臂动作（fixed/raw/overrides）
│   ├── aggregate_ablation.py        # 消融结果汇总
│   │  ── 课题背景（故障检测/其它控制器，未重新验证）──
│   └── msffn_/lstm_fault_detector.py, traditional_fault_baselines.py,
│       fault_method_comparison.py, control_method_comparison.py,
│       fahc_analysis.py, rcn_frt_controller.py
│
├── data_collection/                 # 场景与 Simulink 验证脚本
│   ├── scenario_table_hpt_v2.csv    # 350 场景（7 类 × 50，固定种子）
│   ├── generate_hpt_v2_scenario_table.py
│   ├── ablate_sac_direct.m              # 归因消融验证（统一 SAC直接调制）
│   ├── validate_sac_direct.m        # 生产验证脚本
│   └── generate_strategy_data.m
│
├── data/                            # 大文件（.gitignore）
│   ├── models/sac_hpt_direct_best.zip   # 最佳 SAC 模型（ODE LVRT 70.6%）
│   └── raw_switching_*/                 # 仿真数据集（课题）
│
├── results/
│   ├── HPT_SAC_Control_Report.md    # ★完整正式记录（建模/方法/消融/优缺点）
│   ├── research_report.md           # 课题级文献综述（SAC 部分已标注被取代）
│   ├── ablation/                    # 四臂消融动作与逐场景结果 + summary
│   ├── sac_actions_for_simulink.csv # 部署动作表（当前）
│   ├── sac_direct_scenario_level.json# 逐场景验证（当前，71.43%）
│   ├── sac_hpt_direct_result.json   # SAC 训练结果（ODE）
│   ├── generate_*_plots/figures.py  # 绘图脚本
│   └── *.json                       # 课题对比结果（MSFFN/FAHC/dq 等背景）
│
└── README.md                        # 本文件
```
★ = 权威产物：开关级 .slx 为验证基准，HPT_SAC_Control_Report.md 为正式记录。

---

## 控制架构

```
传感器信号 V2, I2, Vdc
        │
   MSFFN 故障分类（7 类，5 ms 延迟）
        │ 故障概率向量
   SAC 神经网络（256×256×256）
        │ [m_sh, m_se_d, m_se_q]
   混合策略后处理（深度故障物理下限）
        │
   直接 SPWM（SAC直接调制，绕过 PI）
   ├── 并联 VSC：m_sh 控制 DC 母线
   └── 串联 VSC：m_se_d/q 补偿低压侧电压
```

**SAC vs 传统 dq 核心差异**：
- 无 PI 积分延迟（响应 < 1 ms vs 50-100 ms）
- 感知故障类型（针对性策略 vs 固定参数）
- 串联相位可调（d+q 轴 vs 仅 d 轴）

---

## 快速开始

### 训练 SAC

```bash
cd E:\research_space\Hybrid-power-transformer
.venv\Scripts\python.exe ai/train_sac.py
# GPU 训练约 23 分钟，结果保存至 data/models/sac_hpt_direct_best.zip
```

### 生成动作

```bash
.venv\Scripts\python.exe ai/generate_sac_actions.py
# 输出：results/sac_actions_for_simulink.csv
```

### Simulink 验证 / 归因消融（MATLAB）

```matlab
cd('data_collection')
% 统一 SAC直接调制 口径，逐场景结果写 CSV（可分块，见函数说明）
ablate_sac_direct('../results/ablation/sac_overrides.csv', '../results/ablation/sac_overrides_res.csv')
```
```bash
.venv\Scripts\python.exe ai/aggregate_ablation.py   # 汇总各臂 LVRT
```

---

## 各故障类型结果（开关级，统一 SAC直接调制 口径）

| 故障类型 | 固定 m_sh=0.90 | 原始 SAC | SAC+智能混合 | 动作来源 |
|---------|:-------------:|:--------:|:-----------:|:--------:|
| normal | 100 | 100 | 100 | SAC |
| igbt_oc_sh | 86 | 90 | **90** | SAC |
| igbt_oc_se | 60 | 48 | **100** | 补丁(clip) |
| cap_fault | 20 | **40** | **40** | SAC |
| sc_1ph | 100 | 96 | 96 | SAC |
| sc_3ph | 12 | **66** | **66** | SAC |
| cascade | 62 | 4 | **82** | 补丁(策略) |
| **总体** | **62.86** | **63.43** | **82.00** | 5/7 类由 SAC |

注：智能混合在 5/7 类直接放行 SAC（含其大胜的 sc_3ph 66%、cap_fault 40%），仅 igbt_oc_se、
cascade 用最小补丁（这两类训练 ODE 表达不足、SAC 学不会）。相比旧覆盖(71.4%)的 +10.6pp
全部来自放行 SAC 真实强项，已逼近 oracle 上界 82.6%。

---

## 已知限制

1. **平均 ODE 对深故障偏乐观**：仅作训练替身，一切结论以 Simulink 开关级模型 + 消融为准。
2. **串联控制为开环幅值、无 PLL/功角闭环**：现建为对直流的纯代价，尚不能用作可控电压支撑。
3. **8.2 Ω 直流阻尼电阻不现实**（≈78 kW）：为与已验证模型一致而保留，建议改为 kΩ 级泄放并重整定。
4. **cap_fault / sc_3ph 物理极限**：电容偏小、50 Hz 恢复振荡超出缓冲，任何控制均受限。
5. **构建脚本未完全复现二进制**：已验证 `.slx` 为权威产物并纳入版本控制。

详见 [results/HPT_SAC_Control_Report.md](results/HPT_SAC_Control_Report.md) §6（优缺点）、§7（后续工作）。

---

## 依赖

- MATLAB R2025a + Simulink + Power Systems Toolbox
- Python 3.8 + PyTorch 2.4.1 (CUDA 12.1) + stable-baselines3 + gymnasium
- 环境：`.venv/` (项目内虚拟环境)
