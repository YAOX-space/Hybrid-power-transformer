"""test_env_envelope_unification — HPTFRTEnvV2 must trip on the VERSIONED frt_v2 envelope, not the
legacy frt-v1 residual-0.05 / static-1.32 boundary (audit round-4 B)."""
import numpy as np
import pytest
from hpt_frt.common import frt_v2 as FV2
from hpt_frt.device import frt_env as L
from hpt_frt.device.frt_env_v2 import HPTFRTEnvV2

SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='sym3ph', target_V_pu=0.5,
          grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=1)


# ---- the unified versioned envelope interface ----
def test_lvrt_envelope_hold_625ms_and_reach_2s():
    res = 0.4
    assert FV2.lvrt_lower_env(0.0, res) == res                 # hold floor IS the residual (no -0.05)
    assert FV2.lvrt_lower_env(0.624, res) == res               # still residual at 624 ms
    assert FV2.lvrt_lower_env(0.625, res) == res               # boundary of the 625 ms hold
    mid = FV2.lvrt_lower_env(1.3125, res)                       # halfway hold(0.625)->reach(2.0)
    assert res < mid < 0.9 and mid == pytest.approx(res + (0.9 - res) * 0.5, abs=1e-9)
    assert FV2.lvrt_lower_env(2.0, res) == pytest.approx(0.9)   # recovered to 0.9 by 2 s
    assert FV2.lvrt_lower_env(3.0, res) == pytest.approx(0.9)


def test_hvrt_envelope_500ms_1s_steps():
    assert FV2.hvrt_upper_env(0.4) == 1.30
    assert FV2.hvrt_upper_env(0.5) == 1.30                      # <=500 ms
    assert FV2.hvrt_upper_env(0.6) == 1.20                      # (500ms,1s]
    assert FV2.hvrt_upper_env(1.0) == 1.20
    assert FV2.hvrt_upper_env(1.1) == 1.10                      # >1 s


def test_within_envelope_uses_solver_tol_only():
    res = 0.5
    # exactly on boundary passes; below by more than tol fails
    assert FV2.within_envelope('LVRT', 0.1, res, res)
    assert not FV2.within_envelope('LVRT', 0.1, res, res - 0.05)
    # the legacy -0.05 slack would have passed res-0.05; the versioned boundary rejects it
    assert FV2.within_envelope('LVRT', 0.1, res, res - FV2.DEFAULT_SOLVER_TOL / 2)


# ---- the V2 ENV trips on the versioned boundary, not the legacy one ----
def _trip_at(env_cls, v2p, residual=0.5, t_rel_real=0.1):
    e = env_cls([{**SC, 'target_V_pu': residual}]); e.reset()
    e._sc = {**SC, 'target_V_pu': residual}
    e.t = SC['t_fault'] + t_rel_real * L.TSCALE   # compressed time for real t_rel
    e.V2p = v2p
    return e._lvrt_floor(e.t - e._sc['t_fault']), e._trip_tol()


def test_v2_floor_is_versioned_not_legacy():
    res = 0.5
    floor_v2, tol = _trip_at(HPTFRTEnvV2, res, residual=res)
    floor_legacy = L.lvrt_envelope(0.1 * L.TSCALE, res)
    assert floor_v2 == pytest.approx(res)                      # versioned: floor == residual
    assert floor_legacy == pytest.approx(res - 0.05)           # legacy: residual - 0.05
    assert floor_v2 != floor_legacy
    assert tol == FV2.DEFAULT_SOLVER_TOL


def test_v2_trips_a_residual_minus_004_that_legacy_would_pass():
    # V+ at residual-0.04: ABOVE the legacy floor (residual-0.05) so legacy would NOT trip;
    # BELOW the versioned floor (residual) so V2 MUST trip.
    res = 0.5
    e = HPTFRTEnvV2([{**SC, 'target_V_pu': res}]); e.reset()
    e._sc = {**SC, 'target_V_pu': res}
    t_rel_real = 0.1
    e.t = SC['t_fault'] + t_rel_real * L.TSCALE
    # versioned check
    assert not FV2.within_envelope('LVRT', t_rel_real, res, res - 0.04)
    # drive one step at V+=res-0.04 by forcing state then running the trip branch
    e.V2p = res - 0.04
    # replicate the env's trip predicate
    tripped_v2 = e.V2p < e._lvrt_floor(e.t - e._sc['t_fault']) - e._trip_tol()
    assert tripped_v2 is True
    # the legacy env at the same point would NOT trip
    leg = L.HPTFRTEnv([{**SC, 'target_V_pu': res}]); leg.reset(); leg._sc = {**SC, 'target_V_pu': res}
    leg.t = e.t
    tripped_legacy = (res - 0.04) < leg._lvrt_floor(leg.t - leg._sc['t_fault']) - leg._trip_tol()
    assert tripped_legacy is False


def test_v2_hvrt_ceiling_is_time_varying():
    e = HPTFRTEnvV2([{**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph'}]); e.reset()
    e._sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph'}
    # at real 0.4 s -> 1.30 ; at real 0.9 s -> 1.20 (legacy was a flat 1.32 both times)
    assert e._hvrt_ceiling(0.4 * L.TSCALE) == 1.30
    assert e._hvrt_ceiling(0.9 * L.TSCALE) == 1.20
    assert L.HPTFRTEnv([SC])._hvrt_ceiling(0.9 * L.TSCALE) == pytest.approx(1.32)  # legacy static
