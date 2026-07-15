% collect_hpt_v2_sac_energy_teacher_traces
% Collect switch-level teacher labels for the SAC energy-converter action.
%
% The conventional EnergyController is used as the teacher:
%   - hpt_sac_enable = 0
%   - hpt_sac_energy_enable = 0
%   - hpt_sac_policy_mode = -1
%
% The CSV records obs_01..obs_24 plus the conventional Vdc/current loop
% signals.  The intended SAC energy target is:
%   action_03 = id_ref / hpt_energy_id_max
%   action_04 = iq_ref / hpt_energy_id_max
%
% Optional quick mode:
%   assignin('base', 'hpt_energy_teacher_quick', true);
%   collect_hpt_v2_sac_energy_teacher_traces

clearvars -except hpt_energy_teacher_quick;
close all;

rootDir = fileparts(mfilename('fullpath'));
cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

if exist('hpt_energy_teacher_quick', 'var') && logical(hpt_energy_teacher_quick)
    steadyGridVoltages = [9000, 10000, 11000];
    faults = {
        'sag_0p90', 0.90;
        'swell_1p10', 1.10;
    };
else
    steadyGridVoltages = [9000, 10000, 11000];
    faults = {
        'sag_0p20', 0.20;
        'sag_0p50', 0.50;
        'sag_0p75', 0.75;
        'sag_0p85', 0.85;
        'sag_0p90', 0.90;
        'swell_1p10', 1.10;
        'swell_1p20', 1.20;
        'swell_1p25', 1.25;
        'swell_1p30', 1.30;
    };
end

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
faultStart = 0.035;
faultClear = 0.095;
faultStopTime = 0.16;
Ts = 20e-6;
sampleStride = 100;  % 2 ms, matching the averaged SAC environment step.

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};
    sourceBranch = cases{c, 5};
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');

    for k = 1:numel(steadyGridVoltages)
        out = run_teacher_case(M, steadyGridVoltages(k), targetPhaseRms, steadyStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "steady", ...
            sprintf("grid_%.0fV", steadyGridVoltages(k)), steadyGridVoltages(k), ...
            NaN, Ts, sampleStride, 0.010, energyIdMax);
    end

    close_system(M, 0);
    feval(cases{c, 2});
    M = cases{c, 3};
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
        1.0, faultStart, faultClear, faultStopTime);
    for f = 1:size(faults, 1)
        faultName = faults{f, 1};
        faultPu = faults{f, 2};
        configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
            faultStart, faultClear, faultStopTime);
        out = run_teacher_case(M, NaN, targetPhaseRms, faultStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "fault", ...
            faultName, NaN, faultPu, Ts, sampleStride, 0.010, energyIdMax);
    end
    close_system(M, 0);
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_energy_teacher_traces');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['energy_teacher_traces_' stamp '.mat']);
outCsv = fullfile(outDir, ['energy_teacher_traces_' stamp '.csv']);
save(outMat, 'rowCells', 'targetPhaseRms', 'steadyGridVoltages', 'faults', ...
    'faultStart', 'faultClear', 'sampleStride');
write_trace_csv(outCsv, rowCells);

fprintf('Collected %d energy teacher samples.\n', numel(rowCells));
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function out = run_teacher_case(M, gridVoltage, targetPhaseRms, stopTime)
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    if isfinite(gridVoltage)
        in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    end
    in = in.setVariable('hpt_sac_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    out = sim(in);
end

function rowCells = append_trace_rows(rowCells, out, M, topology, scenarioType, ...
    caseName, gridVoltage, faultPu, Ts, sampleStride, minTime, energyIdMax)

    obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
    dbgRows = orient_channels(out.get('Energy_dbg'), 12);
    mRows = orient_channels(out.get('Menergy_cmd'), 3);
    vdcRows = orient_channels(out.get('Vdc'), 1);
    lvRows = orient_channels(out.get('Vlv_abc'), 3);
    n = min([size(obsRows, 2), size(dbgRows, 2), size(mRows, 2), ...
        size(vdcRows, 2), size(lvRows, 2)]);
    t = (0:n-1) * Ts;
    sampleIdx = find(t >= minTime);
    sampleIdx = sampleIdx(1:sampleStride:end);

    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        theta = dbgRows(1, j);
        [md, mq] = abc_to_dq(mRows(:, j), theta);
        row = struct();
        row.model = string(M);
        row.topology = string(topology);
        row.scenario_type = string(scenarioType);
        row.case_name = string(caseName);
        row.t = t(j);
        row.grid_V = gridVoltage;
        row.fault_pu = faultPu;
        row.energy_id_max = energyIdMax;
        row.energy_theta = theta;
        row.energy_vd = dbgRows(2, j);
        row.energy_vq = dbgRows(3, j);
        row.energy_id = dbgRows(4, j);
        row.energy_iq = dbgRows(5, j);
        row.energy_id_ref = dbgRows(6, j);
        row.energy_iq_ref = 0.0;
        row.energy_id_ref_pu = clip_scalar(dbgRows(6, j) / max(energyIdMax, 1e-9), -0.95, 0.95);
        row.energy_iq_ref_pu = 0.0;
        row.energy_vdc = dbgRows(7, j);
        row.energy_vdc_err = dbgRows(8, j);
        row.energy_p_ac = dbgRows(9, j);
        row.m_energy_a = mRows(1, j);
        row.m_energy_b = mRows(2, j);
        row.m_energy_c = mRows(3, j);
        row.m_energy_d_equiv = md;
        row.m_energy_q_equiv = mq;
        row.vdc = vdcRows(1, j);
        row.lv_rms_inst = sqrt(mean(lvRows(:, j).^2));
        row.target_action_03 = row.energy_id_ref_pu;
        row.target_action_04 = row.energy_iq_ref_pu;
        for ii = 1:24
            row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
        end
        rowCells{end+1} = row; %#ok<AGROW>
    end
end

function [d, q] = abc_to_dq(abc, theta)
    a = abc(1);
    b = abc(2);
    c = abc(3);
    alpha = (2/3) * (a - 0.5*b - 0.5*c);
    beta = (sqrt(3)/3) * (b - c);
    d = alpha*cos(theta) + beta*sin(theta);
    q = -alpha*sin(theta) + beta*cos(theta);
end

function y = clip_scalar(x, lo, hi)
    y = min(max(x, lo), hi);
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
    if isvector(x)
        if nChannels == 1
            y = reshape(x, 1, []);
        else
            y = reshape(x, nChannels, []);
        end
    elseif size(x, 1) == nChannels
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
    cleaner = onCleanup(@() fclose(fid)); %#ok<NASGU>
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
