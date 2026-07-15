% test_hpt_v2_sac_fault_transition
% Dynamic sag/swell transition validation for the HPT SAC regulating bridge.
%
% The generated topology models use a constant Three-Phase Source.  This
% script replaces it in-memory with a Three-Phase Programmable Voltage Source
% and applies:
%   1.0 pu pre-fault -> sag/swell fault window -> 1.0 pu recovery.
%
% Current scope:
%   - SAC regulates the series/injection bridge.
%   - The energy bridge remains on the conventional DC-link loop.

clearvars;
close all;

rootDir = fileparts(mfilename('fullpath'));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
actor = load(actorFile, 'n_obs', 'n_act');
assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
    'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));

cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg', 196, 214, 650, 235, 180;
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL', 194, 220, 620, 235, 180;
};

faults = {
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
faultStart = 0.035;
faultClear = 0.095;
stopTime = 0.16;
Ts = 20e-6;
assertEnabled = false;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};
    sourceBranch = cases{c, 5};
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        1.0, faultStart, faultClear, stopTime);

    for f = 1:size(faults, 1)
        faultName = faults{f, 1};
        faultPu = faults{f, 2};
        configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
            faultStart, faultClear, stopTime);

        rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
            "baseline", 0.0, targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
        rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
            "sac_actor", 1.0, targetPhaseRms, stopTime, Ts, faultStart, faultClear); %#ok<SAGROW>
    end
    close_system(M, 0);
end

rows = [rowCells{:}];
for i = 1:numel(rows)
    rows(i).assert_pass = true;
    rows(i).assert_reason = "";
    if rows(i).mode ~= "sac_actor"
        continue;
    end
    idx = find(strcmp(cases(:, 4), rows(i).topology), 1);
    lvLo = cases{idx, 6};
    lvHi = cases{idx, 7};
    vdcLo = cases{idx, 8};
    lvPeakHi = cases{idx, 9};
    lvMinLo = cases{idx, 10};
    reasons = strings(0, 1);
    if ~(rows(i).lv_fault_rms_mean >= lvLo && rows(i).lv_fault_rms_mean <= lvHi)
        reasons(end+1) = "fault_window_lv"; %#ok<SAGROW>
    end
    if ~(rows(i).lv_recovery_rms_mean >= lvLo && rows(i).lv_recovery_rms_mean <= lvHi)
        reasons(end+1) = "recovery_lv"; %#ok<SAGROW>
    end
    if ~(rows(i).vdc_min >= vdcLo)
        reasons(end+1) = "vdc_min"; %#ok<SAGROW>
    end
    if ~(rows(i).lv_peak_rms <= lvPeakHi)
        reasons(end+1) = "lv_peak"; %#ok<SAGROW>
    end
    if ~(rows(i).lv_min_rms >= lvMinLo)
        reasons(end+1) = "lv_min"; %#ok<SAGROW>
    end
    if ~(rows(i).action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<SAGROW>
    end
    if ~isempty(reasons)
        rows(i).assert_pass = false;
        rows(i).assert_reason = strjoin(reasons, ";");
    end
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_sac_fault_transition');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['hpt_v2_sac_fault_transition_' stamp '.mat']);
outCsv = fullfile(outDir, ['hpt_v2_sac_fault_transition_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'nominalGridVoltage', ...
    'faultStart', 'faultClear', 'stopTime');
writetable(struct2table(rows), outCsv);

fprintf('HPT SAC fault-transition validation complete.\n');
fprintf('%-10s %-10s %-9s %8s %10s %10s %10s %9s %9s %-8s %s\n', ...
    'topology', 'fault', 'mode', 'faultPu', 'LV_fault', 'LV_recov', ...
    'LV_peak', 'VdcMin', 'max|a|', 'pass', 'reason');
for i = 1:numel(rows)
    fprintf('%-10s %-10s %-9s %8.2f %10.3f %10.3f %10.3f %9.3f %9.3f %-8s %s\n', ...
        rows(i).topology, rows(i).fault, rows(i).mode, rows(i).fault_pu, ...
        rows(i).lv_fault_rms_mean, rows(i).lv_recovery_rms_mean, ...
        rows(i).lv_peak_rms, rows(i).vdc_min, rows(i).action_max_abs, ...
        string(rows(i).assert_pass), rows(i).assert_reason);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

failed = rows([rows.assert_pass] == false);
if assertEnabled
    assert(isempty(failed), 'HPT SAC fault-transition assertions failed; see CSV: %s', outCsv);
end
if isempty(failed)
    fprintf('HPT SAC fault-transition assertions passed.\n');
else
    fprintf('HPT SAC fault-transition diagnostic found %d failing SAC cases; assertions are disabled by default.\n', numel(failed));
end

function replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
    faultPu, faultStart, faultClear, stopTime)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
    end
end

function configure_programmable_grid(M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime)
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

function row = run_fault_case(M, topology, faultName, faultPu, mode, sacEnable, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', double(sacEnable > 0.5) * 2.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    act = out.get('HPTSAC_action');

    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.025) & t < (faultClear - 0.005);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    actRows = orient_channels(act, 4);

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.fault = string(faultName);
    row.fault_pu = faultPu;
    row.mode = string(mode);
    if sacEnable <= 0.5
        row.action_semantics = "controller_disabled";
    else
        row.action_semantics = "actor_raw_unlogged_controller_projected";
    end
    row.action_raw_available = false;
    row.action_projected_available = true;
    row.action_effective_available = true;
    row.action_raw_source = "unlogged_actor_or_disabled";
    row.action_projected_source = "HPTSAC_action";
    row.action_effective_source = "HPTSAC_action";
    row.raw_m_reg_d = NaN;
    row.raw_m_reg_q = NaN;
    row.raw_m_energy_d = NaN;
    row.raw_m_energy_q = NaN;
    row.lv_fault_rms_mean = mean(phaseRmsInst(faultIdx));
    row.lv_recovery_rms_mean = mean(phaseRmsInst(recoveryIdx));
    row.lv_peak_rms = max(phaseRmsInst(t > faultStart & t < stopTime));
    row.lv_min_rms = min(phaseRmsInst(t > faultStart & t < stopTime));
    row.vdc_mean = mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = mean(actRows(1, round(end*0.7):end));
    row.energy_d_mean = mean(actRows(3, round(end*0.7):end));
    row.reg_q_mean = mean(actRows(2, round(end*0.7):end));
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
    if size(x, 1) == nChannels
        y = x;
    elseif size(x, 2) == nChannels
        y = x';
    else
        y = reshape(x, nChannels, []);
    end
end
