"""plot_sac_convergence.py — SAC learning curves (FRT pass% vs training steps) for the
4 Mode-5 experts, parsed from train_experts_v2.log. Shows the noisy pass/fail metric and
the best-checkpoint line (why deployment uses best-checkpoint, not the final step).

NOTE: Y-axis is FRT pass% (task-success criterion), NOT raw episodic return. The SAC paper
figure plots average return; we never logged raw return as a time series, only this domain
metric. Curves are non-monotonic because FRT pass is a hard 5-criteria gate.
"""
import re
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / 'train_experts_v2.log'

# robust read: file is UTF-16 (BOM); fall back to latin-1
raw = LOG.read_bytes()
for enc in ('utf-16', 'utf-8', 'latin-1'):
    try:
        text = raw.decode(enc)
        break
    except UnicodeError:
        continue

# lines like:  [sym] step= 25,000   FRT=98% (con=98 rea=100 ...) best=98%  2min
pat = re.compile(r'\[(\w+)\]\s*step=\s*([\d,]+)\s+FRT=(\d+)%.*?best=(\d+)%')
data = {}        # expert -> list of (step, frt, best)
for line in text.splitlines():
    m = pat.search(line)
    if m:
        exp, step, frt, best = m.group(1), int(m.group(2).replace(',', '')), int(m.group(3)), int(m.group(4))
        data.setdefault(exp, []).append((step, frt, best))

order = ['sym', 'asym', 'hvrt_sym', 'hvrt_asym']
experts = [e for e in order if e in data] + [e for e in data if e not in order]
titles = {'sym': 'Symmetric 3-ph (sym)', 'asym': 'Asymmetric (asym)',
          'hvrt_sym': 'HVRT symmetric', 'hvrt_asym': 'HVRT asymmetric'}

fig, axes = plt.subplots(2, 2, figsize=(11, 7.5), sharex=True)
for ax, exp in zip(axes.flat, experts):
    pts = data[exp]
    xs = [p[0] / 1000 for p in pts]            # k-steps
    frt = [p[1] for p in pts]
    best = [p[2] for p in pts]
    ax.plot(xs, frt, '-o', color='#d95f02', ms=4, lw=1.4, label='FRT pass% (per eval)')
    ax.plot(xs, best, '--', color='#1b9e77', lw=1.8, label='best-checkpoint (deployed)')
    bi = max(range(len(pts)), key=lambda i: pts[i][1])
    ax.scatter([xs[bi]], [frt[bi]], s=90, facecolors='none', edgecolors='#1b9e77',
               linewidths=2, zorder=5)
    ax.set_title(f'{titles.get(exp, exp)}  (n={len(pts)} evals)', fontsize=10)
    ax.set_ylim(-5, 105); ax.grid(alpha=0.3)
    ax.set_ylabel('FRT pass %')

for ax in axes[-1]:
    ax.set_xlabel('training steps (x1000)')
axes.flat[0].legend(fontsize=8, loc='lower right')
fig.suptitle('Mode-5 multi-expert SAC learning curves -- FRT pass% vs training steps\n'
             '(Y = task pass-rate, NOT raw return; hard 5-criteria gate -> non-monotonic '
             '-> deploy best-checkpoint)', fontsize=11)
fig.tight_layout(rect=[0, 0, 1, 0.95])
out = ROOT / 'results' / 'fig_sac_convergence.png'
fig.savefig(out, dpi=140)
print(f'parsed experts: {[(e, len(data[e])) for e in experts]}')
print(f'saved {out}')
