# HPT 拓扑修正说明

更新日期：2026-05-25

## 修正目标

本次修正解决一个关键建模表达问题：模型不能看起来像“交流全功率整流 -> 直流 -> 逆变 -> 负载”的 UPS/SST 拓扑，而应表达混合式电力变压器的典型结构：

```text
Grid 10 kV
  -> Series_Injection_Transformer_*
  -> Main_Line_Frequency_Transformer
  -> 400 V LV bus
  -> LV_Load

400 V LV bus
  -> Energy_Filter_*
  -> Energy_Extraction_VSC
  -> DC_Link_Capacitor

DC_Link_Capacitor
  -> Regulation_VSC_phase_*
  -> Series_Injection_Transformer_*
  -> main AC path
```

## 当前 Simulink 物理含义

- 主功率通道：`Grid -> Meas_Primary -> Series_Injection_Transformer_* -> Main_Line_Frequency_Transformer -> Meas_Secondary -> LV_Load`
- 取能换流器：`Meas_Secondary` 的 400 V 低压母线经 `Energy_Filter_*` 接入 `Energy_Extraction_VSC`，用于从低压侧取能并维持直流母线。
- 调控换流器：`Regulation_VSC_phase_1/2/3` 为三相单相 H 桥，共用直流母线，通过 `Series_Injection_Transformer_*` 向主交流通道串联注入补偿电压。
- 直流母线：`Energy_Extraction_VSC` 与 `Regulation_VSC_phase_*` 共用 `DC_Link_Capacitor`，并保留 `DC_Link_Cap_Breaker` 和 `DC_Link_Damping_Resistor` 用于故障/阻尼实验。
- 低压侧故障：`LV_AC_Fault` 并接在 400 V 母线侧，用于 LVRT/FRT 场景。

## 文件修改

- `simulink/build_hpt_switching_model.m`
  - 将并联侧命名改为 `Energy_Extraction_VSC`，明确为取能换流器。
  - 将串联侧命名改为 `Regulation_VSC_phase_*`，明确为调控换流器。
  - 将串联注入变压器命名为 `Series_Injection_Transformer_*`。
  - 将主变压器命名为 `Main_Line_Frequency_Transformer`。
  - 将负载和低压侧故障命名为 `LV_Load`、`LV_AC_Fault`。
  - 将直流母线元件命名为 `DC_Link_Capacitor`、`DC_Link_Cap_Breaker`、`DC_Link_Damping_Resistor`、`Meas_DC_Link_Voltage`。
- `data_collection/run_switching_scenarios.m`
  - 同步批量仿真脚本中的新块名。
- `simulink/test_switching_quick.m`
  - 同步快速测试脚本中的新块名。
- `simulink/validate_switching_model.m`
  - 同步验证脚本中的新块名。

## 验证结果

已重新生成：

```matlab
cd('E:/research_space/Hybrid-power-transformer/simulink')
run('build_hpt_switching_model.m')
```

快速测试通过：

```text
normal: samples=401  Vdc_final=775.66  P1_final=319130.46
3ph fault: samples=401  Vdc_final=1085.15  P1_final=4397759.48
```

已导出当前拓扑布局图：

```text
results/hpt_switching_model_layout.png
```

多场景验证通过：

```text
case       Vdc_mean  Vdc_final  Vdc_max   V2_LL_rms   P1_final   P2_final
normal        786.9      819.8    885.2       379.0   362793.3   354348.7
igbt_sh       769.8      879.7    885.2       379.4   344565.0   336152.9
igbt_se       791.0      872.0    885.2       375.1   357412.2   348583.7
cap           625.3        0.1   1335.4       369.7   337825.0   321607.8
sc_1ph        741.1      513.1    917.6       367.4   469255.0   459777.6
sc_3ph        931.9     1057.5   1264.6       309.5  1857899.1  1908631.2
cascade       772.5      914.9    916.9       376.1   342491.0   334016.6
```

## 仍需改进

当前模型已经表达了 HPT 的取能换流器、调控换流器和串联注入路径，但仍是研究用开关级原型。后续如果要更接近论文级或工程级模型，应继续补充：

- 取能换流器的网侧 PLL、dq 电流内环、Vdc 外环和无功控制。
- 调控换流器的串联注入电压闭环、电流限幅和饱和逻辑。
- 串联注入变压器的漏抗、励磁支路、饱和和损耗。
- 主变压器更完整的三相磁耦合、铁耗和短路阻抗参数。
- 故障穿越期间的协调控制：VdcMin/VdcMax/I2Max/recovery time 直接进入在线优化或 PPO/DRL 奖励。
