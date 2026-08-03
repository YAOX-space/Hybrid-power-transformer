% collect_hpt_v2_sac_guard_teacher_traces
% Collect switch-level observation/action pairs from the currently passing
% guarded SAC execution path.
%
% The output is a CSV teacher dataset:
%   obs_01..obs_24  -> HPTSAC_obs
%   action_01..04   -> HPTSAC_action after hpt_sac_guard_enable = 1
%
% This is not the final controller.  It is only a switch-level teacher trace
% used to train the raw actor so the final evaluation can run with guard = 0.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
dynamicActorFile = fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
assert(exist(dynamicActorFile, 'file') == 2, ...
    'Missing dynamic HPT SAC actor: %s', dynamicActorFile);

cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

steadyGridVoltages = [9000, 10000, 11000];
faults = {
    'sag_0p50', 0.50;
    'sag_0p75', 0.75;
    'sag_0p85', 0.85;
    'sag_0p90', 0.90;
    'swell_1p10', 1.10;
    'swell_1p20', 1.20;
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
faultStart = 0.035;
faultClear = 0.095;
faultStopTime = 0.16;
Ts = 20e-6;
sampleStride = 100;  % 2 ms, matching the Python averaged environment step.

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
        out = run_guarded_case(M, steadyGridVoltages(k), 0.0, ...
            targetPhaseRms, steadyStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "steady", ...
            sprintf("grid_%.0fV", steadyGridVoltages(k)), steadyGridVoltages(k), ...
            NaN, 0.0, 1.0, 0.0, Ts, sampleStride, 0.010);
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
        out = run_guarded_case(M, NaN, 2.0, ...
            targetPhaseRms, faultStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "fault", ...
            faultName, NaN, faultPu, 2.0, 1.0, 1.0, Ts, sampleStride, 0.010);
    end
    close_system(M, 0);
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_guard_teacher_traces');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['guard_teacher_traces_' stamp '.mat']);
outCsv = fullfile(outDir, ['guard_teacher_traces_' stamp '.csv']);
save(outMat, 'rowCells', 'targetPhaseRms', 'steadyGridVoltages', 'faults', ...
    'faultStart', 'faultClear', 'sampleStride');
write_trace_csv(outCsv, rowCells);

fprintf('Collected %d guarded switch-level teacher samples.\n', numel(rowCells));
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function out = run_guarded_case(M, gridVoltage, actorSelectMode, ...
    targetPhaseRms, stopTime)

    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    if isfinite(gridVoltage)
        in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    end
    in = in.setVariable('hpt_sac_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, ...
        'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    out = sim(in);
end

function rowCells = append_trace_rows(rowCells, out, M, topology, scenarioType, ...
    caseName, gridVoltage, faultPu, actorSelectMode, policyMode, guardEnable, ...
    Ts, sampleStride, minTime)

    obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
    actRows = orient_channels(out.get('HPTSAC_action'), 4);
    n = min(size(obsRows, 2), size(actRows, 2));
    t = (0:n-1) * Ts;
    sampleIdx = find(t >= minTime);
    sampleIdx = sampleIdx(1:sampleStride:end);
    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        row = struct();
        row.model = string(M);
        row.topology = string(topology);
        row.scenario_type = string(scenarioType);
        row.case_name = string(caseName);
        row.t = t(j);
        row.grid_V = gridVoltage;
        row.fault_pu = faultPu;
        row.actor_select_mode = actorSelectMode;
        row.policy_mode = policyMode;
        row.guard_enable = guardEnable;
        for ii = 1:24
            row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
        end
        for ii = 1:4
            row.(sprintf('action_%02d', ii)) = actRows(ii, j);
        end
        rowCells{end+1} = row; %#ok<AGROW>
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

function write_trace_csv(path, rowCells)
    if isempty(rowCells)
        error('No trace rows to write.');
    end
    fields = fieldnames(rowCells{1});
    fid = fopen(path, 'w');
    cleaner = onCleanup(@() fclose(fid));
    for i = 1:numel(fields)
        if i > 1
            fprintf(fid, ',');
        end
        fprintf(fid, '%s', fields{i});
    end
    fprintf(fid, '\n');
    for r = 1:numel(rowCells)
        row = rowCells{r};
        for i = 1:numel(fields)
            if i > 1
                fprintf(fid, ',');
            end
            value = row.(fields{i});
            if isstring(value)
                fprintf(fid, '"%s"', char(value));
            elseif ischar(value)
                fprintf(fid, '"%s"', value);
            elseif isnumeric(value)
                fprintf(fid, '%.15g', value);
            else
                fprintf(fid, '"%s"', char(string(value)));
            end
        end
        fprintf(fid, '\n');
    end
end

