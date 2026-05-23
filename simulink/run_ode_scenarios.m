% run_ode_scenarios.m
% Generates HPT simulation data using dq-axis average model (no toolbox needed).
% Produces .mat files in the same format as run_scenarios.m / generate_synthetic_mat.py.
% Output: data/raw/ode_*.mat  (keeps separate from synthetic data)

addpath(fileparts(mfilename('fullpath')));   % ensure hpt_ode_model is on path

RAW_DIR = fullfile(fileparts(fileparts(mfilename('fullpath'))), 'data', 'raw_ode');
if ~exist(RAW_DIR, 'dir'), mkdir(RAW_DIR); end

SCENARIO_SPECS = {
% {sc_id, sc_label,    t_end, n_runs}
  {0,  'normal',       2.0,   100}, ...
  {3,  'igbt_oc_sh',   2.0,   60}, ...
  {4,  'igbt_oc_se',   2.0,   60}, ...
  {5,  'cap_fault',    2.0,   60}, ...
  {6,  'sc_1ph',       2.0,   60}, ...
  {7,  'sc_3ph',       2.0,   60}, ...
  {8,  'cascade',      2.5,   60}, ...
};

total = 0;
for i = 1:length(SCENARIO_SPECS), total = total + SCENARIO_SPECS{i}{4}; end
count = 0;
t_start_wall = tic;

fprintf('Generating %d ODE scenarios → %s\n\n', total, RAW_DIR);

for si = 1:length(SCENARIO_SPECS)
    sc_id    = SCENARIO_SPECS{si}{1};
    sc_label = SCENARIO_SPECS{si}{2};
    t_end    = SCENARIO_SPECS{si}{3};
    n_runs   = SCENARIO_SPECS{si}{4};

    for run = 1:n_runs
        count = count + 1;
        seed = sc_id * 1000 + run;
        t_fault = 0.8 + 0.4 * rand();

        try
            [~, ~, Y] = hpt_ode_model(sc_id, t_end, t_fault, seed);
        catch ME
            fprintf('  [SKIP] sc=%d run=%d: %s\n', sc_id, run, ME.message);
            continue
        end

        fname = fullfile(RAW_DIR, ...
            sprintf('ode_scenario_%d_%s_run%03d.mat', sc_id, sc_label, run));

        save(fname, '-struct', 'Y');
        % append scalar metadata
        sc_id_mat   = sc_id;
        sc_label_mat = sc_label;
        P_load_mat  = max(Y.P1);
        Q_load_mat  = max(Y.Q1);
        t_fault_mat = t_fault;
        save(fname, 'sc_id_mat', 'sc_label_mat', ...
             'P_load_mat', 'Q_load_mat', 't_fault_mat', '-append');

        if mod(run, 20) == 0 || run == n_runs
            elapsed = toc(t_start_wall);
            eta = elapsed / count * (total - count);
            fprintf('  [%3d/%3d] sc=%d %-12s  run %3d/%3d   ETA %.0fs\n', ...
                count, total, sc_id, sc_label, run, n_runs, eta);
        end
    end
end

fprintf('\nDone. %d files written to %s\n', count, RAW_DIR);
fprintf('Total wall time: %.1f s\n', toc(t_start_wall));
