import numpy as np

from version_2.sac.build_hpt_switch_dataset import (
    FEATURE_NAMES,
    TARGET_NAMES,
    featurize,
    read_rows,
    split_indices,
)


def test_switch_dataset_parser_keeps_action_semantics_and_featurizes_effective_actions(tmp_path):
    csv_path = tmp_path / "sweep.csv"
    csv_path.write_text(
        "model,topology,grid_pu,target_phase_rms,raw_m_reg_d,raw_m_reg_q,"
        "effective_m_reg_d_mean,effective_m_reg_q_mean,lv_pu_mean,vdc_mean,"
        "vdc_min,vdc_max,lv_unbalance,action_semantics\n"
        "m,topology2,0.9,207,0.4,0.1,0.25,0.05,0.98,760,740,805,2.07,"
        "fixed_command_through_controller_projection\n",
        encoding="utf-8",
    )

    rows = read_rows(csv_path)
    x, y, meta = featurize(rows[0], "reg")

    assert rows[0]["action_semantics"] == "fixed_command_through_controller_projection"
    assert x[FEATURE_NAMES.index("topology2")] == 1.0
    assert x[FEATURE_NAMES.index("raw_m_reg_d")] == 0.4
    assert x[FEATURE_NAMES.index("effective_m_reg_d")] == 0.25
    assert x[FEATURE_NAMES.index("controller_enabled")] == 1.0
    assert y[TARGET_NAMES.index("vdc_pu_mean")] == 0.95
    assert np.isclose(y[TARGET_NAMES.index("lv_unbalance_pu")], 0.01)
    assert meta["topology"] == "topology2"


def test_switch_dataset_split_is_complete_and_nonoverlapping():
    splits = split_indices(20, seed=7)
    merged = np.concatenate([splits["train"], splits["val"], splits["test"]])

    assert len(np.unique(merged)) == 20
    assert set(merged.tolist()) == set(range(20))
    assert len(splits["train"]) > len(splits["val"])
    assert len(splits["test"]) > 0


def test_switch_dataset_featurizes_fault_sweep_rows():
    row = {
        "topology": "topology1",
        "fault_pu": 0.9,
        "target_phase_rms": 207.0,
        "raw_m_reg_d": 0.4,
        "effective_m_reg_d_mean": 0.32,
        "lv_fault_rms_mean": 200.0,
        "vdc_mean": 760.0,
        "vdc_min": 700.0,
        "vdc_max": 820.0,
        "lv_unbalance": 2.07,
        "action_semantics": "fixed_fault_command_through_controller_projection",
    }

    x, y, meta = featurize(row, "fault")

    assert x[FEATURE_NAMES.index("is_fault_sweep")] == 1.0
    assert x[FEATURE_NAMES.index("grid_pu")] == 0.9
    assert x[FEATURE_NAMES.index("raw_m_reg_d")] == 0.4
    assert x[FEATURE_NAMES.index("effective_m_reg_d")] == 0.32
    assert np.isclose(y[TARGET_NAMES.index("lv_pu_mean")], 200.0 / 207.0)
    assert np.isclose(y[TARGET_NAMES.index("vdc_min_pu")], 700.0 / 800.0)
    assert meta["action_semantics"] == "fixed_fault_command_through_controller_projection"


def test_switch_dataset_marks_controller_disabled_fault_rows():
    row = {
        "topology": "topology2",
        "fault_pu": 1.1,
        "target_phase_rms": 207.0,
        "raw_m_reg_d": 0.0,
        "effective_m_reg_d_mean": 0.0,
        "lv_fault_rms_mean": 208.0,
        "vdc_mean": 770.0,
        "vdc_min": 760.0,
        "vdc_max": 820.0,
        "lv_unbalance": 0.0,
        "action_semantics": "controller_disabled_fault_sweep",
    }

    x, _, _ = featurize(row, "fault")

    assert x[FEATURE_NAMES.index("controller_enabled")] == 0.0
    assert x[FEATURE_NAMES.index("is_fault_sweep")] == 1.0
