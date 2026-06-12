"""w1_testbed.py — Phase-2 W1: IEEE 33-bus OpenDSS testbed + fault sag-propagation reproduction.

Deliverables:
  (a) base-case power flow self-check (anchor: min V = 0.9131 pu @ bus 18, Baran-Wu);
  (b) sag propagation: 3-phase fault at different buses -> network-wide voltage profile
      (the physical root of the coordination problem: each HPT sees a different sag);
  (c) figure phase2/fig_w1_sag_propagation.png + results json.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json
from pathlib import Path
import numpy as np
import opendssdirect as dss

HERE = Path(__file__).resolve().parent
HPT_BUSES = [6, 14, 25, 30]          # candidate HPT placement (head/mid/branch/tail)
FAULT_BUSES = [3, 6, 12, 18, 25, 30] # fault locations along main + branches
FAULT_R = 0.5                         # ohms (controllable sag depth, like phase-1 calibration)


def solve_base():
    dss.Text.Command(f'compile "{HERE / "ieee33.dss"}"')
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    assert dss.Solution.Converged(), 'base case did not converge'
    return profile()


def profile():
    """bus -> mean phase voltage (pu)."""
    out = {}
    for b in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(b)
        v = dss.Bus.puVmagAngle()[::2]
        if v:
            out[b] = float(np.mean(v))
    return out


def fault_case(bus, r=FAULT_R):
    dss.Text.Command(f'compile "{HERE / "ieee33.dss"}"')
    dss.Text.Command(f'New Fault.f1 bus1={bus} phases=3 r={r}')
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    assert dss.Solution.Converged(), f'fault at {bus} did not converge'
    return profile()


def main():
    base = solve_base()
    vmin_bus = min(base, key=base.get)
    loss_kw = dss.Circuit.Losses()[0] / 1000.0
    print(f'BASE: minV = {base[vmin_bus]:.4f} pu @ bus {vmin_bus}, losses = {loss_kw:.2f} kW '
          f'(canonical anchors: 0.9038 @ 18, 210.98 kW)')
    ok = abs(base[vmin_bus] - 0.9038) < 0.002 and vmin_bus == '18' and abs(loss_kw - 210.98) < 1.0
    print('SELF-CHECK', 'PASS' if ok else 'FAIL')

    res = {'base': base, 'faults': {}}
    print(f'\nSag propagation (fault r={FAULT_R} ohm). Voltage (pu) at candidate HPT buses:')
    hdr = 'fault@bus | ' + ' | '.join(f'HPT@{b:>2}' for b in HPT_BUSES) + ' | minV(net)'
    print(hdr); print('-' * len(hdr))
    for fb in FAULT_BUSES:
        p = fault_case(fb)
        res['faults'][fb] = p
        row = ' | '.join(f'{p[str(b)]:6.3f}' for b in HPT_BUSES)
        print(f'{fb:>9} | {row} |   {min(p.values()):.3f}')

    (HERE / 'w1_results.json').write_text(json.dumps(res, indent=1))

    # figure: feeder voltage profile (main feeder buses 1-18) per fault location
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        main_feeder = [str(i) for i in range(1, 19)]
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(range(1, 19), [base[b] for b in main_feeder], 'k--', lw=1.2, label='no fault')
        for fb in FAULT_BUSES:
            ax.plot(range(1, 19), [res['faults'][fb][b] for b in main_feeder],
                    marker='o', ms=3, lw=1.3, label=f'fault @ {fb}')
        for hb in HPT_BUSES:
            if hb <= 18:
                ax.axvline(hb, color='gray', alpha=0.3)
                ax.text(hb, 1.02, f'HPT{hb}', ha='center', fontsize=8)
        ax.set_xlabel('main-feeder bus (1-18)'); ax.set_ylabel('voltage (pu)')
        ax.set_title('IEEE-33 sag propagation: same fault, different sag at each HPT location')
        ax.grid(alpha=0.4); ax.legend(fontsize=8, ncol=2); ax.set_ylim(0, 1.1)
        fig.tight_layout(); fig.savefig(HERE / 'fig_w1_sag_propagation.png', dpi=150)
        print('\nfigure saved: fig_w1_sag_propagation.png')
    except Exception as e:
        print('figure skipped:', e)

    print('W1 TESTBED DONE')


if __name__ == '__main__':
    main()
