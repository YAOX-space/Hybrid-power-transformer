# 混合配电变压器(HPT)故障穿越强化学习控制 — 项目工程总说明

> 🔴 **frt-v1 失效声明（2026-06-22 审计）**：本文 §3/§4 的所有通过率与排名为 **legacy frt-v1**，受判据缺陷
> C1–C4/H3–H4 影响（见 [AUDIT_2026-06-22.md](AUDIT_2026-06-22.md)），**不可与修正后 frt-v2 比较；修正后成绩 PENDING**。
> 已停用「专家化净增益 +37.8pp [legacy frt-v1 INVALIDATED, PENDING frt-v2]」「系统层不需要协调学习」「国标合规率」。旧结果存 `lab/results/legacy_pre_audit/`。

> **本文件是项目当前状态的权威索引**(2026-06-17 刷新)。面向工程管理:架构、最终结果、完整文件地图、复现入口。
> 当前唯一报告:[report.md](../src/hpt_frt/network/report.md)(二期网络鲁棒性压测,含 L1 开关级抽查)。一期 FRT 问题定义见 [FRT_SPEC.md](FRT_SPEC.md);模式权威定义见 [CONTROL_MODES.md](CONTROL_MODES.md);文件地图见 [FILE_GUIDE.md](FILE_GUIDE.md)。(2026-06-21 仓库精简:已删 emt/、phase2/、旧报告/讲义/审计,仅保留最新报告 + 必备文档。)

---

## 1. 项目是什么

400 kVA 混合配电变压器(主变 Δ-Yg 10 kV/400 V + 并联取能 VSC + 串联调控 VSC + 共享直流母线,电力电子约 0.3 pu)。参照**中国国标 GB/T 19963/19964**(风/光伏 LVRT/HVRT)的电压-时间穿越曲线定义故障穿越(FRT)判据;目标:在开关级研究模型上以强化学习(SAC)探索逐工况自适应控制并验证鲁棒性。〔注:不主张"GB/T 合规认证"，亦不在 frt-v2 重验前主张"优于传统 dq"——legacy frt-v1 成绩已 INVALIDATED，PENDING frt-v2。〕

项目分两期:**一期**——单台 HPT 的 FRT 控制(训练 + 开关级验证);**二期**——把一期 SAC 放进 IEEE 33 节点配电网做系统级压测(网络作为"试验台");**B 阶段**——双机直流互联的开关级保真复核(三级)。

---

## 2. 三层建模架构(贯穿全项目)

强化学习需数十万步交互,开关级 EMT 单场景约 20 s 无法直接训练 → 训练/验证分离:

| 层 | 模型 | 角色 | 关键文件 |
|---|---|---|---|
| **训练层** | 平均值 ODE(正负序 + 无功优先 + 限流 + GB/T 包络) | 快速试错、策略学习 | `src/hpt_frt/device/frt_env.py`、`residual_env.py` |
| **验证层(权威)** | 开关级 Simulink(Simscape,真 IGBT/5 kHz SPWM/ode23tb 20 µs) | 唯一判据来源 | `lab/simulink/build_hpt_frt_full.m` |
| **网络层(二期)** | OpenDSS 准静态相量(IEEE 33) | 系统级 OOD 试验台 | `src/hpt_frt/network/`(ieee33.dss + opendss_runner.py 等) |

**忠实 ODE(关键方法学)**:朴素 ODE 偏乐观(无功增益高估 ~4.5×、直流母线可被有功随意充电),训出的策略部署即崩。修正:用开关级实测数据标定 ODE 直流模型 `Vdc_eq = 1 − 0.08·|iq|/max(0.3,V) − 1.9·max(0,V_se_d) − 0.5·|V_se_q|`(误差 ≤0.02)。**一切结论以 Simulink 为准。**

---

## 3. 一期最终结果(统一口径全 320 场景,开关级 Simulink)

> 控制器命名/编号/角色/结果有效性以 **[CONTROL_MODES.md](CONTROL_MODES.md)(单一事实源)** 为准。**主方法 = Mode 5(在线门控多专家 SAC)**;**Mode 6(MPC 辅助残差 SAC)为扩展性能方法,非主方法、非"纯 SAC"**。

> ⚠️ **下表为 legacy frt-v1，已失效（2026-06-22 审计）**；权威状态以 `controller_registry.py`/`controller_modes.m`（`validity='pending-frt-v2'`, `score=None`）为准。

#### Historical frt-v1 results — INVALIDATED (PENDING frt-v2)

> 下表全部为 **legacy frt-v1，已失效**（2026-06-22 审计）；frt-v2 重验（P1/P3）前不得作有效性或优劣结论。

| Mode | 控制器(canonical) | LVRT 240 | HVRT 80 | **全 320** | 有效性 |
|:--:|---|:---:|:---:|:---:|---|
| 1 | 最强固定律 tuned fixed-law | 60.4% | 75.0% | 64.1% | INVALIDATED → PENDING frt-v2 |
| 2 | 一步显式 MPC one-step explicit MPC | 74.6% | 95.0% | 79.7% | INVALIDATED → PENDING frt-v2 |
| 3 | 单一 SAC unified SAC | 42.5% | 50.0% | **≈44.4%** | INVALIDATED → PENDING frt-v2(2026-06-18) |
| 4 | Oracle 门控多专家(消融) | 83.3% | 75.0% | **≈81.2%** | INVALIDATED → PENDING frt-v2(仅消融) |
| **5** | **在线门控多专家 SAC ★主方法** | **84.6%** | 75.0% | **82.2%(硬门控版)** | ✅ 硬门控版 INVALIDATED-PENDING-frt-v2;滞环/3维重训版待验证 |
| 6 | MPC 辅助残差 SAC(扩展) | 95.4% | 98.8% | 96.25%(308/320) | INVALIDATED → PENDING frt-v2(扩展) |
| — | dq-legacy(已弃用基线) | 9.6% | 81.2% | 27.5% | deprecated/historical |

**主方法 = Mode 5(在线门控多专家 SAC)= 82.2%(硬门控版)**,高于最强固定律(64.1%)、一步显式 MPC(79.7%)、已弃用 dq-legacy(27.5%);相对本文实现的固定律与一步 MPC,主要增益在强不对称(2ph 域 98.3%),短板在 HVRT(75.0%,低于固定律/MPC——故有 Mode 6 扩展)。**Mode 6(MPC 辅助残差,扩展)= 96.25%(308/320)**,其中 MPC 先验单独已 79.7%、残差+部署机制再补 ~16.6pp(非纯学习贡献)。三个关键发现:
1. **传统固定律主导失效机理 = 串联注入致直流母线能量过度耗竭**(非拓扑硬限)——dq 满额串联升压把直流母线抽到 0.55 而死;克制串联(SAC)/预算内用串联(MPC)都能稳住 Vdc≥0.81;
2. **sim-to-real 差距靠忠实 ODE 标定消除**(乐观 ODE → 部署即崩 ~19%);
3. **学习与优化互补**——多专家 SAC(Mode 5)赢在不对称域逐工况自适应,MPC(Mode 2)赢在可解析的 HVRT;残差扩展(Mode 6)兼得两者。
> **P1 消融(2026-06-18 开关级实测)**:专家化净值 = Mode 5 − Mode 3 = 82.2 − 44.4 = **+37.8pp [legacy frt-v1 INVALIDATED, PENDING frt-v2]**(专家化对强不对称域决定性);门控损失 = Mode 4 oracle − Mode 5 = **≈0**(在线序分量门控基本无损,与 oracle 选同一专家);Mode 5 短板(sym3ph/HVRT)为**专家级非门控级**(oracle 同卡)→ 改进靶向 P2 重训专家。
> 仍待验证见 [CONTROL_MODES.md](CONTROL_MODES.md) §5(Mode 5 滞环/3维/去特权/多种子、Mode 5 二期系统级 OOD)。


---

## 4. 二期:配电网作为一期 SAC 的系统级试验台

**首要目的**:用真实配电网压测一期 SAC 在训练分布外的网络工况下扛不扛得住(**不是**协同学习研究)。

- **二期观察(非通过率)**:相量层(OpenDSS 准静态)OOD 凹陷下 SAC 策略理智、不对称钳位正确、十机不动点零反号——此为**相量层稳定性观察**。〔保真层开关级"守住限流/Vdc≥0.82"基于 legacy frt-v1 criteria,已 **INVALIDATED**,PENDING frt-v2,不作通过率结论。〕系统级跑的是 Mode 6 残差;Mode 5 的网络 OOD 系统级重测待 frt-v2 重验(见 [CONTROL_MODES.md](CONTROL_MODES.md) §5)。
- **副线（结论待重验）**:〔以下由 legacy frt-v1 数值推得,已 **INVALIDATED**,PENDING frt-v2,不作为当前结论〕五条交流侧协同路径影响小(≤+0.7pp);唯一非平凡杠杆是直流母线互联(负荷穿越 57.2%→65.8%)。frt-v2 重验前不主张"系统层不需要协调学习"。

### B 阶段:双机直流互联开关级三级复核(§5.1–5.3)

| 级 | 模型 | 结果 |
|---|---|---|
| Stage 1 电路级 | `build_dual_dcpool.m` | 单机塌 0.246 / 互联存活 0.914 pu |
| Stage 2 真 IGBT 取能 VSC | `build_dual_dcpool_sw.m` | 单机塌 0.00 / 互联存活 0.916 pu |
| Stage 3 完整双 HPT + 双 SAC 闭环 | `build_dual_hpt_sac.m` | 原始 SAC 池无活;池+分配器 Vdc_A 0.827→0.987 |

**Stage 3 揭示 §5 价值链机理**:原始 SAC 自限预算 → 池"无活可干"(故硬件池单独只 +4.0pp);一层薄分配器抬高逐装置上限后,邻机直流裕度才被支取(分配智能 +4.7pp)。**SAC 的单机预算纪律,正是系统层只是温和硬件杠杆而非学习问题的根因。**


---

## 5. 完整文件地图

```
Hybrid-power-transformer/                  # 2026-06-21 工程化重构布局
├── README.md  pyproject.toml  requirements.txt
├── docs/                          # 全部文档
│   ├── CONTROL_MODES.md           # ★ 控制器模式唯一权威定义
│   ├── PROJECT_OVERVIEW.md        # ★ 本文件
│   ├── FRT_SPEC.md  FILE_GUIDE.md
├── src/hpt_frt/                   # ★ Python 包 (pip install -e .)
│   ├── device/                    # 一期装置级
│   │   ├── frt_env.py / residual_env.py            # 训练环境(Mode3/5 / Mode6)
│   │   ├── train_experts.py(★Mode5 4专家) / train_residual.py(Mode6) / train_frt_sac/seeds/ab.py
│   │   ├── export_{experts,residual,sac_actor}.py  # 权重导出 → lab/ + lab/simulink/*.mat
│   │   └── controller_registry / frt_metrics / gen_frt_scenarios / gen_p1_figs / env_compare.py
│   └── network/                   # 二期网络压测
│       ├── config/sequence/sac_wrapper/hpt_interface/opendss_runner/scenarios/metrics.py + ieee33.dss
│       ├── run_exp_A/B/C + study_{vdc_boundary,c10_oscillation,gate_noise} + run_baselines + fill_spotcheck.py
│       ├── report.md + NEXT_STEPS.md   # ★ 当前唯一报告 + 下一步
│       └── results/               # CSV / fig1–11 / simulink_cases(*_sw_result.mat)
├── lab/                           # ★ MATLAB 开关级 + 场景 + 已验证结果
│   ├── simulink/  build_hpt_frt_full.m / hpt_frt_full.slx
│   │              # frt-v2 有效入口: frt_v2_full320_switching.m / frt_v2_spotcheck.m / frt_v2_evaluate.m / frt_v2_calibrate.m
│   │              # legacy guard (非 frt-v2 评价入口): validate_mode_full.m / run_spotcheck.m
│   │              hpt_dual_*.slx + build/run_dual_*.m / sac_*_weights.mat
│   ├── frt_scenarios{,_subset}.csv  sac_*_weights.mat
│   └── results/   frt320_m{4,7,8,12,14}_*.{mat,txt} + 训练 json
├── data/models/  sac_*_best.zip   # SAC 模型(Mode5 四专家 + Mode6 残差 + Mode3, gitignored)
└── references/   week1–4/         # 文献 PDF
```
> 2026-06-21 精简删除(git 可恢复):`emt/`、`phase2/`(二期 v1)、`simulink/legacy/`、非主方法结果
> `frt320_m11/m13/m15_*`、以及全部旧报告/讲义/审计 md。逐文件状态见 [FILE_GUIDE.md](FILE_GUIDE.md)。

---

## 6. 复现入口

```powershell
# Python 环境(必须先设,否则 libiomp 冲突致 numpy/torch matmul 段错误)
$env:KMP_DUPLICATE_LIB_OK="TRUE"; $env:MKL_THREADING_LAYER="SEQUENTIAL"
$PY=".venv\Scripts\python.exe"
& $PY src/hpt_frt/device/train_residual.py     # 训练残差 SAC(Mode 6 扩展, internal m14)
& $PY src/hpt_frt/device/export_residual.py    # 导出权重 → sac_residual_weights.mat
Copy-Item lab/sac_*_weights.mat lab/simulink/
```
```matlab
% MATLAB R2025a + Simscape Electrical:frt-v2 开关级评价【当前有效入口】
cd lab/simulink
frt_v2_full320_switching(14, 1, 320)   % m14 残差 SAC 忠实全 320(标定故障→开环 V+=ODE Vg_p;可分块 i0,i1)
frt_v2_full320_switching(7,  1, 320)   % dq 固定律基线(同峰值基准)
frt_v2_spotcheck()                     % 12 例开关级门禁
% 权威五判据 = frt_v2_evaluate.m。legacy guard(非 frt-v2 入口): validate_mode_full.m / run_spotcheck.m
% B 阶段:run_dual_dcpool / run_dual_dcpool_sw / run_dual_hpt_alloc
```

依赖:MATLAB R2025a + Simulink + Simscape Electrical;Python `.venv`(见 requirements.txt)。

---

## 7. 诚实局限(详见报告)

1. **模型非真机**:400 kVA 单交流口(任务书为多端口含直流口)、线性变压器(无饱和/铁损)、未硬件对标;
2. **忠实 ODE 是静态平衡点拟合**(非动态功率平衡):**关键系数经 2026-06-17 重测复核为忠实**——串联抽取 `1.9·V_se_d` 在 SCR=3/sym3ph 与开关级 Vdc_min 误差 ≤0.022、`K_q∝1/scr` 在 SCR=10 成立(报告 §5-5)。负荷字段 `P_load/Q_load/pf` 是**装饰性的**(ODE 与验证器均不读取、二者跑额定负荷),故"抽取与负荷无关"对验证器忠实(非 sim-to-real 缺口);引入真实负荷依赖须先改验证器(后续)。换拓扑/参数需重标定。曾被"取能饥饿致 Vdc 必塌"的错误直觉主导,真实瓶颈是串联自伤(§1.5/§5-5);
3. **不对称残压深度在 Δ-Yg 下不可达**(MV 单相故障最深把 LV 正序压到 ~0.78),1ph_g 的 0.2/0.5/0.75 实为同一温和工况×3,**名义 320 的有效多样性显著低于标称**,头条百分比含等效重复易例(§5-3);
4. **串联级拓扑限制不对称结论**:开关级串联级为三相桥+浮地星点,只能注正序,"不对称域 RL 不可替代"严格只对该拓扑成立;课题书要求的独立 H 桥可注负序,结论可能改变(§5-9);
5. **训练时间压缩对直流动态非尺度不变**:`TSCALE=0.2` 压缩穿越窗 5× 但直流时常数未压缩,训练求解的是 Vdc 相对动态更易的暂态(开关级实时验证兜底,§5-10);
6. **二期为准静态相量**(无机电暂态);B 阶段开关级为降阶 LV-源背骨(未含完整 MV 背骨),对称工况,逐相不对称 + 100 Hz 纹波的多机耦合未展开;
7. **判据的标定参照依赖、偏置方向不确定**:connect 隐含"故障深度以谁的支撑为参照"。本项目用固定 dq 参照——此前称"对 SAC 保守"系口误,固定 R_fault 下撑压强于 dq 者 connect 反而更易过(偏乐观);中性参照需重标定重测(§5-7)。另 `reactive` 判据含 2ω 均值偏置,2ph 列对固定律偏低(§5-11)。
