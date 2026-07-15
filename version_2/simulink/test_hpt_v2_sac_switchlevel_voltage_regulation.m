% test_hpt_v2_sac_switchlevel_voltage_regulation
% Step-4 validation for the trained HPT SAC actor on the physical
% switch-level Simulink models.
%
% This is an exploratory/regression script, not a surrogate-env test.  It
% rebuilds topology1 and topology2, enables the exported SAC actor, and runs
% steady sag/nominal/swell source-voltage cases directly on the switch-level
% power-electronics models.

clearvars;
close all;

rootDir = fileparts(mfilename('fullpath'));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
actor = load(actorFile, 'n_obs', 'n_act');
assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
    'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));

cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 200, 210, 6.0, 760, 920;
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 198, 212, 8.0, 760, 930;
};

gridVoltages = [9000, 10000, 11000];
targetPhaseRms = 207.0;
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

    for k = 1:numel(gridVoltages)
        rowCells{end+1} = run_case(M, cases{c, 3}, "baseline", gridVoltages(k), ...
            0.0, 0.0, targetPhaseRms, stopTime, settleStart, Ts); %#ok<SAGROW>
        rowCells{end+1} = run_case(M, cases{c, 3}, "sac_teacher", gridVoltages(k), ...
            1.0, 0.0, targetPhaseRms, stopTime, settleStart, Ts); %#ok<SAGROW>
        rowCells{end+1} = run_case(M, cases{c, 3}, "sac_actor", gridVoltages(k), ...
            1.0, 1.0, targetPhaseRms, stopTime, settleStart, Ts); %#ok<SAGROW>
    end
end

rows = [rowCells{:}];

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_sac_switchlevel_step4');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['switchlevel_sac_step4_' stamp '.mat']);
outCsv = fullfile(outDir, ['switchlevel_sac_step4_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'gridVoltages', 'stopTime', 'settleStart');
writetable(struct2table(rows), outCsv);

fprintf('HPT SAC switch-level step-4 validation complete.\\n');
fprintf('Target phase RMS: %.1f V, settle window: t > %.3f s\\n', targetPhaseRms, settleStart);
fprintf('%-24s %-9s %8s %10s %11s %9s %9s %9s %9s %9s %9s\\n', ...
    'model', 'mode', 'grid', 'LV_RMS', 'unbalance', 'VdcMean', 'VdcMin', ...
    'max|a|', 'regD', 'enD', 'obsN');
for i = 1:numel(rows)
    fprintf('%-24s %-9s %8.0f %10.3f %11.3f %9.3f %9.3f %9.3f %9.3f %9.3f %9.0f\\n', ...
        rows(i).model, rows(i).mode, rows(i).grid_V, rows(i).lv_rms_mean, ...
        rows(i).lv_unbalance, rows(i).vdc_mean, rows(i).vdc_min, ...
        rows(i).action_max_abs, rows(i).reg_d_mean, rows(i).energy_d_mean, rows(i).obs_dim);
end
fprintf('Saved MAT: %s\\n', outMat);
fprintf('Saved CSV: %s\\n', outCsv);

for i = 1:numel(rows)
    if rows(i).mode ~= "sac_actor"
        continue;
    end
    idx = find(strcmp(cases(:, 3), rows(i).model), 1);
    lvLo = cases{idx, 4};
    lvHi = cases{idx, 5};
    ubHi = cases{idx, 6};
    vdcLo = cases{idx, 7};
    vdcHi = cases{idx, 8};
    assert(rows(i).lv_rms_mean >= lvLo && rows(i).lv_rms_mean <= lvHi, ...
        '%s SAC LV RMS out of range at grid %.0f V: %.3f V', ...
        rows(i).model, rows(i).grid_V, rows(i).lv_rms_mean);
    assert(rows(i).lv_unbalance <= ubHi, ...
        '%s SAC unbalance too high at grid %.0f V: %.3f V', ...
        rows(i).model, rows(i).grid_V, rows(i).lv_unbalance);
    assert(rows(i).vdc_mean >= vdcLo && rows(i).vdc_mean <= vdcHi, ...
        '%s SAC DC mean out of range at grid %.0f V: %.3f V', ...
        rows(i).model, rows(i).grid_V, rows(i).vdc_mean);
    assert(rows(i).obs_dim == 24 && rows(i).action_dim == 4, ...
        '%s SAC interface size mismatch at grid %.0f V', rows(i).model, rows(i).grid_V);
    assert(rows(i).action_max_abs <= 0.9501, ...
        '%s SAC action exceeds modulation limit at grid %.0f V: %.3f', ...
        rows(i).model, rows(i).grid_V, rows(i).action_max_abs);
end
fprintf('HPT SAC switch-level voltage regulation assertions passed.\\n');

function row = run_case(M, modelName, mode, gridVoltage, sacEnable, policyMode, targetPhaseRms, stopTime, settleStart, Ts)
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');

    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > settleStart;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);

    row = struct();
    row.model = string(modelName);
    row.mode = string(mode);
    row.grid_V = gridVoltage;
    if sacEnable <= 0.5
        row.action_semantics = "controller_disabled";
    elseif policyMode >= 0.5
        row.action_semantics = "actor_raw_unlogged_controller_projected";
    elseif policyMode <= -0.5
        row.action_semantics = "fixed_command_through_controller_projection";
    else
        row.action_semantics = "teacher_raw_unlogged_controller_projected";
    end
    row.action_raw_available = policyMode <= -0.5;
    row.action_projected_available = true;
    row.action_effective_available = true;
    row.action_raw_source = "unlogged_except_fixed_mode";
    row.action_projected_source = "HPTSAC_action";
    row.action_effective_source = "HPTSAC_action";
    row.raw_m_reg_d = NaN;
    row.raw_m_reg_q = NaN;
    row.raw_m_energy_d = NaN;
    row.raw_m_energy_q = NaN;
    row.lv_rms_mean = mean(phaseRms);
    row.lv_rms_a = phaseRms(1);
    row.lv_rms_b = phaseRms(2);
    row.lv_rms_c = phaseRms(3);
    row.lv_unbalance = max(phaseRms) - min(phaseRms);
    row.lv_abs_err = abs(row.lv_rms_mean - targetPhaseRms);
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.obs_dim = size(obsRows, 1);
    row.action_dim = size(actRows, 1);
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_last_reg_d_mean = mean(obsRows(9, round(end*0.7):end));
    row.obs_sag_flag_mean = mean(obsRows(13, round(end*0.7):end));
    row.obs_swell_flag_mean = mean(obsRows(14, round(end*0.7):end));
    row.obs_topology1_flag_mean = mean(obsRows(15, round(end*0.7):end));
    row.obs_topology2_flag_mean = mean(obsRows(16, round(end*0.7):end));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_action_max_abs = max(abs(actRows(1:2, :)), [], 'all');
    row.energy_action_max_abs = max(abs(actRows(3:4, :)), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.energy_q_mean = mean(actRows(4, round(end*0.7):end));
    row.projected_m_reg_d_mean = row.reg_d_mean;
    row.projected_m_reg_q_mean = row.reg_q_mean;
    row.projected_m_energy_d_mean = row.energy_d_mean;
    row.projected_m_energy_q_mean = row.energy_q_mean;
    row.effective_m_reg_d_mean = row.reg_d_mean;
    row.effective_m_reg_q_mean = row.reg_q_mean;
    row.effective_m_energy_d_mean = row.energy_d_mean;
    row.effective_m_energy_q_mean = row.energy_q_mean;
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
