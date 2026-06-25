# P3 Small Reward-Logging Retrain — Training Diagnostics (2026-06-25)

> **Scope & honesty banner.** A **small ODE reward-logging retrain for TRAINING DIAGNOSTICS ONLY**. It is
> **not** a new frt-v2 full-320 experiment, **no Simulink**, **no full-320**, and it does **not** touch
> any certified result or deployed model (all outputs go to a new dir). Its numbers are training
> diagnostics, **not** a performance conclusion. Every figure is labelled *"ODE training diagnostics only;
> not certified switching frt-v2 pass rate."*
>
> **Certified result of record — UNCHANGED:** residual SAC mi=14 **strict 53.1% / no-fail 89.4% / fail
> 10.6%** (170/34/116). See [FRT_V2_RESULTS_2026-06-23.md](FRT_V2_RESULTS_2026-06-23.md).

## Why this rerun

The P3 multi-seed training (run `p3par_20260623_015450`) **did not persist a reward time-series** — its
logs hold only the ODE evaluation proxy, no `monitor.csv` / TensorBoard / `progress.csv`
(see [P3_CONVERGENCE_DATA_AVAILABILITY_2026-06-25.md](P3_CONVERGENCE_DATA_AVAILABILITY_2026-06-25.md)).
Reward is **not recoverable post-hoc**, so this small run re-trains with SB3 `VecMonitor` + CSV +
TensorBoard logging to capture the standard RL diagnostics (reward / ep_rew_mean / actor & critic loss /
entropy / alpha) alongside the ODE success proxy and constraint violation.

## What was run

| setting | value |
|---|---|
| controller | **residual SAC** (`HPTFRTResidualEnvV2`, 20-D observation / 3-D action `[iq, mse_d, mse_q]`) |
| seed | **42** |
| total steps | **100 000** |
| eval interval | **10 000** (10 ODE eval points) |
| parallel envs | 4 (`DummyVecEnv` + `VecMonitor`), CPU |
| logging | SB3 `Monitor` (→ monitor.csv), CSV logger (→ progress.csv), TensorBoard (→ tensorboard/) |
| wall time | ~45 min |
| entry | `python -m hpt_frt.device.train_reward_logging --controller residual --seed 42 --steps 100000 --eval 10000` |

Script: `src/hpt_frt/device/train_reward_logging.py` (new; does **not** modify the original
`train_residual.py` / `train_single.py`). Plots: `src/hpt_frt/device/plot_reward_logging.py` (new).

## Outputs — `lab/results/reward_logging_seed42_100k/`

`monitor.csv` (524 episodes), `progress.csv` (141 rows: `rollout/ep_rew_mean`, `train/actor_loss`,
`train/critic_loss`, `train/ent_coef` = α, `train/entropy`, eval/* mirrors), `tensorboard/events.out.tfevents.*`,
`eval_curve.csv` (10 eval points), `config.json`, `train.log`, `final_model.zip`, and the figures:
`fig_reward_curve.png`, `fig_success_rate_curve.png`, `fig_constraint_violation_curve.png`,
`fig_training_diagnostics_combined.png`.

## Reading the curves

- **Reward — converges.** `ep_rew_mean` rises monotonically from **≈ −103** (first checkpoints) to **≈ +50
  to +100** by 100 k steps (raw episode rewards scatter ±100 around the rising mean). The actor learns;
  reward does not plateau-low or diverge.
- **Success rate (ODE proxy) — high but OSCILLATING**, not monotone:
  `100 / 83 / 72 / 100 / 87 / 80 / 88 / 100 / 100 / 87 %` at 10 k…100 k. This swing is the **known
  residual-SAC proxy noise** (the symmetric/boundary reactive behaviour is seed- and checkpoint-sensitive,
  consistent with the P3 frozen-split variance). It is the **ODE selection proxy, not** a switching pass rate.
- **Constraint violation — reactive dominates.** `connect` and `recover` violation are **≈ 0 throughout**;
  **`reactive` violation oscillates 0–55 %** (mirrors the success-rate swing) — i.e. the only constraint the
  policy struggles with in the ODE is **reactive**, the same weakness the switching error analysis isolated
  ([FRT_V2_ERROR_ANALYSIS_2026-06-24.md](FRT_V2_ERROR_ANALYSIS_2026-06-24.md): 24/34 FAILs are reactive).
- **`limit` and `survive` are `NOT_EVALUATED`** in the ODE (no switching current / DC bus) — **not** plotted,
  **not** zero-filled.

## What this does NOT show

- It does **not** change the certified switching full-320 result, and training convergence here does **not**
  imply the switching pass rate converges (limit/survive — where the real switching failures live — are
  invisible to the ODE).
- A single seed / 100 k steps is a **diagnostic**, not a performance claim.

## Next step (optional)

If a publication-grade reward/constraint study is wanted: run **multi-seed** reward logging (e.g. seeds
42, 7, 123 × 150–300 k steps) with the same `train_reward_logging.py`, then aggregate mean±std curves.
This is purely additional diagnostics; the certified full-320 conclusion stands on the switching result,
not on these ODE training curves.
