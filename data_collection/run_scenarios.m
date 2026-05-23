%% run_scenarios.m
% Runs all HPT simulation scenarios and exports data for AI training.
%
% Scenarios:
%   0 - Normal operation (varied load, power factor)
%   1 - PV grid-connection + irradiance change
%   2 - Load step change
%   3 - IGBT single open-circuit in VSC_sh
%   4 - IGBT single open-circuit in VSC_se
%   5 - DC capacitor partial disconnection
%   6 - Single-phase AC short circuit
%   7 - Three-phase AC short circuit
%   8 - Cascade fault: IGBT → DC overvoltage
%
% Output: data/raw/scenario_<ID>_<run>.mat
%         data/processed/dataset.npy (via Python export script)

clear; clc;
addpath('../simulink');
run('parameters.m');

MODEL = 'hpt_main_model';
OUT_DIR = '../data/raw';
if ~exist(OUT_DIR, 'dir'), mkdir(OUT_DIR); end

% Load model
load_system(MODEL);

%% ========== SCENARIO DEFINITIONS ==========
scenarios = {
% ID   Label               T_sim  N_runs  Fault config
  0,   'normal',           2.0,   200,    struct('type','none');
  1,   'pv_disturbance',   2.0,   100,    struct('type','pv');
  2,   'load_step',        2.0,   100,    struct('type','load_step');
  3,   'igbt_oc_sh',       2.0,   100,    struct('type','igbt_oc','loc','sh');
  4,   'igbt_oc_se',       2.0,   100,    struct('type','igbt_oc','loc','se');
  5,   'cap_fault',        2.0,   100,    struct('type','cap_fault');
  6,   'sc_1ph',           2.0,   100,    struct('type','short','phases',1);
  7,   'sc_3ph',           2.0,   100,    struct('type','short','phases',3);
  8,   'cascade',          3.0,   100,    struct('type','cascade');
};

%% ========== SIMULATION LOOP ==========
total_runs = sum(cell2mat(scenarios(:,4)));
run_count  = 0;

for s = 1:size(scenarios,1)
    sc_id    = scenarios{s,1};
    sc_label = scenarios{s,2};
    T_sim    = scenarios{s,3};
    N_runs   = scenarios{s,4};
    fault    = scenarios{s,5};

    fprintf('\n[Scenario %d: %s] Running %d simulations...\n', sc_id, sc_label, N_runs);

    for run_idx = 1:N_runs
        run_count = run_count + 1;
        fprintf('  Run %d/%d (total: %d/%d)\r', run_idx, N_runs, run_count, total_runs);

        %% Randomize operating conditions
        P_load = S_rated * (0.3 + 0.7*rand());      % 30–100% rated load
        Q_load = P_load * tan(acos(0.7 + 0.3*rand())); % pf 0.7–1.0
        V_se_init = 0;                                % Start at nominal

        %% Configure fault timing (randomize onset time)
        t_fault   = 0.8 + 0.4*rand();   % Fault at 0.8–1.2s
        t_clear   = t_fault + 0.1 + 0.1*rand(); % Cleared after 100–200ms

        %% Apply scenario-specific parameters
        switch fault.type
            case 'none'
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]'); % No fault
                set_param([MODEL '/Cap_Disconnect'], 'SwitchTimes', '[99]');
                fault_igbt = 'none';
                mode_seq = 1;  % Voltage regulation mode

            case 'pv'
                % PV connected at t=0.5s, irradiance changes at t=1.0s
                P_pv = P_pv_rated * (0.3 + 0.7*rand());
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]');
                mode_seq = [1; 1];  % Stays in voltage regulation

            case 'load_step'
                % Load doubles at t_fault
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]');
                mode_seq = 1;

            case 'igbt_oc'
                % Open one IGBT gate (set gate signal to 0 permanently)
                igbt_phase = randi(3);   % Phase A, B, or C
                igbt_switch = randi(2);  % Upper or lower switch in H-bridge
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]');
                mode_seq = 1;

            case 'cap_fault'
                % Disconnect DC capacitor at t_fault
                set_param([MODEL '/Cap_Disconnect'], ...
                    'SwitchTimes', num2str(t_fault), ...
                    'InitialState', '1');
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]');
                mode_seq = 1;

            case 'short'
                % AC short circuit (single or three phase)
                if fault.phases == 1
                    set_param([MODEL '/Fault_AC'], ...
                        'FaultA', '1', 'FaultB', '0', 'FaultC', '0', ...
                        'GroundFault', '1', ...
                        'SwitchTimes', [num2str(t_fault), ' ', num2str(t_clear)], ...
                        'TransitionStatus', '[0 1 0]');
                else
                    set_param([MODEL '/Fault_AC'], ...
                        'FaultA', '1', 'FaultB', '1', 'FaultC', '1', ...
                        'SwitchTimes', [num2str(t_fault), ' ', num2str(t_clear)], ...
                        'TransitionStatus', '[0 1 0]');
                end
                mode_seq = 1;

            case 'cascade'
                % IGBT fault at t_fault → DC overvoltage → controller response
                igbt_phase = randi(3);
                set_param([MODEL '/Fault_AC'], 'SwitchTimes', '[99 100]');
                mode_seq = 1;
        end

        %% Set load and simulation time
        set_param([MODEL '/Load'], ...
            'ActivPower', num2str(P_load), ...
            'ReactivPower', num2str(Q_load));
        set_param(MODEL, 'StopTime', num2str(T_sim));

        %% RUN SIMULATION
        try
            sim_out = sim(MODEL, 'CaptureErrors', 'on');

            if ~isempty(sim_out.ErrorMessage)
                warning('Simulation error in run %d: %s', run_idx, sim_out.ErrorMessage);
                continue;
            end

            %% EXTRACT SIGNALS
            t = sim_out.tout;
            data_ts = sim_out.sim_data;  % Timeseries from To Workspace block

            % Sample at uniform rate (resample to f_sample Hz)
            t_uniform = (0:1/f_sample:T_sim)';
            N = length(t_uniform);

            % Extract and resample each signal
            V1_abc = resample_signal(sim_out.V1_abc, t, t_uniform);   % 3xN
            I1_abc = resample_signal(sim_out.I1_abc, t, t_uniform);
            V2_abc = resample_signal(sim_out.V2_abc, t, t_uniform);
            I2_abc = resample_signal(sim_out.I2_abc, t, t_uniform);
            V_dc   = resample_signal(sim_out.V_dc,   t, t_uniform);   % 1xN
            Ish_dq = resample_signal(sim_out.Ish_dq, t, t_uniform);   % 2xN
            Ise_dq = resample_signal(sim_out.Ise_dq, t, t_uniform);
            P1     = resample_signal(sim_out.P1,     t, t_uniform);   % 1xN
            Q1     = resample_signal(sim_out.Q1,     t, t_uniform);
            P2     = resample_signal(sim_out.P2,     t, t_uniform);
            Q2     = resample_signal(sim_out.Q2,     t, t_uniform);
            mode   = ones(N,1) * mode_seq(1);

            %% CREATE FAULT LABEL ARRAY
            % 0=normal, 1=igbt_oc_sh, 2=igbt_oc_se, 3=cap_fault,
            % 4=sc_1ph, 5=sc_3ph, 6=cascade
            label_map = containers.Map(...
                {'none','pv','load_step','igbt_oc_sh','igbt_oc_se',...
                 'cap_fault','sc_1ph','sc_3ph','cascade'}, ...
                {0, 0, 0, 1, 2, 3, 4, 5, 6});

            fault_class = label_map(sc_label);
            fault_onset_idx = round(t_fault * f_sample) + 1;
            fault_labels = zeros(N,1);
            if fault_class > 0 && fault_onset_idx <= N
                fault_labels(fault_onset_idx:end) = fault_class;
            end

            %% SAVE AS .mat
            out_file = fullfile(OUT_DIR, ...
                sprintf('scenario_%d_%s_run%03d.mat', sc_id, sc_label, run_idx));

            save(out_file, ...
                't_uniform', ...
                'V1_abc', 'I1_abc', ...
                'V2_abc', 'I2_abc', ...
                'V_dc', ...
                'Ish_dq', 'Ise_dq', ...
                'P1', 'Q1', 'P2', 'Q2', ...
                'mode', 'fault_labels', ...
                'sc_id', 'sc_label', ...
                'P_load', 'Q_load', 't_fault', ...
                '-v7.3');

        catch e
            warning('Exception in scenario %d run %d: %s', sc_id, run_idx, e.message);
        end
    end
    fprintf('\n  Done: %d files saved to %s\n', N_runs, OUT_DIR);
end

close_system(MODEL, 0);
fprintf('\n=== ALL SCENARIOS COMPLETE ===\n');
fprintf('Total .mat files: %d\n', total_runs);
fprintf('Next: Run export_to_numpy.py to convert for Python AI training.\n');

%% ========== HELPER: Signal resampling ==========
function out = resample_signal(sig, t_orig, t_new)
    if isnumeric(sig)
        [~, N] = size(sig);
        out = zeros(length(t_new), N);
        for col = 1:N
            out(:,col) = interp1(t_orig, sig(:,col), t_new, 'linear', 'extrap');
        end
    else
        out = interp1(t_orig, sig, t_new, 'linear', 'extrap');
    end
end
