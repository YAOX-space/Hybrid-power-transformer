import json

from version_2.sac.campaigns.run_hpt_family_specialist_matrix import summarize_rows


def test_summary_uses_active_voltage_survival_dc_bounds(tmp_path) -> None:
    rows = [
        {
            "family_eval_label": "case_a",
            "controller": "family_sac_after_finetune",
            "voltage_survival_pass": 0,
            "envelope_pass": 1,
            "recovery_envelope_pass": 1,
            "gbt_vdc_survive_pass": 1,
            "gbt_grid_current_limit_pass": 1,
            "vdc_min": 640.0,
            "vdc_max": 980.0,
            "control_score": 10.0,
            "grid_current_peak_pu": 1.2,
            "envelope_violation_max_pu": 0.0,
        },
        {
            "family_eval_label": "case_b",
            "controller": "family_sac_after_finetune",
            "voltage_survival_pass": 1,
            "envelope_pass": 1,
            "recovery_envelope_pass": 1,
            "gbt_vdc_survive_pass": 1,
            "gbt_grid_current_limit_pass": 1,
            "vdc_min": 670.0,
            "vdc_max": 990.0,
            "control_score": 9.0,
            "grid_current_peak_pu": 1.1,
            "envelope_violation_max_pu": 0.0,
        },
    ]
    output = tmp_path / "summary.json"

    summary = summarize_rows(rows, output)

    controller = summary["family_sac_after_finetune"]
    assert controller["vdc_pass_count"] == 1
    assert controller["gbt_vdc_survive_pass_count"] == 2
    assert json.loads(output.read_text(encoding="utf-8")) == summary
