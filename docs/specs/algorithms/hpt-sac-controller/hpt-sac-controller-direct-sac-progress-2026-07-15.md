# HPT Direct SAC Progress Report - 2026-07-15

## 本轮已完成

1. 明确区分了两条验证路径：
   - `hpt_sac_guard_enable = 1`: guarded smoke，只能作为 teacher / baseline。
   - `hpt_sac_guard_enable = 0`: final raw actor path，才是最终 direct SAC 候选。

2. 新增 raw switch-level 诊断脚本：
   - `version_2/simulink/eval_hpt_v2_sac_raw_switchlevel_smoke.m`
   - 覆盖 topology1/topology2 的 steady 9000/10000/11000 V，以及 sag 0.90 / swell 1.10 fault-transition。
   - 该脚本不做强制 assert，而是输出 pass/fail reason，作为 final promotion gate 的前置诊断。

3. 新增 switch-level guarded teacher trace 采集脚本：
   - `version_2/simulink/collect_hpt_v2_sac_guard_teacher_traces.m`
   - 输出 `obs_01..obs_24 -> action_01..action_04` 的真实 Simulink trace。
   - 本轮采集到 1128 个 2 ms 采样点：
     - topology1 steady: 108
     - topology1 fault: 456
     - topology2 steady: 108
     - topology2 fault: 456

4. 扩展了 Python BC warm-start：
   - 支持 `--teacher-source execution_guard`。
   - 支持 `expanded_fault_transition` curriculum。
   - 支持 `--switch-trace-csv`，把 Simulink guarded trace 直接加入训练集。
   - 支持 topology2 phase-equivalent label，把 guarded hidden phase shift 转成 raw actor 可表达的 `m_reg_d/m_reg_q`。
   - 支持 `--raw-smoke-correction-csv`，从 raw failed states 生成 recovery correction samples。

5. 发现并修正了一个重要数据读取问题：
   - Simulink `HPTSAC_obs` / `HPTSAC_action` 是 `24 x 1 x N` 和 `4 x 1 x N`。
   - 新脚本现在会 `squeeze + reshape` 成 `nChannels x N`，避免误把时间长度看成 1。

6. topology2 打开了 raw actor 的 q-axis 注入通道：
   - `hpt_sac_reg_q_gain = 1.0`
   - 原因：topology2 guarded dynamic path 中有隐藏相位补偿 `inj_phase + 0.55`，最终 `guard=0` 时只能通过 `m_reg_q` 表达等效相位。

## 已训练的候选 actor

1. `hpt_voltage_sac_guard_teacher_expanded_bc_v0.zip`
   - curriculum: `expanded_fault_transition`
   - teacher: proxy execution-guard labels
   - samples: 40716
   - action MSE: `[3.97e-05, 7.82e-06, 7.45e-07, 1.47e-06]`

2. `hpt_voltage_sac_switch_trace_bc_v0.zip`
   - 加入 Simulink guarded trace。
   - samples: 112908
   - switch trace augmented samples: 72192
   - action MSE: `[1.10e-05, 2.17e-05, 5.97e-05, 6.99e-07]`

3. `hpt_voltage_sac_switch_trace_phase_bc_v0.zip`
   - 加入 topology2 phase-equivalent labels。
   - samples: 185100
   - switch trace augmented samples: 144384
   - action MSE: `[9.58e-06, 1.78e-05, 7.11e-05, 2.24e-07]`

4. `hpt_voltage_sac_switch_trace_energy_full_v0.zip`
   - energy action range 扩大到 `[-0.95, 0.95]`。
   - 加入 raw smoke correction samples。
   - samples: 226060
   - switch trace augmented samples: 144384
   - raw smoke correction samples: 40960
   - action MSE: `[4.11e-05, 5.12e-06, 1.88e-05, 5.49e-06]`

## 当前最好结果

### Guarded smoke

guarded smoke 仍然能过，说明物理开关级模型和基本控制通道是可运行的：

- `version_2/simulink/test_hpt_v2_sac_switchlevel_voltage_regulation.m`
- `version_2/simulink/test_hpt_v2_sac_fault_transition.m`

但 guarded smoke 不是最终成果，因为它仍允许执行层覆盖 actor 动作。

### Raw `guard=0`, regulating SAC only

当 `hpt_sac_guard_enable = 0` 且 energy converter 仍用传统 Vdc loop 时，raw actor 有部分改善但没有通过：

- topology1 11000 V steady 一度通过。
- topology2 9000/10000 V steady 有过通过或接近通过。
- topology2 fault-window 电压可接近目标，但 Vdc / recovery 仍失败。

结论：regulating bridge 的 direct actor 有进展，但还没有 strong success。

### Raw `guard=0`, regulating + energy SAC

当把 `hpt_sac_energy_enable = 1` 也打开，结果明显变差：

- topology1 steady LV RMS 降到约 153-197 V，Vdc 大量低于窗口。
- topology2 steady / fault 中 Vdc 接近 0 或为负。

这说明当前 `m_energy_d/m_energy_q -> physical TPFBVSC` 的 direct modulation 接口还没有校准好，不能直接交给 SAC。

## 关键失败原因

1. proxy 训练分布和 switch-level 观测分布不一致。
   - steady 场景中 Simulink 的 `fault_active/recovery_active` 会被置位。
   - `vdcpu` 分布明显偏离 proxy 假设。
   - 只在 proxy obs 上低 MSE，不代表 switch-level obs 上正确。

2. topology2 动态控制需要相位自由度。
   - guarded path 隐含 `inj_phase + 0.55`。
   - final raw path 不能再使用这个 hidden rule。
   - 必须由 actor 的 `m_reg_q` 内化等效相位。

3. 取能桥 direct modulation 尚未校准。
   - 固定 energy command sweep 显示，大多数 `m_energy_d/q` 固定值会让 Vdc 接近 0。
   - 这不是普通 SAC 训练能直接解决的问题，必须先弄清 energy bridge 的物理控制接口、符号和低层闭环结构。

## 尚未完成

1. 还没有一个 `hpt_sac_guard_enable = 0` 的统一 actor 通过 smoke gate。
2. 还没有完成真正双桥 direct SAC：regulating bridge + energy bridge 都由 SAC 稳定控制。
3. 还没有完成 expanded matrix：
   - 0.2/0.5/0.75/0.85/0.9 pu LVRT
   - 1.1/1.2/1.25/1.3 pu HVRT
   - asymmetric faults
   - weak-grid cases
   - DC-link IC variation
4. 还没有训练 TD3+BC / IQL / CQL offline baselines。
5. 还没有训练 SAC-MOPO / MOReL learned-proxy uncertainty 版本。

## 下一步

1. 先校准 energy converter action interface。
   - 目标不是继续盲训，而是确定 `m_energy_d/m_energy_q` 的物理含义和符号。
   - 需要把 conventional Vdc loop 的有效输出映射成 actor 可学习的目标，或重新定义 energy action 为更合理的电流/功率参考。

2. 保留 regulating actor 的 switch-trace BC 路线。
   - 这条路线已证明能把 guarded behavior 部分内化。
   - topology2 的 q-axis phase-equivalent label 是必要的。

3. 在 energy interface 校准后，再重新采集 switch-level teacher traces。
   - 必须包含 Vdc low / recovery states。
   - 必须记录 conventional energy loop 的目标和实际 bridge command。

4. 之后再训练 offline baseline。
   - 优先 TD3+BC 和 IQL。
   - CQL 作为保守对照。

5. 任何最终候选必须通过：
   - `hpt_sac_guard_enable = 0`
   - no execution-layer overwrite
   - switch-level smoke gate
   - expanded validation matrix
