% eval_hpt_v2_sac_raw_switchlevel_smoke
% Diagnostic switch-level evaluation for the final SAC path.
%
% This script intentionally disables execution-layer protection
% (hpt_sac_guard_enable = 0).  It does not assert pass/fail, because its job
% is to expose the remaining gap between the raw actor and the switch-level
% HPT plants.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
dynamicActorFile = fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
assert(exist(dynamicActorFile, 'file') == 2, ...
    'Missing dynamic HPT SAC actor: %s', dynamicActorFile);
actor = load(actorFile, 'n_obs', 'n_act');
assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
    'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));

cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg', 200, 210, 6.0, 760, 920, 196, 214, 650, 235, 180;
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL', 198, 212, 8.0, 760, 930, 194, 220, 620, 235, 180;
};

steadyGridVoltages = [9000, 10000, 11000];
faults = {
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
steadySettleStart = 0.05;
faultStart = 0.035;
faultClear = 0.095;
faultStopTime = 0.16;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};
    sourceBranch = cases{c, 5};

    for k = 1:numel(steadyGridVoltages)
        rowCells{end+1} = run_steady_case(M, topology, "baseline", ...
            steadyGridVoltages(k), 0.0, targetPhaseRms, steadyStopTime, ...
            steadySettleStart, Ts, cases(c, :)); %#ok<SAGROW>
        rowCells{end+1} = run_steady_case(M, topology, ...
            "sac_actor_raw_guard0", steadyGridVoltages(k), 1.0, ...
            targetPhaseRms, steadyStopTime, steadySettleStart, Ts, ...
            cases(c, :)); %#ok<SAGROW>
    end

    close_system(M, 0);
    feval(cases{c, 2});
    M = cases{c, 3};
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        1.0, faultStart, faultClear, faultStopTime);

    for f = 1:size(faults, 1)
        faultName = faults{f, 1};
        faultPu = faults{f, 2};
        configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
            faultStart, faultClear, faultStopTime);
        rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
            "baseline", 0.0, targetPhaseRms, faultStopTime, Ts, faultStart, ...
            faultClear, cases(c, :)); %#ok<SAGROW>
        rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
            "sac_actor_raw_guard0", 1.0, targetPhaseRms, faultStopTime, Ts, ...
            faultStart, faultClear, cases(c, :)); %#ok<SAGROW>
    end
    close_system(M, 0);
end

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_raw_switchlevel_smoke');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['raw_sac_switchlevel_smoke_' stamp '.mat']);
outCsv = fullfile(outDir, ['raw_sac_switchlevel_smoke_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'steadyGridVoltages', ...
    'nominalGridVoltage', 'faultStart', 'faultClear', 'steadyStopTime', ...
    'faultStopTime');
writetable(struct2table(rows), outCsv);

fprintf('Raw SAC guard=0 switch-level diagnostic complete.\n');
fprintf('%-10s %-8s %-11s %-20s %8s %10s %10s %9s %9s %-8s %s\n', ...
    'topology', 'type', 'case', 'mode', 'grid/pu', 'LV_mean', ...
    'LV_recov', 'VdcMin', 'max|a|', 'pass', 'reason');
for i = 1:numel(rows)
    if rows(i).scenario_type == "steady"
        caseValue = rows(i).grid_V;
    else
        caseValue = rows(i).fault_pu;
    end
    fprintf('%-10s %-8s %-11s %-20s %8.2f %10.3f %10.3f %9.3f %9.3f %-8s %s\n', ...
        rows(i).topology, rows(i).scenario_type, rows(i).case_name, ...
        rows(i).mode, caseValue, rows(i).lv_mean, rows(i).lv_recovery_mean, ...
        rows(i).vdc_min, rows(i).action_max_abs, ...
        string(rows(i).within_window), rows(i).window_reason);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = run_steady_case(M, topology, mode, gridVoltage, sacEnable, ...
    targetPhaseRms, stopTime, settleStart, Ts, caseSpec)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = set_common_sac_variables(in, M, sacEnable, 1.0, 0.0, targetPhaseRms);
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

    row = base_row(M, topology, "steady", sprintf("grid_%.0fV", gridVoltage), ...
        mode, gridVoltage, NaN);
    row.lv_mean = mean(phaseRms);
    row.lv_a = phaseRms(1);
    row.lv_b = phaseRms(2);
    row.lv_c = phaseRms(3);
    row.lv_unbalance = max(phaseRms) - min(phaseRms);
    row.lv_recovery_mean = NaN;
    row.lv_peak = max(sqrt(mean(Vlv(:, 1:3).^2, 2)));
    row.lv_min = min(sqrt(mean(Vlv(:, 1:3).^2, 2)));
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.energy_q_mean = mean(actRows(4, round(end*0.7):end));
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));

    [row.within_window, row.window_reason] = assess_steady(row, caseSpec);
end

function row = run_fault_case(M, topology, faultName, faultPu, mode, sacEnable, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear, caseSpec)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = set_common_sac_variables(in, M, sacEnable, 1.0, ...
        double(sacEnable > 0.5) * 2.0, targetPhaseRms);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.025) & t < (faultClear - 0.005);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);

    row = base_row(M, topology, "fault", faultName, mode, NaN, faultPu);
    row.lv_mean = mean(phaseRmsInst(faultIdx));
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak = max(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_min = min(phaseRmsInst(t > faultStart & t < stopTime));
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.energy_q_mean = mean(actRows(4, round(end*0.7):end));
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));

    [row.within_window, row.window_reason] = assess_fault(row, caseSpec);
end

function in = set_common_sac_variables(in, M, sacEnable, policyMode, ...
    actorSelectMode, targetPhaseRms)

    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, ...
        'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
end

function row = base_row(M, topology, scenarioType, caseName, mode, gridVoltage, faultPu)
    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.scenario_type = string(scenarioType);
    row.case_name = string(caseName);
    row.mode = string(mode);
    row.guard_enable = 0.0;
    row.grid_V = gridVoltage;
    row.fault_pu = faultPu;
    row.lv_mean = NaN;
    row.lv_a = NaN;
    row.lv_b = NaN;
    row.lv_c = NaN;
    row.lv_unbalance = NaN;
    row.lv_recovery_mean = NaN;
    row.lv_peak = NaN;
    row.lv_min = NaN;
    row.vdc_mean = NaN;
    row.vdc_min = NaN;
    row.vdc_max = NaN;
    row.action_max_abs = NaN;
    row.reg_d_mean = NaN;
    row.reg_q_mean = NaN;
    row.energy_d_mean = NaN;
    row.energy_q_mean = NaN;
    row.obs_vpu_mean = NaN;
    row.obs_vpos_mean = NaN;
    row.obs_vdcpu_mean = NaN;
    row.obs_verr_mean = NaN;
    row.obs_fault_flag_mean = NaN;
    row.obs_recovery_flag_mean = NaN;
    row.within_window = false;
    row.window_reason = "";
end

function [ok, reason] = assess_steady(row, caseSpec)
    lvLo = caseSpec{6};
    lvHi = caseSpec{7};
    ubHi = caseSpec{8};
    vdcLo = caseSpec{9};
    vdcHi = caseSpec{10};
    reasons = strings(0, 1);
    if row.mode ~= "sac_actor_raw_guard0"
        ok = true;
        reason = "";
        return;
    end
    if ~(row.lv_mean >= lvLo && row.lv_mean <= lvHi)
        reasons(end+1) = "steady_lv"; %#ok<AGROW>
    end
    if ~(row.lv_unbalance <= ubHi)
        reasons(end+1) = "steady_unbalance"; %#ok<AGROW>
    end
    if ~(row.vdc_mean >= vdcLo && row.vdc_mean <= vdcHi)
        reasons(end+1) = "steady_vdc"; %#ok<AGROW>
    end
    if ~(row.action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function [ok, reason] = assess_fault(row, caseSpec)
    lvLo = caseSpec{11};
    lvHi = caseSpec{12};
    vdcLo = caseSpec{13};
    lvPeakHi = caseSpec{14};
    lvMinLo = caseSpec{15};
    reasons = strings(0, 1);
    if row.mode ~= "sac_actor_raw_guard0"
        ok = true;
        reason = "";
        return;
    end
    if ~(row.lv_mean >= lvLo && row.lv_mean <= lvHi)
        reasons(end+1) = "fault_window_lv"; %#ok<AGROW>
    end
    if ~(row.lv_recovery_mean >= lvLo && row.lv_recovery_mean <= lvHi)
        reasons(end+1) = "recovery_lv"; %#ok<AGROW>
    end
    if ~(row.vdc_min >= vdcLo)
        reasons(end+1) = "vdc_min"; %#ok<AGROW>
    end
    if ~(row.lv_peak <= lvPeakHi)
        reasons(end+1) = "lv_peak"; %#ok<AGROW>
    end
    if ~(row.lv_min >= lvMinLo)
        reasons(end+1) = "lv_min"; %#ok<AGROW>
    end
    if ~(row.action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
    faultPu, faultStart, faultClear, stopTime)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, ...
        faultClear, stopTime);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
    end
end

function configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, ...
    faultClear, stopTime)

    grid = [M '/Grid'];
    t1 = max(0.0, faultStart - 1e-4);
    t2 = faultStart;
    t3 = faultClear;
    t4 = min(stopTime, faultClear + 1e-4);
    set_param(grid, ...
        'PositiveSequence', sprintf('[%.12g 0 50]', nominalGridVoltage), ...
        'VariationEntity', 'Amplitude', ...
        'VariationType', 'Table of time-amplitude pairs', ...
        'TimeValues', sprintf('[0 %.12g %.12g %.12g %.12g %.12g]', ...
            t1, t2, t3, t4, stopTime), ...
        'Amplitudes', sprintf('[1 1 %.12g %.12g 1 1]', faultPu, faultPu));
end

function p = ph(blockPath, portKind, idx)
    phs = get_param(blockPath, 'PortHandles');
    p = phs.(portKind)(idx);
end

function connect_if_free(M, srcPort, dstPort)
    dstLine = get_param(dstPort, 'Line');
    if isequal(dstLine, -1)
        add_line(M, srcPort, dstPort, 'autorouting', 'on');
    end
end

function y = orient_channels(x, nChannels)
    x = squeeze(x);
    if size(x, 1) == nChannels
        y = reshape(x, nChannels, []);
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end

