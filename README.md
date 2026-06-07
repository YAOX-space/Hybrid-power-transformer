# Hybrid Power Transformer (HPT) — SAC 自适应 LVRT 控制

400 kVA 混合式电力变压器，基于 SAC 强化学习实现自适应 LVRT 控制，Simulink 开关模型验证。

---

## 结果

开关级 Simulink 验证（350 场景，统一以 Mode 9 运行）。归因消融分离"工程基线"与"强化学习"的贡献：

| 控制策略 | Simulink LVRT | vs 固定基线 |
|---------|--------------|-------|
| 传统 dq 双环 PI | 64.00% | — |
| 固定 m_sh=0.90（无 SAC，仅保护逻辑）| 62.86% | 基线 |
| 原始 SAC（零硬编码）| 63.43% | +0.6 pp |
| **SAC + 按类策略** | **71.43%** | **+8.6 pp** |

SAC + 按类策略较固定基线 +8.6 pp、较 dq +7.4 pp；纯 SAC 与固定基线持平，并在三相短路
（66% vs 12%）、电容故障（40% vs 20%）上体现真实学习自适应。

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
├── simulink/
│   ├── hpt_switching_model.slx      # 主模型（开关级，5 kHz SPWM）
│   ├── parameters.m                 # 系统参数
│   └── dnn_frt_policy.m             # Mode 3 存根（保持编译完整性）
│
├── ai/
│   ├── hpt_direct_env.py            # SAC 训练环境（Gymnasium，ODE）
│   ├── train_sac.py                 # SAC 训练脚本（CUDA GPU）
│   ├── generate_sac_actions.py      # 生成场景级动作 CSV（含混合策略后处理）
│   ├── sac_hpt_controller.py        # SAC 推理控制器
│   ├── msffn_fault_detector.py      # MSFFN 故障分类器（7 类）
│   └── [其他辅助模块]
│
├── data_collection/
│   ├── scenario_table_hpt_v2.csv    # 350 场景（7 类 × 50，固定随机种子）
│   ├── validate_sac_mode9.m         # 350 场景 Simulink Mode 9 验证脚本
│   └── generate_strategy_data.m     # 批量策略数据生成
│
├── data/
│   └── models/
│       ├── sac_hpt_direct_best.zip  # 最佳 SAC 模型（LVRT=100% ODE）
│       └── msffn_fault_detector_*.pt
│
├── results/
│   ├── HPT_SAC_Control_Report.md    # 完整技术报告（本项目最终结果）
│   ├── sac_mode9_scenario_level.json # 350 场景逐条验证结果
│   ├── sac_actions_for_simulink.csv  # 混合策略动作表（当前最新）
│   └── sac_hpt_direct_result.json   # SAC 训练结果（ODE）
│
└── README.md                        # 本文件
```

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
   直接 SPWM（Mode 9，绕过 PI）
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
% 统一 Mode 9 口径，逐场景结果写 CSV（可分块，见函数说明）
ablate_mode9('../results/ablation/sac_overrides.csv', '../results/ablation/sac_overrides_res.csv')
```
```bash
.venv\Scripts\python.exe ai/aggregate_ablation.py   # 汇总各臂 LVRT
```

---

## 各故障类型结果（开关级，统一 Mode 9 口径）

| 故障类型 | 固定 m_sh=0.90 | 原始 SAC | SAC+按类策略 |
|---------|:-------------:|:--------:|:-----------:|
| normal | 100 | 100 | 100 |
| igbt_oc_sh | 86 | 90 | 90 |
| igbt_oc_se | 60 | 48 | **100** |
| cap_fault | 20 | **40** | 20 |
| sc_1ph | 100 | 96 | 96 |
| sc_3ph | 12 | **66** | 12 |
| cascade | 62 | 4 | **82** |
| **总体** | **62.86** | **63.43** | **71.43** |

注：纯 SAC 在 sc_3ph/cap_fault 上有真实学习增益；遗留按类策略对 sc_3ph 强制 m_sh=0.90，
反而压制了 SAC 自身的 66%（放行可再 +~7.7pp，oracle 上界 ≈82.6%）。

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
