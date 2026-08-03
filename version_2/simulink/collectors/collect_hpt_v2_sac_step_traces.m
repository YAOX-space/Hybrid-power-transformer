% collect_hpt_v2_sac_step_traces
% Collect per-SAC-step switch-level traces for specialist HPT SAC training.
%
% The output CSV is compatible with pretrain_hpt_actor_bc.py
% --switch-trace-csv.  For each sampled time step it stores:
%   obs_01..obs_24       HPTSAC observation
%   action_01..action_04 teacher target action used for BC
%   actor_action_01..04  action emitted by HPTSACController in this run
%   LV/Vdc instantaneous values and window-zone labels
%
% The current teacher target is the conventional voltage regulator plus the
% conventional energy current loop.  This gives direct switch-level labels
% without using aggregate smoke rows.

clearvars;
close all;

rootDir = fileparts(fileparts(mfilename('fullpath')));
cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg', 200, 210, 6.0, 760, 920, 196, 214, 650, 235, 180;
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL', 198, 212, 8.0, 760, 930, 194, 220, 620, 235, 180;
};

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

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
faultStart = 0.035;
faultClear = 0.095;
faultStopTime = 0.16;
Ts = 20e-6;
sampleStride = 100;  % 2 ms, matching the Python averaged env step.

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    topology = cases{c, 4};
    sourceBranch = cases{c, 5};
    caseSpec = cases(c, :);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');

    for k = 1:numel(steadyGridVoltages)
        out = run_conventional_case(M, steadyGridVoltages(k), 0.0, targetPhaseRms, steadyStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "steady", ...
            sprintf("grid_%.0fV", steadyGridVoltages(k)), steadyGridVoltages(k), ...
            NaN, NaN, Ts, sampleStride, 0.010, energyIdMax, targetPhaseRms, ...
            faultStart, faultClear, steadyStopTime, caseSpec);
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
        out = run_conventional_case(M, NaN, 2.0, targetPhaseRms, faultStopTime);
        rowCells = append_trace_rows(rowCells, out, M, topology, "fault", ...
            faultName, NaN, faultPu, faultPu, Ts, sampleStride, 0.010, ...
            energyIdMax, targetPhaseRms, faultStart, faultClear, faultStopTime, ...
            caseSpec);
    end
    close_system(M, 0);
end

outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_sac_step_traces');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
outMat = fullfile(outDir, ['step_traces_' stamp '.mat']);
outCsv = fullfile(outDir, ['step_traces_' stamp '.csv']);
save(outMat, 'rowCells', 'targetPhaseRms', 'steadyGridVoltages', 'faults', ...
    'faultStart', 'faultClear', 'sampleStride');
write_trace_csv(outCsv, rowCells);

fprintf('Collected %d per-step switch-level SAC traces.\n', numel(rowCells));
fprintf('Saved MAT: %s\n', outMat);
fprintf('Saved CSV: %s\n', outCsv);

function out = run_conventional_case(M, gridVoltage, actorSelectMode, targetPhaseRms, stopTime)
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    if isfinite(gridVoltage)
        in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    end
    in = in.setVariable('hpt_sac_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, ...
        'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    out = sim(in);
end

function rowCells = append_trace_rows(rowCells, out, M, topology, scenarioType, ...
    caseName, gridVoltage, faultPu, gridPu, Ts, sampleStride, minTime, ...
    energyIdMax, targetPhaseRms, faultStart, faultClear, stopTime, caseSpec)

    obsRows = orient_channels(out.get('HPTSAC_obs'), 24);
    actRows = orient_channels(out.get('HPTSAC_action'), 4);
    regDbgRows = orient_channels(out.get('Mreg_cmd'), 7);
    mRegRows = orient_channels(out.get('Mref6_cmd'), 6);
    dbgRows = orient_channels(out.get('Energy_dbg'), 12);
    vdcRows = orient_channels(out.get('Vdc'), 1);
    lvRows = orient_channels(out.get('Vlv_abc'), 3);
    n = min([size(obsRows, 2), size(actRows, 2), size(regDbgRows, 2), ...
        size(mRegRows, 2), size(dbgRows, 2), size(vdcRows, 2), ...
        size(lvRows, 2)]);
    t = (0:n-1) * Ts;
    sampleIdx = find(t >= minTime);
    sampleIdx = sampleIdx(1:sampleStride:end);

    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        regTheta = regDbgRows(1, j);
        regPhi = regDbgRows(7, j);
        [regMd, regMq] = reg6_to_dq(mRegRows(:, j), regTheta + regPhi);
        energyIdRefPu = clip_scalar(dbgRows(6, j) / max(energyIdMax, 1e-9), -0.95, 0.95);

        lvInst = sqrt(mean(lvRows(:, j).^2));
        vdcInst = vdcRows(1, j);
        [zone, windowOk, windowReason] = classify_window( ...
            scenarioType, t(j), lvInst, vdcInst, faultStart, faultClear, stopTime, caseSpec);

        row = struct();
        row.model = string(M);
        row.topology = string(topology);
        row.scenario_type = string(scenarioType);
        row.condition_class = condition_class(scenarioType, faultPu);
        row.case_name = string(caseName);
        row.t = t(j);
        row.window_zone = string(zone);
        row.window_ok = double(windowOk);
        row.window_reason = string(windowReason);
        row.grid_V = gridVoltage;
        row.fault_pu = faultPu;
        row.grid_pu = gridPu;
        row.lv_rms_inst = lvInst;
        row.vdc_inst = vdcInst;
        row.reg_theta = regTheta;
        row.reg_phi = regPhi;
        row.energy_id_max = energyIdMax;
        for ii = 1:24
            row.(sprintf('obs_%02d', ii)) = obsRows(ii, j);
        end
        row.action_01 = clip_scalar(regMd, -0.80, 0.80);
        row.action_02 = clip_scalar(regMq, -0.80, 0.80);
        row.action_03 = energyIdRefPu;
        row.action_04 = 0.0;
        for ii = 1:4
            row.(sprintf('actor_action_%02d', ii)) = actRows(ii, j);
        end
        rowCells{end+1} = row; %#ok<AGROW>
    end
end

function c = condition_class(scenarioType, faultPu)
    if scenarioType == "steady" || ~isfinite(faultPu)
        c = "steady";
    elseif faultPu < 0.80
        c = "deep_lvrt";
    elseif faultPu < 1.0
        c = "shallow_lvrt";
    elseif faultPu <= 1.20
        c = "shallow_hvrt";
    else
        c = "high_hvrt";
    end
end

function [zone, ok, reason] = classify_window( ...
    scenarioType, t, lvInst, vdcInst, faultStart, faultClear, stopTime, caseSpec)

    reason = "";
    ok = true;
    if scenarioType == "steady"
        if t <= 0.05
            zone = "startup";
            return;
        end
        zone = "steady";
        lvLo = caseSpec{6};
        lvHi = caseSpec{7};
        vdcLo = caseSpec{9};
        vdcHi = caseSpec{10};
        if lvInst < lvLo || lvInst > lvHi
            ok = false;
            reason = append_reason(reason, "steady_lv_inst");
        end
        if vdcInst < vdcLo || vdcInst > vdcHi
            ok = false;
            reason = append_reason(reason, "steady_vdc_inst");
        end
        return;
    end

    if t < faultStart
        zone = "prefault";
        return;
    elseif t < faultClear
        zone = "fault";
    elseif t < stopTime - 0.005
        zone = "recovery";
    else
        zone = "tail";
    end
    lvLo = caseSpec{11};
    lvHi = caseSpec{12};
    vdcLo = caseSpec{13};
    lvPeakHi = caseSpec{14};
    lvMinLo = caseSpec{15};
    if (zone == "fault" || zone == "recovery") && (lvInst < lvLo || lvInst > lvHi)
        ok = false;
        reason = append_reason(reason, "fault_lv_inst");
    end
    if lvInst > lvPeakHi
        ok = false;
        reason = append_reason(reason, "lv_peak_inst");
    end
    if lvInst < lvMinLo
        ok = false;
        reason = append_reason(reason, "lv_min_inst");
    end
    if vdcInst < vdcLo
        ok = false;
        reason = append_reason(reason, "vdc_min_inst");
    end
end

function reason = append_reason(reason, token)
    if strlength(string(reason)) == 0
        reason = token;
    else
        reason = reason + ";" + token;
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
            elseif isnumeric(value) || islogical(value)
                fprintf(fid, '%.15g', value);
            else
                fprintf(fid, '"%s"', char(string(value)));
            end
        end
        fprintf(fid, '\n');
    end
end

