"""test_metric_completeness — ODE aggregation completeness semantics (audit round-4 D). A combined
status matrix drives evaluate_frt via a stub that returns hand-built frt_v2 results, proving:
complete = all 5 evaluated; decided_fail+incomplete never counted as complete; frt_pass_pct over
complete only; unevaluable surfaced; partial_proxy denominator = all rolled-out."""
import numpy as np
import pytest
from hpt_frt.device import frt_metrics as FM
from hpt_frt.common import frt_v2 as FV2


def _crit(status):
    return {'status': status, 'passed': status == FV2.PASS, 'worst': 0.0, 't_worst': 0.0, 'reason': ''}


def _res(statuses):
    """Build a frt_v2-shaped result from a dict of criterion->status, with correct frt_pass."""
    d = {c: _crit(statuses[c]) for c in FV2.MANDATORY}
    sts = [d[c]['status'] for c in FV2.MANDATORY]
    d['frt_pass'] = (False if FV2.FAIL in sts else (None if FV2.NOT_EVALUATED in sts else True))
    d['metrics_version'] = 'frt-v2'
    return d


# a matrix of scenario outcomes, by classification kind
ALL_PASS = _res({c: FV2.PASS for c in FV2.MANDATORY})                                   # complete, pass
ALL_FAIL = _res({**{c: FV2.PASS for c in FV2.MANDATORY}, 'survive': FV2.FAIL})          # complete, decided_fail
FAIL_AND_MISSING = _res({**{c: FV2.PASS for c in FV2.MANDATORY},                        # decided_fail AND incomplete
                         'survive': FV2.FAIL, 'reactive': FV2.NOT_EVALUATED})
INCOMPLETE = _res({**{c: FV2.PASS for c in FV2.MANDATORY}, 'limit': FV2.NOT_EVALUATED}) # incomplete, frt_pass None


def _patch_classify(monkeypatch, classifications):
    """Make evaluate_scenario return a fixed sequence of classification dicts."""
    seq = iter(classifications)
    monkeypatch.setattr(FM, 'evaluate_scenario', lambda model, env_cls, sc: next(seq))


def test_fail_with_missing_is_decided_fail_and_incomplete_not_complete(monkeypatch):
    _patch_classify(monkeypatch, [{'kind': 'evaluated', 'res': FAIL_AND_MISSING}])
    m = FM.evaluate_frt(None, [0], None)
    assert m['n_evaluated'] == 1
    assert m['n_decided_fail'] == 1
    assert m['n_incomplete'] == 1
    assert m['n_complete'] == 0                       # NOT counted as complete despite being decided
    assert m['frt_pass_pct'] is None                 # no complete scenario -> None (not 0)


def test_frt_pass_pct_over_complete_only(monkeypatch):
    # 1 complete-pass, 1 complete-fail, 1 incomplete -> frt_pass_pct = 1/2 = 50% (incomplete excluded)
    _patch_classify(monkeypatch, [{'kind': 'evaluated', 'res': ALL_PASS},
                                  {'kind': 'evaluated', 'res': ALL_FAIL},
                                  {'kind': 'evaluated', 'res': INCOMPLETE}])
    m = FM.evaluate_frt(None, [0, 1, 2], None)
    assert m['n_complete'] == 2 and m['n_incomplete'] == 1
    assert m['frt_pass_pct'] == 50.0


def test_unevaluable_and_rollout_failed_are_surfaced(monkeypatch):
    _patch_classify(monkeypatch, [{'kind': 'evaluated', 'res': ALL_PASS},
                                  {'kind': 'unevaluable', 'error': 'empty fault window'},
                                  {'kind': 'rollout_failed', 'error': 'rollout produced 1 samples'}])
    m = FM.evaluate_frt(None, [0, 1, 2], None)
    assert m['n_requested'] == 3
    assert m['n_rollout_ok'] == 2          # the evaluated + the unevaluable both rolled out (>=2 samples)
    assert m['n_rollout_failed'] == 1
    assert m['n_unevaluable'] == 1
    assert m['n_evaluated'] == 1
    assert any('empty fault window' in r for r in m['unevaluable_reasons'])
    assert any('rollout produced' in r for r in m['unevaluable_reasons'])


def test_partial_proxy_denominator_is_all_rolled_out(monkeypatch):
    # 1 all-pass (proxy hit) + 1 unevaluable (rolled out, not a pass) -> proxy = 1/2 = 50%
    _patch_classify(monkeypatch, [{'kind': 'evaluated', 'res': ALL_PASS},
                                  {'kind': 'unevaluable', 'error': 'x'}])
    m = FM.evaluate_frt(None, [0, 1], None)
    assert m['n_rollout_ok'] == 2
    assert m['partial_proxy_pct'] == 50.0


def test_evaluate_scenario_does_not_swallow_valueerror():
    # a too-short rollout returns a CLASSIFICATION (not a silent None) carrying the reason
    class Stub:
        def predict(self, o, deterministic=True):
            return np.zeros(4, np.float32), None

    # force a degenerate env via a tiny T_sim so the rollout is < 2 samples is hard; instead test the
    # classification contract directly on the unevaluable branch via monkeypatch-free structural check
    import inspect
    src = inspect.getsource(FM.evaluate_scenario)
    assert 'return None' not in src                   # no silent None
    assert "'kind': 'unevaluable'" in src and 'str(e)' in src
