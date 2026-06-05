# Hybrid Power Transformer (HPT) — SAC 自适应 LVRT 控制

400 kVA 混合式电力变压器，基于 SAC 强化学习实现自适应 LVRT 控制，Simulink 开关模型验证。

---

## 最新结果

| 控制策略 | Simulink LVRT | vs dq |
|---------|--------------|-------|
| 传统 dq 双环 PI (Mode 4) | 64.00% | 基准 |
| **SAC Mode 9 混合策略** | **74.00%** | **+10 pp** |
| 固定 Mode 9 (m_sh=0.90) | 96.57%* | — |

\* 96.57% 为早期轻度场景测试结果。当前 350 场景含严苛 sc_3ph 参数（两种模式均失败）。

详细报告：[results/HPT_SAC_Control_Report.md](results/HPT_SAC_Control_Report.md)

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

### Simulink 验证（MATLAB）

```matlab
cd('data_collection')
validate_sac_mode9('../results/sac_actions_for_simulink.csv')
% 约 18 分钟，结果：results/sac_mode9_scenario_level.json
```

---

## 各故障类型结果

| 故障类型 | dq PI | SAC 混合 | 改进 | SAC 关键策略 |
|---------|-------|---------|------|------------|
| normal | ~100% | **100%** | ≈ | m_sh=0.71，DC 平衡维持 |
| igbt_oc_sh | ~60% | **92%** | +32 pp | 立即 m_sh=0.75，无积分延迟 |
| igbt_oc_se | ~100% | **100%** | ≈ | 识别为无 DC 风险 |
| cap_fault | ~50% | **48%** | ≈ | 硬件极限（C 太小） |
| sc_1ph | ~60% | **100%** | **+40 pp** | m_se_d/q 同时注入（≈负序控制）|
| sc_3ph | ~12% | 12% | — | DC 电容 50 Hz 振荡物理极限 |
| cascade | ~10% | **66%** | **+56 pp** | 立即高调制 + 主动串联支撑 |

---

## 已知限制

1. **sc_3ph 场景**：50 Hz 故障恢复振荡超出 C=2200µF 缓冲能力，任何控制均无法通过 LVRT。需增大电容（>10,000 µF）或加储能。
2. **ODE-Simulink 差距**：训练 ODE 为均值模型，深度故障（V2≈0）时与真实开关模型行为不同。
3. **批量推理**：当前为离线动作生成（场景级），在线实时推理需 FPGA 或 dSPACE 部署。

---

## 依赖

- MATLAB R2025a + Simulink + Power Systems Toolbox
- Python 3.8 + PyTorch 2.4.1 (CUDA 12.1) + stable-baselines3 + gymnasium
- 环境：`.venv/` (项目内虚拟环境)
