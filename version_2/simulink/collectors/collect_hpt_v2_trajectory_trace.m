% collect_hpt_v2_trajectory_trace
% Collect per-2-ms switch-level traces for a supplied HPT action trajectory.
%
% Workspace overrides:
%   hpt_trace_topology            "topology1" | "topology2"
%   hpt_trace_fault_pu            default 0.95
%   hpt_trace_fault_duration      default 0.08 s
%   hpt_trace_fault_phase_pu      optional [puA puB puC], default balanced
%   hpt_trace_fault_start         default 0.035 s
%   hpt_trace_fault_stop_margin   default 0.125 s
%   hpt_trace_trajectory_file     MAT with hpt_traj_t / hpt_traj_action
%   hpt_trace_policy_mode         default -2.0, use 1.0 for actor traces
%   hpt_trace_actor_select_mode   default 0.0, use 3.0 for always-on actor
%   hpt_trace_actor_filter_tau    default 0.001 s, set 0 for raw actor diagnostics
%   hpt_trace_model_params        optional struct of model-workspace overrides
%   hpt_trace_run_label           optional result-folder token
%   hpt_trace_sample_stride       default 100, i.e. 2 ms with Ts=20 us

clearvars -except hpt_trace_topology hpt_trace_fault_pu hpt_trace_fault_phase_pu hpt_trace_fault_duration hpt_trace_fault_start hpt_trace_fault_stop_margin hpt_trace_trajectory_file hpt_trace_policy_mode hpt_trace_actor_select_mode hpt_trace_actor_filter_tau hpt_trace_model_params hpt_trace_run_label hpt_trace_sample_stride;
close all;

if ~exist('hpt_trace_topology', 'var')
    hpt_trace_topology = "topology2";
end
if ~exist('hpt_trace_fault_pu', 'var')
    hpt_trace_fault_pu = 0.95;
end
if ~exist('hpt_trace_fault_phase_pu', 'var') || isempty(hpt_trace_fault_phase_pu)
    hpt_trace_fault_phase_pu = [hpt_trace_fault_pu, hpt_trace_fault_pu, hpt_trace_fault_pu];
end
hpt_trace_fault_phase_pu = reshape(double(hpt_trace_fault_phase_pu), 1, []);
assert(numel(hpt_trace_fault_phase_pu) == 3, ...
    'hpt_trace_fault_phase_pu must be [puA puB puC]');
usePhaseFaultSource = max(abs(hpt_trace_fault_phase_pu - hpt_trace_fault_pu)) > 1e-9;
if ~exist('hpt_trace_fault_duration', 'var')
    hpt_trace_fault_duration = 0.08;
end
if ~exist('hpt_trace_fault_start', 'var')
    hpt_trace_fault_start = 0.035;
end
if ~exist('hpt_trace_fault_stop_margin', 'var')
    hpt_trace_fault_stop_margin = 0.125;
end
if ~exist('hpt_trace_trajectory_file', 'var')
    hpt_trace_trajectory_file = "";
end
if ~exist('hpt_trace_policy_mode', 'var')
    hpt_trace_policy_mode = -2.0;
end
if ~exist('hpt_trace_actor_select_mode', 'var')
    hpt_trace_actor_select_mode = 0.0;
end
if ~exist('hpt_trace_actor_filter_tau', 'var')
    hpt_trace_actor_filter_tau = 0.001;
end
if ~exist('hpt_trace_model_params', 'var')
    hpt_trace_model_params = struct();
end
if ~exist('hpt_trace_run_label', 'var')
    hpt_trace_run_label = "";
end
if ~exist('hpt_trace_sample_stride', 'var')
    hpt_trace_sample_stride = 100;
end

hpt_trace_topology = string(hpt_trace_topology);
hpt_trace_trajectory_file = string(hpt_trace_trajectory_file);
if hpt_trace_policy_mode <= -1.5
    assert(strlength(hpt_trace_trajectory_file) > 0, ...
        'hpt_trace_trajectory_file is required for trajectory mode');
    assert(exist(hpt_trace_trajectory_file, 'file') == 2, ...
        'Missing trajectory file: %s', hpt_trace_trajectory_file);
end

rootDir = fileparts(fileparts(mfilename('fullpath')));
cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
Ts = 20e-6;
faultStart = hpt_trace_fault_start;
faultClear = faultStart + hpt_trace_fault_duration;
stopTime = faultClear + hpt_trace_fault_stop_margin;

caseIdx = find(string(cases(:, 4)) == hpt_trace_topology, 1);
assert(~isempty(caseIdx), 'Unknown topology: %s', hpt_trace_topology);

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
cd(cases{caseIdx, 1});
feval(cases{caseIdx, 2});
M = cases{caseIdx, 3};
sourceBranch = cases{caseIdx, 5};
if strlength(hpt_trace_trajectory_file) > 0
    copyfile(char(hpt_trace_trajectory_file), fullfile(pwd, 'hpt_sac_trajectory.mat'), 'f');
end

if usePhaseFaultSource
    replace_grid_with_controlled_phase_source(M, sourceBranch, nominalGridVoltage, ...
        hpt_trace_fault_phase_pu, faultStart, faultClear);
else
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        hpt_trace_fault_pu, faultStart, faultClear, stopTime);
end

in = Simulink.SimulationInput(M);
in = in.setModelParameter('StopTime', num2str(stopTime));
in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_policy_mode', hpt_trace_policy_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_actor_select_mode', hpt_trace_actor_select_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_actor_filter_tau', hpt_trace_actor_filter_tau, 'Workspace', M);
in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
gridNormStartupS = min(0.070, max(0.030, faultStart - 0.005));
in = in.setVariable('hpt_sac_gridnorm_startup_s', gridNormStartupS, 'Workspace', M);
if strlength(hpt_trace_trajectory_file) > 0
    trajData = load(char(hpt_trace_trajectory_file), 'hpt_traj_t', 'hpt_traj_action');
    assert(isfield(trajData, 'hpt_traj_t') && isfield(trajData, 'hpt_traj_action'), ...
        'Trajectory file must contain hpt_traj_t and hpt_traj_action');
    trajT = double(trajData.hpt_traj_t(:));
    trajAction = double(trajData.hpt_traj_action);
    assert(size(trajAction, 1) == numel(trajT) && size(trajAction, 2) == 4, ...
        'hpt_traj_action must be Nx4 and match hpt_traj_t');
    in = in.setVariable('hpt_traj_t', trajT, 'Workspace', M);
    in = in.setVariable('hpt_traj_action', trajAction, 'Workspace', M);
end
modelNames = fieldnames(hpt_trace_model_params);
for modelIdx = 1:numel(modelNames)
    in = in.setVariable(modelNames{modelIdx}, hpt_trace_model_params.(modelNames{modelIdx}), ...
        'Workspace', M);
end
out = sim(in);

obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
actRows = orient_channels(out.get('HPTSAC_action'), 4);
vdcRows = orient_channels(out.get('Vdc'), 1);
lvRows = orient_channels(out.get('Vlv_abc'), 3);
mrefRows = orient_channels(out.get('Mref6_cmd'), 6);
mengRows = orient_channels(out.get('Menergy_cmd'), 3);
mregDbgRows = orient_channels(out.get('Mreg_cmd'), 7);
energyDbgRows = orient_channels(out.get('Energy_dbg'), 12);
energyVRows = orient_channels(out.get('Energy_Vabc'), 3);
if has_logged_var(out, 'Energy_Iabc')
    energyIRows = orient_channels(out.get('Energy_Iabc'), 3);
else
    energyIRows = zeros(size(energyVRows));
end
energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
    energyDbgRows, energyVRows, energyIRows, energyIdMax);
n = min([size(obsRows, 2), size(actRows, 2), size(measActRows, 2), ...
    size(vdcRows, 2), size(lvRows, 2), size(mrefRows, 2), size(mengRows, 2)]);
t = (0:n-1) * Ts;
sampleIdx = 1:hpt_trace_sample_stride:n;

rows = repmat(base_row(), 0, 1);
faultPrefix = "lvrt";
if hpt_trace_fault_pu > 1.0
    faultPrefix = "hvrt";
end
for kk = 1:numel(sampleIdx)
    j = sampleIdx(kk);
    row = base_row();
    row.model = string(M);
    row.topology = hpt_trace_topology;
    row.scenario_type = "fault";
    row.condition_class = condition_class(hpt_trace_fault_pu);
    row.case_name = string(sprintf('%s_%03dms_%.3fpu', faultPrefix, round(1000*hpt_trace_fault_duration), hpt_trace_fault_pu));
    row.t = t(j);
    row.grid_V = NaN;
    row.fault_pu = hpt_trace_fault_pu;
    row.grid_pu = hpt_trace_fault_pu;
    row.fault_a_pu = hpt_trace_fault_phase_pu(1);
    row.fault_b_pu = hpt_trace_fault_phase_pu(2);
    row.fault_c_pu = hpt_trace_fault_phase_pu(3);
    row.lv_rms_inst = sqrt(mean(lvRows(:, j).^2));
    row.vdc_inst = vdcRows(1, j);
    row.window_zone = window_zone(t(j), faultStart, faultClear, stopTime);
    row.action_source = action_source(hpt_trace_policy_mode);
    row.actor_select_mode = hpt_trace_actor_select_mode;
    for ii = 1:24
        row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
    end
    for ii = 1:4
        row.(sprintf('action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('actor_action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('cmd_action_%02d', ii)) = actRows(ii, j);
        row.(sprintf('meas_action_%02d', ii)) = measActRows(ii, j);
        row.(sprintf('teacher_action_%02d', ii)) = measActRows(ii, j);
    end
    for ii = 1:6
        row.(sprintf('mref_%02d', ii)) = mrefRows(ii, j);
    end
    for ii = 1:3
        row.(sprintf('menergy_%02d', ii)) = mengRows(ii, j);
    end
    rows(end+1, 1) = row; %#ok<SAGROW>
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_trajectory_traces');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeLabel = regexprep(sprintf('%s_%s', hpt_trace_topology, hpt_trace_run_label), ...
    '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['trajectory_trace_' char(safeLabel) '_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'faultStart', 'faultClear', ...
    'stopTime', 'hpt_trace_trajectory_file', 'hpt_trace_model_params');
writetable(struct2table(rows), outCsv);
close_system(M, 0);
fprintf('Collected %d trajectory trace samples.\n', numel(rows));
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function row = base_row()
    row = struct();
    row.model = "";
    row.topology = "";
    row.scenario_type = "";
    row.condition_class = "";
    row.case_name = "";
    row.t = NaN;
    row.window_zone = "";
    row.action_source = "";
    row.actor_select_mode = NaN;
    row.grid_V = NaN;
    row.fault_pu = NaN;
    row.grid_pu = NaN;
    row.fault_a_pu = NaN;
    row.fault_b_pu = NaN;
    row.fault_c_pu = NaN;
    row.lv_rms_inst = NaN;
    row.vdc_inst = NaN;
    for ii = 1:24
        row.(sprintf('obs_%02d', ii)) = NaN;
    end
    for ii = 1:4
        row.(sprintf('action_%02d', ii)) = NaN;
        row.(sprintf('actor_action_%02d', ii)) = NaN;
        row.(sprintf('cmd_action_%02d', ii)) = NaN;
        row.(sprintf('meas_action_%02d', ii)) = NaN;
        row.(sprintf('teacher_action_%02d', ii)) = NaN;
    end
    for ii = 1:6
        row.(sprintf('mref_%02d', ii)) = NaN;
    end
    for ii = 1:3
        row.(sprintf('menergy_%02d', ii)) = NaN;
    end
end

function tf = has_logged_var(out, name)
    try
        out.get(name);
        tf = true;
    catch
        tf = false;
    end
end

function actRows = measured_response_rows(hptActRows, mrefRows, mregDbgRows, ...
    energyDbgRows, energyVRows, energyIRows, energyIdMax)
    hasEnergyVI = size(energyVRows, 1) >= 3 && size(energyIRows, 1) >= 3 && ...
        size(energyVRows, 2) >= 1 && size(energyIRows, 2) >= 1;
    n = size(hptActRows, 2);
    if isempty(n) || n < 1
        actRows = hptActRows;
        return;
    end
    actRows = zeros(4, n);
    for k = 1:n
        if k <= size(mrefRows, 2) && k <= size(mregDbgRows, 2) && size(mregDbgRows, 1) >= 7
            theta = mregDbgRows(1, k);
            phi = mregDbgRows(7, k);
            [actRows(1, k), actRows(2, k)] = reg6_to_dq(mrefRows(:, k), theta + phi);
        else
            actRows(1, k) = hptActRows(1, k);
            actRows(2, k) = hptActRows(2, k);
        end
        if hasEnergyVI && k <= size(energyVRows, 2) && k <= size(energyIRows, 2)
            va = energyVRows(1, k);
            vb = energyVRows(2, k);
            vc = energyVRows(3, k);
            ia = energyIRows(1, k);
            ib = energyIRows(2, k);
            ic = energyIRows(3, k);
            valpha = (2/3) * (va - 0.5*vb - 0.5*vc);
            vbeta = (sqrt(3)/3) * (vb - vc);
            ialpha = (2/3) * (ia - 0.5*ib - 0.5*ic);
            ibeta = (sqrt(3)/3) * (ib - ic);
            theta = atan2(vbeta, valpha);
            actRows(3, k) = clip_scalar((ialpha*cos(theta) + ibeta*sin(theta)) / max(energyIdMax, 1e-9), -0.95, 0.95);
            actRows(4, k) = clip_scalar((-ialpha*sin(theta) + ibeta*cos(theta)) / max(energyIdMax, 1e-9), -0.95, 0.95);
        elseif size(energyDbgRows, 1) >= 5 && k <= size(energyDbgRows, 2)
            actRows(3, k) = clip_scalar(energyDbgRows(4, k) / max(energyIdMax, 1e-9), -0.95, 0.95);
            actRows(4, k) = clip_scalar(energyDbgRows(5, k) / max(energyIdMax, 1e-9), -0.95, 0.95);
        else
            actRows(3, k) = hptActRows(3, k);
            actRows(4, k) = hptActRows(4, k);
        end
    end
end

function [d, q] = reg6_to_dq(reg6, angle)
    ma = reg6(1);
    mb = reg6(3);
    mc = reg6(5);
    alpha = (2/3) * (ma - 0.5*mb - 0.5*mc);
    beta = (sqrt(3)/3) * (mb - mc);
    s = sin(angle);
    c = cos(angle);
    d = s*alpha - c*beta;
    q = c*alpha + s*beta;
end

function y = clip_scalar(x, lo, hi)
    y = min(max(x, lo), hi);
end

function s = action_source(policyMode)
    if policyMode <= -1.5
        s = "trajectory_action";
    elseif policyMode >= 0.5
        s = "actor_action";
    else
        s = "rule_action";
    end
end

function c = condition_class(faultPu)
    if faultPu < 0.80
        c = "deep_lvrt";
    elseif faultPu < 1.0
        c = "shallow_lvrt";
    elseif faultPu <= 1.20
        c = "shallow_hvrt";
    else
        c = "high_hvrt";
    end
end

function z = window_zone(t, faultStart, faultClear, stopTime)
    if t < faultStart
        z = "prefault";
    elseif t < faultClear
        z = "fault";
    elseif t < stopTime - 0.005
        z = "recovery";
    else
        z = "tail";
    end
end

function replace_grid_with_controlled_phase_source(M, sourceBranch, nominalGridVoltage, ...
    phasePu, faultStart, faultClear)

    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);

    x0 = pos(1);
    y0 = pos(2);
    add_block('simulink/Sources/Clock', [M '/GridFaultClock'], ...
        'Position', [x0-120 y0-80 x0-90 y0-60]);
    add_block('simulink/Sources/Constant', [M '/GridFaultVline'], ...
        'Position', [x0-125 y0-45 x0-85 y0-25], ...
        'Value', sprintf('%.12g', nominalGridVoltage));
    add_block('simulink/Sources/Constant', [M '/GridFaultF0'], ...
        'Position', [x0-125 y0-15 x0-85 y0+5], ...
        'Value', '50');
    add_block('simulink/Sources/Constant', [M '/GridFaultStart'], ...
        'Position', [x0-125 y0+15 x0-85 y0+35], ...
        'Value', sprintf('%.12g', faultStart));
    add_block('simulink/Sources/Constant', [M '/GridFaultClear'], ...
        'Position', [x0-125 y0+45 x0-85 y0+65], ...
        'Value', sprintf('%.12g', faultClear));
    add_block('simulink/Sources/Constant', [M '/GridFaultPuAbc'], ...
        'Position', [x0-125 y0+75 x0-85 y0+95], ...
        'Value', mat2str(phasePu, 12));

    wav = [M '/GridFaultWaveform'];
    add_block('simulink/User-Defined Functions/MATLAB Function', wav, ...
        'Position', [x0-45 y0-70 x0+55 y0+70]);
    set_matlab_function_script(wav, controlled_phase_waveform_code());
    add_block('simulink/Signal Routing/Demux', [M '/GridFaultDemux'], ...
        'Position', [x0+95 y0-35 x0+100 y0+65], 'Outputs', '3');

    add_line(M, 'GridFaultClock/1', 'GridFaultWaveform/1', 'autorouting', 'on');
    add_line(M, 'GridFaultVline/1', 'GridFaultWaveform/2', 'autorouting', 'on');
    add_line(M, 'GridFaultF0/1', 'GridFaultWaveform/3', 'autorouting', 'on');
    add_line(M, 'GridFaultStart/1', 'GridFaultWaveform/4', 'autorouting', 'on');
    add_line(M, 'GridFaultClear/1', 'GridFaultWaveform/5', 'autorouting', 'on');
    add_line(M, 'GridFaultPuAbc/1', 'GridFaultWaveform/6', 'autorouting', 'on');
    add_line(M, 'GridFaultWaveform/1', 'GridFaultDemux/1', 'autorouting', 'on');

    phaseNames = {'A', 'B', 'C'};
    for k = 1:3
        y = y0 - 30 + (k-1) * 55;
        src = [M '/Grid_' phaseNames{k} '_CVS'];
        gnd = [M '/Grid_' phaseNames{k} '_Ground'];
        add_block('powerlib/Electrical Sources/Controlled Voltage Source', src, ...
            'Position', [x0+145 y x0+205 y+38]);
        add_block('powerlib/Elements/Ground', gnd, ...
            'Position', [x0+145 y+48 x0+175 y+78]);
        add_line(M, sprintf('GridFaultDemux/%d', k), ...
            sprintf('Grid_%s_CVS/1', phaseNames{k}), 'autorouting', 'on');
        connect_replace(M, ph(src, 'RConn', 1), ...
            ph([M '/' sourceBranch], 'LConn', k));
        connect_if_free(M, ph(src, 'LConn', 1), ph(gnd, 'LConn', 1));
    end
end

function set_matlab_function_script(blockPath, codeText)
    rt = sfroot;
    chart = rt.find('-isa', 'Stateflow.EMChart', 'Path', blockPath);
    chart.Script = codeText;
end

function codeText = controlled_phase_waveform_code()
    lines = {
        'function vabc = fcn(t, vline, f0, faultStart, faultClear, phasePu)'
        '%#codegen'
        'vabc = zeros(3,1);'
        'pu = reshape(phasePu, 3, 1);'
        'if ~(t >= faultStart && t <= faultClear)'
        '    pu(:) = 1.0;'
        'end'
        'vpk = sqrt(2) * vline / sqrt(3);'
        'theta = 2*pi*f0*t;'
        'vabc(1) = vpk * pu(1) * sin(theta);'
        'vabc(2) = vpk * pu(2) * sin(theta - 2*pi/3);'
        'vabc(3) = vpk * pu(3) * sin(theta + 2*pi/3);'
        'end'
    };
    codeText = strjoin(lines, newline);
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

function connect_replace(M, srcPort, dstPort)
    dstLine = get_param(dstPort, 'Line');
    if ~isequal(dstLine, -1)
        delete_line(dstLine);
    end
    add_line(M, srcPort, dstPort, 'autorouting', 'on');
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

