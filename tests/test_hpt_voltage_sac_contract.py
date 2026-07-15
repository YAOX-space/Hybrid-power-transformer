import numpy as np
import joblib

from version_2.sac.build_hpt_switch_dataset import FEATURE_NAMES
from version_2.sac.hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
    classify_hpt_operating_condition,
    teacher_action,
)


class _TinySafetyClassifier:
    def predict_proba(self, x):
        raw_reg_d = x[:, FEATURE_NAMES.index("raw_m_reg_d")]
        safe_prob = np.where(raw_reg_d > 0.5, 0.10, 0.95)
        return np.column_stack([1.0 - safe_prob, safe_prob])


def test_hpt_sac_env_contract_is_24_obs_4_action():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.9)],
        train_mode=False,
    )

    obs, _ = env.reset()

    assert env.observation_space.shape == (OBS_DIM_HPT,) == (24,)
    assert env.action_space.shape == (ACT_DIM_HPT,) == (4,)
    assert obs.shape == (24,)
    assert np.all(np.isfinite(obs))


def test_teacher_boosts_sag_and_absorbs_swell():
    sag_env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        train_mode=False,
    )
    sag_obs, _ = sag_env.reset()
    sag_action = teacher_action(sag_obs)

    swell_env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology2", grid_pu=1.10)],
        train_mode=False,
    )
    swell_obs, _ = swell_env.reset()
    swell_action = teacher_action(swell_obs)

    assert sag_action.shape == (4,)
    assert swell_action.shape == (4,)
    assert sag_action[0] > 0.0
    assert swell_action[0] < 0.0


def test_corrective_action_improves_voltage_error_on_sag():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        train_mode=False,
    )
    obs, _ = env.reset()
    initial_error = abs(1.0 - obs[0])

    for _ in range(10):
        action = teacher_action(obs)
        obs, _, terminated, truncated, _ = env.step(action)
        assert not terminated
        if truncated:
            break

    assert abs(1.0 - obs[0]) < initial_error


def test_fault_transition_features_latch_and_recover():
    env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.85,
                duration_s=0.24,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.04,
                fault_duration_s=0.08,
            )
        ],
        train_mode=False,
    )
    obs, _ = env.reset()
    assert obs[16] == 0.0

    saw_fault = False
    saw_recovery = False
    for _ in range(140):
        obs, _, terminated, truncated, _ = env.step(teacher_action(obs))
        assert not terminated
        saw_fault = saw_fault or bool(obs[16] > 0.5)
        saw_recovery = saw_recovery or bool(obs[17] > 0.5)
        if truncated:
            break

    assert saw_fault
    assert saw_recovery


def test_default_scenarios_cover_both_topologies_and_frt_types():
    from version_2.sac.hpt_voltage_sac_env import default_hpt_voltage_scenarios

    scenarios = default_hpt_voltage_scenarios()
    topologies = {s.topology for s in scenarios}
    categories = {s.category for s in scenarios}
    fault_types = {s.fault_type for s in scenarios}

    assert topologies == {"topology1", "topology2"}
    assert {"steady", "LVRT", "HVRT"} <= categories
    assert {"sym3ph", "1ph_g", "2ph", "2ph_g", "swell_3ph", "swell_1ph"} <= fault_types


def test_fault_condition_classifier_covers_sag_swell_and_asymmetry():
    assert classify_hpt_operating_condition(1.00, 0.00, grid_pu=1.00) == "nominal"
    assert classify_hpt_operating_condition(0.90, 0.00, grid_pu=0.90) == "sag"
    assert classify_hpt_operating_condition(1.10, 0.00, grid_pu=1.10) == "swell"
    assert classify_hpt_operating_condition(0.92, 0.08, grid_pu=0.90) == "asymmetric_sag"
    assert classify_hpt_operating_condition(1.08, 0.08, grid_pu=1.12) == "asymmetric_swell"


def test_env_reports_safety_classifier_unsafe_action(tmp_path):
    classifier_path = tmp_path / "classifier.joblib"
    joblib.dump(
        {
            "schema": "hpt-safety-classifier-v1",
            "classifier": _TinySafetyClassifier(),
            "feature_names": FEATURE_NAMES,
            "target_names": [],
            "safe_probability_threshold": 0.75,
        },
        classifier_path,
    )
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        config=HPTVoltageEnvConfig(safety_classifier_path=str(classifier_path)),
        train_mode=False,
    )
    env.reset()

    _, _, _, _, info = env.step(np.asarray([0.8, 0.0, 0.0, 0.0], dtype=np.float32))

    assert info["safety_safe_probability"] == 0.10
    assert info["safety_threshold"] == 0.75
    assert info["safety_unsafe"] is True
