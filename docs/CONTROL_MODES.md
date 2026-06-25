# 控制模式注册表(CONTROL MODES — Single Source of Truth)

> 🔴 **frt-v1 失效声明（2026-06-22 审计）**：下文所有 score（82.2/96.25/79.7/64.1/44.4/81.2/27.5）均为
> **legacy frt-v1**，受判据缺陷影响（见 [AUDIT_2026-06-22.md](AUDIT_2026-06-22.md)），**不可与 frt-v2 比较；
> 修正后成绩 PENDING**。各 mode 的 `score=` 在 frt-v2 重验前应读作「legacy，待重测」。已停用「专家化净增益 +37.8pp [legacy frt-v1 INVALIDATED, PENDING frt-v2]」「系统层不需要协调学习」「国标合规率」。

> **本文件是控制器模式的唯一权威定义**。任何源码、结果表、论文、报告、讲义引用控制器时,**名称/编号/角色/结果有效性以本表为准**。
> 最后更新:2026-06-18(控制模式收敛与文档一致性重构)。

---

## 0. 研究主线(统一表述)

> 针对共享直流母线 HPT 在对称/不对称 LVRT 与 HVRT 下动力学与控制目标显著差异的问题,提出**基于在线序分量工况识别的多专家 Soft Actor-Critic 控制**:控制器按在线实测正/负序电压识别运行域,调用对应专用 SAC 策略,经统一 dq 底层执行。
> 结构:**工况识别 → SAC 专家选择 → 共享 dq 底层执行**;
> $k_t=g(V_t^+,V_t^-),\quad a_t=\pi_{k_t}(o_t)$,其中 $g$ 为在线序分量门控,$\pi_k$ 为第 $k$ 个 SAC 专家,$o_t$ 仅含部署可得观测,所有专家共享动作定义/归一化/控制周期/底层执行。

**本文主方法 = Mode 5(在线门控多专家 SAC)。** 残差 SAC(Mode 6)为**扩展性能方法**(含 MPC 先验),不是主方法,亦不得称为"纯 SAC"。"多专家 SAC"**不译作"混合 SAC"**(hybrid 一词仅指不同控制范式组合,如 MPC+SAC)。

---

## 1. 正式模式表(0–6,canonical)

| Mode | Canonical name | 中文名 | Family | 学习? | 模型先验? | Oracle? | 可部署? | 控制周期 | 动作维 | 状态 | 论文角色 |
|:--:|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|---|---|
| **0** | Calibration / no-HLC | 标定/无高层控制 | infra | 否 | 否 | 否 | n/a | n/a | n/a | active(基础设施) | 标定与模型自检 |
| **1** | Tuned fixed-law controller | 最强固定律控制 | fixed law | 否 | 否 | 否 | 是 | 20 µs | 3 | active | 传统控制基线 |
| **2** | One-step explicit MPC | 一步显式 MPC | model-based | 否 | 是 | 否 | 是 | 2 ms | 3 | active | 模型驱动基线 |
| **3** | Unified SAC | 单一 SAC | learning | 是 | 否 | 否 | 是 | 2 ms | 3(eff) | active | 单策略消融 |
| **4** | Oracle-gated expert SAC | Oracle 门控多专家 SAC | learning | 是 | 否 | **是** | **否** | 2 ms | 3(eff) | active | 理想门控消融(性能上限) |
| **5** | **Online-gated expert SAC** | **在线门控多专家 SAC** | learning | 是 | 否 | 否 | 是 | 2 ms | 3(eff) | **active ★主方法** | **本文主方法** |
| **6** | MPC-assisted residual SAC | MPC 辅助残差 SAC | learning+model | 是 | 是 | 否 | 是 | 双速率 20µs/2ms | 3 | active | 扩展性能方法 |

> **动作接口统一**:高层输出 `a=[i_q^ref, m_se_d, m_se_q]`(3 维有效)。`i_d` 部署时由 Vdc 外环自调,**SAC 不输出实际被忽略的 i_d**。残差(Mode 6)训练环境已结构性约束为 3 维(`residual_env.py` 第 0 维上界 0.01 且 step 置零)→ 训练-部署一致,无失配。Mode 3/4/5 当前由 4 维训练环境(`frt_env.py`)训练,**第 0 维为退化维**(仅进限流惩罚、不进动力学,部署丢弃)——见 §5 待验证项(3 维重训)。

---

## 2. 旧内部编号 → 新 canonical 映射(deprecation map)

> Simulink HLC 的内部整数(`mi==…`)与结果文件名 `frt320_m{N}_*` **保持不变**(改之即需全量重建+重验证),仅通过本映射与 registry 别名层对外暴露 canonical 0–6。**旧编号不得再出现在正式论文/讲义**;代码中保留并标 deprecated。

| 旧内部 HLC `mi` | 旧惯用名 | → canonical | 结果文件 | 状态 |
|:--:|---|:--:|---|---|
| (calib:mi=4 零设定 + mi=10 定值探针) | EMF/R_fault 标定、定值扫描 | **Mode 0** | (sim_compare/diag) | active(基础设施)⚠️见§6 |
| 7 | 最强固定律(宋幸式+0.27限幅) | **Mode 1** | `frt320_m7_*` | legacy INVALIDATED (PENDING frt-v2): **205/320=64.06%** |
| 8 | 决策层一步 MPC | **Mode 2** | `frt320_m8_*` | legacy INVALIDATED (PENDING frt-v2): **255/320=79.69%** |
| 11 | 单一 SAC | **Mode 3** | `frt320_m11_*` | legacy INVALIDATED (PENDING frt-v2): **≈44.4%**(2026-06-18 开关级全320) |
| 15 | 4 专家 + 真标签 Oracle 门控 | **Mode 4** | `frt320_m15_*` | legacy INVALIDATED (PENDING frt-v2): **≈81.2%**(2026-06-18,仅消融、不可部署) |
| 12 | 4 专家在线门控 SAC | **Mode 5 ★** | `frt320_m12_*` | active,硬门控版 INVALIDATED-PENDING-frt-v2 **263/320=82.19%**;滞环增强版**待验证** |
| 14 | 残差 SAC(m14-v2) | **Mode 6** | `frt320_m14_*` | legacy INVALIDATED (PENDING frt-v2): **308/320 = 96.25%** |
| 4 | dq-legacy(自设串联律) | — (无 canonical) | `frt320_m4_*` | **deprecated → 失效演示**(historical 27.5%) |
| 5 | dq-宋幸式(串联置零) | — | `dq_variants_*` | deprecated → historical |
| 6 | dq-贾科式(Vdc 降额) | — | `dq_variants_*` | deprecated → historical |
| 10 | 定值设定点 | — | sim_compare | deprecated → calibration config |
| 13 | 分域 SAC/MPC hybrid | — | `frt320_m13_*` | **deprecated**(historical 88.4%) |

**不再占用 canonical 编号、转为 test/calibration/historical/diagnostic**:dq-legacy、宋幸式、贾科式、定值扫描、早期 3 专家(44.1% 已撤回)、mode-13 分域 hybrid、residual v1(75.6%)、泄漏标定版(90.0%/32.8% 已作废)、旧奖励版(v2/v3)、旧推理频率版、手工测试动作模式。

---

## 3. 结果有效性(不得把旧成绩赋给新模式)

#### Historical frt-v1 results — INVALIDATED (PENDING frt-v2)

> 下表所有数字为 **legacy frt-v1，已失效**（2026-06-22 审计，判据缺陷 C1–C4/H3–H4）；各 `有效性`
> 列读作 *INVALIDATED → PENDING frt-v2*。frt-v2 MATLAB 重验（P1/P3）前不得作有效性或优劣结论。

| Canonical | 数字 | 口径 | 有效性 |
|:--:|:--:|---|---|
| Mode 1 最强固定律 | **205/320 = 64.06%** | 统一口径全 320 | INVALIDATED → PENDING frt-v2 |
| Mode 2 一步显式 MPC | **255/320 = 79.69%** | 统一口径全 320 | INVALIDATED → PENDING frt-v2 |
| Mode 3 单一 SAC | **142/320 = 44.38%** | 统一口径全 320 开关级(2026-06-18) | INVALIDATED → PENDING frt-v2(sym 12/60·1ph 58/60·2ph 7/60·2phg 25/60·hvrt 40/80;ODE 侧 best 89% 为 80 抽样、勿混) |
| Mode 4 Oracle 门控 | **260/320 = 81.25%** | 统一口径全 320 开关级(2026-06-18) | INVALIDATED → PENDING frt-v2(仅消融、不可部署、**非上界**;sym 22/60·1ph 60/60·2ph 59/60·2phg 59/60·hvrt 60/80) |
| Mode 5 在线门控多专家 | **263/320 = 82.19%** | 统一口径全 320,**硬门控版** | ✅ 硬门控版 INVALIDATED-PENDING-frt-v2;➕滞环/最小驻留/限速/3维重训后**待验证** |
| **P1 消融** | 多专家−单一 = M5 263 − M3 142 = **+37.8pp [legacy frt-v1 INVALIDATED, PENDING frt-v2]**(含容量/总预算影响,非纯专家化);在线门控 vs oracle = M5 263 vs M4 260(**未见明显损失**,oracle 非上界) | 开关级 | ✅ 短板(sym3ph/hvrt)专家级非门控级(oracle 同卡)→ P2 |
| Mode 6 MPC 辅助残差 | **308/320 = 96.25%** | 统一口径全 320 | INVALIDATED → PENDING frt-v2(**非主方法**;96.25 含 MPC 先验 79.7 + 残差/部署机制 ~16.6,非纯学习) |

**作废/撤回(仅作研究演进,不得当有效结果)**:3 专家 44.1%(人工分流,撤回)、4 专家 90.0%/dq 32.8%(标定泄漏,作废)、residual v1 75.6%、乐观 ODE 部署 ~19%。

---

## 4. 观测与训练公平(口径)

- **部署型 SAC(Mode 3/5)观测只含部署可得量**:`Vdc, V⁺, V⁻, 滤波 i_q, 无功跟踪误差, 电压偏差, 故障/恢复状态, 归一化已持续时间, 上一步动作, 必要变化率, 门控估计类别`。**不得用真实故障 one-hot / 真实目标残压 / 未来故障时长 / 仅仿真器可知标签**作为可部署主方法输入。
  - ⚠️ 现状:`frt_env.py` 观测含"故障 one-hot probs(6)"。Mode 5 部署(HLC)由门控自判类别填充(非真标签),但**训练环境仍按场景类别填**——属特权信息残留,见 §5 待验证(去特权重训)。
- **Mode 4(Oracle)**可用真实类别**仅用于选专家**,不得作为 expert actor 隐含输入。
- **公平训练**(Mode 3/4/5):须报告 每专家步数 / 总交互步数 / 参数量 / 训练时间 / buffer / 网络 / 种子 / lr / batch / γ / τ / ent_coef / 归一化 / 动作缩放 / 训练环境 git commit / faithful-ODE 标定版本;**≥5 随机种子,报均值±std,禁止只取最优 seed**;两类公平比较:等总交互预算 / 等单策略预算。

---

## 5. 待验证清单(未重测,严禁沿用其他模式成绩)

1. ~~**Mode 3 单一 SAC** 开关级全 320~~ → ✅ 已完成(2026-06-18,≈44.4%,`frt320_m11_*`);
2. ~~**Mode 4 Oracle 门控** 全 320~~ → ✅ 已完成(2026-06-18,≈81.2%,`frt320_m15_*`);可选:同会话重跑 m12 消除新旧运行混淆;
3. **Mode 5 滞环增强版**(进入/退出滞环、最小驻留、切换限速)——新增部署保护,**结果待统一验证**;原始硬门控版 = 82.2%;
4. **3 维动作重训** Mode 3/4/5(去退化维),旧 4 维权重保留为 legacy 不得与新结果混用;
5. **去特权信息重训**(去掉真实故障 one-hot);
6. **≥5 随机种子**统计(均值±std);
7. **门控鲁棒性消融**:硬门控 vs 滞环、无延迟 vs 延迟、干净 vs 噪声测量、3 vs 4 专家、独立网络 vs 共享骨干多头、门控边界动作一致性 $\Delta a_{ij}=|\pi_i(o)-\pi_j(o)|$;
8. **Mode 5 二期网络 OOD 压测**(现有二期系统级结果对应 **Mode 6 残差**,非 Mode 5)。

---

## 6. 未解决的矛盾(需决策,本次未擅自更改以免伪造)

1. **标定参照 vs Mode 0 no-control**:用户要求标定用 Mode 0(无控制)以杜绝泄漏;但**当前全部结果的 R_fault 是在 dq-legacy 支撑下标定的(统一口径参照)**。改用真 no-control 参照会改变所有残压深度 → **全部结果须重测**。本次保留现口径并显式记录;采用 no-control 标定 = 一项重大重验证(列入待验证)。connect 判据偏置方向非单向(撑压强于 dq 者反更易过),亦源于此参照选择。
2. **Mode 5 主方法 vs 性能最高(Mode 6)**:Mode 6(308/320=96.25%)性能高于 Mode 5(263/320=82.19%),但**性能最高 ≠ 论文主方法**;主方法定为纯学习的 Mode 5。
3. **Mode 5 训练-部署接口**:Mode 5 现由 4 维 `frt_env.py` 训练(退化维)+ 训练含特权 one-hot;严格部署一致版需 §5 第 4/5 项重训。
4. **二期压测对象**:现有二期开关级/OpenDSS 压测跑的是 Mode 6 残差;Mode 5 的系统级 OOD 验证**待补**。

---

## 7. 命名术语统一

| 术语 | 含义 |
|---|---|
| SAC | 标准 Soft Actor-Critic 算法 |
| unified SAC / 单一 SAC | 单策略覆盖全工况(Mode 3) |
| expert SAC / 专家 SAC | 针对某物理域训练的 SAC |
| multi-expert SAC / 多专家 SAC | 多专家策略 + 门控架构(Mode 4/5) |
| online physics gate / 在线序分量门控 | 用在线实测 V⁺/V⁻ 的门控(Mode 5) |
| oracle gate | 用真实工况标签的门控(Mode 4,仅消融) |
| residual SAC / MPC-assisted residual SAC | MPC 先验 + 学习残差(Mode 6) |
| hybrid controller / 混合控制器 | **仅**指不同控制范式组合(如 MPC+SAC);**不得**用于描述多专家 SAC |
| tuned fixed-law / 最强固定律 | 传统固定律基线(Mode 1) |

**禁用旧表述**:"m14 是最终/主控制器""residual SAC 是本文 SAC""mode 12 只是中间方法""九种决策律是主对比""SAC=残差 SAC""真实故障类型选专家(作为可部署主方法)""champion/winner/final""mode 13 主混合"。
