% calibrate_hpt_v2_topology2_energy_branch
% Fault-window topology2 energy-branch calibration.
%
% This script keeps the regulating branch on a known trajectory and sweeps the
% SAC energy commands [m_energy_d, m_energy_q].  The goal is to identify the
% physical direction and useful operating region of the energy converter during
% topology2 LVRT/HVRT, using the same switch-level plant and voltage-survival
% windows as eval_hpt_v2_control_comparison.
%
% Optional workspace overrides:
%   hpt_energy_calib_faults      cell array {case_name, fault_pu, reg_pre,
%                                reg_fault, reg_recovery}
%   hpt_energy_calib_d_values    numeric row vector
%   hpt_energy_calib_q_values    numeric row vector
%   hpt_energy_calib_id_values   energy dq current limit vector, default 20 A
%   hpt_energy_calib_chop_values chopper threshold vector, default 850 V
%   hpt_energy_calib_rchop_scales Rchop multiplier vector, default 1
%   hpt_energy_calib_run_label   string result label
%   hpt_energy_calib_fault_start default 0.080
%   hpt_energy_calib_duration    default 0.060
%   hpt_energy_calib_stop_margin default 0.125
%   hpt_energy_calib_settle_s    default 0.020
%   hpt_energy_calib_i_kp        energy current-loop Kp, default 0.50
%   hpt_energy_calib_i_ki        energy current-loop Ki, default 100.0
%   hpt_energy_calib_vff_gain    energy voltage feed-forward gain, default 1.06
%   hpt_energy_calib_control_sign default -1.0
%   hpt_energy_calib_bridge_polarity default -1.0
%   hpt_energy_calib_inj_phase_offset default -1.05

clearvars -except hpt_energy_calib_faults hpt_energy_calib_d_values hpt_energy_calib_q_values hpt_energy_calib_id_values hpt_energy_calib_chop_values hpt_energy_calib_rchop_scales hpt_energy_calib_run_label hpt_energy_calib_fault_start hpt_energy_calib_duration hpt_energy_calib_stop_margin hpt_energy_calib_settle_s hpt_energy_calib_i_kp hpt_energy_calib_i_ki hpt_energy_calib_vff_gain hpt_energy_calib_control_sign hpt_energy_calib_bridge_polarity hpt_energy_calib_inj_phase_offset;
close all;

if ~exist('hpt_energy_calib_fault_start', 'var')
    hpt_energy_calib_fault_start = 0.080;
end
if ~exist('hpt_energy_calib_duration', 'var')
    hpt_energy_calib_duration = 0.060;
end
if ~exist('hpt_energy_calib_stop_margin', 'var')
    hpt_energy_calib_stop_margin = 0.125;
end
if ~exist('hpt_energy_calib_settle_s', 'var')
    hpt_energy_calib_settle_s = 0.020;
end
if ~exist('hpt_energy_calib_d_values', 'var')
    hpt_energy_calib_d_values = [-0.60, -0.30, -0.10, 0.00, 0.10, 0.30, 0.60];
end
if ~exist('hpt_energy_calib_q_values', 'var')
    hpt_energy_calib_q_values = [-0.30, 0.00, 0.30];
end
if ~exist('hpt_energy_calib_id_values', 'var')
    hpt_energy_calib_id_values = 20.0;
end
if ~exist('hpt_energy_calib_chop_values', 'var')
    hpt_energy_calib_chop_values = 850.0;
end
if ~exist('hpt_energy_calib_rchop_scales', 'var')
    hpt_energy_calib_rchop_scales = 1.0;
end
if ~exist('hpt_energy_calib_faults', 'var')
    hpt_energy_calib_faults = {
        'lvrt090_reg014_down004', 0.90, 0.14, 0.14, -0.04;
        'hvrt110_reg000_rec024', 1.10, 0.00, 0.00, 0.24;
    };
end
if ~exist('hpt_energy_calib_run_label', 'var')
    hpt_energy_calib_run_label = "default";
end
if ~exist('hpt_energy_calib_i_kp', 'var')
    hpt_energy_calib_i_kp = 0.50;
end
if ~exist('hpt_energy_calib_i_ki', 'var')
    hpt_energy_calib_i_ki = 100.0;
end
if ~exist('hpt_energy_calib_vff_gain', 'var')
    hpt_energy_calib_vff_gain = 1.06;
end
if ~exist('hpt_energy_calib_control_sign', 'var')
    hpt_energy_calib_control_sign = -1.0;
end
if ~exist('hpt_energy_calib_bridge_polarity', 'var')
    hpt_energy_calib_bridge_polarity = -1.0;
end
if ~exist('hpt_energy_calib_inj_phase_offset', 'var')
    hpt_energy_calib_inj_phase_offset = -1.05;
end

rootDir = fileparts(fileparts(mfilename('fullpath')));
topologyDir = fullfile(rootDir, 'topology2');
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
Ts = 20e-6;
faultStart = hpt_energy_calib_fault_start;
faultClear = faultStart + hpt_energy_calib_duration;
stopTime = faultClear + hpt_energy_calib_stop_margin;
faultSettle = hpt_energy_calib_settle_s;

cd(topologyDir);
build_hpt_v2_topology2_paper;
M = 'hpt_v2_topology2_paper';
replace_grid_with_programmable_source(M, 'Source_RL', nominalGridVoltage, ...
    1.0, faultStart, faultClear, stopTime);

rowCells = {};
for f = 1:size(hpt_energy_calib_faults, 1)
    caseName = string(hpt_energy_calib_faults{f, 1});
    faultPu = hpt_energy_calib_faults{f, 2};
    regPre = hpt_energy_calib_faults{f, 3};
    regFault = hpt_energy_calib_faults{f, 4};
    regRecovery = hpt_energy_calib_faults{f, 5};
    configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
        faultStart, faultClear, stopTime);
    for cidx = 1:numel(hpt_energy_calib_chop_values)
        chopperThreshold = hpt_energy_calib_chop_values(cidx);
        for ridx = 1:numel(hpt_energy_calib_rchop_scales)
            rchopScale = hpt_energy_calib_rchop_scales(ridx);
            for imax = 1:numel(hpt_energy_calib_id_values)
                energyIdMax = hpt_energy_calib_id_values(imax);
                for d = 1:numel(hpt_energy_calib_d_values)
                    for q = 1:numel(hpt_energy_calib_q_values)
                        rowCells{end+1} = run_energy_trajectory_case(M, caseName, faultPu, ...
                            regPre, regFault, regRecovery, hpt_energy_calib_d_values(d), ...
                            hpt_energy_calib_q_values(q), energyIdMax, chopperThreshold, ...
                            rchopScale, targetPhaseRms, stopTime, Ts, faultStart, ...
                            faultClear, faultSettle, hpt_energy_calib_i_kp, ...
                            hpt_energy_calib_i_ki, hpt_energy_calib_vff_gain, ...
                            hpt_energy_calib_control_sign, hpt_energy_calib_bridge_polarity, ...
                            hpt_energy_calib_inj_phase_offset); %#ok<SAGROW>
                    end
                end
            end
        end
    end
end
close_system(M, 0);

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_topology2_energy_branch_calibration');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeLabel = regexprep(char(string(hpt_energy_calib_run_label)), '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['topology2_energy_branch_' safeLabel '_' stamp '.mat']);
outCsv = fullfile(outDir, ['topology2_energy_branch_' safeLabel '_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'nominalGridVoltage', ...
    'faultStart', 'faultClear', 'stopTime', 'faultSettle', ...
    'hpt_energy_calib_d_values', 'hpt_energy_calib_q_values', ...
    'hpt_energy_calib_id_values', 'hpt_energy_calib_chop_values', ...
    'hpt_energy_calib_rchop_scales', 'hpt_energy_calib_faults', ...
    'hpt_energy_calib_i_kp', 'hpt_energy_calib_i_ki', ...
    'hpt_energy_calib_vff_gain', 'hpt_energy_calib_control_sign', ...
    'hpt_energy_calib_bridge_polarity', 'hpt_energy_calib_inj_phase_offset');
writetable(struct2table(rows), outCsv);

fprintf('Topology2 fault energy-branch calibration complete.\n');
fprintf('%-26s %6s %6s %6s %7s %8s %8s %10s %10s %9s %9s %6s %s\n', ...
    'case', 'fault', 'IdMax', 'Chop', 'Rscale', 'cmdEd', 'cmdEq', 'LV_fault', 'LV_recov', ...
    'VdcMin', 'VdcMax', 'pass', 'reason');
for i = 1:numel(rows)
    fprintf('%-26s %6.2f %6.0f %6.0f %7.3f %8.3f %8.3f %10.3f %10.3f %9.3f %9.3f %6.0f %s\n', ...
        rows(i).case_name, rows(i).fault_pu, rows(i).energy_id_max, ...
        rows(i).chopper_threshold, rows(i).rchop_scale, rows(i).cmd_m_energy_d, ...
        rows(i).cmd_m_energy_q, rows(i).lv_fault_mean, ...
        rows(i).lv_recovery_mean, rows(i).vdc_min, rows(i).vdc_max, ...
        rows(i).voltage_survival_pass, rows(i).voltage_survival_reason);
end
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = run_energy_trajectory_case(M, caseName, faultPu, regPre, ...
    regFault, regRecovery, energyD, energyQ, energyIdMax, chopperThreshold, ...
    rchopScale, targetPhaseRms, ...
    stopTime, Ts, faultStart, faultClear, faultSettle, energyIKp, energyIKi, ...
    energyVffGain, energyControlSign, energyBridgePolarity, injPhaseOffset)

    hpt_traj_t = [0.0; max(0.0, faultStart - 0.004); faultStart; ...
        faultClear; faultClear + 0.020; stopTime];
    hpt_traj_action = [
        regPre,      0.0, energyD, energyQ;
        regPre,      0.0, energyD, energyQ;
        regFault,    0.0, energyD, energyQ;
        regRecovery, 0.0, energyD, energyQ;
        regRecovery, 0.0, energyD, energyQ;
        0.0,         0.0, 0.0,     0.0;
    ];
    save('hpt_sac_trajectory.mat', 'hpt_traj_t', 'hpt_traj_action');

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setVariable('hpt_traj_t', hpt_traj_t, 'Workspace', M);
    in = in.setVariable('hpt_traj_action', hpt_traj_action, 'Workspace', M);
    in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -2.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_filter_tau', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_inj_phase_offset', injPhaseOffset, 'Workspace', M);
    in = in.setVariable('hpt_energy_i_kp', energyIKp, 'Workspace', M);
    in = in.setVariable('hpt_energy_i_ki', energyIKi, 'Workspace', M);
    in = in.setVariable('hpt_energy_id_max', energyIdMax, 'Workspace', M);
    in = in.setVariable('hpt_energy_vff_gain', energyVffGain, 'Workspace', M);
    in = in.setVariable('hpt_energy_control_sign', energyControlSign, 'Workspace', M);
    in = in.setVariable('hpt_energy_bridge_polarity', energyBridgePolarity, 'Workspace', M);
    in = in.setBlockParameter([M '/Chopper_gate'], 'Value', num2str(chopperThreshold));
    baseRchop = (800.0^2) / 120e3;
    in = in.setBlockParameter([M '/Rchop'], 'Resistance', num2str(baseRchop * rchopScale));
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    act = orient_channels(out.get('HPTSAC_action'), 4);
    meng = orient_channels(out.get('Menergy_cmd'), 3);
    if has_logged_var(out, 'Energy_Iabc')
        Ienergy = orient_channels(out.get('Energy_Iabc'), 3);
    else
        Ienergy = zeros(3, size(act, 2));
    end
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + max(faultSettle, 0.0)) & t < (faultClear - 0.005);
    if ~any(faultIdx)
        faultIdx = t >= faultStart & t <= faultClear;
    end
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    if ~any(recoveryIdx)
        recoveryIdx = t > faultClear;
    end
    envIdx = t >= (faultStart + max(faultSettle, 0.0)) & t <= stopTime;
    recEnvIdx = t >= (faultClear + 0.020) & t <= stopTime;

    lvFault = mean(phaseRmsInst(faultIdx));
    lvRecovery = mean(phaseRmsInst(recoveryIdx));
    vdcMin = min(Vdc(:, 1));
    vdcMax = max(Vdc(:, 1));
    [envPass, envViolationMax] = voltage_envelope_pass(phaseRmsInst(envIdx), ...
        targetPhaseRms, 0.88, 1.12);
    [recPass, recViolationMax] = voltage_envelope_pass(phaseRmsInst(recEnvIdx), ...
        targetPhaseRms, 0.92, 1.08);
    % Match eval_hpt_v2_control_comparison voltage-survival fault gate.
    vdcPass = vdcMin >= 650.0 && vdcMax <= 1000.0;
    lvMeanPass = lvFault >= 176.0 && lvFault <= 238.0 && ...
        lvRecovery >= 180.0 && lvRecovery <= 235.0;
    pass = envPass && recPass && vdcPass && lvMeanPass;
    reasons = strings(0);
    if ~envPass
        reasons(end+1) = "timestep_voltage_envelope"; %#ok<AGROW>
    end
    if ~recPass
        reasons(end+1) = "timestep_recovery_envelope"; %#ok<AGROW>
    end
    if ~vdcPass
        reasons(end+1) = "dc_link_bounds"; %#ok<AGROW>
    end
    if ~lvMeanPass
        reasons(end+1) = "lv_mean_bounds"; %#ok<AGROW>
    end
    if isempty(reasons)
        reason = "pass";
    else
        reason = strjoin(reasons, ";");
    end

    row = struct();
    row.model = string(M);
    row.topology = "topology2";
    row.case_name = string(caseName);
    row.fault_pu = faultPu;
    row.fault_start_s = faultStart;
    row.fault_clear_s = faultClear;
    row.stop_time_s = stopTime;
    row.reg_pre = regPre;
    row.reg_fault = regFault;
    row.reg_recovery = regRecovery;
    row.energy_id_max = energyIdMax;
    row.energy_i_kp = energyIKp;
    row.energy_i_ki = energyIKi;
    row.energy_vff_gain = energyVffGain;
    row.energy_control_sign = energyControlSign;
    row.energy_bridge_polarity = energyBridgePolarity;
    row.inj_phase_offset = injPhaseOffset;
    row.chopper_threshold = chopperThreshold;
    row.rchop_scale = rchopScale;
    row.cmd_m_energy_d = energyD;
    row.cmd_m_energy_q = energyQ;
    row.lv_fault_mean = lvFault;
    row.lv_recovery_mean = lvRecovery;
    row.lv_min = min(phaseRmsInst(envIdx));
    row.lv_peak = max(phaseRmsInst(envIdx));
    row.vdc_min = vdcMin;
    row.vdc_max = vdcMax;
    row.vdc_mean_tail = mean(Vdc(round(end*0.7):end, 1));
    row.cmd_m_reg_d_mean = mean(act(1, round(end*0.7):end));
    row.cmd_m_energy_d_mean = mean(act(3, round(end*0.7):end));
    row.cmd_m_energy_q_mean = mean(act(4, round(end*0.7):end));
    row.energy_bridge_modulation_max = max(abs(meng(:)));
    row.energy_i_rms_mean = mean(sqrt(mean(Ienergy.^2, 2)));
    row.envelope_violation_max_pu = envViolationMax;
    row.recovery_violation_max_pu = recViolationMax;
    row.timestep_envelope_pass = envPass;
    row.recovery_envelope_pass = recPass;
    row.vdc_bounds_pass = vdcPass;
    row.lv_mean_bounds_pass = lvMeanPass;
    row.voltage_survival_pass = pass;
    row.voltage_survival_reason = reason;
end

function [pass, violationMax] = voltage_envelope_pass(values, targetPhaseRms, lo, hi)
    if isempty(values)
        pass = false;
        violationMax = NaN;
        return;
    end
    pu = values(:) / targetPhaseRms;
    lowViolation = max(0, lo - pu);
    highViolation = max(0, pu - hi);
    violation = max(lowViolation, highViolation);
    violationMax = max(violation);
    pass = violationMax <= 1e-9;
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

function tf = has_logged_var(out, name)
    tf = false;
    vars = out.who;
    for i = 1:numel(vars)
        if strcmp(vars{i}, name)
            tf = true;
            return;
        end
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

