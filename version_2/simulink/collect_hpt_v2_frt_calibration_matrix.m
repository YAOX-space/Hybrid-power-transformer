% collect_hpt_v2_frt_calibration_matrix
% Switch-level FRT calibration matrix for the version-2 HPT SAC proxy.
%
% Workspace overrides:
%   hpt_calib_mode       "pilot" | "full"        default: "full"
%   hpt_calib_topology   "topology1" | "topology2" | "all"
%
% The script records both aggregate metrics and 2-ms traces.  It uses fixed
% SAC commands so the averaged proxy can be calibrated against the physical
% switch-level response before scenario-specialist SAC training resumes.

clearvars -except hpt_calib_mode hpt_calib_topology;
close all;

if ~exist('hpt_calib_mode', 'var')
    hpt_calib_mode = "full";
end
if ~exist('hpt_calib_topology', 'var')
    hpt_calib_topology = "all";
end
hpt_calib_mode = string(hpt_calib_mode);
hpt_calib_topology = string(hpt_calib_topology);

rootDir = fileparts(mfilename('fullpath'));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

cases = {
    fullfile(rootDir, 'topoloty1'), 'build_hpt_v2_1to1_switchlevel', 'hpt_v2_1to1_switchlevel', 'topology1', 'Zg';
    fullfile(rootDir, 'topology2'), 'build_hpt_v2_topology2_paper', 'hpt_v2_topology2_paper', 'topology2', 'Source_RL';
};

faults = {
    'sag_0p20',   0.20, 'LVRT';
    'sag_0p50',   0.50, 'LVRT';
    'sag_0p75',   0.75, 'LVRT';
    'sag_0p85',   0.85, 'LVRT';
    'sag_0p90',   0.90, 'LVRT';
    'swell_1p10', 1.10, 'HVRT';
    'swell_1p20', 1.20, 'HVRT';
    'swell_1p25', 1.25, 'HVRT';
    'swell_1p30', 1.30, 'HVRT';
};

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
faultStart = 0.035;
faultClear = 0.095;
stopTime = 0.22;
Ts = 20e-6;
sampleStride = 100;  % 2 ms, matching the Python SAC/proxy step.

if hpt_calib_mode == "pilot"
    regDValues = [-0.40, 0.00, 0.40];
    regQValues = 0.0;
    energyActions = [0.0, 0.0; 0.4, 0.0; 0.0, 0.2];
    jointEnergyValues = [0.0, 0.4];
    faults = faults([5, 6], :);
else
    regDValues = [-0.80, -0.60, -0.40, -0.20, 0.00, 0.20, 0.40, 0.60, 0.80];
    regQValues = [-0.40, 0.00, 0.40];
    energyActions = [
        0.00,  0.00;
        0.20,  0.00;
       -0.20,  0.00;
        0.40,  0.00;
       -0.40,  0.00;
        0.00,  0.20;
        0.00, -0.20;
        0.20,  0.20;
        0.40,  0.20
    ];
    jointEnergyValues = [0.0, 0.2, 0.4];
end

rowCells = {};
traceCells = {};
for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if hpt_calib_topology ~= "all" && topology ~= hpt_calib_topology
        continue;
    end

    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    sourceBranch = cases{c, 5};
    replace_grid_with_programmable_source(M, sourceBranch);

    for f = 1:size(faults, 1)
        faultName = string(faults{f, 1});
        faultPu = faults{f, 2};
        category = string(faults{f, 3});

        rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
            "baseline", 0.0, 0.0, 0.0, 0.0, [0.0, 0.0], targetPhaseRms, ...
            nominalGridVoltage, faultStart, faultClear, stopTime, Ts); %#ok<SAGROW>
        traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>

        for rd = 1:numel(regDValues)
            for rq = 1:numel(regQValues)
                rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                    "reg_sweep", 1.0, 0.0, regDValues(rd), regQValues(rq), [0.0, 0.0], ...
                    targetPhaseRms, nominalGridVoltage, faultStart, faultClear, ...
                    stopTime, Ts); %#ok<SAGROW>
                traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
            end
        end

        for ea = 1:size(energyActions, 1)
            rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                "energy_sweep", 0.0, 1.0, 0.0, 0.0, energyActions(ea, :), ...
                targetPhaseRms, nominalGridVoltage, faultStart, faultClear, ...
                stopTime, Ts); %#ok<SAGROW>
            traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
        end

        if faultPu < 1.0
            jointRegValues = [0.20, 0.40, 0.60];
        else
            jointRegValues = [-0.20, -0.40, -0.60];
        end
        for rd = 1:numel(jointRegValues)
            for ed = 1:numel(jointEnergyValues)
                rowCells{end+1} = run_fixed_case(M, topology, faultName, category, faultPu, ...
                    "joint_sweep", 1.0, 1.0, jointRegValues(rd), 0.0, ...
                    [jointEnergyValues(ed), 0.0], targetPhaseRms, nominalGridVoltage, ...
                    faultStart, faultClear, stopTime, Ts); %#ok<SAGROW>
                traceCells = append_trace_cells(traceCells, rowCells{end}, sampleStride); %#ok<AGROW>
            end
        end
    end
    close_system(M, 0);
end

aggregateCells = cell(size(rowCells));
for i = 1:numel(rowCells)
    aggregateCells{i} = strip_trace(rowCells{i});
end
rows = [aggregateCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', 'hpt_v2_frt_calibration_matrix');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = char(regexprep(sprintf('%s_%s', hpt_calib_mode, hpt_calib_topology), '[^A-Za-z0-9_]+', '_'));
outMat = fullfile(outDir, ['frt_calibration_matrix_' safeName '_' stamp '.mat']);
outCsv = fullfile(outDir, ['frt_calibration_matrix_' safeName '_' stamp '.csv']);
traceCsv = fullfile(outDir, ['frt_calibration_traces_' safeName '_' stamp '.csv']);
save(outMat, 'rows', 'traceCells', 'faults', 'targetPhaseRms', ...
    'nominalGridVoltage', 'faultStart', 'faultClear', 'stopTime', ...
    'Ts', 'sampleStride', 'hpt_calib_mode', 'hpt_calib_topology');
writetable(struct2table(rows), outCsv);
write_trace_csv(traceCsv, traceCells);

fprintf('HPT FRT calibration matrix complete.\n');
fprintf('Rows: %d, trace samples: %d\n', numel(rows), numel(traceCells));
fprintf('Saved aggregate CSV: %s\n', outCsv);
fprintf('Saved trace CSV: %s\n', traceCsv);

function row = run_fixed_case(M, topology, faultName, category, faultPu, mode, ...
    regEnable, energyEnable, mRegD, mRegQ, energyCmd, targetPhaseRms, ...
    nominalGridVoltage, faultStart, faultClear, stopTime, Ts)

    mEnergyD = energyCmd(1);
    mEnergyQ = energyCmd(2);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = set_programmable_grid(in, M, nominalGridVoltage, faultPu, ...
        faultStart, faultClear, stopTime);
    in = in.setVariable('hpt_sac_enable', regEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', energyEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', -1.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', 2.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_d', mRegD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', mRegQ, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', mEnergyD, 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', mEnergyQ, 'Workspace', M);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    if has_logged_var(out, 'Energy_Iabc')
        Ienergy = out.get('Energy_Iabc');
    else
        Ienergy = zeros(size(Vlv));
    end

    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    iRows = orient_channels(Ienergy, 3);
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultIdx = t > (faultStart + 0.010) & t < (faultClear - 0.002);
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    activeIdx = t > faultStart & t < stopTime;
    tailStart = max(1, round(size(actRows, 2) * 0.7));
    phaseRmsFault = sqrt(mean(Vlv(faultIdx, 1:3).^2, 1));
    iRmsFault = sqrt(mean(iRows(:, faultIdx).^2, 2));

    row = struct();
    row.model = string(M);
    row.topology = string(topology);
    row.scenario_type = "fault";
    row.category = string(category);
    row.condition_class = lower(string(category));
    row.fault = string(faultName);
    row.case_name = string(faultName);
    row.fault_pu = faultPu;
    row.grid_pu = faultPu;
    row.mode = string(mode);
    row.target_phase_rms = targetPhaseRms;
    row.fault_start = faultStart;
    row.fault_clear = faultClear;
    row.stop_time = stopTime;
    row.raw_m_reg_d = mRegD;
    row.raw_m_reg_q = mRegQ;
    row.raw_m_energy_d = mEnergyD;
    row.raw_m_energy_q = mEnergyQ;
    row.reg_enable = regEnable;
    row.energy_enable = energyEnable;
    row.action_semantics = "fixed_frt_calibration_command";
    row.action_raw_available = true;
    row.action_projected_available = true;
    row.action_effective_available = true;
    row.lv_fault_rms_mean = safe_mean(phaseRmsInst(faultIdx));
    row.lv_recovery_rms_mean = safe_mean(phaseRmsInst(recoveryIdx));
    row.lv_peak_rms = max(phaseRmsInst(activeIdx));
    row.lv_min_rms = min(phaseRmsInst(activeIdx));
    row.lv_pu_mean = row.lv_fault_rms_mean / targetPhaseRms;
    row.lv_recovery_pu_mean = row.lv_recovery_rms_mean / targetPhaseRms;
    row.lv_peak_pu = row.lv_peak_rms / targetPhaseRms;
    row.lv_min_pu = row.lv_min_rms / targetPhaseRms;
    row.lv_unbalance = max(phaseRmsFault) - min(phaseRmsFault);
    row.lv_unbalance_pu = row.lv_unbalance / targetPhaseRms;
    row.vdc_mean = safe_mean(Vdc(round(end*0.7):end, 1));
    row.vdc_min = min(Vdc(:, 1));
    row.vdc_max = max(Vdc(:, 1));
    row.vdc_pu_mean = row.vdc_mean / 800.0;
    row.vdc_min_pu = row.vdc_min / 800.0;
    row.vdc_max_pu = row.vdc_max / 800.0;
    row.energy_i_rms_mean = safe_mean(iRmsFault);
    row.action_max_abs = max(abs(actRows), [], 'all');
    row.reg_d_mean = safe_mean(actRows(1, tailStart:end));
    row.reg_q_mean = safe_mean(actRows(2, tailStart:end));
    row.energy_d_mean = safe_mean(actRows(3, tailStart:end));
    row.energy_q_mean = safe_mean(actRows(4, tailStart:end));
    row.obs_dim = size(obsRows, 1);
    row.action_dim = size(actRows, 1);
    row.trace_t = t;
    row.trace_vlv = phaseRmsInst;
    row.trace_vdc = Vdc(:, 1);
    row.trace_obs = obsRows;
    row.trace_act = actRows;
end

function traceCells = append_trace_cells(traceCells, row, sampleStride)
    t = row.trace_t;
    n = numel(t);
    sampleIdx = 1:sampleStride:n;
    for kk = 1:numel(sampleIdx)
        j = sampleIdx(kk);
        tr = struct();
        tr.model = row.model;
        tr.topology = row.topology;
        tr.scenario_type = row.scenario_type;
        tr.category = row.category;
        tr.condition_class = row.condition_class;
        tr.fault = row.fault;
        tr.case_name = row.case_name;
        tr.mode = row.mode;
        tr.t = t(j);
        tr.fault_pu = row.fault_pu;
        tr.grid_pu = row.grid_pu;
        tr.raw_m_reg_d = row.raw_m_reg_d;
        tr.raw_m_reg_q = row.raw_m_reg_q;
        tr.raw_m_energy_d = row.raw_m_energy_d;
        tr.raw_m_energy_q = row.raw_m_energy_q;
        tr.lv_rms_inst = row.trace_vlv(j);
        tr.lv_pu_inst = row.trace_vlv(j) / row.target_phase_rms;
        tr.vdc_inst = row.trace_vdc(j);
        tr.vdc_pu_inst = row.trace_vdc(j) / 800.0;
        tr.window_zone = classify_zone(t(j), row.fault_start, row.fault_clear, row.stop_time);
        for ii = 1:24
            tr.(sprintf('obs_%02d', ii)) = row.trace_obs(ii, j);
        end
        for ii = 1:4
            tr.(sprintf('actor_action_%02d', ii)) = row.trace_act(ii, j);
        end
        traceCells{end+1} = tr; %#ok<AGROW>
    end
end

function zone = classify_zone(t, faultStart, faultClear, stopTime)
    if t < faultStart
        zone = "pre_fault";
    elseif t < faultClear
        zone = "fault";
    elseif t < stopTime - 0.005
        zone = "recovery";
    else
        zone = "final";
    end
end

function in = set_programmable_grid(in, M, nominalGridVoltage, faultPu, faultStart, faultClear, stopTime)
    grid = [M '/Grid'];
    t1 = max(0.0, faultStart - 1e-4);
    t2 = faultStart;
    t3 = faultClear;
    t4 = min(stopTime, faultClear + 1e-4);
    in = in.setBlockParameter(grid, 'PositiveSequence', ...
        sprintf('[%.12g 0 50]', nominalGridVoltage));
    in = in.setBlockParameter(grid, 'VariationEntity', 'Amplitude');
    in = in.setBlockParameter(grid, 'VariationType', 'Table of time-amplitude pairs');
    in = in.setBlockParameter(grid, 'TimeValues', ...
        sprintf('[0 %.12g %.12g %.12g %.12g %.12g]', t1, t2, t3, t4, stopTime));
    in = in.setBlockParameter(grid, 'Amplitudes', ...
        sprintf('[1 1 %.12g %.12g 1 1]', faultPu, faultPu));
end

function replace_grid_with_programmable_source(M, sourceBranch)
    grid = [M '/Grid'];
    pos = get_param(grid, 'Position');
    delete_block(grid);
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source', ...
        grid, 'Position', pos);
    for k = 1:3
        connect_if_free(M, ph(grid, 'RConn', k), ...
            ph([M '/' sourceBranch], 'LConn', k));
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

function tf = has_logged_var(out, name)
    names = who(out);
    tf = any(strcmp(names, name));
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

function m = safe_mean(x)
    if isempty(x)
        m = NaN;
    else
        y = x(:);
        y = y(~isnan(y));
        if isempty(y)
            m = NaN;
        else
            m = mean(y);
        end
    end
end

function row = strip_trace(row)
    row = rmfield(row, {'trace_t', 'trace_vlv', 'trace_vdc', 'trace_obs', 'trace_act'});
end

function write_trace_csv(path, rowCells)
    if isempty(rowCells)
        fid = fopen(path, 'w');
        fclose(fid);
        return;
    end
    T = struct2table([rowCells{:}]);
    writetable(T, path);
end
