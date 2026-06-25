# 整改变更报告（2026-06-22, frt-v1 → frt-v2）

> 配套审计：[AUDIT_2026-06-22.md](AUDIT_2026-06-22.md)。**整改未产生任何新的通过率**——所有 frt-v1 成绩
> 标失效并迁移，frt-v2 成绩 **PENDING**（须执行下方重训/重验命令）。无伪造结果；未运行的实验明确标 PENDING。

---

## 1. 本次已完成（代码级，已验证）

| 步 | 项 | 级 | 状态 | 验证 |
|----|----|----|------|------|
| A | 审计清单 + 影响范围 + 失效结果 | — | ✅ | `docs/AUDIT_2026-06-22.md` |
| B | `src/hpt_frt/common/pu.py` 单一事实源（基值/dq 功率/峰RMS 基/换算） | 🔴一 | ✅ | `python src/hpt_frt/common/pu.py` 全 ~0；`tests/test_pu.py` |
| B | `lab/simulink/pu_params.m`（MATLAB 镜像，含 frt-v2 峰值电流基 `I_dq_base_peak`） | 🔴一 | ✅ | 与 pu.py 数值一致 |
| B | network `config`/`hpt_interface` 改为从 `pu` 派生（iq=0.3→120kvar 锁死） | 🔴一 | ✅ | `tests`、smoke |
| C | `tests/`：pu / sequence / frt_envelope / metrics / scenario_usage / train_deploy_interface | — | ✅ | **22 passed** |
| D | `src/hpt_frt/common/frt_v2.py`：版本化判据（真时间向量、包络 connect、含 id 的 limit + 峰值基、时变 HVRT、full-domain Vdc + I2≤3pu、独立 5ms response） | 🔴C1-3,H3-4 | ✅(Py) | `tests/test_metrics.py` 逐判据通过/失败 |
| D | `src/hpt_frt/device/frt_env_v2.py`：真 3 维动作 `[iq,mse_d,mse_q]` + 去特权在线 one-hot | 🟠H1,H2 | ✅(接口) | `tests/test_train_deploy_interface.py` |
| E | OpenDSS `2ph_g` 改共点 LLG（原为两独立 SLG） | 🟡M4 | ✅ | smoke：Vp0.40/Vn0.257 收敛 |
| G | 旧 frt-v1 结果迁移 `lab/results/legacy_pre_audit/`（45 文件 + 失效 README） | — | ✅ | 目录已建 |
| G | README/CONTROL_MODES/PROJECT_OVERVIEW/report.md 顶部加 **frt-v1 失效声明**；停用「国标合规率/+37.8pp/系统层不需要协调学习」 | ⚪ | ✅ | 4 文件 banner |
| C | `pyproject.toml` 含 `hpt_frt.common`（`pip install -e .` 可导入） | — | ✅ | import 验证 |

## 2. 修正前 → 修正后（关键差异）

| 项 | frt-v1（前） | frt-v2（后） |
|----|------|------|
| iq=0.3 物理量 | OpenDSS 120kvar，但 MATLAB limit 用 /173.2(RMS) 对峰值 dq → √2 混用 | 单一源 pu.py：0.3=120kvar=173.2Arms=244.9Apeak；峰值 dq 用 `I_sys_peak` 归一 |
| Simulink 时间 | `linspace(0,Tsim,N)` 猜测（变步长失真） | frt_v2 取真实 `tout`（Py 已实现；MATLAB 重写 PENDING） |
| connect | `LVflt>=tV−0.07`（混稳态 + 标定残压参照） | GB/T 电压-时间包络全窗口（`lvrt_lower_env`/`hvrt_upper_env`） |
| limit | 仅 iq，且峰/RMS 混 | `max(峰值相电流, sqrt(id²+iq²))/I_sys_peak ≤ 0.35` |
| HVRT connect | 静态 `V≤1.35` | 时变上界 1.3@≤500ms / 1.2@≤1s / 1.1 |
| survive | 仅 Vdc，窗口非全域 | 全域 Vdc∈[0.75,1.25] + I2≤3pu（规范判据5 补上） |
| 动作 | 名义 4 维（退化 i_d） | 真 3 维 `[iq,mse_d,mse_q]` |
| 训练 obs | 故障 one-hot 用场景标签（特权） | 在线 (V2p,V2n) 分类（去特权） |
| 故障标定 | mode 4（dq 控制器撑过后的电压） | **PENDING**：改 Mode 0/no-HLC（见 §3） |
| 2ph_g | 两独立 SLG | 共点 LLG |

## 3. PENDING（需算力/MATLAB；给可执行命令与精确补丁）

> 这些**未运行**，因此**不得给出 frt-v2 通过率**。命令在仓库根、`.venv` 下执行；先
> `set KMP_DUPLICATE_LIB_OK=TRUE & set MKL_THREADING_LAYER=SEQUENTIAL`。

**P1 🔴 MATLAB criteria → frt-v2 重写 + 全 320 重验**（影响所有开关级成绩）
- 改 `lab/simulink/validate_mode_full.m`：① 时间用 `o.tout`（不用 linspace）；② `criteria/hvrt_criteria` 改用 `lab/simulink/pu_params.m` 的 `I_dq_base_peak` 归一 + 查 `sqrt(id²+iq²)` 与三相峰值；③ connect 用 frt_v2 同款包络；④ HVRT 时变上界；⑤ survive 全域 + I2；⑥ 标定改 Mode 0/no-HLC（下条）。
- 重验（每模式、每故障类型，~数十分钟/模式）：
  ```matlab
  cd lab/simulink
  for ft = ["sym3ph","1ph_g","2ph","2ph_g","hvrt"]
    validate_mode_full(12, ft)   % Mode 5（主方法）
    validate_mode_full(14, ft)   % Mode 6
    validate_mode_full(7,  ft); validate_mode_full(8, ft)   % 基线 Mode1/2
  end
  ```
  产物 → `lab/results/frt320_m*_*`（标 `metrics_version=frt-v2`）。

**P2 🔴 故障标定改 Mode 0/no-HLC**（影响深度标签 → 全部结果）
- `validate_mode_full.m` 与 `lab/simulink/run_spotcheck.m` 的 `calib_emf/calib_rfault` 把 `set_param([M '/mode'],'Value','4')` 改为 no-HLC（mode 10 固定设定值 + iq_ref/mse_d/mse_q=0，使装置零注入）；先验证 mode 10 确实零注入再用。保存 (目标残压, 实测正序, 误差, Rfault)；误差超限场景标 `unreachable`，不按目标标签计数。

**P3 🟠 frt-v2 接口重训**（影响 Mode 3/5 模型与成绩）
- 用 `HPTFRTEnvV2`（3 维 + 去特权）重训 4 专家与单一 SAC，≥5 随机种子，报均值±标准差、总参数量/步数/时间：
  ```bash
  # 需把 train_experts.py / train_frt_sac.py 的 env 换成 frt_env_v2.HPTFRTEnvV2（一行）
  .venv/Scripts/python.exe src/hpt_frt/device/train_experts.py
  .venv/Scripts/python.exe src/hpt_frt/device/train_seeds.py
  ```
- 两套公平实验：(a) 等总交互步数 (b) 等单策略步数（单一 SAC vs 多专家）。

**P4 🟠 Mode 2 命名/实现**：要么实现真一步预测优化（状态预测+目标+有限时域），要么把 `mpc_prior` 文档/标签改「解析约束控制律」。当前仅 docstring 标注，PENDING 决策。

**P5 🟡 场景治理**：①设计/验证/OOD 三集分离 + 固定种子 + 存清单；②LVRT 含标准边界档（0.2pu/625ms）；③`T_sim` 覆盖完整恢复（勿截 1.2s）；④CSV 装饰字段（Rg/Lg/P_load/Q_load/pf/trans_resistance/recover）**送入模型或删除**（`tests/test_scenario_usage.py` 已守门，新增未用字段会失败）；⑤Δ-Yg 不可达不对称残压去重/单独报告。

**P6 🟡 网络层**：①串联补偿对 LV 负荷/MV 取能/DC 功率平衡反馈回网络（当前串联仅本地）；②FIDVR 加感应电机/动态负荷（现仅源压斜坡，勿称完整 FIDVR）；③硬门控 vs 滞环门控分别整跑（report 已分 raw/hyst，确保不混报）；④10 例 L1 抽查保存对应 `scenario_id`/三相相量/时长/映射误差。

**P7 🟡 训练 ODE**：Vdc 动态显式含 Cdc/并联取能/串联注入/负荷/损耗的量纲一致功率平衡；恢复/负荷/时长进动态方程；建拟合点 vs 独立验证点数据集报误差分布。

**P8 🟡 Simulink**：powergui/求解器与「ode23tb EMT」表述核对；20/10/5µs 步长敏感性；加恒阻抗/恒功率/感应电机(ZIP) 三类负荷由场景表驱动；门控状态**直接记录**（勿事后重建当真实内部态）。

## 4. 已运行的测试
- `pytest tests/` → **22 passed**（pu 5 / sequence 3 / frt_envelope 3 / metrics 6 / scenario_usage 2 / train_deploy_interface 4，本会话计数含部分合并）。
- `python src/hpt_frt/common/pu.py` 自检全 ~0（含 dq 功率=120kVAr、峰/RMS 基）。
- OpenDSS 2ph_g 共点 LLG smoke（收敛、Vn>0）。
- 网络 `run_exp_B_multi_hpt.py debug` 仍可跑（重构后路径正确）——但其**通过率为 frt-v1-phasor，已降级 PENDING**。

## 5. 验收条件状态（用户 §九）
1. Python 测试全部通过 — ✅ 22 passed
2. `pip install -e .` 正常导入 — ✅（含 `hpt_frt.common`）
3. 一指令在 ODE/Simulink/OpenDSS 单位一致 — ✅ 命令/基值层（pu 单一源 + 三层换算 ≤2% 一致：OpenDSS 已验证 120kvar；MATLAB 基值镜像就位）；**MATLAB criteria 的 /173.2 归一仍待 P1 改用峰值基**
4. 五判据人工通过/失败单测 — ✅ `test_metrics.py`
5. CSV 字段被读取或删除 — ⚠️ 守门测试已加（`test_scenario_usage`）；feed-or-drop 本身 **PENDING(P5)**
6. Mode 5 不读真实标签/时刻/未来时长 — ✅ 接口（`frt_env_v2`+测试）；**已部署模型仍 legacy，重训 PENDING(P3)**
7. 每类故障一个 Mode 0 标定 + 一个控制器案例 — **PENDING(P1/P2，MATLAB)**
8. 输出前后差异/未解决/已测/未跑耗时实验 — ✅ 本报告
9. 未完成全量重训/320 验证不得给新通过率 — ✅ 全程遵守（无新成绩）

## 6. 仍未解决（需决策）
- P4 Mode 2 是否实现真 MPC（影响命名与一个基线的合法性）。
- P7 ODE 是否升级为动态功率平衡（大改训练环境 → 触发全面重训）。
- Δ-Yg 不对称残压不可达（M3）：320 名义多样性偏低是物理事实，需在论文口径里去重报告，非代码能消。

---

## 7. Round-2 code-level fixes (2026-06-22, no retraining / no full-320)

All verified; **no new pass rate produced** (frt-v2 numbers remain PENDING P1/P3).

| # | Fix | Status | Verify |
|---|-----|--------|--------|
| 1 | frt_v2 LVRT envelope = **one explicit boundary = residual** (removed stacked 0.05+0.02≈residual-0.07); separate small `solver_tol=1e-3` (float guard only, configurable) | ✅ | `test_frt_envelope` + `test_metrics::test_connect_boundary_is_residual_not_minus_007` |
| 2 | frt_v2 **PASS/FAIL/NOT_EVALUATED** status; missing iq/current/Vdc/I2 → criterion NOT_EVALUATED → `frt_pass=None`; insufficient recovery window → NOT_EVALUATED; structural input validation (length/finite/monotonic/empty-window) → ValueError | ✅ | `test_metrics` (8 tests) |
| 4 | `frt_env_v2` **OnlineFaultDetector**: latches detected onset from measured (V2p,V2n), elapsed from detected onset, resets on recovery; obs reads **no** true t_fault/type/duration/residual | ✅ | `test_train_deploy_interface::test_detector_elapsed_independent_of_true_onset` + `test_obs_identical_for_same_measurement_different_true_tfault` |
| 5 | **Proper package**: package-relative imports throughout; `pip install -e .`; `python -m hpt_frt.…`; package-data `network/ieee33.dss`; **conftest path injection removed**; export scripts guarded under `main()`; `sb3_contrib` lazy | ✅ | `test_packaging` (subprocess install-free imports + env step) |
| 6 | Pure `common/sequence.py` (no OpenDSS); `network/sequence` imports it; pytest process never loads the dss backend (subprocess for network) → **clean exit, 0xe0465043 gone** | ✅ | `test_sequence::test_pure_sequence_does_not_import_opendssdirect`; pytest exit 0 |
| 3 | **pu_params wired into ALL active MATLAB**: no bare `173.2`/`326.6`/`0.35*173.2` left; embedded HLC `Imax`/`Vnom` interpolated from `pu_params` at build time; criteria divisor → **correct peak base** `I_dq_base_peak`; `pu_selfcheck.m` confirms MATLAB==Python + 120 kVAr. ⚠️ The HLC command-base **peak-redesign** (Imax conflates scale/limit/peak-RMS; correct = I_sys_peak) is a controller redesign → **deferred to P3** (value preserved, single-sourced, flagged) | ✅(wire)/PENDING(redesign) | `pu_selfcheck` all OK; `test_pu::test_matlab_python_pu_constants_match` |
| 7 | Legacy JSONs → `legacy_pre_audit/`; `gen_p1_figs` disabled (raises unless `HPT_ALLOW_LEGACY_FIGS=1`); `controller_registry.py` + `controller_modes.m` → `validity='pending-frt-v2'`, `score=None` (legacy in `legacy_frt_v1_score`); table captions added; `metrics_spec.py`→`frt_v2.py` ref fixed | ✅ | `test_registry` (3 tests) |
| — | Python `fill_spotcheck.IBASE` 173.2 → `I_SYS_PEAK`; OpenDSS 2ph_g header comment corrected | ✅ | import smoke |

**Verification run:** `pytest tests/ -p no:cacheprovider` → **34 passed, exit 0** (no backend crash); AST/py_compile scan of all modules → OK; grep for hard-coded current bases (Python+MATLAB) → none outside `pu.py`/`pu_params.m`; grep for live legacy scores → none (only `legacy_frt_v1_score=`); `pu_selfcheck.m` → MATLAB==Python + 120 kVAr OK.

**Still PENDING (unchanged, compute/MATLAB):** P1 (frt-v2 MATLAB criteria full rewrite — connect envelope, HVRT, I2, real `tout` — + 320 re-validation), P2 (Mode-0 calibration), P3 (3-D/de-privileged retrain + HLC peak-base command redesign), P4–P8 (Mode-2 MPC, scenario split/feed-or-drop, ODE power balance, Simulink loads/steps). No frt-v2 score may be quoted until P1/P3 run.

---

## 8. Round-3 integration fixes (2026-06-22, frt-v2 wired into production paths; no retrain/no 320)

Connects the frt-v2 code to the production training/validation/deployment paths. **No new pass rate.**
Verification: `pytest tests -q` → **63 passed**; `pu_selfcheck.m` + `frt_v2_hlc_selftest.m` → ALL OK
(MATLAB); guard fires `HPT:PENDING_FRT_V2`; AST/compile/subprocess-imports clean.

| # | Integration fix | Status | Verify |
|---|-----------------|--------|--------|
| 1 | `device/frt_metrics.py` = ADAPTER around `common.frt_v2.evaluate` (legacy bool formulas removed). `run_episode` records real t/V1/V2/Vdc/iq; missing current+I2 stay **None** (not 0) → ODE `limit`/`survive` NOT_EVALUATED → `frt_pass=None` (ODE can't certify). `evaluate_frt` counts PASS/FAIL/NOT_EVALUATED separately, never `int(None)`, reports `n_incomplete`/`frt_pass_pct`(complete-only)/`partial_proxy_pct`(selection). 5 train scripts select on the proxy. | ✅ | `test_device_pipeline` (6) |
| 2 | `network/metrics.py` QUARANTINED → `screen_*`/`screen_pass`; `frt_pass` is a `None` tombstone (static snapshot never certifies); `metrics_version='frt-v1-phasor-screening'`+`evaluation_scope`; non-converged a separate mandatory `convergence_pct`/`n_nonconverged`. 5 callers renamed. | ✅ | `test_network_screening` (4) |
| 3 | MATLAB guards: `frt_v2_guard.m` (fail-fast `HPT:PENDING_FRT_V2` unless `HPT_ALLOW_LEGACY_FRT=1` → output forced to `legacy_pre_audit`), `assert_metrics_version.m`; `validate_mode_full.m`+`run_spotcheck.m` guarded + tag `metrics_version='frt-v1-INVALIDATED'` in every MAT. | ✅ | `test_matlab_guards` (5) |
| 4 | `frt_v2_hlc.m` codegen-compatible ONLINE detector (latches measured onset, elapsed from detected onset; NO true tf/fdur/type) + de-privileged 20-D obs builder. Diagnostic: identical measured history, different true onset → identical obs (max diff 2e-16). | ✅ | `frt_v2_hlc_selftest.m`; `test_train_deploy_interface` |
| 5 | True 3-D actor: `frt_env_v2` obs **explicit 20-D** (`OBS_DIM_V2`, dropped dummy 4th last-action), action 3-D; `export_sac_actor.export_actor` reads n_obs/n_act from the model, rejects non-20/3 unless `legacy=True` (labelled path); `frt_v2_hlc('actor')` consumes 3-output mu. | ✅ | `test_actor_contract` (5) |
| 6 | Current base: `pu.py`/`pu_params.m` add `I_action_peak`(=I_sys_peak), `I_converter_peak`(=I_pe_peak); `clip_converter_current` (combined-vector clip, no 2nd 0.3). `pu_selfcheck.m`+`pu.self_check` extended to action→amp→kVAr→pu round trip (iq=0.3→244.95 A→120 kVAr) + clip. `frt_v2_hlc('iq_cmd'/'clip')` use them. | ✅ | `test_current_base` (5); MATLAB selftest |
| 7 | `frt_v2` precedence: any mandatory FAIL → `frt_pass=False` FIRST; else NOT_EVALUATED → None; else True. | ✅ | `test_metrics::test_status_precedence_fail_beats_missing` |
| 8 | `frt_v2.response_metrics`: explicit onset/baseline/settled-target/tolerance-band/dwell → rise+settling time+not-settled+insufficient-resolution. NEVER in `frt_pass`. | ✅ | `test_metrics::test_response_metric_*` |
| 9 | Doc governance: `Historical frt-v1 results — INVALIDATED` headings above tables; `✅ VALID`/`valid-hardgate`/`active,VALID` → `PENDING frt-v2`; `+37.8pp`/superiority/GB-T-compliance prose marked INVALIDATED. Enforced by a test. | ✅ | `test_docs_governance` (4) |
| 10 | Migration inventory `docs/MIGRATION_INVENTORY_2026-06-22.md` (102 renames / 220 adds / 156 deletes resolved); caches removed (gitignored), `.codex/` added to `.gitignore`; index untouched (no commit). | ✅ | inventory file |

**Remaining production callers of frt-v1 code:** none in Python (`frt_criteria` gone; network is `screen_*`).
The MATLAB **build scripts'** embedded HLC still carry the frt-v1 command path (`Imax=I_pe_rms`,
`0.3*Imax` reactive-priority reserve, 4-D action, true tf/fdur obs) — these construct the **legacy
deployed model** and are now (a) superseded by `frt_v2_hlc.m` for the frt-v2 contract and (b) only
reachable for results through `frt_v2_guard` (PENDING_FRT_V2). Swapping the embedded HLC to
`frt_v2_hlc.m` changes commanded current and REQUIRES the P3 retrain + P1 re-validation → deferred.

**Still PENDING (compute/MATLAB):** P1 (MATLAB criteria full frt-v2 rewrite + 320 re-validation),
P2 (Mode-0 calibration), P3 (frt-v2 retrain on `HPTFRTEnvV2` + swap embedded HLC to `frt_v2_hlc.m`),
P4–P8. No frt-v2 score may be quoted until P1/P3 run.

---

## 9. Round-4 production-chain integration (2026-06-22; no retrain / no full-320 / no new pass rate)

112 pytest pass; MATLAB pu_selfcheck + frt_v2_hlc_selftest OK; checkcode 0 issues; guard fires.

| § | Fix | Production chain touched | Test |
|---|-----|--------------------------|------|
| A | `fill_spotcheck.py` REFUSES non-`frt-v2` MATs (`LegacyMatRefused`), reads REAL time (no linspace), recomputes criteria via `frt_v2.evaluate` (ignores `crit.frt`); 20 legacy MATs moved to `simulink_cases/legacy_pre_audit/`; `--legacy` gated by `HPT_ALLOW_LEGACY_FRT`, no active CSV/fig7/PASS | network analysis | `test_spotcheck_governance` (6) |
| B | `HPTFRTEnvV2` trips (and connect-reward) on the VERSIONED `frt_v2` envelope (residual hold, time-varying HVRT) via overridable `_lvrt_floor/_hvrt_ceiling/_trip_tol`; legacy `residual-0.05`/`1.32` quarantined in the base class; `solver_tol` numeric-only | device env | `test_env_envelope_unification` (7) |
| C | All 5 train entrypoints default to `HPTFRTEnvV2` (20-D/3-D) via `train_common.select_env`; new `HPTFRTResidualEnvV2`; `--legacy` -> legacy env + legacy namespace; JSON carry metrics_version/env_contract/obs_dim/act_dim/seed/scenario_split; `assert_fresh_contract` blocks 21-D/4-D | training | `test_training_contract` (10) |
| D | `frt_metrics`: no swallowed ValueError (classification dict + reason); complete = ALL 5 evaluated; decided_fail+missing is incomplete (not complete); frt_pass_pct over complete only; partial_proxy denom = all rolled-out; unevaluable surfaced | device eval | `test_metric_completeness` (5) |
| E | reactive = MINIMUM-SUPPORT (project-defined, documented in FRT_SPEC): LVRT iq>=ref-tol / HVRT iq<=ref+tol; response delay + sustained dwell + max-under-support + wrong-sign immediate FAIL; over-injection bounded by LIMIT not here; NOT whole-window mean | criteria | `test_reactive_criterion` (8) |
| F | 5 ms `response_metrics` actually CALLED in device eval (`_response_of`, explicit iq reference target — not median); emits response_status/rise/settling/meets_5ms; NOT_EVALUATED on coarse-time/no-event; aggregated separately; MATLAB validator field plan documented; non-uniform-time test | device eval | `test_response_wiring` (6) |
| G | README headline = "frt-v2 PENDING; 当前无有效通过率"; region-aware doc test (strong conclusions must be in a legacy section, inline PENDING insufficient); result-file governance test (no unversioned MAT in active dirs); broken path `INVALIDATED-...ate_mode_full.m` fixed | docs | `test_docs_governance` (8) + `test_result_governance` (4) |
| H | `.gitignore` += `*.slxc`/`.codex/`; slprj + caches removed (regenerable); MIGRATION_INVENTORY reconciled with git status; grouped commit plan; index untouched (4 pre-existing staged renames only) | repo | inventory file |

**Production training env = `HPTFRTEnvV2` / `HPTFRTResidualEnvV2`: observation_dim=20, action_dim=3, env_contract='frt-v2' (verified by 5-step smoke).** Legacy `HPTFRTEnv` (21-D/4-D) reachable only via `--legacy`.

**Still PENDING (unchanged):** P1 (MATLAB criteria frt-v2 rewrite incl. the response field + 320 re-validation), P2 (Mode-0 calibration), P3 (retrain on the V2 envs + swap embedded HLC to frt_v2_hlc.m), P4-P8. No frt-v2 pass rate may be quoted until P1/P3 run.
