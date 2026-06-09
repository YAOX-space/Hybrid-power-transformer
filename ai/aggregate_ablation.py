"""aggregate_ablation.py — summarise ablate_sac_direct per-scenario result CSVs (#9)."""
import sys
from pathlib import Path
import pandas as pd

SC_NAMES = {0:'normal',3:'igbt_oc_sh',4:'igbt_oc_se',5:'cap_fault',
            6:'sc_1ph',7:'sc_3ph',8:'cascade'}
ABL = Path(__file__).resolve().parent.parent / 'results' / 'ablation'

ARMS = {
    'fixed_082':     'Fixed m_sh=0.82 (no SAC, floors only)',
    'fixed_090':     'Fixed m_sh=0.90 (no SAC, floors only)',
    'raw_sac':       'Raw SAC (no overrides, no swap)',
    'sac_overrides': 'SAC + hand-coded overrides',
}


def summarise(res_csv: Path) -> dict:
    df = pd.read_csv(res_csv).drop_duplicates('scenario_idx', keep='last')
    out = {'n': len(df), 'overall': round(100*df.lvrt_pass.mean(), 2), 'per_class': {}}
    for sc, name in SC_NAMES.items():
        g = df[df.sc_id == sc]
        if len(g):
            out['per_class'][name] = round(100*g.lvrt_pass.mean(), 2)
    return out


def main():
    print(f'{"arm":34s} {"N":>4s} {"overall":>8s}  per-class')
    print('-'*100)
    summ = {}
    for key, label in ARMS.items():
        p = ABL / f'{key}_res.csv'
        if not p.exists():
            print(f'{label:34s}  (missing {p.name})'); continue
        s = summarise(p); summ[key] = s
        pc = '  '.join(f'{n}={v:.0f}' for n, v in s['per_class'].items())
        print(f'{label:34s} {s["n"]:4d} {s["overall"]:7.2f}%  {pc}')
    # net SAC contribution
    if 'raw_sac' in summ and 'fixed_090' in summ:
        print('-'*100)
        print(f"Net SAC vs fixed-0.90:  {summ['raw_sac']['overall'] - summ['fixed_090']['overall']:+.2f} pp")
    if 'sac_overrides' in summ and 'raw_sac' in summ:
        print(f"Overrides vs raw SAC:   {summ['sac_overrides']['overall'] - summ['raw_sac']['overall']:+.2f} pp")
    import json
    (ABL / 'ablation_summary.json').write_text(json.dumps(summ, indent=2), encoding='utf-8')
    print(f"\nSaved -> {ABL/'ablation_summary.json'}")


if __name__ == '__main__':
    main()
