# 误差分析驱动的闭环优化控制 — 完整流程（2026-06-27）

> 把"训练 → 认证 → 误差分析 → 改参数 → 重训"这一圈写成一个**双保真双层优化**的方法学规范。
> 约束：**纯 4 专家 SAC，不叠混合模型**；改进只动这 4 个专家本身（奖励/采样/标定）。
> 相关文献见 [REWARD_SHAPING_LIT_2026-06-27.md](REWARD_SHAPING_LIT_2026-06-27.md)；HVRT 标定见
> [RESIDUAL_EXPERT_PLAN_2026-06-25.md] 与 Stage A `lab/results/dc_sweep_grid_s3ph.mat`。

---

## 0. 定位（贡献怎么写）
文献里：奖励整形理论(Ng 1999 PBRS)、超参优化(AutoRL/PBT)、失败课程(PER/curriculum)、自动奖励设计
(Eureka) 各自成熟，但**"人工误差分析 → 改奖励/标定 → 重认证"这个完整环大多是 ad-hoc 工程实践、未形式化**。
本方法的贡献 = 把它做成**显式、判据对齐、可复现、且区分"改 ODE / 改奖励"**的闭环——用于安全攸关、
国标判据约束的 FRT 控制器。最接近的正式命名是 Eureka 的 "reward reflection"，本方法是其**人工在环 + 双保真**的版本。

---

## 1. 总体架构：双保真双层闭环

```
        ┌────────── Simulink 标定 (dc_sweep, 扩/校 ODE) ──────────┐(扫描数据)
        ▼                                                          │
┌──────────────────┐   ┌────────────────────────┐   ┌──────────────────┐
│ Parameters Opt   │   │ 4 Experts SAC Training  │   │ Simulink 认证     │
│ ┌──────────────┐ │   │  LVRT_sym  LVRT_asym    │   │ (真裁判, 五判据)   │
│ │ODE Adjustment│◀┼───│  HVRT_sym  HVRT_asym    │──▶│ frt_v2_full320    │
│ │(改标定)       │ │   │   ┌────── ODE ──────┐   │   └────────┬─────────┘
│ ├──────────────┤ │   │   └──(标定的训练环境)──┘   │            │
│ │SAC Adjustment│◀┼─┐ └────────────────────────┘            ▼
│ │(BO 调奖励权重 │ │ │  (只重训受影响的专家)          ┌──────────────────┐
│ │ +采样)        │ │ └──── ODE-visible ───────────────│ error analysis    │
│ └──────────────┘ │ ◀─── ODE-blind (→改标定) ─────────│ (聚类+分流闸)      │
└──────────────────┘                                   └──────────────────┘
   防遗忘门: 新参数不许让"已过的簇"退步
```

**两层 / 两保真:**
- **内层（便宜，ODE）**：给定奖励权重 θ + 采样 w，在标定过的 ODE 上训专家（SAC）。检查点选择用
  **Vdc-gated proxy**（廉价代理；frt_metrics 的 `partial_proxy_pct` + Vdc 存活门）。
- **外层（贵，Simulink）**：开关级全 320 认证 `pass|det` = **唯一真目标**（绝不用 ODE proxy 当最终目标）。

**两个调节出口（误差分析分流）:**
- **ODE Adjustment**：当失败 **ODE-blind**（ODE 看不见）→ 跑 Simulink 扫描重标定 ODE。**不是优化变量**——
  标定只为忠实，绝不为提分调（调它=自欺）。
- **SAC Adjustment**：当失败 **ODE-visible** → BO 调奖励权重 + 采样率。

---

## 2. 环节详解

### 2.1 Simulink 认证（"测什么" = 五判据）
`frt_v2_full320_switching.m` → `frt_v2_evaluate.m`：320 标定故障，开关级 EMT，逐场景评五判据:

| 判据 | 测什么 |
|---|---|
| connect 穿越 | 正序电压不跌破/超出 GB/T 电压-时间包络（不脱网）|
| reactive 无功 | 无功电流按 GB/T 下垂、**符号对**、量足 |
| limit 限流 | 实测电流峰值 ≤ 变流器上限（无功优先）|
| recover 恢复 | 清除后电压按时回 ≥0.9 |
| survive 存活 | Vdc∈[0.75,1.25] 全程 **且** 负序电流 I2≤3pu |

门禁子测试：`frt_v2_spotcheck`(12 例)、`frt_v2_consistency_test`(SB3==MAT==HLC)、`frt_v2_golden_test`(Py==MATLAB 判据)。
输出：逐场景 True/False/NE + strict/no-fail/pass|det + 分域 + provenance（`p3_full320_sw_mi*.mat`）。

### 2.2 error analysis（"怎么修" = 聚类 + 分流）
`error_analysis_*.py`（纯事后处理，不重跑）:
1. **读** 结果 MAT（逐场景 crit + prov）；
2. **逐失败拆解**：挂哪条判据、reason、worst/t_worst、是否带 NE、dq 是否也挂；
3. **聚类**：按 判据 / 故障类型 / SCR / 域 / 深度 / 单vs多判据 / SAC-only vs dq / 交叉表；
4. **分流闸（ODE-visible?）**：把每个失败场景**在 ODE 里用当前策略重跑**，看 ODE 是否**也**报该失败 →
   visible（奖励能感知，给 SAC Adjustment）/ blind（奖励瞎，给 ODE Adjustment）；
5. **输出**：CSV + 汇总 JSON + 分维度图 + **"改 ODE 还是改 SAC"的决定**。

### 2.3 分流决策表（簇 → 补救）— 要编码的映射
| 失败簇（判据@域/工况）| ODE 看得见 | 补救出口 |
|---|---|---|
| survive @ 深 sym (LVRT) | ✅ 是（ODE 有串联抽直流项）| SAC：↑`w_vdc`、↑深sym采样 |
| survive @ swell_3ph (HVRT) | ✅ 是（Stage A 扩标定后）| SAC：↑`w_vdc`、加`w_secouple`、↑swell采样 |
| reactive 反号 @ 边界 | ✅ 是 | SAC：加`w_signfix`；或部署端钳位 |
| reactive @ swell_1ph (V+≤1.1) | — 判据边界 | 部署端反号钳位（safety_projection Part1）|
| 任意 @ 真·开关级独有暂态 | ❌ 否 | **ODE Adjustment**：dc_sweep 重标定 → 变 visible |
| 物理不可达（单端口硬限）| — | 记诚实局限，不强求 |

### 2.4 ODE Adjustment（改标定，**非优化变量**）
触发：分流闸判某簇 ODE-blind。流程（= Stage A-C，已跑通一次）:
1. **Simulink 开环扫描**（`frt_v2_dc_sweep.m`）：固定指令网格 + 故障 → 测真实响应（如 Vdc 欠冲）；
2. **拟合小公式**（物理定骨架 + 看数据定交叉项 + 比 R² 定复杂度）；
3. **塞进 ODE**（`frt_env.py` 对应区段，只动该区段、别处不变）；
4. **验证**：扩展后 ODE 用同指令重跑，数对得上 Simulink（如 swell：ODE 0.674 vs Sim 0.601）。
> 例：swell 直流欠冲 R²=0.91，已实现。**ODE 系数永远标定到忠实，绝不进 BO 优化。**

### 2.5 SAC Adjustment（BO 调奖励权重 + 采样）
对 ODE-visible 簇，BO 在**误差分析点名的少数权重维**上找最优。详见 §3。

---

## 3. BO 自动调参详解

### 3.1 优化变量（随失败簇变化的小清单，各带范围）
| 参数 | 含义 | 现值 | 范围 | 失败簇 |
|---|---|---|---|---|
| `w_vdc` | Vdc 欠冲惩罚强度 | −10 | [5,40] | 深sym / swell survive |
| `vdc_floor` | 惩罚安全地板 | 0.82 | [0.78,0.88] | survive |
| `w_signfix` | 无功反号惩罚（**新项,0=关**）| 0 | [0,20] | reactive 反号 |
| `w_secouple` | 低Vdc抑制串联升压（**新项,0=关**）| 0 | [0,15] | swell survive |
| `s_swell` | swell 过采样率 | 1× | [1,5] | swell 簇 |
| `s_deepsym` | 深 sym 过采样率 | 1× | [1,5] | 深 sym 簇 |

**铁律**：只调奖励权重/采样率；**不调 ODE 系数、不调判据**；每轮只激活与当前失败簇相关的 2~4 个。
"0" = 候选**新奖励项**（现有项不精准针对该失败模式，BO 决定要不要从 0 打开）。

### 3.2 完整奖励 vs BO 子集（5 判据都覆盖，只调失败的）
```
connect  → r_connect, r_v2        (不失败→不调)
reactive → r_reactive       ──→ +w_signfix
limit    → r_limit                (不失败→不调)
recover  → r_v2                   (不失败→不调)
survive  → r_vdc            ──→ w_vdc/vdc_floor/+w_secouple
```

### 3.3 BO 原理
- **代理模型（高斯过程）**：从已试点猜出"权重→pass|det"整条曲线 + 每处不确定带；新点贝叶斯更新。
- **采集函数（Expected Improvement）**：挑"最可能比当前最好成绩提升"的下一组权重（平衡利用/探索）。
- **省**：从不把昂贵评估浪费在确信差的点；几万次网格压到几十次。
- 工具：`scikit-optimize` / `Ax` / `Optuna`。

---

## 4. 完整算法

```
输入: θ = 当前奖励权重(误差分析选的子集); w = 均匀采样; 历史 H = {}
循环:
  1. 训练:   在 ODE(θ,w) 上训【受影响的】专家 (SAC, 内层)
             检查点选择用 Vdc-gated proxy (便宜)
  2. 认证:   export → build → frt_v2_full320 → pass|det + 逐场景 T/F/NE (外层, 真值, 贵)
  3. 分析:   error_analysis 自动聚类失败
  4. 分流:   每簇判 ODE-visible? ; blind → 标"待重标定"出循环; 留 visible
  5. 停判:   若无 ODE-visible 可调簇 → 停 (剩下交给重标定/记硬限)
  6. 出招:   BO 在【失败簇→权重】映射的少数维上建议下一组 θ;
             w 过采样这些簇 (PER/课程)
  7. 守门:   接受 θ 仅当 pass|det↑ 且 无簇退步(防遗忘); 否则拒绝, BO 记此方向差
             把 (θ, pass|det, 逐簇) 入 H → 更新 GP
直到 预算耗尽(~15-20 评估) / pass|det 收敛 / 仅剩 blind
```

成本：每评估 = 1 次内层训练 + 1 次 Simulink 认证(~10min)；BO ~15-20 评估 → 数小时。
省钱三招：**误差分析压维度 + Vdc-gated proxy 当内层代理 + BO 聪明采样**。

---

## 5. 护栏（防 reward hacking — Amodei/Krakovna）
1. **只在判据对齐项里调权重**，不准发明非物理项；
2. **真目标必须 Simulink 认证**，proxy 只配内层选检查点（proxy 会被钻空子）；
3. **防遗忘门**：不准为提总分牺牲已过工况（mi=17 即反例）；
4. **ODE 系数不进优化**：标定只为忠实，杜绝"把 ODE 调乐观"这条作弊路。

---

## 6. 实现状态（done vs to-build）

| 环节 | 状态 |
|---|---|
| Simulink 认证（五判据 + 门禁）| ✅ 已实现 |
| error analysis 聚类 | ✅ 已实现（`error_analysis_mi14.py`，硬编码 mi=14）|
| ODE proxy（Vdc 存活门）| ✅ 已修（`frt_metrics.py`，audit 2026-06-27）|
| 重训脚本（自动迁移+100k）| ✅ 已实现（`retrain_expert.py`）|
| ODE Adjustment（dc_sweep→拟合→塞ODE→验证）| ✅ 已跑通一次（swell）|
| **error_analysis 参数化（任意 mi）** | ❌ 待建 |
| **"簇→权重"映射表（编码）** | ❌ 待建 |
| **ODE-visible 自动分流** | ✅ 已实现（`error_analysis_mi14.py`：逐 FAIL 调 ODE 重放；当前 mi=14 为 34/34 visible） |
| **BO 外层循环 + 防遗忘门** | ❌ 待建 |
| **orchestrator（串起整圈）** | ❌ 待建 |

**当前是"诊断闭环 + 人工在环优化"**：认证/分析自动，决策/改/重训由 agent 编排。

---

## 7. 第一版最小可行（建议落地顺序）
1. `error_analysis` 参数化（收 mi 参数）；
2. 写"簇→权重"映射表（§2.3 编码）；
3. 定 §3.1 参数清单 + 范围；
4. 接 `scikit-optimize` 做 BO 外层（目标=Simulink pass|det，带防遗忘门）；
5. 内层用 Vdc-gated proxy 选检查点；
6. 跑 5~10 轮 BO，看 pass|det 曲线。

不上 LLM、不上 PBT（要并行算力）；LLM(Eureka) 作可选上层，下面仍 BO+认证+护栏兜底。

---

## 8. 文献对应
| 组件 | 文献 |
|---|---|
| 奖励整形有原则 | Ng, Harada, Russell 1999 (PBRS) |
| 诊断→改奖励闭环 | Ma 2023 Eureka (reward reflection) |
| 奖励权重=超参 | Eimer 2023；Parker-Holder 2022 (AutoRL) |
| 失败过采样 | Schaul 2016 (PER)；Narvekar 2020 (curriculum) |
| barrier 形奖励(违规区陡) | DRL-for-converter 综述 2025 + 电压控制 DRL |
| 防 reward hacking | Amodei 2016；Krakovna 2020 |
| BO | 贝叶斯优化（GP + Expected Improvement）|
