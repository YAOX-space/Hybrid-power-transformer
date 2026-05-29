# Literature And Model Review For HPT v2

更新日期：2026-05-25

## 结论

当前项目主模型已经切换到正确的混合式电力变压器 HPT v2 拓扑：

```text
主功率通道:
Grid -> Series_Injection_Transformer_* -> Main_Line_Frequency_Transformer -> LV_Load

取能换流器:
400 V LV bus -> Energy_Filter_* -> Energy_Extraction_VSC -> DC_Link_Capacitor

调控换流器:
DC_Link_Capacitor -> Regulation_VSC_phase_* -> Series_Injection_Transformer_* -> main AC path
```

这与混合式电力变压器文献中的核心思想一致：工频主变压器承担主要功率传输，电力电子部分以较小容量完成直流母线取能、串联电压注入、调压、无功/潮流辅助和故障穿越。

## 与文献一致的部分

- 存在工频主变压器，不是全功率固态变压器。
- 存在低压侧取能换流器，用于维持 DC link。
- 存在串联调控换流器，通过串联注入变压器影响主交流通道。
- 存在 DC link，作为取能换流器和调控换流器之间的能量缓冲。
- 当前评估指标已经覆盖 LVRT/FRT 关键量：`VdcMin`、`VdcMax`、`I2Max`、恢复时间和低压侧电压跌落。

## 仍然简化的部分

- 取能换流器仍是规则/SPWM 控制，还不是完整 PLL + dq 电流内环 + Vdc 外环。
- 调控换流器仍是规则/SPWM 控制，还不是完整负载电压外环 + 串联注入内环。
- 主变压器和串联注入变压器的饱和、铁耗、频变损耗和详细磁耦合尚未展开。
- 故障场景已经包含 IGBT 开路、电容故障、单相短路、三相短路和级联故障，但还需要固定随机场景表以保证控制器公平对比。
- AI 控制仍沿用旧 imitation policy，在 HPT v2 上已经证明失败，需要重训或换成 Simulink-in-the-loop PPO/DRL。

## 当前实验可信度

可信：

- HPT v2 开关级模型能运行。
- HPT v2 数据集能生成。
- 传统诊断基线、AI 诊断、LVRT/FRT 指标能在同一数据集上重算。
- 当前结论“AI 尚未超过传统方法”是可信的。

不应声称：

- AI 已经击败文献方法。
- DNN-FRT 已经优于传统 FRT。
- 当前控制器是完整论文级 dq 双闭环控制。

## 下一步文献对标

后续要对标文献，需要至少补齐：

1. 完整传统 dq 双闭环控制基线。
2. 固定随机场景表。
3. AI 诊断模型超过 ELM/SVM/RF。
4. AI 控制模型超过 rule-based FRT。
5. 将 `VdcMin/VdcMax/I2Max/recovery time` 作为 PPO/DRL 奖励直接训练。
