# 文件指南 — 工程化布局（2026-06-21 重构）

> 仓库已重构为标准工程布局：Python 源在 `src/hpt_frt/`，MATLAB 开关级实验在 `lab/`，文档在 `docs/`，
> 文献在 `references/`，训练模型在 `data/models/`。图例：✅当前核心 · 🔧辅助/工具 · 📚参考。

## 最小可信研究包（2026-06-25 收口）

**当前 frt-v2 主线 = 以下 active 入口 + authoritative 结果 + 核心文档。** 完整分类清单见
[CLEANUP_INVENTORY_2026-06-25.md](CLEANUP_INVENTORY_2026-06-25.md)。

- **active 评价/分析入口**：
  - MATLAB：`lab/simulink/frt_v2_evaluate.m`（权威五判据）· `frt_v2_full320_switching.m`（忠实全 320）·
    `frt_v2_spotcheck.m`（12 例门禁）· `frt_v2_calibrate.m`（场景标定）· `frt_v2_projected_spotcheck.m`（投影抽查）
  - Python：`src/hpt_frt/common/{frt_v2,pu,sequence}.py` · `src/hpt_frt/device/{frt_env_v2,frt_metrics,
    safety_projection,error_analysis_mi14,plot_p3_convergence,project_offline_check}.py`
- **authoritative 结果**：`lab/results/p3_full320_switching_summary.json` + `p3_full320_sw_mi{14,7}.mat`
  （+ `p3_scenario_faultparams.json`、`calib_*.mat`、`error_analysis_mi14_*`、`projection_*`、收敛图 CSV/PNG）。
- **核心文档**：`README.md` · `FRT_V2_RESULTS_2026-06-23.md` · `FRT_V2_ERROR_ANALYSIS_2026-06-24.md` ·
  `FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md` · `FRT_V2_PROJECTION_SPOTCHECK_2026-06-24.md` ·
  `P3_SAC_CONVERGENCE_NOTE_2026-06-24.md` · `HPT_weekly_group_meeting_20260625.tex`。
- **legacy guard（非 frt-v2 入口，未删除）**：`lab/simulink/validate_mode_full.m`、`run_spotcheck.m`。
- **archive（不参与任何当前 frt-v2 结论）**：`lab/results/archive_2026-06-25/`（旧日志/早期中断 run）、
  `lab/simulink/archive_2026-06-25/`（0 引用诊断脚本）、`lab/results/legacy_pre_{audit,resweep}/`（旧范式）。
  以及历史审计 `docs/{AUDIT,CHANGE_REPORT,MIGRATION_INVENTORY}_2026-06-22.md`（仍被链接，作历史参考，非当前结论）。
- **复现当前图表**（只读已有文件，无 Simulink/无重训）：
  `python -m hpt_frt.device.{plot_p3_convergence,error_analysis_mi14,project_offline_check}`。

```
.
├── README.md                      # 仓库入口
├── pyproject.toml                 # 可安装包 (pip install -e .)  hpt-frt
├── requirements.txt               # 锁定的运行环境(py3.8)
├── .gitignore
├── docs/                          # 全部文档
│   ├── CONTROL_MODES.md           # ★ 控制器模式唯一权威定义 (Mode 0–6, Mode 5=主方法)
│   ├── PROJECT_OVERVIEW.md        # 项目总索引
│   ├── FRT_SPEC.md                # FRT 问题定义/判据规范
│   └── FILE_GUIDE.md              # 本文件
├── references/                    # 文献 PDF + 任务书 (week1–4)
├── data/models/                   # 训练好的 SAC .zip (gitignored)
│   └── sac_{sym,asym,hvrt_sym,hvrt_asym,frt,residual}_*.zip
├── lab/                           # ★ MATLAB 开关级实验台 + 场景 + 已验证结果
│   ├── simulink/                  # *.m / *.slx / sac_*_weights.mat (coder.load)
│   ├── frt_scenarios.csv (+_subset)
│   ├── sac_*_weights.mat          # 导出的权重(export 脚本写这里 + simulink/)
│   └── results/                   # frt320_m7/m8/m12/m14_*, dq_variants, experts_train.json
└── src/hpt_frt/                   # ★ Python 包
    ├── device/                    # Phase-1 装置级 FRT
    └── network/                   # Phase-2 IEEE-33 网络鲁棒性压测
```

## `src/hpt_frt/device/` — Phase-1 装置级（✅）
- 环境：`frt_env.py`(Mode3/5 训练环境)、`residual_env.py`(Mode6)
- 训练：`train_experts.py`(★Mode5 四专家)、`train_residual.py`(Mode6)、`train_frt_sac.py`(Mode3)、`train_ab.py`/`train_seeds.py`(消融/多种子)
- 工具：`controller_registry.py`(模式注册)、`frt_metrics.py`、`gen_frt_scenarios.py`、`gen_p1_figs.py`、`env_compare.py`
- 导出：`export_experts.py`/`export_residual.py`/`export_sac_actor.py`(SAC 权重 → `lab/` + `lab/simulink/*.mat`)

## `src/hpt_frt/network/` — Phase-2 网络压测（✅，当前主要工作）
- 核心库：`config.py` `sequence.py` `sac_wrapper.py` `hpt_interface.py` `opendss_runner.py` `scenarios.py` `metrics.py` `ieee33.dss`
- 实验：`run_exp_A_single_hpt.py` `run_exp_B_multi_hpt.py` `run_exp_C_slow_recovery.py` `export_simulink_cases.py`
- 第二轮：`fill_spotcheck.py` `study_vdc_boundary.py` `study_c10_oscillation.py` `study_gate_noise.py` `run_baselines.py`
- 绘图/报告：`plot_results.py` · **`report.md`（当前唯一报告）** · `NEXT_STEPS.md` · `results/`(CSV + fig1–11 + `simulink_cases/*_sw_result.mat`)

## `lab/` — MATLAB 开关级（✅）
- `simulink/hpt_frt_full.slx` + `build_hpt_frt_full.m`：★ 权威单机开关级模型(L1 真值)
- **frt-v2 有效入口（当前评价/复现）**：`simulink/frt_v2_evaluate.m`（权威五判据，单一事实源）· `frt_v2_full320_switching.m`（忠实全 320，标定故障）· `frt_v2_spotcheck.m`（12 例开关门禁）· `frt_v2_calibrate.m`（场景标定曲线）· `frt_v2_golden_test.m`/`frt_v2_consistency_test.m`（Python↔MATLAB 一致性）
- **legacy guard（historical / fail-fast，【非】 frt-v2 评价入口，勿用于当前结论）**：`simulink/validate_mode_full.m`、`run_spotcheck.m`（保留作守卫，未删除）
- `simulink/hpt_dual_*.slx` + `build/run_dual_*.m`：双机直流互联(下一步重点)
- `simulink/sac_*_weights.mat`：HLC `coder.load` 用权重；`frt_scenarios.csv`、`results/frt320_m*`：场景与已验证结果
- MATLAB 脚本用 `../frt_scenarios.csv`、`../results/`(=lab 根)定位，重构后仍有效

## `data/models/` — 控制器（gitignored）
`sac_{sym,asym,hvrt_sym,hvrt_asym}_best.zip`(★Mode5 四专家) · `sac_residual_*_best.zip`(Mode6) · `sac_frt_*.zip`(Mode3)

## 运行（先 `pip install -r requirements.txt`）
```bash
PY=.venv/Scripts/python.exe
$PY src/hpt_frt/network/run_exp_B_multi_hpt.py full     # 二期多机压测
$PY src/hpt_frt/network/study_c10_oscillation.py        # C10 振荡+缓解
$PY src/hpt_frt/network/fill_spotcheck.py               # L1 抽查分析(仅接受 metrics_version=frt-v2 + 真实时间向量的 MAT;
                                                        #   旧无版本 MAT 已隔离 legacy_pre_audit/,默认 fail-fast;crit.frt 不被信任。
                                                        #   --legacy 需 HPT_ALLOW_LEGACY_FRT=1,输出仅入 legacy_pre_audit,无 PASS)
# 一期训练：$PY src/hpt_frt/device/train_experts.py
```

## 历史（2026-06-21 已删除，git 可恢复）
旧目录 `emt/`、`phase2/`、`frt_standard/simulink/legacy/`；非主方法结果 `frt320_m4/m11/m13/m15_*`、`*_partial.mat`；
全部旧报告/讲义/审计 md、`MODE_COMPARISON_AUDIT.csv`、`audit_extract.py`。仅保留**最新报告** `src/hpt_frt/network/report.md` + 必备文档。
