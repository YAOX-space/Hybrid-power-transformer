# P3 frt-v2 SAC — ODE Selection Proxy Convergence (2026-06-24)

> ⚠️ **The convergence curves below are an ODE *selection proxy*, NOT a certified frt-v2 / GB-T
> switching pass rate.** Do not cite them as a pass rate. The certified switching-level result is in
> [FRT_V2_RESULTS_2026-06-23.md](FRT_V2_RESULTS_2026-06-23.md) and
> `lab/results/p3_full320_switching_summary.json`.

## What this figure is

Generated **from existing P3 training logs only** (no re-training, no Simulink, no full-320 re-run):
parsed `lab/results/p3par_20260623_015450_jobs/*.log` (22 logs) → step / proxy / best_proxy per
expert × seed.

- **Source**: P3 frt-v2 multi-random-seed training (run `p3par_20260623_015450`).
- **Policy contract**: **20-D de-privileged observation, 3-D action** `[iq, mse_d, mse_q]` (the frt-v2
  contract; the online detector/classifier sees only measured `(V2p, V2n)` — no privileged labels).
- **Training metric (y-axis)** = `partial_proxy_pct`, the **ODE selection proxy** over the criteria the
  ODE can evaluate (connect / reactive / recover). `limit` and `survive` are **NOT_EVALUATED** in the
  ODE (no switching-level current / DC bus), so this is a model-selection signal, **not** a
  switching-level certified pass rate.

Outputs:
- `lab/results/figures/p3_sac_ode_proxy_convergence.png` / `.pdf` — 5 panels (sym / asym / hvrt_sym /
  hvrt_asym experts + single-SAC/residual ablation) + a methodology note panel.
  Solid = proxy at each eval; dashed = running best (historical best_proxy).
- `lab/results/p3_sac_ode_proxy_convergence.csv` — `expert, seed, step, ode_selection_proxy_pct,
  best_proxy_pct, metric_note`.

## Convergence read (proxy, per expert; 5 seeds = 42, 7, 123, 2024, 31)

| Expert | final proxy by seed | behaviour |
|---|---|---|
| **sym** | 0, 0, 100, 90, 100 | **high variance / bimodal** (0-or-~100) — seed-unstable |
| **asym** | 75, 25, 70, 75, 52 | moderate variance, settles ~25–75% (proxy-saturated: reactive often the only evaluable demand) |
| **hvrt_sym** | 80, 0, 100, 0, 0 | **high variance / bimodal** — seed-unstable |
| **hvrt_asym** | 100 ×5 | flat 100% but **proxy-saturated** (reactive frequently NOT_EVALUATED) — stable ≠ strong |
| single-SAC (ablation, seed 42) | 52 | reported separately, not in the 5-seed statistics |
| residual (EMA, seed 42) | 73 (EMA best 85) | reported separately |

**Most seeds converge by ~25–50 k steps** then plateau (best_proxy often latches early). The symmetric
experts (`sym`, `hvrt_sym`) are the **high-variance** ones: across seeds the proxy is bimodal (≈0 or
≈100), i.e. the symmetric policy does not reliably learn under this proxy. `asym` is moderate;
`hvrt_asym` is flat-100 but that reflects proxy **saturation** (reactive not demanded), not strength.

## The certified result (use this for any conclusion)

frt-v2 **switching-layer** full-320 (calibrated sags, all five criteria evaluated):

| Controller | strict_pass | no-fail / effective | fail | True/False/NE |
|---|:---:|:---:|:---:|:---:|
| residual SAC mi=14 | **53.1%** | **89.4%** | **10.6%** | 170 / 34 / 116 |
| dq fixed-law mi=7 | 39.7% | 68.1% | 31.9% | 127 / 102 / 91 |

Definitions: **strict_pass** = all 5 criteria evaluated AND PASS; **NOT_EVALUATED** = no FAIL but ≥1
criterion N/A (no assessment window); **no-fail/effective** = no FAIL (PASS + NE) — **not** a strict
grid-code pass rate.

## Caveat the proxy↔switching gap makes explicit

The ODE proxy is **blind to limit/survive**, which is exactly where the switching layer finds the SAC's
real failures (HVRT weak-grid deep-swell DC undershoot). So a high training proxy (e.g. hvrt_asym 100%)
does **not** imply a switching pass — only the switching-layer table above is certifiable.

Regenerate: `python -m hpt_frt.device.plot_p3_convergence`.
