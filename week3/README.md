# week3:MPC(在线优化)基线文献与复现

目的:为决策层对比补上"模型已知 + 显式约束"的在线优化路线(MPC),与 SAC(mode 12)和固定律 dq 家族(mode 4-7)同台。复现实现为模型 **mode 8**(见下)。

## 已下载文献

| 文件 | 文献 | 与本项目的关系 |
|---|---|---|
| `mpc_hdt_voltage_pf_mdpi2024.pdf` | Operation Assessment of a Hybrid Distribution Transformer Compensating for Voltage and Power Factor Using Predictive Control, *Mathematics* 12(5):774, 2024 | **同拓扑**(并联+串联+共享DC 的 HDT)的 FCS-MPC,HIL 验证;但 MPC 在**执行层**(开关级,Np=2,前向欧拉电流模型),决策参考值仍由线性环给;**只做稳态电能质量,无 FRT** |
| `mpc_hdt_grid_services_arxiv2602.00798.pdf` | Modeling and Control of Hybrid Distribution Transformers for Simultaneous Grid Services, arXiv:2602.00798, 2026 | HDT 多服务控制最新综述型工作,HDT≈UPQC 等价性 |
| `mpc_pmsg_frt_frontiers2023.pdf` | A model predictive control strategy for enhancing fault ride through in PMSG wind turbines using SMES and improved GSC control, *Front. Energy Res.*, 2023 | **FRT 任务**的 MPC(风机 GSC + 超导储能);约束显式、无功支撑按导则 |
| (未获取) | FCS-MPC LVRT of two-stage PV (IJRED, 2025) | FRT+FCS-MPC,付费/下载失败;问题表述同 GB/T 判据结构 |

## 经典/背景文献(未下载,设计依据)

- J. Rodríguez et al., FCS-MPC 系列(IEEE TIE, 2007 起)——有限集 MPC 范式;
- S. Vazquez et al., "Model Predictive Control for Power Converters and Drives"(IEEE 综述)——CCS-MPC vs FCS-MPC 谱系。

## 文献格局与我们的空白

- LVRT-MPC 系列:✅FRT ❌HDT 拓扑 ❌与 RL 对比;
- HDT-MPC 系列:✅拓扑 ❌FRT ❌与 RL 对比;
- **空白(本工作)**:HDT + GB/T 全判据 FRT + **MPC vs RL 同台**。

## 复现设计(mode 8:决策层一步 MPC)

文献 MPC 都在执行层(开关/电流层);与 SAC 公平对比要求 MPC 站在**同一决策接口**(每 2 ms 输出 [iq_ref, mse_d, mse_q],内环不动)。故复现为**滚动时域的一步约束优化**:

```
每 2ms,用当前测量 (V, Vdc) 解:
  max   电压支撑(串联升压 + 无功)
  s.t.  |iq| ≤ 0.27               (限流裕度,与 SAC/mode7 同等信息)
        Vdc_eq(iq, mse) ≥ 0.82    (存活裕度;Vdc_eq 用忠实标定模型
                                    Vdc_eq = 1 − 0.08|iq|/max(0.3,V) − 1.9·max(0,m_boost) − 0.5|m_q|)
        |mse| ≤ 0.2               (容量)
  其中 iq 按 GB/T droop 取(判据即目标),mse_q*=0(模型中纯抽直流无收益)
```

由于预测模型是代数平衡点模型(动态由内环吸收),该优化**有闭式解**:iq* = clip(droop, ±0.27);串联升压用到 Vdc 约束的边界为止 `m_boost* = min(0.2, (1−0.82−sag_iq)/1.9)`,并以实测 Vdc 做滚动反馈修正。实现于 `frt_standard/simulink/build_hpt_frt_full.m` 的 HLC mode 8。

**与各对照的关系**:mode 5/7 把串联一刀切置零;mode 6 按 Vdc 线性降额(启发式);**mode 8 用标定模型把串联用到约束允许的最大值**——这是"模型已知时的最优固定结构"。对比 SAC 检验:显式优化 vs 学习的逐工况自适应,孰优。

## 结果(2026-06-10,32 场景分层子集)

| 控制器 | LVRT 24 | HVRT 8 | 全 32 |
|---|:---:|:---:|:---:|
| **MPC(mode 8)** | 75.0% | **87.5%(全场最佳)** | **78.1%** |
| SAC 4 专家(mode 12) | **83.3%** | 75.0% | **81.2%** |
| 最强固定律(mode 7) | 62.5% | 75.0% | 65.6% |

- MPC 失分集中在 **2ph 强不对称的无功判据**(79.2%):平衡点预测模型无负序/2ω 动态,固定优化结构无法逐工况补偿——SAC 的学习优势正在此;
- MPC 的 **HVRT 87.5%** 反超 SAC(75%):droop 目标直接进优化、吸无功深度精确——恰是 SAC 弱域;
- **互补性 → 混合架构**(LVRT-SAC + HVRT-MPC,按既有门控切换)预计 ~84%+,留作后续;
- 注:MPC 的预测模型 = 主项目标定的忠实 ODE,约束裕度(0.27/0.82)沿用 RL 实验发现——它的好成绩本身建立在本项目的方法学之上。

数据:`frt_standard/results/dq_variants3_compare.{mat,txt}`;实现:HLC mode 8(`build_hpt_frt_full.m`);harness:`validate_dq_variants3.m`。主报告 §4.9 已并入。
