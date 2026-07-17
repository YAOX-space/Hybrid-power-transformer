% collect_hpt_v2_trajectory_trace
% Collect per-2-ms switch-level traces for a supplied HPT action trajectory.
%
% Workspace overrides:
%   hpt_trace_topology            "topology1" | "topology2"
%   hpt_trace_fault_pu            default 0.95
%   hpt_trace_fault_duration      default 0.08 s
%   hpt_trace_fault_start         default 0.035 s
%   hpt_trace_fault_stop_margin   default 0.125 s
%   hpt_trace_trajectory_file     MAT with hpt_traj_t / hpt_traj_action
%   hpt_trace_policy_mode         default -2.0, use 1.0 for actor traces
%   hpt_trace_actor_select_mode   default 0.0, use 3.0 for always-on actor
%   hpt_trace_run_label           optional result-folder token
%   hpt_trace_sample_stride       default 100, i.e. 2 ms with Ts=20 us

clearvars -except hpt_trace_topology hpt_trace_fault_pu hpt_trace_fault_duration hpt_trace_fault_start hpt_trace_fault_stop_margin hpt_trace_trajectory_file hpt_trace_policy_mode hpt_trace_actor_select_mode hpt_trace_run_label hpt_trace_sample_stride;
close all;

if ~exist('hpt_trace_topology', 'var')
    hpt_trace_topology = "topology2";
end
if ~exist('hpt_trace_fault_pu', 'var')
    hpt_trace_fault_pu = 0.95;
end
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

rootDir = fileparts(mfilename('fullpath'));
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

replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
    hpt_trace_fault_pu, faultStart, faultClear, stopTime);

in = Simulink.SimulationInput(M);
in = in.setModelParameter('StopTime', num2str(stopTime));
in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_energy_enable', 1.0, 'Workspace', M);
in = in.setVariable('hpt_sac_policy_mode', hpt_trace_policy_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_actor_select_mode', hpt_trace_actor_select_mode, 'Workspace', M);
in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
out = sim(in);

obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
actRows = orient_channels(out.get('HPTSAC_action'), 4);
vdcRows = orient_channels(out.get('Vdc'), 1);
lvRows = orient_channels(out.get('Vlv_abc'), 3);
n = min([size(obsRows, 2), size(actRows, 2), size(vdcRows, 2), size(lvRows, 2)]);
t = (0:n-1) * Ts;
sampleIdx = 1:hpt_trace_sample_stride:n;

rows = repmat(base_row(), 0, 1);
for kk = 1:numel(sampleIdx)
    j = sampleIdx(kk);
    row = base_row();
    row.model = string(M);
    row.topology = hpt_trace_topology;
    row.scenario_type = "fault";
    row.condition_class = condition_class(hpt_trace_fault_pu);
    row.case_name = string(sprintf('lvrt_%03dms_%.3fpu', round(1000*hpt_trace_fault_duration), hpt_trace_fault_pu));
    row.t = t(j);
    row.grid_V = NaN;
    row.fault_pu = hpt_trace_fault_pu;
    row.grid_pu = hpt_trace_fault_pu;
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
    'stopTime', 'hpt_trace_trajectory_file');
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
    row.lv_rms_inst = NaN;
    row.vdc_inst = NaN;
    for ii = 1:24
        row.(sprintf('obs_%02d', ii)) = NaN;
    end
    for ii = 1:4
        row.(sprintf('action_%02d', ii)) = NaN;
        row.(sprintf('actor_action_%02d', ii)) = NaN;
    end
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
