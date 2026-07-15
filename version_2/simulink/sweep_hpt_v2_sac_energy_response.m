% sweep_hpt_v2_sac_energy_response
% Calibrate the HPT SAC energy-converter proxy against the physical
% switch-level topology1/topology2 Simulink models.
%
% The regulating converter stays on the existing voltage loop:
%   hpt_sac_enable = 0
% The energy converter is driven by fixed SAC energy commands:
%   hpt_sac_policy_mode = -1
%   hpt_sac_energy_enable = 1
%
% This isolates how [m_energy_d,m_energy_q] changes the DC link and the
% energy-side current on each topology.

clearvars;
close all;

rootDir = fileparts(mfilename('fullpath'));
cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2';
};

gridVoltages = [9000, 10000, 11000];
targetPhaseRms = 207.0;
energyActions = [
    0.00,  0.00;
    0.20,  0.00;
   -0.20,  0.00;
    0.40,  0.00;
   -0.40,  0.00;
    0.00,  0.20;
    0.00, -0.20;
];
stopTime = 0.08;
settleStart = 0.05;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};

    for gv = 1:numel(gridVoltages)
        for a = 1:size(energyActions, 1)
            rowCells{end+1} = run_energy_case( ...
                M, topology, gridVoltages(gv), targetPhaseRms, ...
                energyActions(a, 1), energyActions(a, 2), ...
                stopTime, settleStart, Ts); %#ok<SAGROW>
        end
    end
end

rows = [rowCells{:}];

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_sac_energy_sweep');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['hpt_v2_sac_energy_sweep_' stamp '.mat']);
outCsv = fullfile(outDir, ['hpt_v2_sac_energy_sweep_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'gridVoltages', 'energyActions', ...
    'stopTime', 'settleStart');
writetable(struct2table(rows), outCsv);

fprintf('HPT SAC fixed-energy switch-level sweep complete.\n');
fprintf('%-10s %8s %8s %8s %10s %9s %9s %10s %9s\n', ...
    'topology', 'grid', 'cmdEd', 'cmdEq', 'LV_RMS', 'VdcMean', ...
    'VdcMin', 'IengRMS', 'obsN');
for i = 1:numel(rows)
    fprintf('%-10s %8.0f %8.3f %8.3f %10.3f %9.3f %9.3f %10.3f %9.0f\n', ...
        rows(i).topology, rows(i).grid_V, rows(i).cmd_m_energy_d, ...
        rows(i).cmd_m_energy_q, rows(i).lv_rms_mean, rows(i).vdc_mean, ...
        rows(i).vdc_min, rows(i).energy_i_rms_mean, rows(i).obs_dim);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = run_energy_case(M, topology, gridVoltage, targetPhaseRms, ...
    mEnergyD, mEnergyQ, stopTime, settleStart, Ts)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = in.setVariable('hpt_sac_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_d', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', mEnergyD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', mEnergyQ, 'Workspace', M);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    Ienergy = out.get('Energy_Iabc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');

    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > settleStart;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));
    iRms = sqrt(mean(Ienergy(idx, 1:3).^2, 1));
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    tailStart = max(1, round(size(actRows, 2) * 0.7));
    vdcTailStart = max(1, round(size(Vdc, 1) * 0.7));

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.grid_V = gridVoltage;
    row.grid_pu = gridVoltage / 10000.0;
    row.target_phase_rms = targetPhaseRms;
    row.cmd_m_energy_d = mEnergyD;
    row.cmd_m_energy_q = mEnergyQ;
    row.lv_rms_mean = mean(phaseRms);
    row.lv_unbalance = max(phaseRms) - min(phaseRms);
    row.lv_pu_mean = row.lv_rms_mean / targetPhaseRms;
    row.vdc_mean = mean(Vdc(vdcTailStart:end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.energy_i_rms_mean = mean(iRms);
    row.energy_i_unbalance = max(iRms) - min(iRms);
    row.obs_dim = size(obsRows, 1);
    row.action_dim = size(actRows, 1);
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, tailStart:end));
    row.reg_q_mean = mean(actRows(2, tailStart:end));
    row.energy_d_mean = mean(actRows(3, tailStart:end));
    row.energy_q_mean = mean(actRows(4, tailStart:end));
end

function y = orient_channels(x, nChannels)
    if size(x, 1) == nChannels
        y = x;
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end
