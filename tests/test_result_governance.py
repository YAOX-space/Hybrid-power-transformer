"""test_result_governance — ACTIVE result directories must not contain unversioned / frt-v1 result
artifacts (audit round-4 G.8). Legacy artifacts live only under legacy_pre_audit/. This scans the
real tree, so a future stray legacy MAT in an active dir fails the build."""
from pathlib import Path
import scipy.io as sio
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_RESULT_DIRS = [ROOT / 'src/hpt_frt/network/results', ROOT / 'lab/results']


def _active_mats():
    for d in ACTIVE_RESULT_DIRS:
        if not d.exists():
            continue
        for p in d.rglob('*.mat'):
            if 'legacy_pre_audit' in p.parts:
                continue
            yield p


def _mv(p):
    try:
        S = sio.loadmat(str(p), squeeze_me=True, struct_as_record=False)
    except Exception:
        return '<unreadable>'
    v = S.get('metrics_version', None)
    if v is None:
        return None
    return str(np.ravel(v)[0]) if isinstance(v, np.ndarray) else str(v)


def test_no_unversioned_or_frtv1_mat_in_active_dirs():
    bad = [(str(p.relative_to(ROOT)), _mv(p)) for p in _active_mats() if _mv(p) != 'frt-v2']
    assert not bad, 'active result dir contains non-frt-v2 MAT(s) — move to legacy_pre_audit/:\n' + \
        '\n'.join(f'  {rel}: metrics_version={mv!r}' for rel, mv in bad)


def test_no_frt320_legacy_naming_in_active_dirs():
    bad = []
    for d in ACTIVE_RESULT_DIRS:
        if not d.exists():
            continue
        for p in d.rglob('frt320_*'):
            if 'legacy_pre_audit' not in p.parts:
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, 'legacy frt320_* result files in active dirs (must be under legacy_pre_audit):\n' + \
        '\n'.join(f'  {x}' for x in bad)


def test_legacy_spotcheck_mats_are_isolated():
    # the 20 switching spot-check MATs must be under legacy_pre_audit, not the active simulink_cases root
    sim = ROOT / 'src/hpt_frt/network/results/simulink_cases'
    if not sim.exists():
        pytest.skip('simulink_cases absent')
    root_mats = [p.name for p in sim.glob('*.mat')]      # direct children only
    assert root_mats == [], f'unversioned MATs still in active simulink_cases root: {root_mats}'
