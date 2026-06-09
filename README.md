# 混合配电变压器（HPT）标准故障穿越 — 强化学习 vs 传统 dq 控制

400 kVA 混合配电变压器（Hybrid Power Transformer）。按**中国国标 GB/T（风/光伏 LVRT/HVRT）** 重新定义故障穿越（FRT），用 **Soft Actor-Critic（SAC）** 强化学习学习并联无功 + 串联电压的协调策略，在**从零脚本重建、全部件齐全的开关级 HPT 模型**上与 **dq 双环 PI 传统控制**同平台对比。SAC 策略权重**导出后内嵌进 Simulink 控制块逐步推理（真闭环，与 dq 对等）**。

> 完整学术报告（背景/算式/方法/结果/机理/局限/参考文献/可复现附录 A-C）：
> **[results/FRT_Academic_Report.md](results/FRT_Academic_Report.md)**

---

## 核心成果（开关级 Simulink，全 320 场景）

| 场景 | 数量 | dq 传统 | 闭环 SAC（单一策略） | 谁优 |
|------|:----:|:------:|:------:|:----:|
| **LVRT**（欠压穿越） | 240 | 9.6% | **25.0%** | **SAC ≈2.6×** |
| **HVRT**（过压穿越） | 80 | **81.2%** | 25.0% | **dq** |
| **全 320 合计** | 320 | 27.5% | 25.0% | 约打平 |

**诚实结论**：
- **SAC 在 LVRT（深跌欠压，最难）上完胜**——优势来自**更好的限流（97.5% vs 42%）与直流母线存活（57.5% vs 50%）**：dq 为撑压猛注无功+串联、抽干共享直流；SAC 学会克制保住 Vdc。
- **dq 在 HVRT（过压）上完胜**——单一 SAC 训练以 LVRT 为主，**没学会吸无功**；标准 droop 天然处理骤升。
- → **SAC 的优势是训练域（LVRT）特定的。** 正在按"**分层 3 专家 + 物理门控**"（对称-LVRT / 不对称-LVRT / HVRT，按 V、V2n 实时路由）训练以在全 320 上全面超越（进行中）。

**已验证的物理硬限**：单交流口拓扑下，**无功注入、Vdc 存活、限流三者抢同一份并联电流**——纯调奖励超不过 25%（v2/v3 重训实验，见报告 §4.5）；突破需改拓扑（多端口/直流端口）。

---

## 两层方法学（训练—验证分离）

强化学习需数十万步交互，开关级 EMT 单场景约 20 s，**无法直接在 Simulink 上训练**。故：

| 层 | 模型 | 角色 | 文件 |
|----|------|------|------|
| **训练层** | 平均值 ODE（含正负序、无功优先、限流、GB/T 包络） | 快速试错、策略学习 | `frt_standard/frt_env.py` |
| **验证层** | 开关级 Simulink（Simscape Electrical） | 权威评判，逼近真实电磁暂态 | `frt_standard/simulink/hpt_frt_full.slx` |

ODE 系统性偏乐观（实测无功增益高估 ~4.5×；ODE 59% → Simulink 25%）；**一切结论以 Simulink 为准**。

---

## 标准 FRT 定义（GB/T 19963 / 19964）

- **故障类型**：对称三相 `sym3ph`；不对称 `1ph_g / 2ph / 2ph_g`（含负序）；过压 `swell_3ph / swell_1ph`；
- **深度**：LVRT 残压 {0.2, 0.5, 0.75}，HVRT 幅值 {1.2, 1.3}；
- **电网强弱**：强网 SCR=10、弱网 SCR=3；
- **5 项判据**：①不脱网（电压-时间包络内）②无功跟踪（`Iq=1.5(0.9−U)` droop，过压时吸）③限流（≤0.35 pu）④电压恢复（±7%）⑤装置存活（Vdc∈[0.75,1.25]）；
- **场景集**：320 = LVRT 240（4型×3深×2网×10）+ HVRT 80（2型×2幅×2网×10）。

---

## 完整开关级 HPT 模型（验证平台，纯脚本可复现）

`build_hpt_frt_full.m` → `hpt_frt_full.slx`（32 块，真实 10 kV MV / 400 V LV 两电压等级）：

```
MV弱网(R/L按SCR) → MV序故障 → 主变 Δ-Yg(400kVA) → LV负载
        └→ Tsh耦合变(120kVA) → 并联取能VSC(2电平IGBT桥) ┐
                                                          ├ 共享DC母线(2200µF)+条件斩波器(Vdc>1.20pu)
        串联调控VSC(2电平桥) → 3×单相Tse → 串入LV线 ─────┘
```

- 真 IGBT 开关（5 kHz SPWM）、真变压器（含漏抗/Δ-Yg 相移）、EMT 求解器（ode23tb，20 µs）；
- **HVRT 用可编程电压源**（幅值表做骤升）+ 外接串联 Z；
- **控制**：并联 = SRF-PLL + dq 电流环（解耦+前馈+抗饱和）+ Vdc 外环；串联 = 锁 LV 角开环 dq 注入；
- **闭环 SAC（Mode 11）**：actor 权重 `coder.load` 进控制块，每步重建 21 维观测（正负序 T/4 延迟提取、故障 one-hot、上步动作）→ MLP 前向 → 实时出动作（前向已对 Python 验证误差 1e-7）。

---

## 文件结构（当前 FRT 工作在 `frt_standard/`）

```
frt_standard/
├── FRT_SPEC.md                  # GB/T 规格：5 判据、包络、场景矩阵
├── gen_frt_scenarios.py         # 生成 320 场景
├── frt_scenarios.csv            # 320 标准场景（含 Rg/Lg/t_fault/dur）
├── frt_env.py                   # 平均值 ODE 训练环境（正负序+无功优先+限流+包络）
├── frt_metrics.py               # 5 项 FRT 判据
├── train_frt_sac.py             # 单一 SAC 训练
├── train_experts.py             # ★ 3 专家训练（sym / asym / hvrt）
├── export_sac_actor.py          # 导出 actor 权重供 Simulink 闭环内嵌
├── gen_sac_frt_actions.py       # （旧）开环设定值生成
└── simulink/
    ├── build_hpt_frt_full.m     # ★ 完整 HPT 模型脚本重建（stage1-4 + gridmode swell）
    ├── hpt_frt_full.slx         # ★ 完整 HPT 开关级模型（权威验证平台）
    ├── validate_frt_full.m      # ★ LVRT 对比 harness（场景映射+残压标定+5判据+故障型过滤）
    ├── validate_hvrt.m          # ★ HVRT 对比 harness（骤升注入+过压判据）
    ├── gen_fault_waveforms.m    # 各故障型波形图
    └── sac_actor_weights.mat    # 当前内嵌权重

data/models/  sac_frt_best.zip（v1，LVRT 最佳）、sac_frt_best_v1/v2/v3.zip（实验存档）、
              sac_{sym,asym,hvrt}_best.zip（3 专家，训练中）
results/      FRT_Academic_Report.md（★完整报告）、FRT_SAC_vs_dq_FullHPT.md、
              frt_full_compare.{mat,txt}（LVRT 240）、hvrt_compare.{mat,txt}（HVRT 80）、
              figs/（柱状图 + 机理波形 + 4 故障型波形）
```

> 旧范式工作（350 个器件故障场景、SAC直接调制 82%、`hpt_switching_model.slx`）已被本 GB/T 标准 FRT 工作取代；旧产物仍在 `simulink/`、`ai/`、`data_collection/`、`results/HPT_SAC_Control_Report.md` 中保留备查。

---

## 复现流程（端到端）

```bash
# Python 环境：E:\anaconda\envs\pandapower_dev（SB3 2.8.0 + torch + gymnasium）
PY="E:\anaconda\envs\pandapower_dev\python.exe"

# 1) 生成场景（如需）
& $PY frt_standard/gen_frt_scenarios.py

# 2) 训练（单一策略 或 3 专家）
& $PY frt_standard/train_frt_sac.py            # 单一 SAC → data/models/sac_frt_best.zip
& $PY frt_standard/train_experts.py            # 3 专家 → sac_{sym,asym,hvrt}_best.zip

# 3) 导出权重供 Simulink 闭环
& $PY frt_standard/export_sac_actor.py         # → frt_standard/sac_actor_weights.mat
```

```matlab
% 4) MATLAB（R2025a + Simscape Electrical，会话需 satk_initialize 共享给 MCP）
cd frt_standard/simulink
copyfile('../sac_actor_weights.mat','sac_actor_weights.mat')   % coder.load 用
validate_frt_full(inf, '../frt_scenarios.csv')                 % LVRT 240：mode4(dq) vs mode11(闭环SAC)
validate_hvrt()                                                % HVRT 80
% 故障型过滤（3 专家路由）：validate_frt_full(inf,'../frt_scenarios.csv',{'sym3ph'}) 等
```

---

## 诚实局限（详见报告 §3.3 / §5）

1. **绝对通过率低**（LVRT 25%、HVRT 25%）：**单交流口拓扑深跌时 Vdc 必塌**——物理硬限，约束两者；
2. **ODE→Simulink 乐观差**（59%→25%）：相对优势（SAC>dq on LVRT）在开关级成立，绝对值回落；
3. **SAC 优势 LVRT 域特定**：HVRT 需补训（3 专家方案进行中）；
4. **模型非真机**：400 kVA 单口（课题书为多端口含直流口）、线性变压器（无饱和/铁损）、理想开关、故障残压标定、**未硬件对标**；
5. **reactive 判据对不对称故障 2ω 敏感**（可改严格正序计算）。

---

## 依赖

- **MATLAB R2025a** + Simulink + **Simscape Electrical**（专用电力系统）；MCP 会话需 `addpath(...agentic-toolkits/simulink); satk_initialize` 共享；
- **Python**：`E:\anaconda\envs\pandapower_dev` — stable-baselines3 2.8.0 + PyTorch（CPU 即可）+ gymnasium + numpy + scipy。
