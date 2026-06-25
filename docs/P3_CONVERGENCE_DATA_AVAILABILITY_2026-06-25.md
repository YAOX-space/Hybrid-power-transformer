# P3 SAC Convergence — Training-Curve Data Availability (2026-06-25)

> Post-processing of existing logs only — **no retraining, no Simulink, no full-320 re-run.** This note
> records which training curves can be drawn from what was actually saved, and why the **reward curve
> cannot** (and was therefore NOT fabricated).

## What was searched

| source | present? |
|---|---|
| `lab/results/p3par_20260623_015450_jobs/*.log` (22 logs) | ✅ yes (the per-expert/seed eval logs) |
| `lab/results/archive_2026-06-25/**/*.log` (early/aborted runs) | ✅ yes (older, same format) |
| `monitor.csv` (SB3 episode monitor) | ❌ **absent** |
| `events.out.tfevents.*` (TensorBoard) | ❌ **absent** |
| `progress.csv` (SB3 logger) | ❌ **absent** |
| `data/models/**/*.json` (checkpoint sidecars) | ✅ yes, but **no reward field** |

## Does the data contain reward? — **No.**

The training logs record, at each **evaluation** checkpoint (every 25 k steps), only the **ODE evaluation
proxy**, not the RL reward / episode return. A representative line:

```
[sym] step= 25,000 proxy=100% frt_pass=n/a [req10 ok10 cmpl0 incmpl10 fail0 unev0]
      (con=100 rea=100 lim=n/e rec=100 sur=n/e) [frt-v2] best_proxy=100%@25000 5min
```

Available fields: `step`, `proxy` (= partial_proxy_pct), `best_proxy`, the rollout counts
(`req/ok/cmpl/incmpl/fail/unev`), and the per-criterion pass% (`con/rea/lim/rec/sur`). The checkpoint
sidecars (`*_best.json`) add `validation_partial_proxy_pct`, `proxy_saturated`, `n_complete`, etc. **None
of these is an episode reward or return.** SB3's `Monitor` / `configure(...csv,tensorboard)` was not
enabled during P3 training, so no reward time-series was persisted.

## Which curves CAN be drawn (and were)

| curve | status | output |
|---|---|---|
| **A. reward convergence** | ❌ **not possible** — no reward data; not fabricated | (this note) |
| **B. success-rate convergence** | ✅ generated | `lab/results/figures/p3_success_rate_convergence.png` + `lab/results/p3_success_rate_convergence.csv` |
| **C. constraint-violation convergence** | ✅ generated | `lab/results/figures/p3_constraint_violation_convergence.png` + `lab/results/p3_constraint_violation_convergence.csv` |

- **B** plots the **ODE evaluation success rate** (= partial_proxy_pct) and its running best, per
  expert/seed. Title carries: *"ODE evaluation success rate, not certified switching frt-v2 pass rate."*
- **C** plots **connect / reactive / recover violation** (= 100 − pass%), mean over seeds. **limit and
  survive are `NOT_EVALUATED` in the ODE** (no switching current / DC bus) — they are **not** plotted and
  **not** zero-filled (left blank / labelled NOT_EVALUATED in the CSV).

Generator: `python -m hpt_frt.device.plot_p3_curves` (reads `p3par_20260623_015450_jobs/`).
The earlier `plot_p3_convergence.py` (single proxy curve) remains valid; this adds the success-rate +
violation framing.

## What is only obtainable from FUTURE training (reward / richer curves)

To get a genuine **reward / episode-return** curve, the *next* training run must persist it — it cannot be
recovered post-hoc. Minimal changes to the SB3 training scripts (`src/hpt_frt/device/train_*.py`):

1. **Wrap the env in `Monitor`** so per-episode returns land in `monitor.csv`:
   ```python
   from stable_baselines3.common.monitor import Monitor
   env = Monitor(env, filename=str(logdir / f'{tag}_monitor.csv'))
   ```
2. **Enable the SB3 logger** (CSV + TensorBoard) so `progress.csv` / `events.out.tfevents.*` capture
   `rollout/ep_rew_mean`, `train/*`, etc.:
   ```python
   from stable_baselines3.common.logger import configure
   model.set_logger(configure(str(logdir / tag), ['stdout', 'csv', 'tensorboard']))
   ```
3. Optionally log per-eval reward in an `EvalCallback`, and (for a true constraint curve) log
   limit/survive only where they are evaluable.

With those, a future run yields A (reward), and richer B/C directly from `progress.csv` — without changing
the frt-v2 evaluation semantics.

## Framing rules honoured

- The success-rate curve is the **ODE evaluation proxy**, explicitly **not** a certified switching frt-v2
  pass rate; training convergence here is **not** claimed to imply the switching full-320 pass rate
  converges. The certified switching result (`docs/FRT_V2_RESULTS_2026-06-23.md`,
  `lab/results/p3_full320_switching_summary.json`) is unchanged: residual SAC mi=14 strict 53.1% /
  no-fail 89.4% / fail 10.6%.
- `NOT_EVALUATED` (limit/survive, and any `n/e` criterion) is never converted to 0 or counted as a pass.
