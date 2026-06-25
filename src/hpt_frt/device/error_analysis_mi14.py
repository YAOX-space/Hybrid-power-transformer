"""error_analysis_mi14.py — POST-PROCESSING error analysis of the residual SAC (mi=14) FAILs in the
frt-v2 switching full-320. Reads ONLY existing results (no training / no Simulink / no re-run / no
mutation of result values):
    lab/results/p3_full320_sw_mi14.mat  (SAC)   lab/results/p3_full320_sw_mi7.mat  (dq baseline)
Per FAIL scenario it extracts the failed criteria + reason + worst/t_worst, whether a NOT_EVALUATED
criterion co-exists, and whether the matching dq scenario also failed. Writes CSV + summary JSON + 4
breakdown figures.

NOTE: NE is never counted as PASS; no-fail/effective is NOT a strict grid-code pass rate.

    python -m hpt_frt.device.error_analysis_mi14
"""
from __future__ import annotations
import json
import csv
from collections import Counter, defaultdict
from pathlib import Path
import scipy.io as sio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / 'lab' / 'results'
FIG = RES / 'figures'
CRITERIA = ['connect', 'reactive', 'limit', 'recover', 'survive']


def load(mi):
    R = sio.loadmat(RES / f'p3_full320_sw_mi{mi}.mat', simplify_cells=True)['R']
    R = [R] if isinstance(R, dict) else list(R)
    out = {}
    for r in R:
        p = r['prov']
        ft = p['fault_type']
        out[int(r['sid'])] = dict(sid=int(r['sid']), frt=str(r['frt']), ft=ft,
                                  cat='HVRT' if str(ft).startswith('swell') else 'LVRT',
                                  scr=int(p['scr']), Vg_p=float(p['Vg_p']),
                                  target_V_pu=float(p['target_V_pu']), crit=r['crit'])
    return out


def fail_record(rec, dq):
    """Build the per-FAIL row: failed criteria, reasons, worst/t, NE present, dq-also-fail."""
    cr = rec['crit']
    failed = [k for k in CRITERIA if str(cr[k]['status']) == 'FAIL']
    ne = [k for k in CRITERIA if str(cr[k]['status']) == 'NOT_EVALUATED']
    reasons = {k: str(cr[k]['reason']) for k in failed}
    worst = {k: (None if not _finite(cr[k]['worst']) else float(cr[k]['worst'])) for k in failed}
    t_worst = {k: float(cr[k]['t_worst']) for k in failed}
    dq_rec = dq.get(rec['sid'])
    return dict(
        sid=rec['sid'], fault_type=rec['ft'], category=rec['cat'], scr=rec['scr'],
        target_V_pu=rec['target_V_pu'], Vg_p=rec['Vg_p'],
        failed_criteria='+'.join(failed), n_failed=len(failed),
        connect=_st(cr, 'connect'), reactive=_st(cr, 'reactive'), limit=_st(cr, 'limit'),
        recover=_st(cr, 'recover'), survive=_st(cr, 'survive'),
        primary_reason=' | '.join(f'{k}:{reasons[k][:70]}' for k in failed),
        worst=' | '.join(f'{k}={worst[k]}' for k in failed if worst[k] is not None),
        t_worst=' | '.join(f'{k}@{t_worst[k]:.3f}' for k in failed),
        has_not_evaluated=bool(ne), not_evaluated='+'.join(ne),
        dq_frt=(dq_rec['frt'] if dq_rec else 'NA'),
        dq_also_fail=(dq_rec is not None and dq_rec['frt'] == 'False'))


def _finite(x):
    try:
        return x == x and abs(float(x)) != float('inf')
    except Exception:
        return False


def _st(cr, k):
    return str(cr[k]['status'])


def main():
    sac, dq = load(14), load(7)
    fails = [fail_record(sac[s], dq) for s in sorted(sac) if sac[s]['frt'] == 'False']
    assert len(fails) == sum(1 for s in sac if sac[s]['frt'] == 'False')

    # ---- CSV (per-scenario) ----
    FIG.mkdir(parents=True, exist_ok=True)
    csv_path = RES / 'error_analysis_mi14_failures.csv'
    cols = ['sid', 'fault_type', 'category', 'scr', 'target_V_pu', 'Vg_p', 'failed_criteria',
            'n_failed', 'connect', 'reactive', 'limit', 'recover', 'survive', 'primary_reason',
            'worst', 't_worst', 'has_not_evaluated', 'not_evaluated', 'dq_frt', 'dq_also_fail']
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in fails:
            w.writerow(r)

    # ---- aggregate stats ----
    by_crit = Counter()             # each failed criterion occurrence (a scenario may fail 2)
    for r in fails:
        for k in r['failed_criteria'].split('+'):
            by_crit[k] += 1
    multi = [r['sid'] for r in fails if r['n_failed'] >= 2]
    fail_plus_ne = [r['sid'] for r in fails if r['has_not_evaluated']]
    by_ft = Counter(r['fault_type'] for r in fails)
    by_scr = Counter(r['scr'] for r in fails)
    by_cat = Counter(r['category'] for r in fails)
    by_depth = Counter(round(r['Vg_p'], 3) for r in fails)
    dq_also = [r['sid'] for r in fails if r['dq_also_fail']]
    sac_only = [r['sid'] for r in fails if not r['dq_also_fail']]
    # criterion x (cat,scr) cross-tab
    cross = defaultdict(Counter)
    for r in fails:
        for k in r['failed_criteria'].split('+'):
            cross[k][f"{r['category']}/scr{r['scr']}"] += 1

    summary = dict(
        analysis='post-processing of existing MAT/JSON only — NO training / Simulink / re-run',
        metrics_version='frt-v2', layer='switching',
        certified_full320=dict(
            residual_SAC_mi14=dict(strict_pass_pct=53.1, no_fail_effective_pct=89.4, fail_pct=10.6,
                                   true=170, false=34, none=116),
            dq_mi7=dict(strict_pass_pct=39.7, no_fail_effective_pct=68.1, fail_pct=31.9,
                        true=127, false=102, none=91)),
        note=('strict_pass=all 5 criteria evaluated AND PASS; NOT_EVALUATED never counted as PASS; '
              'no-fail/effective is NOT a strict grid-code pass rate.'),
        n_sac_fail=len(fails),
        fail_by_criterion=dict(by_crit),
        multi_criterion_fail=dict(count=len(multi), sids=multi),
        fail_plus_not_evaluated=dict(count=len(fail_plus_ne), sids=fail_plus_ne),
        fail_by_fault_type=dict(by_ft), fail_by_scr={str(k): v for k, v in by_scr.items()},
        fail_by_category=dict(by_cat), fail_by_Vg_p={str(k): v for k, v in sorted(by_depth.items())},
        criterion_by_cat_scr={k: dict(v) for k, v in cross.items()},
        dq_also_fail=dict(count=len(dq_also), sids=dq_also),
        sac_only_fail=dict(count=len(sac_only), sids=sac_only))
    json_path = RES / 'error_analysis_mi14_summary.json'
    json_path.write_text(json.dumps(summary, indent=1), encoding='utf-8')

    # ---- figures ----
    _bar(by_crit, 'SAC mi=14 FAILs by criterion (occurrences; a scenario may fail >1)',
         'failed criterion', FIG / 'error_fail_by_criterion.png',
         order=CRITERIA)
    _bar(by_ft, 'SAC mi=14 FAILs by fault_type', 'fault_type', FIG / 'error_fail_by_fault_type.png')
    _bar({f'scr {k}': v for k, v in sorted(by_scr.items())}, 'SAC mi=14 FAILs by SCR (3=weak / 10=strong)',
         'grid SCR', FIG / 'error_fail_by_scr.png')
    _bar(by_cat, 'SAC mi=14 FAILs by ride-through type', 'category', FIG / 'error_fail_by_lvrt_hvrt.png')

    # console summary
    print(f'SAC mi=14 FAILs: {len(fails)}/320')
    print(f'  by criterion: {dict(by_crit)}')
    print(f'  multi-criterion: {len(multi)} {multi}')
    print(f'  FAIL+NE mixed: {len(fail_plus_ne)} {fail_plus_ne}')
    print(f'  by fault_type: {dict(by_ft)}')
    print(f'  by scr: {dict(by_scr)}  by cat: {dict(by_cat)}')
    print(f'  dq-also-fail: {len(dq_also)}  SAC-only: {len(sac_only)} {sac_only}')
    print(f'wrote {csv_path}\nwrote {json_path}\nwrote 4 figures in {FIG}')


def _bar(counter, title, xlabel, path, order=None):
    keys = order if order else list(counter.keys())
    keys = [k for k in keys if k in counter] if order else keys
    vals = [counter[k] for k in keys]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar([str(k) for k in keys], vals, color='tab:red', alpha=0.8)
    ax.bar_label(bars)
    ax.set_title(title + '\n(ODE selection proxy NOT involved — switching-level certified frt-v2 FAILs)',
                 fontsize=10)
    ax.set_xlabel(xlabel); ax.set_ylabel('# FAIL scenarios')
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


if __name__ == '__main__':
    main()
