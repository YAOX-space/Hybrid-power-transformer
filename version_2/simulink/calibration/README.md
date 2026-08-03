# Calibration

Focused Simulink-side calibration scripts that do not fit the general collector
or sweep workflows.

## Topology2 Energy Branch

`calibrate_hpt_v2_topology2_energy_branch.m` sweeps topology2 energy-bridge
commands while holding a regulating trajectory fixed.  Use it to diagnose
energy-command direction, DC-link response, and LV fault/recovery interaction.

Minimal pilot command from the Simulink root:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/version_2/simulink'); hpt_energy_calib_run_label='stage2_t2_energy_pilot'; hpt_energy_calib_faults={'lvrt090_reg014_down004',0.90,0.14,0.14,-0.04;'hvrt110_reg000_rec024',1.10,0.00,0.00,0.24}; hpt_energy_calib_d_values=[-0.30 0.00 0.30]; hpt_energy_calib_q_values=0.0; hpt_energy_calib_chop_values=780.0; hpt_energy_calib_rchop_scales=0.65; run(fullfile(pwd,'calibration','calibrate_hpt_v2_topology2_energy_branch.m'));"
```

Important: the script must inject `hpt_traj_t` and `hpt_traj_action` through
`SimulationInput`; older pilot rows where `cmd_m_energy_d_mean` stayed zero for
nonzero requested commands are diagnostic only and must not be used for proxy
training.
