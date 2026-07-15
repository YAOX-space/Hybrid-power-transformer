from version_2.sac.calibrate_hpt_energy_proxy_from_sweep import _read_rows as read_energy_rows
from version_2.sac.calibrate_hpt_proxy_from_sweep import _read_rows as read_reg_rows


def test_reg_calibration_parser_accepts_action_semantics_column(tmp_path):
    csv_path = tmp_path / "reg.csv"
    csv_path.write_text(
        "model,topology,grid_pu,cmd_m_reg_d,reg_d_mean,lv_pu_mean,vdc_mean,action_semantics\n"
        "m,topology1,0.9,0.4,0.4,1.0,800,fixed_command_through_controller_projection\n",
        encoding="utf-8",
    )
    rows = read_reg_rows(csv_path)
    assert rows[0]["grid_pu"] == 0.9
    assert rows[0]["action_semantics"] == "fixed_command_through_controller_projection"


def test_energy_calibration_parser_accepts_action_semantics_column(tmp_path):
    csv_path = tmp_path / "energy.csv"
    csv_path.write_text(
        "model,topology,grid_pu,cmd_m_energy_d,energy_d_mean,vdc_mean,energy_i_rms_mean,action_semantics\n"
        "m,topology2,1.1,0.2,0.2,820,100,fixed_energy_command_through_controller_projection\n",
        encoding="utf-8",
    )
    rows = read_energy_rows(csv_path)
    assert rows[0]["grid_pu"] == 1.1
    assert rows[0]["action_semantics"] == "fixed_energy_command_through_controller_projection"
