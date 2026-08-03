import json
import math

from version_2.sac.hpt_voltage_sac_env import (
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)


def _row(reg_d: float, energy_q: float, vdc_min: float) -> dict:
    return {
        "category": "LVRT",
        "fault_phase_key": "a",
        "fault_duration_s": 0.2,
        "grid_pu": 0.6,
        "cmd_m_reg_d": reg_d,
        "cmd_m_reg_q": 0.0,
        "cmd_m_energy_d": 0.0,
        "cmd_m_energy_q": energy_q,
        "vdc_min_pu": vdc_min,
        "voltage_survival_pass": False,
    }


def _env(tmp_path) -> HPTVoltageSACEnv:
    rows = [_row(0.12, 0.0, 0.70), _row(0.03, 0.60, 0.78)]
    calibration = {
        "schema": "hpt_proxy_calibration_v1",
        "topologies": {
            "topology2": {
                "fault_joint_response_table": rows,
                "fault_conventional_response_table": [],
            }
        },
    }
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    scenario = HPTVoltageScenario(
        topology="topology2",
        grid_pu=0.6,
        fault_phase_key="a",
        duration_s=0.405,
        category="LVRT",
        fault_type="1ph_g",
        fault_start_s=0.08,
        fault_duration_s=0.2,
    )
    return HPTVoltageSACEnv(
        [scenario],
        config=HPTVoltageEnvConfig(calibration_path=str(path)),
        seed=1,
        train_mode=False,
    )


def test_joint_support_rejects_unsampled_cross_combination(tmp_path):
    env = _env(tmp_path)
    assert env._calibration_support_violation(0.03, 0.0, 0.0, 0.60) == 0.0
    assert env._calibration_support_violation(0.12, 0.0, 0.0, 0.60) > 0.0


def test_sparse_joint_metric_has_conservative_failed_fallback(tmp_path):
    env = _env(tmp_path)
    value = env._calibrated_fault_metric(0.6, 0.12, 0.0, 0.0, 0.60, "vdc_min_pu")
    assert value is not None
    assert math.isfinite(value)
