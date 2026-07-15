from version_2.sac.measure_hpt_proxy_gap import (
    analyze_reg_sweep,
    projected_reg_command,
    summarize,
)


def test_projected_reg_command_blocks_wrong_sign_support():
    assert projected_reg_command(-0.5, 0.90) == 0.0
    assert projected_reg_command(0.5, 1.10) == 0.0
    assert projected_reg_command(0.4, 0.90) == 0.4


def test_reg_sweep_gap_summary_uses_calibration_table():
    calibration = {
        "topologies": {
            "topology1": {
                "source_gain": 0.8,
                "source_bias": 0.1,
                "reg_gain": 0.2,
                "vdc_base_pu": 1.0,
                "vdc_reg_abs_cost": 0.1,
                "response_table": [
                    {"grid_pu": 0.9, "reg_d_mean": 0.0, "lv_pu_mean": 0.8, "vdc_pu_mean": 1.0},
                    {"grid_pu": 0.9, "reg_d_mean": 0.4, "lv_pu_mean": 1.0, "vdc_pu_mean": 0.9},
                ],
            }
        }
    }
    rows = [
        {
            "model": "toy",
            "topology": "topology1",
            "grid_pu": 0.9,
            "target_phase_rms": 207.0,
            "cmd_m_reg_d": 0.4,
            "reg_d_mean": 0.4,
            "lv_pu_mean": 1.0,
            "vdc_mean": 720.0,
            "vdc_min": 710.0,
            "lv_unbalance": 0.0,
        }
    ]

    gap_rows = analyze_reg_sweep(rows, calibration)
    summary = summarize(gap_rows)

    assert gap_rows[0]["proxy_table_lv_pu"] == 1.0
    assert gap_rows[0]["err_table_lv_pu"] == 0.0
    assert summary["total_rows"] == 1
    assert summary["by_topology"]["topology1"]["reg_table_lv_rmse_pu"] == 0.0
