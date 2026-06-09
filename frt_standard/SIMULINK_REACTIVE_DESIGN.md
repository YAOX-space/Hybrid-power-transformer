# Simulink 无功电流注入通道 — 设计方案（阶段⑤前置）

**目的**：让新 FRT SAC 的动作 `i_sh_q`（无功电流）能在权威 Simulink 开关级模型上验证。
**现状差距**：Mode 9 并联控制只给 `m_sh`（栅锁相位的幅值调制），无电流环、无无功控制、
并联电流也没测进控制块。真·无功注入必须做成 **dq 电流控制**。
**状态**：仅设计（不写代码）；待 ODE 侧训练验证 reactive 可学后再动手。

---

## 一、要加的三大件
| 件 | 作用 | 现状 |
|----|------|------|
| ① 正序锁相环 PLL | 给出对齐正序电网电压的角度 θ_pll；不对称故障需正序分离（DSOGI-PLL）| 无（Mode 9 用开环 θ=2π50t）|
| ② 并联电流测量 + Park | 测 Energy_Filter/桥的 i_sh_abc → i_sh_d、i_sh_q | 桥 Measurements 输出未连进控制 |
| ③ dq 电流控制器 + 逆Park | i_d_ref/i_q_ref → 调制，含解耦/限流/无功优先 | 无 |

## 二、控制律（标准并网 VSC 电流控制）
坐标：dq 对齐正序电网电压（θ_pll）。测量：i_sh_d/q、v_d/q、Vdc。
指令：`i_d_ref` 有功(稳直流)←SAC i_sh_d 或 Vdc PI；`i_q_ref` 无功←SAC i_sh_q 或 GB/T droop 1.5(0.9−V)。

无功优先 + 限流：
```
i_q_ref = clip(i_q_ref, −0.3, +0.3)                  # PE 容量上限
i_d_ref = clip(i_d_ref, 0, sqrt(I_max² − i_q_ref²))  # 有功让位
```
内环 PI + 解耦前馈（Kp_ish=9.42, Ki_ish=157 已在 parameters.m，500Hz 带宽）：
```
u_d = PI(i_d_ref − i_d) − ωL·i_q + v_d
u_q = PI(i_q_ref − i_q) + ωL·i_d + v_q
m_d = 2u_d/Vdc ; m_q = 2u_q/Vdc
m_a = m_d·cosθ − m_q·sinθ  (b,c 各 ∓120°) ;  gate = (m_a ≥ carrier)
```

## 三、模型结构改动（结构件，须改 .slx）
1. 加并联电流测量（Energy_Extraction_VSC 电流测量输出，或 Energy_Filter 加 Current Measurement）→ i_sh_abc。
2. 加正序 PLL（DSOGI 正序分离）→ θ_pll（不对称必需）。
3. 把 i_sh_abc + θ_pll 接进 Energy_VSC_SPWM（新增输入端口）。
4. 改写/扩展 Energy_VSC_SPWM：加 dq 电流控制器（PI 需 persistent 积分状态）。
5. 动作端口映射（端口大多现成）：RL_Energy_Bias→i_d_ref、**RL_Current_Bias→i_q_ref**、
   RL_Reg_Bias→m_se_d、补一个输入给 m_se_q（可复用 VDC_Ref_Delta）。

## 四、落地方式
| 方式 | 做法 | 代价 |
|------|------|------|
| **A. 新增 Mode 10（推荐）** | chart 加 `controller_mode==10` FRT-电流控制分支，Mode 9 原样保留 | 仍须手工在二进制 .slx 接电流测量+PLL；可复现性差 |
| B. 先修构建脚本端口 bug 再重建 | 修好端口维度问题→纯源码重建→加无功通道 | 先啃端口 bug；之后可复现 |

→ 建议 A（不破坏现有 82% Mode 9 验证）；但"接电流测量+PLL"是**结构性 GUI 编辑**，无法纯脚本完成。

## 五、验证设计本身
1. i_sh_q 阶跃：测 i_q 跟踪、i_d 解耦不受扰；
2. 限流：i_q_ref 顶 0.3 → i_d 被压到 sqrt(I_max²−0.3²)；
3. 撑压：故障注 i_q>0 → MV/机端电压被抬（STATCOM 方向对）；
4. 不对称：单相故障下正序 PLL 锁正序、无功只注正序（不注负序谐波）。

## 六、工作量/风险
- 正序 PLL（DSOGI）：中等（二阶广义积分 + 几个积分器）；
- 电流测量接线：结构性 GUI 编辑（最麻烦）；
- 内环 PI：parameters.m 已有参数可直接用；
- 最大风险：二进制 .slx 手工编辑的可复现性（与构建脚本不能纯重建是同一老问题）。

## 诚实判断
控制律与接口清晰可设计；硬骨头是"把并联电流测量+正序 PLL 接进控制块"这一步结构性编辑，
及其带来的二进制可复现性问题。故训练侧先做好（不依赖此步），验证侧单独攻。
