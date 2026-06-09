"""
gen_ablation_actions.py  —  generate action CSVs for the SAC attribution ablation (#9).

Produces, on the SAME 350-scenario table, four action sources for ablate_sac_direct.m:
  fixed_082.csv      m_sh=0.82 (pre-fault balance), no series  — isolates protection floors
  fixed_090.csv      m_sh=0.90 (max),               no series  — isolates protection floors
  raw_sac.csv        raw SAC actions, NO per-class overrides   — net SAC contribution
  sac_overrides.csv  SAC + the published hand-coded overrides  — the published pipeline

Comparing the four on identical footing (all run under SAC直接调制, no cascade->dq双环PI swap)
isolates what the SAC actually adds beyond fixed commands + in-binary protection floors.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_sac_actions import initial_state_obs   # 17-dim obs identical to training

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCEN_CSV  = PROJECT_ROOT / 'data_collection' / 'scenario_table_hpt_v2.csv'
OUT_DIR   = PROJECT_ROOT / 'results' / 'ablation'
OUT_DIR.mkdir(parents=True, exist_ok=True)

M_SH_MAX, M_SE_BOUND = 0.90, 0.30


def _overrides(sc_id, m_sh, m_se_d, m_se_q):
    """The published per-class hand-coded overrides (from generate_sac_actions.py)."""
    if sc_id == 7:
        return 0.90, 0.0, 0.0
    if sc_id in (3, 5):
        return float(np.clip(m_sh, 0.75, 0.80)), 0.0, 0.0
    if sc_id == 4:
        return float(np.clip(m_sh, 0.72, 0.80)), 0.0, 0.0
    if sc_id == 6:
        return max(m_sh, 0.68), float(np.clip(m_se_d, -0.15, 0.15)), m_se_q
    if sc_id == 8:
        return 0.85, max(m_se_d, 0.10), m_se_q
    return m_sh, float(np.clip(m_se_d, -0.10, 0.10)), m_se_q


def main(checkpoint):
    from stable_baselines3 import SAC
    scen = pd.read_csv(SCEN_CSV).reset_index(drop=True)
    sac  = SAC.load(checkpoint)

    rows_082, rows_090, rows_raw, rows_ovr = [], [], [], []
    for i, (_, row) in enumerate(scen.iterrows()):
        sc_id = int(row.sc_id)
        obs = initial_state_obs(row).reshape(1, -1)
        a, _ = sac.predict(obs, deterministic=True)
        m_sh   = float(np.clip(a[0][0], 0.0, M_SH_MAX))
        m_se_d = float(np.clip(a[0][1], -M_SE_BOUND, M_SE_BOUND))
        m_se_q = float(np.clip(a[0][2], -M_SE_BOUND, M_SE_BOUND))
        o_sh, o_d, o_q = _overrides(sc_id, m_sh, m_se_d, m_se_q)
        base = dict(scenario_idx=i + 1, sc_id=sc_id)
        rows_082.append({**base, 'm_sh': 0.82, 'm_se_d': 0.0, 'm_se_q': 0.0})
        rows_090.append({**base, 'm_sh': 0.90, 'm_se_d': 0.0, 'm_se_q': 0.0})
        rows_raw.append({**base, 'm_sh': round(m_sh, 4), 'm_se_d': round(m_se_d, 4), 'm_se_q': round(m_se_q, 4)})
        rows_ovr.append({**base, 'm_sh': round(o_sh, 4), 'm_se_d': round(o_d, 4), 'm_se_q': round(o_q, 4)})

    for name, rows in [('fixed_082', rows_082), ('fixed_090', rows_090),
                       ('raw_sac', rows_raw), ('sac_overrides', rows_ovr)]:
        p = OUT_DIR / f'{name}.csv'
        pd.DataFrame(rows).to_csv(p, index=False)
        print(f'wrote {p}')
    print('\nraw SAC action stats:')
    df = pd.DataFrame(rows_raw)
    print(f"  m_sh mean={df.m_sh.mean():.3f} [{df.m_sh.min():.3f},{df.m_sh.max():.3f}]  "
          f"m_se_d mean={df.m_se_d.mean():.3f}  m_se_q mean={df.m_se_q.mean():.3f}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--checkpoint', default=str(PROJECT_ROOT / 'data' / 'models' / 'sac_hpt_direct_best.zip'))
    main(p.parse_args().checkpoint)
