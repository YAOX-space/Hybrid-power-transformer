% eval_hpt_v2_control_comparison
% Compare legacy conventional, tuned conventional dq/PI, and SAC raw guard=0
% on the same switch-level HPT plants and FRT scenarios.
%
% Workspace overrides:
%   hpt_compare_topology       "topology1" | "topology2" | "all"
%   hpt_compare_scenario_type  "steady" | "fault" | "all"
%   hpt_compare_case_name      e.g. "grid_10000V", "sag_0p90", "all"
%   hpt_compare_modes          string array, default primary comparison modes
%   hpt_compare_energy_enable  default 1.0 for SAC energy bridge
%   hpt_compare_conventional_profile "tuned_v1" | "model_default"
%   hpt_compare_conventional_params  optional struct of model-workspace overrides
%   hpt_compare_faults        optional cell array: {name, pu} or {name, pu, duration_s}
%   hpt_compare_fault_start   optional fault start time, default 0.035 s
%   hpt_compare_fault_stop_margin optional post-fault window after clear, default 0.125 s
%   hpt_compare_fixed_action optional 1x4 fixed action for mode "fixed_action":
%                            [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

clearvars -except hpt_compare_topology hpt_compare_scenario_type hpt_compare_case_name hpt_compare_modes hpt_compare_energy_enable hpt_compare_conventional_profile hpt_compare_conventional_params hpt_compare_faults hpt_compare_fault_start hpt_compare_fault_stop_margin hpt_compare_run_label hpt_compare_fixed_action;
close all;

if ~exist('hpt_compare_topology', 'var')
    hpt_compare_topology = "all";
end
if ~exist('hpt_compare_scenario_type', 'var')
    hpt_compare_scenario_type = "all";
end
if ~exist('hpt_compare_case_name', 'var')
    hpt_compare_case_name = "all";
end
if ~exist('hpt_compare_modes', 'var')
    hpt_compare_modes = ["legacy_conventional", "conventional_dq", "sac_actor_raw_guard0"];
end
if ~exist('hpt_compare_energy_enable', 'var')
    hpt_compare_energy_enable = 1.0;
end
if ~exist('hpt_compare_conventional_profile', 'var')
    hpt_compare_conventional_profile = "tuned_v1";
end
if ~exist('hpt_compare_conventional_params', 'var')
    hpt_compare_conventional_params = struct();
end
if ~exist('hpt_compare_fault_start', 'var')
    hpt_compare_fault_start = 0.035;
end
if ~exist('hpt_compare_fault_stop_margin', 'var')
    hpt_compare_fault_stop_margin = 0.125;
end
if ~exist('hpt_compare_run_label', 'var')
    hpt_compare_run_label = "";
end
if ~exist('hpt_compare_fixed_action', 'var')
    hpt_compare_fixed_action = [0, 0, 0, 0];
end
hpt_compare_fixed_action = double(hpt_compare_fixed_action(:)');
assert(numel(hpt_compare_fixed_action) == 4, ...
    'hpt_compare_fixed_action must be [m_reg_d,m_reg_q,m_energy_d,m_energy_q]');

hpt_compare_topology = string(hpt_compare_topology);
hpt_compare_scenario_type = string(hpt_compare_scenario_type);
hpt_compare_case_name = string(hpt_compare_case_name);
hpt_compare_modes = string(hpt_compare_modes);
hpt_compare_conventional_profile = string(hpt_compare_conventional_profile);

rootDir = fileparts(mfilename('fullpath'));
actorFile = fullfile(rootDir, 'hpt_sac_actor_weights.mat');
dynamicActorFile = fullfile(rootDir, 'hpt_sac_actor_weights_dynamic.mat');
if any(hpt_compare_modes == "sac_actor_raw_guard0")
    assert(exist(actorFile, 'file') == 2, 'Missing HPT SAC actor: %s', actorFile);
    assert(exist(dynamicActorFile, 'file') == 2, ...
        'Missing dynamic HPT SAC actor: %s', dynamicActorFile);
    actor = load(actorFile, 'n_obs', 'n_act');
    assert(double(actor.n_obs) == 24 && double(actor.n_act) == 4, ...
        'HPT SAC actor must be 24/4, got %.0f/%.0f', double(actor.n_obs), double(actor.n_act));
end

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
if exist('hpt_compare_faults', 'var') && ~isempty(hpt_compare_faults)
    faults = hpt_compare_faults;
end

targetPhaseRms = 207.0;
nominalGridVoltage = 10000;
steadyStopTime = 0.08;
steadySettleStart = 0.05;
faultStart = hpt_compare_fault_start;
defaultFaultDuration = 0.060;
faultStopMargin = hpt_compare_fault_stop_margin;
Ts = 20e-6;

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
rowCells = {};

for c = 1:size(cases, 1)
    topology = string(cases{c, 4});
    if hpt_compare_topology ~= "all" && topology ~= hpt_compare_topology
        continue;
    end

    cd(cases{c, 1});
    feval(cases{c, 2});
    M = cases{c, 3};
    sourceBranch = cases{c, 5};

    if hpt_compare_scenario_type == "all" || hpt_compare_scenario_type == "steady"
        for k = 1:numel(steadyGridVoltages)
            caseName = string(sprintf("grid_%.0fV", steadyGridVoltages(k)));
            if hpt_compare_case_name ~= "all" && caseName ~= hpt_compare_case_name
                continue;
            end
            for m = 1:numel(hpt_compare_modes)
                mode = hpt_compare_modes(m);
                rowCells{end+1} = run_steady_case(M, topology, mode, ...
                    steadyGridVoltages(k), targetPhaseRms, steadyStopTime, ...
                    steadySettleStart, Ts, cases(c, :), hpt_compare_energy_enable); %#ok<SAGROW>
            end
        end
    end
    close_system(M, 0);

    if hpt_compare_scenario_type == "all" || hpt_compare_scenario_type == "fault"
        feval(cases{c, 2});
        M = cases{c, 3};
        replace_grid_with_programmable_source(M, sourceBranch, nominalGridVoltage, ...
            1.0, faultStart, faultStart + defaultFaultDuration, ...
            faultStart + defaultFaultDuration + faultStopMargin);

        for f = 1:size(faults, 1)
            faultName = string(faults{f, 1});
            if hpt_compare_case_name ~= "all" && faultName ~= hpt_compare_case_name
                continue;
            end
            faultPu = faults{f, 2};
            if size(faults, 2) >= 3 && ~isempty(faults{f, 3})
                faultDuration = faults{f, 3};
            else
                faultDuration = defaultFaultDuration;
            end
            faultClear = faultStart + faultDuration;
            faultStopTime = faultClear + faultStopMargin;
            configure_programmable_grid(M, nominalGridVoltage, faultPu, ...
                faultStart, faultClear, faultStopTime);
            for m = 1:numel(hpt_compare_modes)
                mode = hpt_compare_modes(m);
                rowCells{end+1} = run_fault_case(M, topology, faultName, faultPu, ...
                    mode, targetPhaseRms, faultStopTime, Ts, faultStart, ...
                    faultClear, cases(c, :), hpt_compare_energy_enable); %#ok<SAGROW>
            end
        end
        close_system(M, 0);
    end
end

assert(~isempty(rowCells), 'No comparison cases matched topology=%s scenario=%s case=%s', ...
    hpt_compare_topology, hpt_compare_scenario_type, hpt_compare_case_name);

rows = [rowCells{:}];
outDir = fullfile(rootDir, '..', '..', 'lab', 'results', ...
    'hpt_v2_control_comparison');
if exist(outDir, 'dir') ~= 7
    mkdir(outDir);
end
stamp = datestr(now, 'yyyymmdd_HHMMSS');
safeName = regexprep(sprintf('%s_%s_%s_%s', hpt_compare_topology, ...
    hpt_compare_scenario_type, hpt_compare_case_name, hpt_compare_run_label), ...
    '[^A-Za-z0-9_]+', '_');
outMat = fullfile(outDir, ['control_comparison_' char(safeName) '_' stamp '.mat']);
outCsv = fullfile(outDir, ['control_comparison_' char(safeName) '_' stamp '.csv']);
save(outMat, 'rows', 'targetPhaseRms', 'hpt_compare_topology', ...
    'hpt_compare_scenario_type', 'hpt_compare_case_name', 'hpt_compare_modes', ...
    'hpt_compare_conventional_profile', 'hpt_compare_conventional_params', ...
    'faults', 'hpt_compare_run_label', 'hpt_compare_fixed_action');
writetable(struct2table(rows), outCsv);

fprintf('HPT control comparison complete.\n');
fprintf('%-10s %-8s %-11s %-22s %8s %10s %10s %9s %9s %9s %-8s %s\n', ...
    'topology', 'type', 'case', 'mode', 'grid/pu', 'LV_mean', ...
    'LV_recov', 'VdcMin', 'max|a|', 'score', 'pass', 'reason');
for i = 1:numel(rows)
    if rows(i).scenario_type == "steady"
        caseValue = rows(i).grid_V;
    else
        caseValue = rows(i).fault_pu;
    end
    fprintf('%-10s %-8s %-11s %-22s %8.2f %10.3f %10.3f %9.3f %9.3f %9.3f %-8s %s\n', ...
        rows(i).topology, rows(i).scenario_type, rows(i).case_name, ...
        rows(i).mode, caseValue, rows(i).lv_mean, rows(i).lv_recovery_mean, ...
        rows(i).vdc_min, rows(i).action_max_abs, rows(i).control_score, ...
        string(rows(i).within_window), rows(i).window_reason);
end
fprintf('Saved CSV: %s\n', outCsv);

function [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, scenarioType, topology, energyEnableDefault)
    mode = string(mode);
    topology = string(topology);
    if mode == "legacy_conventional" || mode == "no_control"
        sacEnable = 0.0;
        energyEnable = 0.0;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "conventional_dq"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "rule_fallback"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 0.0;
        actorSelectMode = 0.0;
    elseif mode == "sac_actor_raw_guard0"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = 1.0;
        if string(scenarioType) == "fault"
            actorSelectMode = 2.0;
        else
            actorSelectMode = 0.0;
        end
    elseif mode == "fixed_action"
        sacEnable = 1.0;
        energyEnable = energyEnableDefault;
        policyMode = -1.0;
        actorSelectMode = 0.0;
    else
        error('Unknown comparison mode: %s', mode);
    end
end

function row = run_steady_case(M, topology, mode, gridVoltage, targetPhaseRms, ...
    stopTime, settleStart, Ts, caseSpec, energyEnableDefault)

    [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, "steady", topology, energyEnableDefault);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = in.setBlockParameter([M '/Grid'], 'Voltage', num2str(gridVoltage));
    in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
        actorSelectMode, targetPhaseRms);
    in = apply_conventional_profile(in, M, topology, mode);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    mref = out.get('Mref6_cmd');
    meng = out.get('Menergy_cmd');
    mregDbg = out.get('Mreg_cmd');
    energyDbg = out.get('Energy_dbg');
    t = (0:size(Vlv, 1)-1)' * Ts;
    idx = t > settleStart;
    phaseRms = sqrt(mean(Vlv(idx, 1:3).^2, 1));
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    mrefRows = orient_channels(mref, 6);
    mengRows = orient_channels(meng, 3);
    mregDbgRows = orient_channels(mregDbg, 7);
    energyDbgRows = orient_channels(energyDbg, 12);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    cmdActRows = actRows;
    measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
        energyDbgRows, energyIdMax);

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
    row = add_action_semantics(row, cmdActRows, measActRows, mrefRows, mengRows);
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));

    [row.within_window, row.window_reason] = assess_steady(row, caseSpec);
    row.voltage_survival_pass = row.within_window;
    row.voltage_survival_reason = row.window_reason;
    row.full_frt_pass = row.within_window;
    row.full_frt_reason = row.window_reason;
    row.control_score = score_row(row);
end

function row = run_fault_case(M, topology, faultName, faultPu, mode, ...
    targetPhaseRms, stopTime, Ts, faultStart, faultClear, caseSpec, energyEnableDefault)

    [sacEnable, energyEnable, policyMode, actorSelectMode] = mode_settings(mode, "fault", topology, energyEnableDefault);
    in = Simulink.SimulationInput(M);
    in = in.setModelParameter('StopTime', num2str(stopTime));
    in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
        actorSelectMode, targetPhaseRms);
    in = apply_conventional_profile(in, M, topology, mode);
    out = sim(in);

    Vlv = out.get('Vlv_abc');
    Vdc = out.get('Vdc');
    if string(topology) == "topology1"
        Vgrid = out.get('Vmv_abc');
    else
        Vgrid = out.get('Vpri_abc');
    end
    Igrid = out.get('Igrid_abc');
    obs = out.get('HPTSAC_obs');
    act = out.get('HPTSAC_action');
    mref = out.get('Mref6_cmd');
    meng = out.get('Menergy_cmd');
    mregDbg = out.get('Mreg_cmd');
    energyDbg = out.get('Energy_dbg');
    t = (0:size(Vlv, 1)-1)' * Ts;
    phaseRmsInst = sqrt(mean(Vlv(:, 1:3).^2, 2));
    faultDuration = faultClear - faultStart;
    faultEnterGuard = min(0.025, max(0.004, 0.20 * faultDuration));
    faultExitGuard = min(0.005, max(0.002, 0.10 * faultDuration));
    faultIdx = t > (faultStart + faultEnterGuard) & t < (faultClear - faultExitGuard);
    if ~any(faultIdx)
        faultIdx = t >= faultStart & t <= faultClear;
    end
    recoveryIdx = t > (faultClear + 0.035) & t < (stopTime - 0.005);
    obsRows = orient_channels(obs, 24);
    actRows = orient_channels(act, 4);
    gridVRows = orient_channels(Vgrid, 3);
    gridIRows = orient_channels(Igrid, 3);
    mrefRows = orient_channels(mref, 6);
    mengRows = orient_channels(meng, 3);
    mregDbgRows = orient_channels(mregDbg, 7);
    energyDbgRows = orient_channels(energyDbg, 12);
    energyIdMax = getVariable(get_param(M, 'ModelWorkspace'), 'hpt_energy_id_max');
    cmdActRows = actRows;
    measActRows = measured_response_rows(actRows, mrefRows, mregDbgRows, ...
        energyDbgRows, energyIdMax);

    row = base_row(M, topology, "fault", faultName, mode, NaN, faultPu);
    row.fault_start_s = faultStart;
    row.fault_clear_s = faultClear;
    row.fault_duration_s = faultClear - faultStart;
    row.stop_time_s = stopTime;
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
    row = add_action_semantics(row, cmdActRows, measActRows, mrefRows, mengRows);
    row.obs_vpu_mean = mean(obsRows(1, round(end*0.7):end));
    row.obs_vpos_mean = mean(obsRows(2, round(end*0.7):end));
    row.obs_vdcpu_mean = mean(obsRows(4, round(end*0.7):end));
    row.obs_verr_mean = mean(obsRows(6, round(end*0.7):end));
    row.obs_fault_flag_mean = mean(obsRows(17, round(end*0.7):end));
    row.obs_recovery_flag_mean = mean(obsRows(18, round(end*0.7):end));
    row = add_gbt_fault_metrics(row, phaseRmsInst, Vdc(:, 1), actRows, ...
        gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
        faultClear, stopTime);

    [row.voltage_survival_pass, row.voltage_survival_reason] = assess_fault_voltage_survival(row);
    [row.full_frt_pass, row.full_frt_reason] = assess_fault(row);
    row.within_window = row.full_frt_pass;
    row.window_reason = row.full_frt_reason;
    row.control_score = score_row(row);
end

function in = apply_conventional_profile(in, M, topology, mode)
    mode = string(mode);
    if mode ~= "conventional_dq"
        return;
    end

    profile = evalin('base', 'hpt_compare_conventional_profile');
    overrides = evalin('base', 'hpt_compare_conventional_params');
    profile = string(profile);
    topology = string(topology);

    if profile == "tuned_v1"
        if topology == "topology1"
            in = in.setVariable('hpt_vreg_kp', 16.0, 'Workspace', M);
            in = in.setVariable('hpt_vreg_ki', 4.0, 'Workspace', M);
            in = in.setVariable('hpt_m_reg_max', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_inj_phase_offset', -1.05, 'Workspace', M);
            in = in.setVariable('hpt_swell_gain_scale', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_vdc_kp', 0.16, 'Workspace', M);
            in = in.setVariable('hpt_vdc_ki', 0.30, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_kp', 0.65, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_ki', 90.0, 'Workspace', M);
        else
            % Topology2's physical EnergyController outer DC loop currently
            % has the wrong sign around the parallel-coupled energy port.
            % Use the HPTSACController policy_mode=0 rule/dq current loop as
            % the strong traditional baseline, keeping its calibrated default
            % current-loop and injection parameters.
            in = in.setVariable('hpt_inj_phase_offset', -1.05, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_kp', 0.50, 'Workspace', M);
            in = in.setVariable('hpt_energy_i_ki', 100.0, 'Workspace', M);
            in = in.setVariable('hpt_energy_vff_gain', 1.06, 'Workspace', M);
            in = in.setVariable('hpt_energy_control_sign', -1.0, 'Workspace', M);
            in = in.setVariable('hpt_energy_bridge_polarity', -1.0, 'Workspace', M);
        end
    elseif profile ~= "model_default"
        error('Unknown conventional profile: %s', profile);
    end

    names = fieldnames(overrides);
    for k = 1:numel(names)
        in = in.setVariable(names{k}, overrides.(names{k}), 'Workspace', M);
    end
end

function v = actual_action_max(mrefRows, mengRows)
    v = max([abs(mrefRows(:)); abs(mengRows(:))]);
end

function actRows = measured_response_rows(hptActRows, mrefRows, mregDbgRows, ...
    energyDbgRows, energyIdMax)
    n = min([size(mrefRows, 2), size(mregDbgRows, 2), size(energyDbgRows, 2)]);
    if isempty(n) || n < 1
        actRows = hptActRows;
        return;
    end
    actRows = zeros(4, n);
    for k = 1:n
        theta = mregDbgRows(1, k);
        phi = mregDbgRows(7, k);
        [actRows(1, k), actRows(2, k)] = reg6_to_dq(mrefRows(:, k), theta + phi);
        actRows(3, k) = clip_scalar(energyDbgRows(6, k) / max(energyIdMax, 1e-9), ...
            -0.95, 0.95);
        actRows(4, k) = 0.0;
    end
end

function row = add_action_semantics(row, cmdRows, measRows, mrefRows, mengRows)
    row.cmd_action_max_abs = matrix_max_abs(cmdRows);
    row.bridge_modulation_abs_max = actual_action_max(mrefRows, mengRows);
    row.action_max_abs = row.bridge_modulation_abs_max;

    row.cmd_m_reg_d_mean = tail_row_mean(cmdRows, 1);
    row.cmd_m_reg_q_mean = tail_row_mean(cmdRows, 2);
    row.cmd_m_energy_d_mean = tail_row_mean(cmdRows, 3);
    row.cmd_m_energy_q_mean = tail_row_mean(cmdRows, 4);

    row.meas_reg_d_mean = tail_row_mean(measRows, 1);
    row.meas_reg_q_mean = tail_row_mean(measRows, 2);
    row.meas_energy_d_mean = tail_row_mean(measRows, 3);
    row.meas_energy_q_mean = tail_row_mean(measRows, 4);

    % Backward-compatible fields now mean effective switch-level response.
    row.reg_d_mean = row.meas_reg_d_mean;
    row.reg_q_mean = row.meas_reg_q_mean;
    row.energy_d_mean = row.meas_energy_d_mean;
    row.energy_q_mean = row.meas_energy_q_mean;
end

function v = matrix_max_abs(rows)
    if isempty(rows)
        v = NaN;
    else
        v = max(abs(rows(:)));
    end
end

function v = tail_row_mean(rows, idx)
    if isempty(rows) || size(rows, 1) < idx || size(rows, 2) < 1
        v = NaN;
        return;
    end
    tailStart = max(1, round(size(rows, 2) * 0.7));
    v = mean(rows(idx, tailStart:end));
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

function in = set_common_variables(in, M, sacEnable, energyEnable, policyMode, ...
    actorSelectMode, targetPhaseRms)

    in = in.setVariable('hpt_sac_enable', sacEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_energy_enable', energyEnable, 'Workspace', M);
    in = in.setVariable('hpt_sac_policy_mode', policyMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_actor_select_mode', actorSelectMode, 'Workspace', M);
    in = in.setVariable('hpt_sac_guard_enable', 0.0, 'Workspace', M);
    in = in.setVariable('hpt_sac_vref_phase', targetPhaseRms, 'Workspace', M);
    fixedAction = evalin('base', 'hpt_compare_fixed_action');
    in = in.setVariable('hpt_sac_fixed_reg_d', fixedAction(1), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_reg_q', fixedAction(2), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_d', fixedAction(3), 'Workspace', M);
    in = in.setVariable('hpt_sac_fixed_energy_q', fixedAction(4), 'Workspace', M);
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
    row.fault_start_s = NaN;
    row.fault_clear_s = NaN;
    row.fault_duration_s = NaN;
    row.stop_time_s = NaN;
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
    row.cmd_action_max_abs = NaN;
    row.bridge_modulation_abs_max = NaN;
    row.cmd_m_reg_d_mean = NaN;
    row.cmd_m_reg_q_mean = NaN;
    row.cmd_m_energy_d_mean = NaN;
    row.cmd_m_energy_q_mean = NaN;
    row.meas_reg_d_mean = NaN;
    row.meas_reg_q_mean = NaN;
    row.meas_energy_d_mean = NaN;
    row.meas_energy_q_mean = NaN;
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
    row.gbt_category = "";
    row.gbt_voltage_margin_min = NaN;
    row.gbt_voltage_envelope_pass = false;
    row.gbt_recover_cover_s = NaN;
    row.gbt_recover_evaluated = false;
    row.gbt_recover_final_dev = NaN;
    row.gbt_recover_pass = false;
    row.gbt_vdc_pu_min = NaN;
    row.gbt_vdc_pu_max = NaN;
    row.gbt_vdc_survive_pass = false;
    row.gbt_action_limit_pass = false;
    row.grid_vpos_pu_min = NaN;
    row.grid_vpos_pu_mean = NaN;
    row.grid_id_mean_pu = NaN;
    row.grid_iq_mean_pu = NaN;
    row.grid_iq_ref_mean_pu = NaN;
    row.grid_iq_shortfall_max_pu = NaN;
    row.grid_iq_met_fraction = NaN;
    row.grid_iq_wrong_sign = false;
    row.grid_current_peak_pu = NaN;
    row.grid_idq_peak_pu = NaN;
    row.gbt_reactive_evaluated = false;
    row.gbt_reactive_response_ms = NaN;
    row.gbt_reactive_response_pass = false;
    row.gbt_grid_current_limit_pass = false;
    row.gbt_reactive_status = "";
    row.gbt_reactive_pass = false;
    row.gbt_limit_status = "";
    row.gbt_certifiable = false;
    row.voltage_survival_pass = false;
    row.voltage_survival_reason = "";
    row.full_frt_pass = false;
    row.full_frt_reason = "";
    row.within_window = false;
    row.window_reason = "";
    row.control_score = NaN;
end

function [ok, reason] = assess_steady(row, caseSpec)
    lvLo = caseSpec{6};
    lvHi = caseSpec{7};
    ubHi = caseSpec{8};
    vdcLo = caseSpec{9};
    vdcHi = caseSpec{10};
    reasons = strings(0, 1);
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

function [ok, reason] = assess_fault(row)
    reasons = strings(0, 1);
    if ~row.gbt_voltage_envelope_pass
        reasons(end+1) = "gbt_voltage_envelope"; %#ok<AGROW>
    end
    if ~row.gbt_recover_evaluated
        reasons(end+1) = "gbt_recover_not_evaluated"; %#ok<AGROW>
    elseif ~row.gbt_recover_pass
        reasons(end+1) = "gbt_recover"; %#ok<AGROW>
    end
    if ~row.gbt_vdc_survive_pass
        reasons(end+1) = "gbt_vdc_survive"; %#ok<AGROW>
    end
    if ~row.gbt_action_limit_pass
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    if ~row.gbt_grid_current_limit_pass
        reasons(end+1) = "grid_current_limit"; %#ok<AGROW>
    end
    if ~row.gbt_reactive_pass
        reasons(end+1) = string(row.gbt_reactive_status); %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function [ok, reason] = assess_fault_voltage_survival(row)
    reasons = strings(0, 1);
    % This staged gate measures whether a conventional controller can keep
    % the switch-level plant alive and voltage-bounded over the main fault and
    % recovery windows.  It intentionally uses window RMS values instead of
    % instantaneous min/max so PWM spikes do not hide the controller boundary.
    % Full FRT certification still uses the stricter envelope/current/reactive
    % checks in assess_fault().
    if ~(row.lv_mean >= 176.0 && row.lv_mean <= 238.0)
        reasons(end+1) = "lv_fault_mean_bounds"; %#ok<AGROW>
    end
    if ~(row.lv_recovery_mean >= 180.0 && row.lv_recovery_mean <= 235.0)
        reasons(end+1) = "lv_recovery_mean_bounds"; %#ok<AGROW>
    end
    if ~(row.vdc_min >= 650.0 && row.vdc_max <= 1000.0)
        reasons(end+1) = "dc_link_bounds"; %#ok<AGROW>
    end
    if ~(row.action_max_abs <= 0.9501)
        reasons(end+1) = "action_limit"; %#ok<AGROW>
    end
    ok = isempty(reasons);
    reason = strjoin(reasons, ";");
end

function score = score_row(row)
    score = 0.0;
    if row.scenario_type == "steady"
        score = score + abs(row.lv_mean - 207.0) / 5.0;
        score = score + row.lv_unbalance / 5.0;
        score = score + max(0.0, 760.0 - row.vdc_mean) / 10.0;
        score = score + max(0.0, row.vdc_mean - 930.0) / 10.0;
    else
        score = score + abs(row.lv_mean - 207.0) / 5.0;
        score = score + abs(row.lv_recovery_mean - 207.0) / 5.0;
        score = score + max(0.0, row.lv_peak - 235.0) / 3.0;
        score = score + max(0.0, 180.0 - row.lv_min) / 3.0;
        score = score + max(0.0, 650.0 - row.vdc_min) / 10.0;
        score = score + max(0.0, row.vdc_max - 1000.0) / 10.0;
        if ~isnan(row.grid_iq_shortfall_max_pu)
            score = score + 40.0 * max(0.0, row.grid_iq_shortfall_max_pu);
        end
        if ~isnan(row.grid_current_peak_pu)
            score = score + 50.0 * max(0.0, row.grid_current_peak_pu - 1.5);
        end
    end
    score = score + max(0.0, row.action_max_abs - 0.9501) * 100.0;
    if ~row.within_window
        score = score + 100.0;
    end
end

function row = add_gbt_fault_metrics(row, lvRmsInst, vdc, actRows, ...
    gridVRows, gridIRows, t, targetPhaseRms, faultPu, faultStart, ...
    faultClear, stopTime)

    solverTol = 1e-3;
    vdcBase = 800.0;
    lvPu = lvRmsInst ./ targetPhaseRms;
    tRel = t - faultStart;
    assessIdx = t >= faultStart & t <= stopTime;
    if faultPu < 1.0
        row.gbt_category = "LVRT";
        env = arrayfun(@(x) lvrt_lower_env(x, faultPu), tRel);
        margin = lvPu - env;
    else
        row.gbt_category = "HVRT";
        env = arrayfun(@hvrt_upper_env, tRel);
        margin = env - lvPu;
    end

    row.gbt_voltage_margin_min = min(margin(assessIdx));
    row.gbt_voltage_envelope_pass = row.gbt_voltage_margin_min >= -solverTol;
    row.gbt_recover_cover_s = stopTime - faultClear;
    row.gbt_recover_evaluated = row.gbt_recover_cover_s >= 0.10;
    postIdx = t > faultClear;
    if row.gbt_recover_evaluated && any(postIdx)
        finalStart = max(faultClear, stopTime - 0.12);
        finalIdx = t >= finalStart & t <= stopTime;
        row.gbt_recover_final_dev = max(abs(lvPu(finalIdx) - 1.0));
        row.gbt_recover_pass = row.gbt_recover_final_dev <= 0.07 && ...
            min(margin(postIdx)) >= -solverTol;
    else
        row.gbt_recover_final_dev = NaN;
        row.gbt_recover_pass = false;
    end

    row.gbt_vdc_pu_min = min(vdc) / vdcBase;
    row.gbt_vdc_pu_max = max(vdc) / vdcBase;
    row.gbt_vdc_survive_pass = row.gbt_vdc_pu_min >= 0.75 && ...
        row.gbt_vdc_pu_max <= 1.25;
    row.gbt_action_limit_pass = max(abs(actRows), [], 'all') <= 0.9501;
    row = add_grid_reactive_metrics(row, gridVRows, gridIRows, t, ...
        faultStart, faultClear);
    row.gbt_limit_status = sprintf("grid_current_peak_pu=%.3f;action_max=%.3f", ...
        row.grid_current_peak_pu, max(abs(actRows), [], 'all'));
    row.gbt_certifiable = row.gbt_reactive_evaluated && ...
        row.gbt_grid_current_limit_pass;
end

function row = add_grid_reactive_metrics(row, gridVRows, gridIRows, t, ...
    faultStart, faultClear)

    reactiveTol = 0.12;
    reactiveDelay = 0.06;
    reactiveDwell = 0.80;
    signEps = 1e-3;
    iqPeLimitPu = 0.30;
    currentLimitPu = 1.50;
    vMvLineRms = 10000.0;
    sBase = 400e3;
    vPhasePeak = sqrt(2) * vMvLineRms / sqrt(3);
    iBasePeak = sqrt(2) * sBase / (sqrt(3) * vMvLineRms);

    [vPosPu, idPu, iqPu] = grid_dq_from_voltage_angle(gridVRows, gridIRows, ...
        vPhasePeak, iBasePeak);
    refPu = arrayfun(@(v) grid_iq_reference(v, iqPeLimitPu), vPosPu);
    assessIdx = t >= faultStart + reactiveDelay & t <= faultClear;
    demandIdx = assessIdx & abs(refPu) > reactiveTol;

    row.grid_vpos_pu_min = min(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_vpos_pu_mean = mean(vPosPu(t >= faultStart & t <= faultClear));
    row.grid_id_mean_pu = mean(idPu(assessIdx));
    row.grid_iq_mean_pu = mean(iqPu(assessIdx));
    row.grid_iq_ref_mean_pu = mean(refPu(assessIdx));
    row.grid_current_peak_pu = max(max(abs(gridIRows))) / iBasePeak;
    row.grid_idq_peak_pu = max(sqrt(idPu.^2 + iqPu.^2));
    row.gbt_grid_current_limit_pass = row.grid_current_peak_pu <= currentLimitPu;

    wrongSign = (vPosPu < 0.9 & iqPu < -signEps) | ...
        (vPosPu > 1.1 & iqPu > signEps);
    row.grid_iq_wrong_sign = any(wrongSign(assessIdx));

    if ~any(assessIdx)
        row.gbt_reactive_status = "not_evaluated_no_fault_current_window";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
        return;
    end
    if ~any(demandIdx)
        row.grid_iq_shortfall_max_pu = 0.0;
        row.grid_iq_met_fraction = NaN;
        row.gbt_reactive_status = "not_evaluated_no_sustained_reactive_demand_after_delay";
        row.gbt_reactive_evaluated = false;
        row.gbt_reactive_pass = false;
        return;
    end

    shortfall = zeros(size(refPu));
    lvrtIdx = refPu > reactiveTol;
    hvrtIdx = refPu < -reactiveTol;
    shortfall(lvrtIdx) = max(0.0, (refPu(lvrtIdx) - reactiveTol) - iqPu(lvrtIdx));
    shortfall(hvrtIdx) = max(0.0, iqPu(hvrtIdx) - (refPu(hvrtIdx) + reactiveTol));
    metIdx = demandIdx & shortfall <= 1e-9;

    row.gbt_reactive_evaluated = true;
    row.grid_iq_shortfall_max_pu = max(shortfall(demandIdx));
    row.grid_iq_met_fraction = nnz(metIdx) / nnz(demandIdx);

    firstMet = find(metIdx, 1, 'first');
    if isempty(firstMet)
        row.gbt_reactive_response_ms = Inf;
        row.gbt_reactive_response_pass = false;
    else
        row.gbt_reactive_response_ms = 1000.0 * (t(firstMet) - faultStart);
        row.gbt_reactive_response_pass = row.gbt_reactive_response_ms <= ...
            1000.0 * reactiveDelay + 1e-6;
    end

    if row.grid_iq_wrong_sign
        row.gbt_reactive_status = "reactive_wrong_sign";
        row.gbt_reactive_pass = false;
    elseif row.grid_iq_met_fraction < reactiveDwell
        row.gbt_reactive_status = "reactive_shortfall";
        row.gbt_reactive_pass = false;
    elseif ~row.gbt_reactive_response_pass
        row.gbt_reactive_status = "reactive_response_slow";
        row.gbt_reactive_pass = false;
    else
        row.gbt_reactive_status = "pass";
        row.gbt_reactive_pass = true;
    end
end

function [vPosPu, idPu, iqPu] = grid_dq_from_voltage_angle(gridVRows, ...
    gridIRows, vPhasePeak, iBasePeak)

    va = gridVRows(1, :)';
    vb = gridVRows(2, :)';
    vc = gridVRows(3, :)';
    ia = gridIRows(1, :)';
    ib = gridIRows(2, :)';
    ic = gridIRows(3, :)';

    valpha = (2/3) * (va - 0.5*vb - 0.5*vc);
    vbeta = (sqrt(3)/3) * (vb - vc);
    ialpha = (2/3) * (ia - 0.5*ib - 0.5*ic);
    ibeta = (sqrt(3)/3) * (ib - ic);
    theta = atan2(vbeta, valpha);
    id = ialpha .* cos(theta) + ibeta .* sin(theta);
    iq = -ialpha .* sin(theta) + ibeta .* cos(theta);

    vPosPu = sqrt(valpha.^2 + vbeta.^2) ./ vPhasePeak;
    idPu = id ./ iBasePeak;
    % The V-I block current is oriented grid/source -> HPT.  FRT support is
    % reported in the opposite convention: positive iq means the HPT injects
    % voltage-supporting reactive current during LVRT.
    iqPu = -iq ./ iBasePeak;
end

function iqRef = grid_iq_reference(vPosPu, iqPeLimitPu)
    if vPosPu < 0.9
        iqRef = min(iqPeLimitPu, 1.5 * (0.9 - vPosPu));
    elseif vPosPu > 1.1
        iqRef = max(-iqPeLimitPu, -1.5 * (vPosPu - 1.1));
    else
        iqRef = 0.0;
    end
end

function y = lvrt_lower_env(tRel, residual)
    if tRel < 0
        y = 0.9;
    elseif tRel <= 0.625
        y = max(0.20, residual);
    elseif tRel <= 2.0
        y = max(0.20, residual) + ...
            (0.9 - max(0.20, residual)) * (tRel - 0.625) / (2.0 - 0.625);
    else
        y = 0.9;
    end
end

function y = hvrt_upper_env(tRel)
    if tRel < 0
        y = 1.1;
    elseif tRel <= 0.5
        y = 1.30;
    elseif tRel <= 1.0
        y = 1.20;
    else
        y = 1.10;
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
