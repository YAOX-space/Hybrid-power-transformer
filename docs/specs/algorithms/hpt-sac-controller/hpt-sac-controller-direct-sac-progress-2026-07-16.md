# HPT Direct SAC 进展报告 - 2026-07-16

## 本轮完成内容

1. 修正了 SAC energy 动作的物理接口。
   - 旧接口：`act[3:4] = m_energy_d/m_energy_q`，直接作为 TPFBVSC 三相 PWM 调制量。
   - 新接口：`act[3:4] = i_energy_d_ref_pu/i_energy_q_ref_pu`，作为归一化 dq 电流参考。
   - Simulink 中由 `HPTSACController` 内部 dq 电流环把该参考量转换成三相 TPFBVSC PWM 调制量。

2. 新增取能桥 teacher trace 采集脚本。
   - 文件：`version_2/simulink/collect_hpt_v2_sac_energy_teacher_traces.m`
   - 数据来源：常规 `EnergyController` 的 Vdc 外环和 dq 电流环。
   - quick trace 已跑通，生成 520 个 switch-level teacher 样本。
   - 最新 CSV：`lab/results/hpt_v2_sac_energy_teacher_traces/energy_teacher_traces_20260716_005433.csv`

3. 扩展 BC warm-start，使其可以读取 energy teacher trace。
   - 文件：`version_2/sac/pretrain_hpt_actor_bc.py`
   - 新参数：
     - `--energy-teacher-trace-csv`
     - `--energy-teacher-trace-repeat`
   - trace 中 `target_action_03 = id_ref / hpt_energy_id_max`，`target_action_04 = iq_ref / hpt_energy_id_max`。

4. 修正 raw smoke correction 的观测窗口。
   - 旧逻辑使用 `obs_vpu_mean`，在 fault case 中更偏向尾段/恢复段，不能代表失败窗口。
   - 新逻辑使用 `lv_mean / 207` 和 `vdc_min / 800` 构造 correction state，更贴近 fault-window 失败原因。

5. 重新生成两个 switch-level Simulink 模型。
   - `version_2/simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
   - `version_2/simulink/topology2/hpt_v2_topology2_paper.slx`

## 关键验证结果

### Energy fixed-command sweep

脚本：`version_2/simulink/sweep_hpt_v2_sac_energy_response.m`

最新结果：

- CSV：`lab/results/hpt_v2_sac_energy_sweep/hpt_v2_sac_energy_sweep_20260716_005721.csv`
- 所有固定 energy current-reference 命令下，VdcMin 保持在约 673 V 以上。
- 之前 raw modulation 接口会导致 Vdc 接近 0 或变成负值；本轮已经消除这个主要崩溃模式。

结论：把 energy action 改成 dq current reference 是正确方向。

### 新 SAC 候选训练

训练了 3 个候选：

1. `hpt_voltage_sac_energy_trace_smoke.zip`
   - 用于验证 energy trace 数据管线。
   - 样本数：840
   - energy teacher samples：520

2. `hpt_voltage_sac_currentref_bc_candidate.zip`
   - 样本数：80,291
   - switch trace samples：36,096
   - energy teacher samples：16,640
   - action MSE：`[1.44e-3, 3.98e-4, 1.41e-2, 3.63e-4]`

3. `hpt_voltage_sac_currentref_bc_windowcorr_candidate.zip`
   - 当前导出到 Simulink 的候选。
   - 样本数：121,251
   - switch trace samples：36,096
   - raw smoke correction samples：40,960
   - energy teacher samples：16,640
   - action MSE：`[3.78e-4, 1.00e-4, 2.87e-3, 3.05e-5]`

### 最新 raw guard=0 switch-level smoke

脚本：`version_2/simulink/eval_hpt_v2_sac_raw_switchlevel_smoke.m`

最新结果：

- CSV：`lab/results/hpt_v2_sac_raw_switchlevel_smoke/raw_sac_switchlevel_smoke_20260716_012512.csv`
- `hpt_sac_guard_enable = 0`
- 当前通过 3 / 10 个 smoke cases：
  - topology1 steady 10 kV
  - topology1 steady 11 kV
  - topology2 steady 10 kV
- 最小 Vdc：约 559 V。

对比本轮之前：

- 之前 raw energy modulation 会出现 Vdc 接近 0 或负值。
- 当前已经没有系统性 DC-link 崩溃。
- 失败模式主要变成电压调节幅值/相位不够，以及 topology2 dynamic fault 下 Vdc 支撑不足。

## 还没有完成

1. 还没有一个统一 actor 通过全部 raw guard=0 smoke gate。
2. topology1 在 9 kV steady 和 sag fault-window 中仍偏低。
3. topology2 在 9 kV/11 kV steady 中仍不稳，11 kV case 还有 unbalance/Vdc 窗口问题。
4. topology2 dynamic sag/swell fault 仍未通过，尤其 swell case 的 VdcMin 约 559 V，低于目标窗口。
5. 还没有进入 expanded matrix 最终验证；当前只完成了 smoke 层面的迭代。

## 下一步建议

1. 分离 steady actor 和 dynamic actor 的 teacher 权重。
   - 当前同一个 BC 训练集里 steady、dynamic、raw correction 混在一起，topology2 11 kV steady 被 fault correction 拉偏。
   - 建议 dynamic actor 只用于 fault transition，steady actor 使用独立 steady trace/correction。

2. 对 topology2 dynamic 单独增加 switch-level trace。
   - 当前 dynamic 失败主要不是 energy 接口，而是 series regulating bridge 相位和幅值不够稳。
   - 需要采集更密的 topology2 sag/swell fault-window obs -> action 数据。

3. 对 Vdc 支撑加入专门的 topology2 HVRT teacher。
   - 最新 topology2 swell raw case：LV 还可接近窗口，但 Vdc 下冲明显。
   - energy current-ref 应该在 HVRT/fault edge 更积极地支撑 DC-link。

4. 在 smoke 通过之前，不进入 8 小时 SAC/MOPO 长训。
   - 当前瓶颈是 switch-level action semantics 和 data alignment。
   - 长训前必须先让 BC/teacher 数据在 smoke gate 上有稳定通过趋势。
