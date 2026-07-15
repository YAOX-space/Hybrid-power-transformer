# HPT Direct SAC Progress Report - 2026-07-15

## 本轮已完成

1. 统一 24-D observation / 4-D action 接口继续保持可用：
   `observation -> actor -> [m_reg_d, m_reg_q, m_energy_d, m_energy_q]`。

2. 两个最终开关级 Simulink 模型均通过 SAC 接口回归：
   - `version_2/simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
   - `version_2/simulink/topology2/hpt_v2_topology2_paper.slx`

3. 稳态 Step4 开关级电压调节验证通过：
   - 结果 CSV: `lab/results/hpt_v2_sac_switchlevel_step4/switchlevel_sac_step4_20260715_221935.csv`
   - topology1 SAC actor:
     - 9000 V: LV RMS 200.035 V, Vdc min 750.640 V
     - 10000 V: LV RMS 204.938 V, Vdc min 753.580 V
     - 11000 V: LV RMS 207.820 V, Vdc min 749.351 V
   - topology2 SAC actor:
     - 9000 V: LV RMS 201.870 V, Vdc min 765.413 V
     - 10000 V: LV RMS 200.729 V, Vdc min 773.917 V
     - 11000 V: LV RMS 203.759 V, Vdc min 722.854 V

4. fault-transition 开关级验证已从诊断模式改为断言模式，并通过：
   - 结果 CSV: `lab/results/hpt_v2_sac_fault_transition/hpt_v2_sac_fault_transition_20260715_221740.csv`
   - topology1 sag 0.90: LV fault 198.936 V, recovery 202.921 V, Vdc min 752.432 V
   - topology1 swell 1.10: LV fault 202.954 V, recovery 202.894 V, Vdc min 752.432 V
   - topology2 sag 0.90: LV fault 201.851 V, recovery 206.739 V, Vdc min 786.874 V
   - topology2 swell 1.10: LV fault 208.512 V, recovery 207.402 V, Vdc min 786.874 V

5. topology2 动态故障路径完成一次物理保护校准：
   - 动态限幅从 0.605 调整为 0.60。
   - topology2 动态模式下加入 conventional-like 电压闭环保护：
     `m_reg_d = clip(20 * (1 - vpu), +/- dynamic_reg_limit)`。
   - topology2 swell/负注入时使用 `inj_phase + 0.55` 的注入相位，贴近原 conventional regulator 的 swell phase。

6. Python 合同测试通过：
   - `tests/test_hpt_voltage_sac_contract.py`
   - `tests/test_hpt_safety_classifier.py`
   - `tests/test_hpt_switch_dataset_builder.py`
   - `tests/test_hpt_learned_proxy.py`
   - `tests/test_hpt_proxy_gap_measurement.py`
   - `tests/test_hpt_experiment_metadata.py`

7. proxy gap 基线已重新生成：
   - 结果目录: `lab/results/hpt_v2_proxy_gap/proxy_gap_20260715_222036`
   - reg table LV RMSE: 0.0471 pu
   - reg linear LV RMSE: 0.1359 pu
   - topology2 reg table LV RMSE: 0.0279 pu
   - energy fit Vdc RMSE: 0.0285 pu

## 重要说明

当前通过的 fault-transition 是 guarded smoke，不是最终成果：

- `hpt_sac_guard_enable = 1` 时，topology1 使用已校准的执行层安全投影。
- `hpt_sac_guard_enable = 1` 时，topology2 动态 fault-transition 使用 conventional-like 执行层保护，避免 actor 在动态故障边沿产生不物理的注入。
- `hpt_sac_guard_enable = 0` 才是最终 direct SAC 路径；除硬件调制限幅外，不允许执行层覆盖 actor 动作。

因此，本轮达到了研究计划里的 minimum success / smoke gate：

- 两个 topology 的最终开关级模型可运行。
- 直接 SAC 通道可接入 PWM/gate 级模型。
- steady sag/swell smoke 通过。
- fault-transition smoke 从失败修到通过。

但还没有达到 strong/final success：

- 还没有证明一个无执行层保护的统一 actor 能单独通过全动态矩阵。
- final promotion gate 必须在 `hpt_sac_guard_enable = 0` 下通过。
- 还没有完成 TD3+BC/IQL/CQL offline baseline。
- 还没有完成 SAC-MOPO/MOReL 与 learned proxy uncertainty penalty 的正式比较。
- 还没有跑 full validation matrix，包括更深 sag、HVRT、更弱电网、非对称故障和 DC-link 初值扰动。

## 下一步

1. 把当前 execution-layer protection 只作为 teacher 生成训练目标，让 SAC actor 内化 topology2 dynamic control law。
2. 扩展 fault-transition 数据集，覆盖 0.2/0.5/0.75/0.85/0.9 pu LVRT、1.1/1.2/1.25/1.3 pu HVRT 和非对称故障。
3. 训练 offline baseline：TD3+BC 和 IQL 优先，CQL 作为保守策略对照。
4. 训练 SAC-MOPO/MOReL，使用 learned proxy uncertainty 避免 SAC exploiting proxy errors。
5. 只有在 `hpt_sac_guard_enable = 0` 下通过 switch-level expanded matrix 的 actor 才能晋级为最终候选。
