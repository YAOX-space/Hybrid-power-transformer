# Proxy Calibration And Alignment

- `build_hpt_family_proxy_matrix.py`: build family-specific calibration rows.
- `calibrate_hpt_frt_proxy_from_matrix.py`: fit the active averaged proxy.
- `fit_hpt_energy_cmd_response.py`: distinguish commanded and measured energy
  branch response.
- `measure_hpt_frt_proxy_gap.py`: metric-level proxy/Simulink gap.
- `measure_hpt_reward_alignment.py`: action ranking and reward alignment.
- `verify_hpt_proxy_rollout_alignment.py`: trajectory rollout alignment.

Calibration, reward alignment, and rollout alignment are separate gates. A good
fit at calibration points does not by itself authorize SAC promotion.
