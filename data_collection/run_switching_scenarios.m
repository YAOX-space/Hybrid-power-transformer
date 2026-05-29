%% run_switching_scenarios.m
% Runs short switching-level HPT scenarios through hpt_switching_model.slx.
% Output: data/raw_switching_hpt_v2/switching_<ID>_<label>_runNNN.mat
%
% Controller modes:
%   2 = Rule FRT (SPWM, voltage-sag based)
%   3 = DNN imitation FRT  (deprecated)
%   4 = dq double-loop PI
%   5 = PPO action  (reads RL_Energy_Bias / RL_Reg_Bias / RL_Current_Bias)
%   6 = RCN  (reads HPT_RCN_REF_TABLE or HPT_VDC_REF_DELTA/V2_REF_DELTA/ILIM_DELTA)
%   7 = FAHC (reads HPT_FAHC_STRATEGY_TABLE or HPT_FAHC_STRATEGY)

clear; clc;
addpath('../simulink');
run('parameters.m');

MODEL = 'hpt_switching_model';
OUT_DIR = getenv('HPT_SWITCHING_OUT_DIR');
if isempty(OUT_DIR)
    OUT_DIR = '../data/raw_switching_hpt_v2';
end
if ~exist(OUT_DIR, 'dir'), mkdir(OUT_DIR); end

SCENARIO_TABLE_PATH  = getenv('HPT_SCENARIO_TABLE');
ACTION_TABLE_PATH    = getenv('HPT_PPO_ACTION_TABLE');
RCN_REF_TABLE_PATH   = getenv('HPT_RCN_REF_TABLE');
FAHC_STRATEGY_TABLE_PATH = getenv('HPT_FAHC_STRATEGY_TABLE');

if ~exist(fullfile('../simulink', [MODEL '.slx']), 'file')
    run('../simulink/build_hpt_switching_model.m');
end
load_system(MODEL);

SCENARIOS = {
% ID   Label               T_sim
  0,   'normal',           0.05;
  3,   'igbt_oc_sh',       0.05;
  4,   'igbt_oc_se',       0.05;
  5,   'cap_fault',        0.05;
  6,   'sc_1ph',           0.05;
  7,   'sc_3ph',           0.05;
  8,   'cascade',          0.05;
};

n_runs = str2double(getenv('HPT_SWITCHING_RUNS'));
if isnan(n_runs) || n_runs < 1
    n_runs = 1;
end
controller_mode = str2double(getenv('HPT_CONTROLLER_MODE'));
if isnan(controller_mode)
    controller_mode = 2;
end
rl_action = parse_rl_action(getenv('HPT_RL_ACTION'));

% Mode 6 single-scenario env vars (used when no RCN ref table is given)
env_vdc_delta  = str2double(getenv('HPT_VDC_REF_DELTA'));
env_v2_delta   = str2double(getenv('HPT_V2_REF_DELTA'));
env_ilim_delta = str2double(getenv('HPT_ILIM_DELTA'));
if isnan(env_vdc_delta),  env_vdc_delta  = 0; end
if isnan(env_v2_delta),   env_v2_delta   = 0; end
if isnan(env_ilim_delta), env_ilim_delta = 0; end

% Mode 7 single-scenario env var (used when no FAHC strategy table given)
env_fahc_strategy = str2double(getenv('HPT_FAHC_STRATEGY'));
if isnan(env_fahc_strategy), env_fahc_strategy = 0; end

fprintf('Running %d switching run(s) for %d scenarios (ControllerMode=%g).\n', ...
    n_runs, size(SCENARIOS,1), controller_mode);

if ~isempty(SCENARIO_TABLE_PATH)
    scenario_table = readtable(SCENARIO_TABLE_PATH, 'TextType', 'string');
    row_filter = str2double(getenv('HPT_SCENARIO_ROW'));
    if ~isnan(row_filter) && row_filter >= 1 && row_filter <= height(scenario_table)
        scenario_table = scenario_table(row_filter, :);
    end
    fprintf('Using fixed scenario table: %s (%d rows).\n', ...
        SCENARIO_TABLE_PATH, height(scenario_table));

    %% Mode 5 — PPO batch action table
    if ~isempty(ACTION_TABLE_PATH)
        action_table = readtable(ACTION_TABLE_PATH, 'TextType', 'string');
        fprintf('Using PPO action table: %s (%d rows).\n', ...
            ACTION_TABLE_PATH, height(action_table));
        for action_idx = 1:height(action_table)
            arow = action_table(action_idx, :);
            scenario_row = get_table_number(arow, 'scenario_row', 1);
            scenario_row = max(1, min(height(scenario_table), round(scenario_row)));
            row = scenario_table(scenario_row, :);
            scenario_id = get_table_number(arow, 'rollout_id', action_idx);
            run_idx = get_table_number(row, 'run_idx', scenario_row);
            action = [
                get_table_number(arow, 'energy_bias', 0), ...
                get_table_number(arow, 'reg_bias', 0), ...
                get_table_number(arow, 'current_bias', 0)];
            run_scenario_table_row(MODEL, OUT_DIR, scenario_id, row, run_idx, ...
                action, controller_mode, f_sample, S_rated, ...
                0, 0, 0, 0);
        end

    %% Mode 6 — RCN batch ref table
    elseif ~isempty(RCN_REF_TABLE_PATH)
        rcn_table = readtable(RCN_REF_TABLE_PATH, 'TextType', 'string');
        fprintf('Using RCN ref table: %s (%d rows).\n', ...
            RCN_REF_TABLE_PATH, height(rcn_table));
        for ridx = 1:height(rcn_table)
            rrow = rcn_table(ridx, :);
            scenario_row = get_table_number(rrow, 'scenario_row', ridx);
            scenario_row = max(1, min(height(scenario_table), round(scenario_row)));
            row = scenario_table(scenario_row, :);
            scenario_id = get_table_number(rrow, 'rollout_id', ridx);
            run_idx = get_table_number(row, 'run_idx', scenario_row);
            dvdc  = get_table_number(rrow, 'delta_vdc_ref', 0);
            dv2   = get_table_number(rrow, 'delta_v2_ref',  0);
            dilim = get_table_number(rrow, 'delta_ilim',    0);
            run_scenario_table_row(MODEL, OUT_DIR, scenario_id, row, run_idx, ...
                rl_action, controller_mode, f_sample, S_rated, ...
                dvdc, dv2, dilim, 0);
        end

    %% Mode 7 — FAHC batch strategy table
    elseif ~isempty(FAHC_STRATEGY_TABLE_PATH)
        fahc_table = readtable(FAHC_STRATEGY_TABLE_PATH, 'TextType', 'string');
        fprintf('Using FAHC strategy table: %s (%d rows).\n', ...
            FAHC_STRATEGY_TABLE_PATH, height(fahc_table));
        for fidx = 1:height(fahc_table)
            frow = fahc_table(fidx, :);
            scenario_row = get_table_number(frow, 'scenario_row', fidx);
            scenario_row = max(1, min(height(scenario_table), round(scenario_row)));
            row = scenario_table(scenario_row, :);
            scenario_id = get_table_number(frow, 'rollout_id', fidx);
            run_idx = get_table_number(row, 'run_idx', scenario_row);
            strategy_id = get_table_number(frow, 'strategy_id', 0);
            run_scenario_table_row(MODEL, OUT_DIR, scenario_id, row, run_idx, ...
                rl_action, controller_mode, f_sample, S_rated, ...
                0, 0, 0, strategy_id);
        end

    %% No batch table — iterate all rows with single env params
    else
        for row_idx = 1:height(scenario_table)
            row = scenario_table(row_idx, :);
            scenario_id = get_table_number(row, 'scenario_id', row_idx);
            run_idx = get_table_number(row, 'run_idx', row_idx);
            run_scenario_table_row(MODEL, OUT_DIR, scenario_id, row, run_idx, ...
                rl_action, controller_mode, f_sample, S_rated, ...
                env_vdc_delta, env_v2_delta, env_ilim_delta, env_fahc_strategy);
        end
    end

else
    %% No scenario table — random legacy mode
    for s = 1:size(SCENARIOS, 1)
        sc_id = SCENARIOS{s, 1};
        sc_label = SCENARIOS{s, 2};
        T_sim = SCENARIOS{s, 3};

        for run_idx = 1:n_runs
            scenario_id = (s - 1) * n_runs + run_idx;
            P_load = S_rated * (0.7 + 0.2*rand());
            Q_load = P_load * tan(acos(0.85 + 0.1*rand()));
            t_fault = 0.012 + 0.018*rand();
            fault_variant = choose_fault_variant(sc_id);
            fault_mag = choose_fault_magnitude(sc_id);
            fault_resistance = default_fault_resistance(sc_id);
            ground_resistance = fault_resistance;

            run_one_case(MODEL, OUT_DIR, scenario_id, sc_id, sc_label, run_idx, ...
                T_sim, P_load, Q_load, t_fault, fault_variant, fault_mag, ...
                fault_resistance, ground_resistance, controller_mode, rl_action, f_sample, ...
                env_vdc_delta, env_v2_delta, env_ilim_delta, env_fahc_strategy);
        end
    end
end

close_system(MODEL, 0);
fprintf('Done. Files written to %s\n', OUT_DIR);

% ── Internal helpers ───────────────────────────────────────────────────────────

function run_scenario_table_row(model, out_dir, scenario_id, row, run_idx, ...
        rl_action, controller_mode, f_sample, S_rated, ...
        vdc_ref_delta, v2_ref_delta, ilim_delta, fahc_strategy)
    sc_id = get_table_number(row, 'sc_id', 0);
    sc_label = char(get_table_string(row, 'sc_label', scenario_id_to_label(sc_id)));
    T_sim = get_table_number(row, 'T_sim', 0.05);
    P_load = get_table_number(row, 'P_load', S_rated * 0.8);
    Q_load = get_table_number(row, 'Q_load', S_rated * 0.2);
    t_fault = get_table_number(row, 't_fault', 99);
    fault_variant = get_table_number(row, 'fault_variant', 1);
    fault_mag = get_table_number(row, 'fault_mag', 1);
    fault_resistance = get_table_number(row, 'fault_resistance', default_fault_resistance(sc_id));
    ground_resistance = get_table_number(row, 'ground_resistance', fault_resistance);

    run_one_case(model, out_dir, scenario_id, sc_id, sc_label, run_idx, ...
        T_sim, P_load, Q_load, t_fault, fault_variant, fault_mag, ...
        fault_resistance, ground_resistance, controller_mode, rl_action, f_sample, ...
        vdc_ref_delta, v2_ref_delta, ilim_delta, fahc_strategy);
end

function run_one_case(model, out_dir, scenario_id, sc_id, sc_label, run_idx, ...
        T_sim, P_load, Q_load, t_fault, fault_variant, fault_mag, ...
        fault_resistance, ground_resistance, controller_mode, rl_action, f_sample, ...
        vdc_ref_delta, v2_ref_delta, ilim_delta, fahc_strategy)
    configure_switching_case(model, sc_id, t_fault, P_load, Q_load, ...
        fault_variant, fault_mag, fault_resistance, ground_resistance, ...
        controller_mode, rl_action, ...
        vdc_ref_delta, v2_ref_delta, ilim_delta, fahc_strategy);
    set_param(model, 'StopTime', num2str(T_sim));

    fprintf('  sid=%04d sc=%d %-12s run=%03d mode=%d ... ', ...
        scenario_id, sc_id, sc_label, run_idx, controller_mode);
    out = sim(model, 'CaptureErrors', 'on');
    if ~isempty(out.ErrorMessage)
        warning('failed: %s', out.ErrorMessage);
        return;
    end
    fprintf('ok\n');

    t = out.tout;
    t_uniform = (0:1/f_sample:T_sim)';
    N = numel(t_uniform);

    V1_abc = get_logged_signal(out, 'V1_abc', t, t_uniform);
    I1_abc = get_logged_signal(out, 'I1_abc', t, t_uniform);
    V2_abc = get_logged_signal(out, 'V2_abc', t, t_uniform);
    I2_abc = get_logged_signal(out, 'I2_abc', t, t_uniform);
    V_dc   = get_logged_signal(out, 'V_dc',   t, t_uniform);
    Ish_dq = get_logged_signal(out, 'Ish_dq', t, t_uniform);
    Ise_dq = get_logged_signal(out, 'Ise_dq', t, t_uniform);
    P1     = get_logged_signal(out, 'P1',     t, t_uniform);
    Q1     = get_logged_signal(out, 'Q1',     t, t_uniform);
    P2     = get_logged_signal(out, 'P2',     t, t_uniform);
    Q2     = get_logged_signal(out, 'Q2',     t, t_uniform);
    mode   = get_logged_signal(out, 'mode',   t, t_uniform);

    fault_labels = zeros(N, 1);
    fault_class = scenario_to_fault_class(sc_id);
    onset = round(t_fault * f_sample) + 1;
    if fault_class > 0 && onset <= N
        fault_labels(onset:end) = fault_class;
    end

    out_file = fullfile(out_dir, ...
        sprintf('scenario_%04d_switching_%d_%s_run%03d.mat', ...
        scenario_id, sc_id, sc_label, run_idx));
    save(out_file, ...
        'scenario_id', 't_uniform', 'V1_abc', 'I1_abc', 'V2_abc', 'I2_abc', ...
        'V_dc', 'Ish_dq', 'Ise_dq', 'P1', 'Q1', 'P2', 'Q2', ...
        'mode', 'fault_labels', 'sc_id', 'sc_label', ...
        'P_load', 'Q_load', 't_fault', 'fault_variant', 'fault_mag', ...
        'fault_resistance', 'ground_resistance', 'controller_mode', 'rl_action', ...
        'vdc_ref_delta', 'v2_ref_delta', 'ilim_delta', 'fahc_strategy', '-v7.3');
end

function configure_switching_case(model, sc_id, t_fault, P_load, Q_load, ...
        fault_variant, fault_mag, fault_resistance, ground_resistance, ...
        controller_mode, rl_action, ...
        vdc_ref_delta, v2_ref_delta, ilim_delta, fahc_strategy)
    set_param([model '/Sc_id'],          'Value', num2str(sc_id));
    set_param([model '/T_fault'],        'Value', num2str(t_fault));
    set_param([model '/FaultVariant'],   'Value', num2str(fault_variant));
    set_param([model '/FaultMag'],       'Value', num2str(fault_mag));
    set_param([model '/ControllerMode'], 'Value', num2str(controller_mode));

    % PPO action inputs (Mode 5)
    if exist_block(model, 'RL_Energy_Bias')
        set_param([model '/RL_Energy_Bias'],   'Value', num2str(rl_action(1)));
        set_param([model '/RL_Reg_Bias'],      'Value', num2str(rl_action(2)));
        set_param([model '/RL_Current_Bias'],  'Value', num2str(rl_action(3)));
    end

    % RCN reference delta inputs (Mode 6)
    if exist_block(model, 'VDC_Ref_Delta')
        set_param([model '/VDC_Ref_Delta'], 'Value', num2str(vdc_ref_delta));
        set_param([model '/V2_Ref_Delta'],  'Value', num2str(v2_ref_delta));
        set_param([model '/ILim_Delta'],    'Value', num2str(ilim_delta));
    end

    % FAHC strategy selector input (Mode 7)
    if exist_block(model, 'FAHC_Strategy')
        set_param([model '/FAHC_Strategy'], 'Value', num2str(fahc_strategy));
    end

    set_param([model '/LV_Load'], ...
        'ActivePower', num2str(P_load), ...
        'InductivePower', num2str(Q_load), ...
        'CapacitivePower', '0');
    set_param([model '/DC_Link_Cap_Breaker'], ...
        'InitialState', '1', 'SwitchingTimes', '[99]');
    set_param([model '/DC_Link_Capacitor'], ...
        'Capacitance', '2200e-6', ...
        'InitialVoltage', '800');
    set_param([model '/LV_AC_Fault'], ...
        'FaultA', 'off', 'FaultB', 'off', 'FaultC', 'off', 'GroundFault', 'off', ...
        'SwitchTimes', '[99 100]');

    if sc_id == 5
        set_param([model '/DC_Link_Capacitor'], ...
            'Capacitance', '680e-6', ...
            'InitialVoltage', '800');
    elseif sc_id == 6
        set_param([model '/LV_AC_Fault'], ...
            'FaultA', 'on', 'FaultB', 'off', 'FaultC', 'off', 'GroundFault', 'on', ...
            'FaultResistance', num2str(fault_resistance), ...
            'GroundResistance', num2str(ground_resistance), ...
            'SwitchTimes', sprintf('[%.6f %.6f]', t_fault, t_fault + 0.015));
    elseif sc_id == 7
        set_param([model '/LV_AC_Fault'], ...
            'FaultA', 'on', 'FaultB', 'on', 'FaultC', 'on', 'GroundFault', 'on', ...
            'FaultResistance', num2str(fault_resistance), ...
            'GroundResistance', num2str(ground_resistance), ...
            'SwitchTimes', sprintf('[%.6f %.6f]', t_fault, t_fault + 0.015));
    end
end

function action = parse_rl_action(raw)
    action = [0 0 0];
    if isempty(raw)
        return;
    end
    parts = split(string(raw), ',');
    for k = 1:min(3, numel(parts))
        v = str2double(parts(k));
        if ~isnan(v)
            action(k) = min(1, max(-1, v));
        end
    end
end

function tf = exist_block(model, block_name)
    tf = ~isempty(find_system(model, 'SearchDepth', 1, 'Name', block_name));
end

function r = default_fault_resistance(sc_id)
    if sc_id == 6
        r = 0.35;
    elseif sc_id == 7
        r = 0.28;
    else
        r = 0.01;
    end
end

function label = scenario_id_to_label(sc_id)
    switch sc_id
        case 0,  label = "normal";
        case 3,  label = "igbt_oc_sh";
        case 4,  label = "igbt_oc_se";
        case 5,  label = "cap_fault";
        case 6,  label = "sc_1ph";
        case 7,  label = "sc_3ph";
        case 8,  label = "cascade";
        otherwise, label = "unknown";
    end
end

function value = get_table_number(row, name, default)
    if any(strcmp(row.Properties.VariableNames, name))
        raw = row.(name);
        value = raw(1);
        if iscell(value), value = value{1}; end
        if isstring(value), value = str2double(value); end
        if isnan(value), value = default; end
    else
        value = default;
    end
end

function value = get_table_string(row, name, default)
    if any(strcmp(row.Properties.VariableNames, name))
        raw = row.(name);
        value = string(raw(1));
    else
        value = string(default);
    end
end

function v = choose_fault_variant(sc_id)
    if sc_id == 3 || sc_id == 8
        v = randi(6);
    elseif sc_id == 4
        v = randi(4);
    elseif sc_id == 6
        v = randi(3);
    else
        v = 1;
    end
end

function m = choose_fault_magnitude(sc_id)
    if sc_id == 3 || sc_id == 4
        m = 0.75 + 0.25*rand();
    elseif sc_id == 8
        m = 0.90 + 0.10*rand();
    elseif sc_id == 5
        m = 1.0;
    else
        m = 0.8 + 0.2*rand();
    end
end

function cls = scenario_to_fault_class(sc_id)
    switch sc_id
        case 3,  cls = 1;
        case 4,  cls = 2;
        case 5,  cls = 3;
        case 6,  cls = 4;
        case 7,  cls = 5;
        case 8,  cls = 6;
        otherwise, cls = 0;
    end
end

function out = get_logged_signal(sim_out, name, t_orig, t_new)
    raw = squeeze(sim_out.get(name));
    if isvector(raw)
        raw = raw(:);
    elseif size(raw, 1) <= 4 && size(raw, 2) > size(raw, 1)
        raw = raw.';
    elseif size(raw, 2) == numel(t_orig)
        raw = raw.';
    end
    n = size(raw, 1);
    if n == numel(t_orig)
        t_sig = t_orig;
    else
        t_sig = linspace(t_orig(1), t_orig(end), n).';
    end
    out = resample_signal(raw, t_sig, t_new);
end

function out = resample_signal(sig, t_orig, t_new)
    if isvector(sig)
        out = interp1(t_orig, sig(:), t_new, 'linear', 'extrap');
        return;
    end
    out = zeros(numel(t_new), size(sig, 2));
    for col = 1:size(sig, 2)
        out(:, col) = interp1(t_orig, sig(:, col), t_new, 'linear', 'extrap');
    end
end
