"""
frt_metrics.py — evaluate the 5 FRT criteria (FRT_SPEC §1) for a policy on the ODE env.

(For Simulink validation the same 5 criteria are applied to switching waveforms; that
script is deferred until the Simulink reactive-injection channel is added.)
"""
from __future__ import annotations
import numpy as np


def run_episode(model, env):
    """Roll out one scenario; return trajectory dict."""
    obs, _ = env.reset()
    V2p, V2n, Vdc, iq, iqref = [], [], [], [], []
    tripped = False
    done = False
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        V2p.append(info['V2p']); V2n.append(info['V2n']); Vdc.append(info['Vdc'])
        iq.append(info['iq']); iqref.append(info['iq_ref'])
        tripped = tripped or info['tripped']
        done = term or trunc
    return dict(V2p=np.array(V2p), V2n=np.array(V2n), Vdc=np.array(Vdc),
                iq=np.array(iq), iqref=np.array(iqref), tripped=tripped)


def frt_criteria(tr) -> dict:
    """5 FRT criteria → pass/fail (FRT_SPEC §1)."""
    c1_connect  = not tr['tripped']                                  # 不脱网
    # 无功跟踪：故障期 iq 与 droop 参考的平均偏差 ≤ 0.1 pu（在 PE 能力内）
    mask = np.abs(tr['iqref']) > 1e-3
    c2_reactive = (np.mean(np.abs(tr['iq'][mask] - tr['iqref'][mask])) <= 0.10) if mask.any() else True
    # 限流：|iq| 未超 PE 上限（env 已钳，这里复核）
    c3_limit    = bool(np.all(np.abs(tr['iq']) <= 0.301))
    # 电压恢复：末段 V2p 在 ±7% 内
    c4_recover  = abs(1.0 - float(np.mean(tr['V2p'][-10:]))) <= 0.07
    # 装置存活：Vdc 始终在 [0.75,1.25]
    c5_survive  = bool(tr['Vdc'].min() >= 0.75 and tr['Vdc'].max() <= 1.25)
    overall = c1_connect and c2_reactive and c3_limit and c4_recover and c5_survive
    return dict(connect=c1_connect, reactive=c2_reactive, limit=c3_limit,
                recover=c4_recover, survive=c5_survive, frt_pass=overall)


def evaluate_frt(model, scenarios, env_cls, n_eval=None):
    """FRT pass rate + per-criterion rates over scenarios."""
    rng = np.random.default_rng(0)
    idx = range(len(scenarios)) if n_eval is None else rng.choice(
        len(scenarios), min(n_eval, len(scenarios)), replace=False)
    keys = ['connect', 'reactive', 'limit', 'recover', 'survive', 'frt_pass']
    agg = {k: 0 for k in keys}
    n = 0
    for i in idx:
        env = env_cls([scenarios[i]], seed=42, train_mode=False)
        c = frt_criteria(run_episode(model, env))
        for k in keys:
            agg[k] += int(c[k])
        n += 1
    return {k: round(100.0 * agg[k] / n, 1) for k in keys}
