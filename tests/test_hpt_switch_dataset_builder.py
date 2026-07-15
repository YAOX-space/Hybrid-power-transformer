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
