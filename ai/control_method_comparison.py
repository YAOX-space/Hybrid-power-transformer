"""
HPT v2 control-method comparison.

This script intentionally ignores legacy metrics from earlier average/ODE or
misleading topology experiments. It compares only controllers measured on the
correct switching-level HPT model:

  Grid -> series injection transformer -> line-frequency transformer -> load
  LV bus -> energy-extraction VSC -> DC link
  DC link -> regulation VSCs -> series injection transformers
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / 'results'

CONTROL_RUNS = [
    {
        'id': 'rule_frt_hpt_v2',
        'name': 'Rule-based FRT',
        'family': 'Traditional control',
        'dataset': 'data/raw_switching_hpt_v2_fixed_rule',
        'metrics': RESULTS_DIR / 'lvrt_metrics_raw_switching_hpt_v2_fixed_rule.json',
        'status': 'fixed 350-scenario table, corrected HPT v2 topology',
        'legacy': False,
    },
    {
        'id': 'dq_double_loop_hpt_v2',
        'name': 'dq double-loop baseline',
        'family': 'Traditional control',
        'dataset': 'data/raw_switching_hpt_v2_fixed_dq',
        'metrics': RESULTS_DIR / 'lvrt_metrics_raw_switching_hpt_v2_fixed_dq.json',
        'status': 'fixed 350-scenario table, corrected HPT v2 topology',
        'legacy': False,
    },
    {
        'id': 'ppo_drl_hpt_v2',
        'name': 'PPO/DRL controller',
        'family': 'AI control',
        'dataset': 'data/ppo_hpt_v2_rollouts/ppo_batch_1779763706483',
        'metrics': RESULTS_DIR / 'lvrt_metrics_ppo_hpt_v2_spe32_10ep_best.json',
        'status': 'fixed 350-scenario evaluation of best spe32 10-epoch checkpoint',
        'legacy': False,
    },
    {
        'id': 'msffn_fahc_pipeline',
        'name': 'MSFFN→FAHC pipeline',
        'family': 'AI control',
        'dataset': 'data/raw_switching_hpt_v2_pipeline',
        'metrics': RESULTS_DIR / 'lvrt_metrics_raw_switching_hpt_v2_pipeline.json',
        'status': 'MSFFN online detection (5 ms) → FAHC strategy → Mode 7; fixed 350-scenario table',
        'legacy': False,
    },
]

# DNN-FRT was trained via imitation learning on a different (pre-v2) topology.
# It achieves 0.29% LVRT pass rate on the corrected model — do NOT cite in paper.
LEGACY_RUNS = [
    {
        'id': 'dnn_frt_hpt_v2',
        'name': 'DNN-FRT (legacy, invalid)',
        'family': 'AI control',
        'dataset': 'data/raw_switching_hpt_v2_fixed_dnn',
        'metrics': RESULTS_DIR / 'lvrt_metrics_raw_switching_hpt_v2_fixed_dnn.json',
        'status': 'EXCLUDED — imitation policy trained on old topology; 0.29% pass rate on HPT v2',
        'legacy': True,
    },
]


def load_summary(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)['summary']


def aggregate(summary):
    scenarios = list(summary.values())
    pass_rates = [s['pass_rate_pct'] for s in scenarios]
    recoveries = [
        s['recovery_ms_max'] for s in scenarios
        if s.get('recovery_ms_max') is not None
    ]
    return {
        'mean_pass_rate_pct': round(sum(pass_rates) / len(pass_rates), 2),
        'worst_pass_rate_pct': round(min(pass_rates), 2),
        'max_vdc_pu': round(max(s['vdc_peak_pu_max'] for s in scenarios), 4),
        'min_vdc_pu': round(min(s['vdc_min_pu_min'] for s in scenarios), 4),
        'max_i2_pu': round(max(s['i2_peak_pu_max'] for s in scenarios), 4),
        'min_v2_pu': round(min(s['v2_min_pu_min'] for s in scenarios), 4),
        'max_recovery_ms': None if not recoveries else round(max(recoveries), 4),
    }


def _build_row(cfg):
    row = {
        'id': cfg['id'],
        'name': cfg['name'],
        'family': cfg['family'],
        'dataset': cfg['dataset'],
        'status': cfg['status'],
        'legacy': cfg.get('legacy', False),
    }
    if cfg['metrics'] is not None and cfg['metrics'].exists():
        summary = load_summary(cfg['metrics'])
        row.update(aggregate(summary))
        row['metrics'] = str(cfg['metrics'].relative_to(PROJECT_ROOT))
        row['scenario_summary'] = summary
    else:
        row.update({
            'metrics': None,
            'mean_pass_rate_pct': None,
            'worst_pass_rate_pct': None,
            'max_vdc_pu': None,
            'min_vdc_pu': None,
            'max_i2_pu': None,
            'min_v2_pu': None,
            'max_recovery_ms': None,
        })
    return row


def run():
    rows = [_build_row(cfg) for cfg in CONTROL_RUNS]
    legacy_rows = [_build_row(cfg) for cfg in LEGACY_RUNS]

    out_json = RESULTS_DIR / 'control_method_comparison_hpt_v2.json'
    out_md = RESULTS_DIR / 'control_method_comparison_hpt_v2.md'
    out_json.write_text(json.dumps({
        'scope': 'corrected HPT v2 topology only',
        'rows': rows,
        'legacy_rows': legacy_rows,
        'honest_conclusion': (
            'AI control (PPO/DRL) has not beaten traditional control on the corrected '
            'HPT v2 model. DNN-FRT is excluded — it was trained on the old topology '
            'and is not a valid comparison.'
        ),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown(rows, legacy_rows, out_md)

    print(f'Saved {out_json}')
    print(f'Saved {out_md}')
    print('\nValid controllers:')
    for row in rows:
        if row['mean_pass_rate_pct'] is None:
            print(f"  {row['name']}: {row['status']}")
        else:
            print(
                f"  {row['name']}: pass={row['mean_pass_rate_pct']:.2f}% "
                f"VdcMin={row['min_vdc_pu']:.3f} "
                f"VdcMax={row['max_vdc_pu']:.3f} I2Max={row['max_i2_pu']:.3f}"
            )
    print('\nExcluded (legacy):')
    for row in legacy_rows:
        print(f"  [{row['name']}] {row['status']}")


def fmt(value, suffix=''):
    return 'N/A' if value is None else f'{value}{suffix}'


def write_markdown(rows, legacy_rows, path: Path):
    measured = [r for r in rows if r['mean_pass_rate_pct'] is not None]
    full_measured = [
        r for r in measured
        if 'smoke' not in str(r.get('status', '')).lower()
    ]
    ranked_pool = full_measured or measured
    best = max(
        ranked_pool,
        key=lambda r: (r['mean_pass_rate_pct'], r['min_vdc_pu'], -r['max_i2_pu']),
    )

    lines = [
        '# HPT v2 Control Method Comparison',
        '',
        '## Scope',
        '',
        'Only corrected HPT v2 switching-level Simulink results are included. '
        'All valid controllers use the same fixed 350-scenario table.',
        '',
        f'Best measured controller: `{best["name"]}`.',
        '',
        '## Valid Controllers',
        '',
        '| Controller | Family | Mean Pass | Worst Pass | V2min | VdcMin | VdcMax | I2Max | Max Recovery |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in rows:
        lines.append(
            f'| {row["name"]} | {row["family"]} | '
            f'{fmt(row["mean_pass_rate_pct"], "%")} | '
            f'{fmt(row["worst_pass_rate_pct"], "%")} | {fmt(row["min_v2_pu"])} | '
            f'{fmt(row["min_vdc_pu"])} | {fmt(row["max_vdc_pu"])} | '
            f'{fmt(row["max_i2_pu"])} | {fmt(row["max_recovery_ms"], " ms")} |'
        )

    lines += [
        '',
        '## Honest Conclusion',
        '',
        'AI control (PPO/DRL) has not beaten traditional control on the fixed HPT v2 '
        'scenario table. The dq double-loop baseline is the strongest measured controller.',
        '',
        '## Excluded (Legacy) — Do Not Cite',
        '',
        '| Controller | Reason |',
        '|---|---|',
    ]
    for row in legacy_rows:
        lines.append(f'| {row["name"]} | {row["status"]} |')

    lines += [
        '',
        '## Next AI-Control Steps',
        '',
        '| Track | Baseline to beat | Metrics |',
        '|---|---|---|',
        '| Ride-through control | dq double-loop 64.0% | LVRT pass, VdcMin/VdcMax, I2Max, recovery time |',
        '| Fault detection | Random Forest 95.68% | Accuracy, macro F1, 5 ms latency |',
        '| Full AI strategy | PPO/DRL with trained MSFFN | Same physical metrics on identical scenarios |',
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    run()
