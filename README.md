# 混合配电变压器（HPT）故障穿越 — 在线门控多专家 SAC

> 🔴 **frt-v1 失效声明（2026-06-22 审计）**：本文件全部通过率与排名（Mode 5 = 82.2%、Mode 6 = 96.25%、
> Mode 2 = 79.7%、Mode 1 = 64.1% 等）均为 **legacy frt-v1**，受判据缺陷 C1–C4/H3–H4 影响
> （见 [docs/AUDIT_2026-06-22.md](docs/AUDIT_2026-06-22.md)），**不可与修正后 frt-v2 结果比较；修正后成绩 PENDING**
> （重验命令见 [docs/CHANGE_REPORT_2026-06-22.md](docs/CHANGE_REPORT_2026-06-22.md)）。已**停用**表述：
> 「国标合规率」「专家化净增益 +37.8pp [legacy frt-v1 INVALIDATED, PENDING frt-v2]」「系统层不需要协调学习」。旧结果存于 `lab/results/legacy_pre_audit/`。

> 控制器命名/编号/角色/结果以 **[CONTROL_MODES.md](docs/CONTROL_MODES.md)（单一事实源）** 为准。**主方法 = Mode 5（在线门控多专家 SAC）**；Mode 6（MPC 辅助残差 SAC）为扩展，非主方法、非"纯 SAC"。

400 kVA 混合配电变压器（HPT）。按**中国国标 GB/T（风/光伏 LVRT/HVRT）** 重定义故障穿越（FRT），在**从零脚本重建、显式包含变流器与变压器的开关级 HPT 研究模型(component-complete switching-level;理想 IGBT/线性变压器/无硬件对标)**上、**同一决策接口/同一标定口径**下对比 canonical 控制律谱系：最强固定律（Mode 1）、一步显式 MPC（Mode 2）、单一 SAC（Mode 3）、Oracle 门控消融（Mode 4）、**在线门控多专家 SAC（Mode 5，本文主方法）**、MPC 辅助残差 SAC（Mode 6，扩展）。主方法核心:**在线测正/负序判运行域 → 调用工况专精 SAC 专家 → 统一 dq 底层执行**（不依赖真实故障标签）。

## 当前结果状态

> **frt-v2 full-320 开关级验证已完成（2026-06-23）—— 首份认证 frt-v2 结果（非 proxy，limit + survive 真实评价）。**

**收口状态（2026-06-23）**
- ✅ **frt-v2 full-320 switching 已完成**（SAC mi=14 + dq mi=7，标定故障）。
- ✅ **P3 多 seed 重训练已完成**（5 seed × 4 专家 + ablation + residual，冻结 held-out split）。
- ✅ **pytest 全绿：`pytest tests -p no:cacheprovider -q` = 134 passed**（数值/物理核心为真实突变敏感测试；另含 ~32 项 provenance/anti-over-claim 治理断言；Python↔MATLAB 数值一致性由 MATLAB 侧 `frt_v2_golden_test.m` / `frt_v2_consistency_test.m` 守护，**不在 pytest 内**）。
- 📌 **当前有效结果以 [docs/FRT_V2_RESULTS_2026-06-23.md](docs/FRT_V2_RESULTS_2026-06-23.md) 与 `lab/results/p3_full320_switching_summary.json` 为准。**
- ⛔ 旧 frt-v1 结果仍 **INVALIDATED**，不得引用为当前结论。

部署残差 SAC（mi=14）与公平 dq 固定律基线（mi=7，同峰值电流基准）的**忠实开关级全 320** 结果。每个场景的故障经**标定**，使开环正序电压 V+ 复现 ODE 的 `Vg_p = fault_sequence(故障类型, target_V_pu)`：

| 控制器 | True | False | NE | strict_pass | no-fail / effective | fail |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **残差 SAC mi=14（部署冠军）** | 170/320 | 34/320 | 116/320 | **53.1%** | **89.4%** | **10.6%** |
| dq 固定律 mi=7（公平基线） | 127/320 | 102/320 | 91/320 | 39.7% | 68.1% | 31.9% |

**三个口径（务必区分；均不得称为"国标认证通过率"）**：
- **strict_pass**（*frt-v2 switching strict pass rate*）：五项 frt-v2 判据**全部可评价且全部 PASS**。
- **NOT_EVALUATED（NE）**：无任一 FAIL，但 ≥1 项判据不适用/无评价窗口。本批 **116/320 NE 并非"无故障"**，而是 **reactive 判据在响应延迟后没有持续无功需求（"no sustained reactive demand after response delay"）**——多为浅跌或单相 swell，正序压降/抬升不足以触发持续无功指令。
- **no-fail / effective_pass**：无任一 FAIL（含 PASS 与 NE）。**不得称为严格国标通过率**，仅表示"未判失败"。

**分域（诚实）**：SAC 碾压 LVRT（可判定通过 92.0% vs dq 53.8%；1ph_g 零失败、sym3ph 60/0/0），但 dq 在 HVRT 反超（66.7% vs SAC 33.3%）。**SAC 的 34 个 FAIL 主要是弱网深 swell 的直流欠冲（survive=FAIL）与边界无功**——这是开关层暴露、ODE proxy（HVRT 100%）看不见的弱点，也是后续 error analysis 的重点（本轮不再跑大实验）。完整数据：`lab/results/p3_full320_switching_summary.json` + 逐场景 `p3_full320_sw_mi{14,7}.mat`（带 provenance）。

> **frt-v2 当前有效入口**（评价/复现）：`lab/simulink/frt_v2_full320_switching.m`（忠实全 320）、`lab/simulink/frt_v2_spotcheck.m`（12 例开关门禁）、`lab/simulink/frt_v2_evaluate.m`（权威五判据，单一事实源）。
> **legacy guard 入口**（**不**作为 frt-v2 评价入口，仅历史/fail-fast 守卫）：`lab/simulink/validate_mode_full.m`、`lab/simulink/run_spotcheck.m`。
>
> 📦 **最小可信研究包 + archive 清单**（2026-06-25 收口）：见 [docs/FILE_GUIDE.md](docs/FILE_GUIDE.md#最小可信研究包2026-06-25-收口) 与 [docs/CLEANUP_INVENTORY_2026-06-25.md](docs/CLEANUP_INVENTORY_2026-06-25.md)。旧日志/早期中断 run 已移至 `lab/results/archive_2026-06-25/`，0-引用诊断脚本移至 `lab/simulink/archive_2026-06-25/`（**均为移动、未删除**，不参与当前结论）。

历史 frt-v1 成绩（Mode 5 = 82.2%、Mode 6 = 96.25%、Mode 1 = 64.1%、Mode 2 = 79.7% 等）仍被
2026-06-22 审计**失效（INVALIDATED）**并隔离到 `lab/results/legacy_pre_audit/`；它们仅作历史记录，
**不得**与上方 frt-v2 结果比较或用于任何合规结论。方法学描述（控制律谱系、在线门控多专家结构）
仍然成立。具体见下方「Historical frt-v1 results — INVALIDATED」表与 [CONTROL_MODES.md](docs/CONTROL_MODES.md)（单一事实源）。

> 工程总说明（架构/文件地图/复现入口,**权威索引**）：**[PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)**；逐文件状态：**[FILE_GUIDE.md](docs/FILE_GUIDE.md)**
> **当前唯一报告**（二期网络鲁棒性压测 + L1 开关级抽查）：**[src/hpt_frt/network/report.md](src/hpt_frt/network/report.md)**；一期 FRT 规范见 [docs/FRT_SPEC.md](docs/FRT_SPEC.md)。
> ⚠️ 2026-06-21 仓库精简：旧学术报告/讲义/审计 md、`phase2/`(二期 v1)、`emt/` 已删除（git 可恢复）。下方"二期"段落为历史叙述，其引用的报告/代码已移除，最新二期结论以上述报告为准。

---

## 二期（2026-06-12 A 阶段闭环）：配电网作为一期 SAC 的系统级试验台

**首要目的**：用真实配电网（IEEE-33 + 多台 HPT，OpenDSS 三层架构，全部经审计）**压测一期训练的装置级 SAC**——它在训练分布外的网络工况下扛不扛得住。

**二期观察（相量层鲁棒性，非通过率）**：
- 轻量层（OpenDSS 准静态）：真 SAC 在 OOD 凹陷（0.05–0.90）上策略理智、不对称钳位正确、十机不动点稳定零反号（相量层稳定性观察，非 FRT 通过率）；
- 保真层（开关级 Simulink）：〔该层的"全过/守住限流"判定基于 legacy frt-v1 criteria，已 **INVALIDATED**，PENDING frt-v2；此处不作通过率结论〕。

**副线发现**：定量证明系统层**不是协同学习问题**（五条交流侧路径排除 ≤+0.7pp），从而确立网络的"试验台"定位；唯一非平凡杠杆是**直流母线互联**（硬件），负荷穿越 57.2%→65.8%，且分配器经枚举**解析即最优**。**系统层 = SAC 试验台 + 一层薄解析硬件杠杆,不是、也不需要是学习型协调器。**

**B 阶段——双机直流互联开关级三级复核**（§5.1–5.3）：Stage 1 电路级（单机塌 0.246 / 互联存活 0.914）→ Stage 2 真 IGBT 取能 VSC（单机塌 0.00 / 互联存活 0.916）→ Stage 3 完整双 HPT + 双 SAC 闭环。Stage 3 揭示 §5 价值链机理:**原始 SAC 自限预算 → 池"无活可干"(故硬件池单独只 +4.0pp);一层薄分配器抬高上限后,邻机直流裕度才被支取(Vdc_A 0.827→0.987)。**

> （历史）上述二期 v1 报告 `results/PHASE2_Report.md`、计划书 `week4/PHASE2_PLAN.md`、代码 `phase2/` 已于 2026-06-21 精简删除；
> 最新二期（Mode 5 单机 SAC 入网鲁棒性 + L1 开关级抽查）见 **[src/hpt_frt/network/report.md](src/hpt_frt/network/report.md)**。双机直流互联开关级在 `lab/simulink/hpt_dual_*.slx`。


---

## 核心成果（统一口径全 320，5 控制器同台）

> ⚠️ **下表为 legacy frt-v1，已失效（2026-06-22 审计 C1–C4）**，不可与 frt-v2 比较；权威机器可读状态见
> [docs/CONTROL_MODES.md](docs/CONTROL_MODES.md) 与 `controller_registry.py`（`validity='pending-frt-v2'`, `score=None`）。

#### Historical frt-v1 results — INVALIDATED (PENDING frt-v2 re-validation)

> Every number in the table below is **legacy frt-v1 and INVALIDATED** by the 2026-06-22 audit
> (criteria defects C1–C4/H3–H4). Retained only for the record; no comparison or superiority
> conclusion may be drawn until the frt-v2 MATLAB re-validation (P1/P3) is run.

| 控制器 | sym3ph | 1ph_g | 2ph | 2ph_g | LVRT 240 | HVRT 80 | **全 320** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| dq-legacy（已弃用基线） | 0% | 26.7% | 11.7% | 0% | 9.6% | 81.2% | 27.5% |
| Mode 1 最强固定律 | 50% | 95% | 0% | 96.7% | 60.4% | 75.0% | 64.1% |
| Mode 2 一步显式 MPC | 78.3% | 100% | 20% | 100% | 74.6% | 95.0% | 79.7% |
| **Mode 5 在线门控多专家 SAC ★主方法（硬门控版）** | 40% | 100% | 98.3% | 100% | 84.6% | 75.0% | **82.2%** |
| ~~混合 SAC/MPC~~（已弃用,internal m13） | 40% | 100% | 98.3% | 100% | 84.6% | 100% | 88.4% |
| Mode 6 MPC 辅助残差 SAC（扩展,非纯 SAC） | 81.7% | 100% | 100% | 100% | 95.4% | 98.8% | 96.25%(308/320) |



**三个关键发现**：
1. **“深故障 Vdc 必塌”是控制自伤，不是拓扑硬限**——dq-legacy 深跌满额串联升压，把共享直流母线抽到 0.55 而死；克制串联（SAC）或预算内用串联（MPC）都能稳住 Vdc≥0.81；
2. **sim-to-real 差距靠实测标定消除（忠实 ODE）**——乐观 ODE 训出的专家部署即崩；用开关级 mode-10 扫描数据逐点标定 ODE 直流模型（`Vdc_eq=1−0.08·|iq|/V −1.9·max(0,V_se_d)−0.5·|V_se_q|`，误差 ≤0.02）后同一管线发生质变；
3. **学习与优化互补而非对立**——多专家 SAC(Mode 5)赢在不对称域的逐工况自适应,一步显式 MPC(Mode 2)赢在可解析目标的 HVRT;**残差扩展(Mode 6)以 MPC 先验 + 学习残差在每个动作维度兼得两者**(达 96.25%(308/320))。〔历史上亦试过按域二选一的 SAC/MPC hybrid(internal m13,88.4%),现已弃用,见 [CONTROL_MODES.md](docs/CONTROL_MODES.md)〕

### 演进过程（每步均为开关级 Simulink 实测；诚实记录三次修正）

| 阶段 | 全 320 | 说明 |
|------|:---:|------|
| 单一 SAC（乐观 ODE） | ~25% | HVRT 全败，LVRT 被 Vdc 存活卡住 |
| 3 专家 + 人工分流 | 44.1%（已撤回） | 依赖手工换权重，检查点被覆盖不可复现 |
| 4 专家在线门控（乐观 ODE） | 18.8%* | 诚实验证暴露 sim-to-real 差距 |
| 4 专家在线门控（忠实 ODE） | 90.0%（已作废） | 后发现验证标定泄漏（利好 SAC），触发统一口径重测 |
| 统一口径：SAC 82.2% / 混合 m13 88.4% | 88.4% | 标定泄漏修复 + 混合架构 |
| 残差 SAC v1 | 75.6% | 测量尖峰不忠实通道暴露（1ph_g 限流 36.7%） |
| Mode 6 残差 SAC v2（扩展,非主方法） | 96.25%(308/320) | 部署侧不对称域 0.24 纹波钳位（报告 §4.10-(9)/§4.11） |
| dq-legacy（已弃用基线） | 27.5% | 深跌串联注入致直流母线能量过度耗竭 + 限流超标 |

> 上表为**研究演进的诚实记录**(含撤回/作废数字);正式口径与主方法(Mode 5)见顶部与 [CONTROL_MODES.md](docs/CONTROL_MODES.md)。

\* 18.8% 为 32 场景分层子集的指示值。

**诚实结论**（统一口径,canonical 见 [CONTROL_MODES.md](docs/CONTROL_MODES.md)）：
- **主方法结论**:**Mode 5 在线门控多专家 SAC 在纯 SAC 架构下取得 82.2%(硬门控版)**,高于 Mode 1 最强固定律(64.1%)、Mode 2 一步显式 MPC(79.7%)、已弃用 dq-legacy(27.5%);相对本文实现的固定律与一步 MPC,主要增益在强不对称(2ph 域 98.3%),短板在 HVRT(75.0%);
- **扩展性能结论**:**Mode 6 在引入 MPC 先验后达 96.25%(308/320)**(LVRT 95.4%、HVRT 98.8%);其中 MPC 先验单独已 79.7%、残差+部署机制再补 ~16.6pp(**非纯学习贡献**)。Mode 5 的 HVRT 与 sym3ph 中深度短板,正是 Mode 6 残差融合所针对;
- **判据的标定参照依赖、偏置方向不确定**是本项目的方法学教训：connect 隐含"故障深度以谁的支撑为参照"，本文用固定 dq 参照——此前称"对 SAC 保守"系口误，固定 R_fault 下撑压强于 dq 者 connect 反而更易过（偏乐观，报告 §5-7）。

---

## 两层方法学（训练—验证分离）

强化学习需数十万步交互，开关级 EMT 单场景约 20 s，**无法直接在 Simulink 上训练**。故：

| 层 | 模型 | 角色 | 文件 |
|----|------|------|------|
| **训练层** | 平均值 ODE（含正负序、无功优先、限流、GB/T 包络） | 快速试错、策略学习 | `src/hpt_frt/device/frt_env.py` |
| **验证层** | 开关级 Simulink（Simscape Electrical） | 权威评判，逼近真实电磁暂态 | `lab/simulink/hpt_frt_full.slx` |

**忠实 ODE（本项目关键方法学）**：朴素 ODE 系统性偏乐观（无功增益高估 ~4.5×、直流母线可被有功随意充电），训出的策略部署即崩（ODE 82% → Simulink 0%）。修正：用 Simulink mode-10 固定设定值扫描**实测标定** ODE 的直流模型——`Vdc_eq = 1 − 0.08·|iq|/max(0.3,V) − 1.9·max(0,V_se_d) − 0.5·|V_se_q|`（串联升压抽取是主项），标定后 ODE 与 Simulink 的 Vdc 平衡点误差 ≤0.02。**一切结论仍以 Simulink 为准**。

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
- **闭环控制器（HLC mode 4–14）**：actor 权重 `coder.load` 进控制块，构建 21 维观测（正负序 T/4 延迟提取 + EMA 滤波、故障 one-hot、上步动作）→ MLP 前向 → 出动作。**网络按训练步长 2 ms 降频推理、期间保持动作**（直接以 20 µs 步长推理会因 100× 频率失配产生 ~3 kHz 极限环——实测命令反向 2628 次/故障，降频后 34 次）。关键模式(canonical,见 [CONTROL_MODES.md](docs/CONTROL_MODES.md)):**Mode 5 在线门控多专家 SAC = 主方法**(internal m12;`V>1.1` 按 V2n 分 hvrt_asym/sym;`V2n>0.05`→asym;否则 sym);Mode 6 MPC 辅助残差 SAC(扩展,internal m14)= MPC 闭式先验 + 学习残差 + 部署侧不对称域 0.24 纹波钳位;Mode 2 一步显式 MPC(m8);Mode 1 最强固定律(m7);dq-legacy(m4,已弃用)。

---

## 文件结构（当前；完整带注释地图见 [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) §5）

> **完整带注释文件地图见 [docs/FILE_GUIDE.md](docs/FILE_GUIDE.md)。** 概览（2026-06-21 工程化重构后）：
> - `src/hpt_frt/device/` — 一期装置级 Python（`frt_env.py`/`residual_env.py`/`train_*`/`export_*`）
> - `src/hpt_frt/network/` — 二期网络压测 Python + **`report.md`（当前唯一报告）**
> - `lab/simulink/` — MATLAB 开关级权威平台（`hpt_frt_full.slx`；**frt-v2 有效入口** `frt_v2_full320_switching.m`/`frt_v2_spotcheck.m`/`frt_v2_evaluate.m`；**legacy guard** `validate_mode_full.m`/`run_spotcheck.m`/`hpt_dual_*`）
> - `lab/`（`frt_scenarios.csv` + `results/frt320_m{4,7,8,12,14}_*`）· `data/models/`（SAC 权重）· `docs/` · `references/`

> 2026-06-21 精简删除：`emt/`、`phase2/`(二期 v1)、`simulink/legacy/`、`frt320_m11/m13/m15_*`、全部旧报告/讲义/审计 md（git 可恢复）。逐文件状态见 [FILE_GUIDE.md](docs/FILE_GUIDE.md)。

> 旧范式工作（器件故障场景、SAC直接调制、MSFFN 分类器、3 专家旧权重等）**已被本 GB/T 标准 FRT 工作取代**（git 可恢复代码；data/models 旧模型已永久删除）。

---

## 复现流程（端到端）

```powershell
# Python 环境：仓库内 .venv（py3.8）；依赖见 requirements.txt（pip install -r requirements.txt）
# 必须先设置（否则 libiomp 冲突导致 numpy/torch matmul 段错误）：
$env:KMP_DUPLICATE_LIB_OK="TRUE"; $env:MKL_THREADING_LAYER="SEQUENTIAL"
$PY=".venv\Scripts\python.exe"

& $PY src/hpt_frt/device/gen_frt_scenarios.py        # 1) 生成 320 场景（如需）
& $PY src/hpt_frt/device/train_residual.py           # 2) 训练残差 SAC（Mode 6 扩展, internal m14, 单模型）
& $PY src/hpt_frt/device/export_residual.py          # 3) 导出权重 → sac_residual_weights.mat
Copy-Item lab/sac_*_weights.mat lab/simulink/
# （4 专家基线 m12：train_experts.py + export_experts.py）
```

```matlab
% 4) MATLAB（R2025a + Simscape Electrical）— frt-v2 开关级评价【当前有效入口】
cd lab/simulink
frt_v2_full320_switching(14, 1, 320)   % m14 残差 SAC 忠实全 320（每场景故障经标定→开环 V+ = ODE Vg_p；可分块传 i0,i1；resumable）
frt_v2_full320_switching(7,  1, 320)   % dq 固定律基线对照（同峰值电流基准，公平）
frt_v2_spotcheck()                     % 12 例开关级门禁（快速健全性检查）
% 五判据权威评价器 = frt_v2_evaluate.m（单一事实源；frt_v2_golden_test.m 守 Python↔MATLAB 一致）
% legacy guard（historical / fail-fast，【非】 frt-v2 评价入口，勿用于当前结论）：validate_mode_full.m / run_spotcheck.m
% B 阶段双机直流互联：run_dual_dcpool / run_dual_dcpool_sw / run_dual_hpt_alloc
```

---

## 诚实局限（详见报告）

1. **不对称故障的残压深度在 Δ-Yg 拓扑下不可达**：MV 单相故障最深只能把 LV 正序压到 ~0.78，故 1ph_g 三档深度实际是同一工况——名义 320 含等效重复易例，**有效多样性显著低于标称**（§5-3）；
2. **模型非真机**：400 kVA 单口（课题书为多端口含直流口）、线性变压器（无饱和/铁损）、故障残压标定、**未硬件对标**；
3. **忠实 ODE 为静态平衡点拟合**——关键系数经 2026-06-17 重测复核**为忠实**（串联抽取 SCR=3 误差 ≤0.022、`K_q∝1/scr` 在 SCR=10 成立）；负荷字段装饰性（两模型均跑额定负荷），换拓扑/参数需重标定（§5-5）；
4. **串联级拓扑限制不对称结论**：三相桥+浮地星点只能注正序，"不对称域 RL 不可替代"严格只对该拓扑成立（课题书要求的独立 H 桥可注负序，结论或变，§5-9）；
5. **判据的标定参照依赖、偏置方向不确定**：connect 隐含"故障深度以谁的支撑为参照"，本项目用固定 dq 参照——此前称"对 SAC 保守"系口误，固定 R_fault 下撑压强于 dq 者反而更易过（偏乐观，§5–7）；`reactive` 判据含 2ω 偏置使 2ph 列对固定律偏低（§5-11）；
6. **"3.5× dq"须谨慎解读〔legacy frt-v1，已 INVALIDATED，勿作当前结论〕**：旧 96.25%(308/320) 中 MPC 解析先验单独已 79.7%，学习+部署钳位补 ~16pp；约六成原始差距来自 dq 基线串联自伤（§5-12）。当前有效口径见 §当前结果状态（frt-v2：SAC strict 53.1% / no-fail 89.4% vs dq 39.7%/68.1%）；
7. **训练时间压缩对直流动态非尺度不变**：`TSCALE=0.2` 压缩穿越窗 5× 但直流时常数未压缩，训练求解的 Vdc 暂态偏易（开关级实时验证兜底，§5-10）；
8. **二期为准静态相量**（无机电暂态）；B 阶段开关级为降阶 LV-源背骨、对称工况，逐相不对称 + 100 Hz 纹波的多机耦合未展开。

> ⚠️ **HVRT 是部署残差 SAC（mi=14）当前的已知弱项，尚未解决**：frt-v2 全 320 开关级实测 HVRT 可判定通过仅 **33.3%（< dq 66.7%）**，弱网（scr3）深 swell 的直流欠冲（survive=FAIL）+ 边界无功为主因，是后续改进靶点（见 §当前结果状态 与 [docs/FRT_V2_RESULTS_2026-06-23.md](docs/FRT_V2_RESULTS_2026-06-23.md)、[docs/FRT_V2_ERROR_ANALYSIS_2026-06-24.md](docs/FRT_V2_ERROR_ANALYSIS_2026-06-24.md)）。
> 〔早期"m14 残差已解决 HVRT（98.8%）/ SAC 75% < dq 81.2%"系 **legacy frt-v1** 数字，受判据缺陷影响**已 INVALIDATED，勿引用**；且 Mode 6 从未在 frt-v2 下重跑，frt-v2 认证的部署 mi=14 在 HVRT 反而更弱。〕

---

## 依赖

- **MATLAB R2025a** + Simulink + **Simscape Electrical**（专用电力系统）；MCP 会话需 `addpath(...agentic-toolkits/simulink); satk_initialize` 共享；
- **Python**：仓库内 `.venv`(py3.8) — stable-baselines3 2.4.1 + PyTorch（CPU 即可）+ gymnasium + numpy + scipy；精确版本以 `requirements.txt` 为准。
