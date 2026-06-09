# 开关级 dq STATCOM FRT 测试台 (`build_frt_statcom.m` → `frt_statcom.slx`)

**目的**：在**开关级**(real IGBT + PWM)、**完全可复现**(纯脚本、不碰 108 块二进制)的模型上,
验证并联无功通道——SAC FRT 策略学到的 `i_sh_q` 无功电流指令能否被真正注入、支撑弱网电压、
遵守限流,并给出 5 项 FRT 判据。这是原二进制模型无法做到的(并联无真实电流测量、永久 78kW
泄放、电压型无法有效注无功——见下"为什么另起测试台")。

## 为什么另起测试台(而非改原二进制)
诊断原 `hpt_switching_model.slx` 发现三处阻塞:
1. **`Ish_dq` 不是真实并联电流**,是手工 DNN 特征 `0.05*(800-Vdc)+0.02*(id1-id2)` → 无法闭电流环;
2. **DC 阻尼电阻 8.2Ω 永久接入 = 78kW 泄放**(占 120kVA PE 的 65%),既是被错误照搬的 ODE
   数值阻尼,又是事实上的过压斩波器 → 电网故障一来取不到能就把 Vdc 抽干;
3. **电压型 STATCOM(仅抬幅值 m)无法有效注无功**:实测 V2 仅动 0.2%(无 PLL/电流环,抬 m 主要
   去充 Vdc)。
→ 故在 400V(并联 VSC 原生电平,弱网阻抗反射至此)从零搭建聚焦测试台。代价:聚焦并联无功通道,
不含全系统串联交互——对"验证无功支撑"完全够。

## 拓扑(400V 层)
```
弱网源(R/L 按 SCR) → MeasPCC → PCC母线 ┬ GridFault(三相故障,残压随 R)
                                        ├ Load(额定阻性)
                                        └ Lfilt(R_sh+L_sh) → MeasVSC(电流) → VSC(2电平IGBT桥)
                                                                                  │ DC: Cdc(2200µF,初值800V)
                                                                                  │     + 条件斩波器(IGBT+Rchop, Vdc>1.20pu投入)
```

## 控制(`CTRL` MATLAB Function,50µs 离散)
- **SRF-PLL**：锁 PCC 正序角 θ(err=+Vq/Vm 归一化,Kp=90 Ki=1500);
- **外环 Vdc PI** → 有功电流参考 id_ref(双向,限幅±0.9·Imax,限速);
- **无功优先限流**：iqr=clip(iq_ref,±0.3·Imax);idr 让位 sqrt(Imax²−iqr²);
- **dq 电流内环**(Kp=2.5 Ki=150)+ 解耦 ±ωL + 电网前馈 + 抗饱和(饱和时冻结积分);
- **软启动**：Vdc>620 latch 投控制(此前二极管整流预充);
- **条件斩波器**:Vdc>1.20pu 投入(仅管故障过压)。
- 约定:电流**流入变流器为正**(充电);PLL 误差 +Vq、电流环 PI 取负、解耦反号——三处符号已对齐验证。

## 动作接口(Constant 块 / 每场景)
- `iq_ref`(A)：SAC 无功电流指令 i_sh_q(+容性支撑电压);
- `Vdc_ref`=800;有功 id_ref 由 Vdc 外环自动生成(真实取能 VSC 行为)。
- 故障:`GridFault` 的相/接地/R + `Grid` 的 R/L(SCR)+ Voltage(EMF 校准)。

## 当前状态(2026-06-09)——已跑通,待精修
**已验证可用**：
- PLL 锁相(Vd≈Vm≈298, Vq≈0, θ 干净 0→2π);
- Vdc 稳态≈800(均值 802);
- **无功注入真实有效**：稳态 iq=+52A → PCC 0.936→0.952pu(+1.6%);iq=−52A → 0.899pu(−3.7%)
  (对比电压型捷径仅 0.2%);
- FRT 故障(残压 0.63):注无功使 **Vdc_min 0.756→0.823**、过压 1.20→1.10。

**待精修(下一步)**：
1. iq 跟踪有 +~15A 偏置(开关纹波/稳态误差)→ 调电流环积分 / 测量滤波;
2. Vdc 纹波偏大(std~60V)→ 调外环 / 加母线滤波;
3. 故障期残压标定按 SCR 做(弱网 EMF 需抬高保证故障前 PCC=1.0pu);
4. 接 `frt_scenarios.csv` 跑子集 + 算 5 判据,与 ODE 侧(react 74% / frt_pass 59%)对比。

## 复现
```matlab
cd frt_standard/simulink
build_frt_statcom();      % 重建 frt_statcom.slx
% 设 iq_ref / GridFault / Grid 后 sim('frt_statcom')
% 注意:To Workspace 'dq' 是 7×1×N 三维数组,读取须 squeeze(dq).'
```

## 重要数据读取陷阱
`dq` 日志是 **7×1×N** 三维数组(To Workspace 存 7×1 向量),必须 `squeeze(dq).'` 转成 N×7,
否则按 N×7 直接索引得到的全是错位垃圾(调试期踩过此坑)。
