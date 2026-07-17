% sweep_hpt_v2_conventional_boundary
% Find pass/fail boundaries for the tuned conventional dq controller.
%
% The matrix intentionally mixes mild, near-boundary, and severe FRT cases so
% the traditional controller should pass some rows and fail others.  SAC
% training/evaluation should later beat this measured boundary, not an
% artificially weak or impossible baseline.

clearvars;
close all;

rootDir = fileparts(mfilename('fullpath'));
oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));
cd(rootDir);

durations = [0.040, 0.080, 0.120, 0.200];
lvrtDepths = [0.995, 0.990, 0.980, 0.950, 0.920, 0.900, 0.880, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600, 0.500, 0.350, 0.200];
hvrtDepths = [1.005, 1.010, 1.020, 1.050, 1.080, 1.100, 1.120, 1.150, 1.180, 1.200, 1.250, 1.300];

faults = {};
for d = 1:numel(durations)
    dur = durations(d);
    durMs = round(1000 * dur);
    for k = 1:numel(lvrtDepths)
        pu = lvrtDepths(k);
        name = sprintf('lvrt_%03dms_%0.3fpu', durMs, pu);
        name = strrep(name, '.', 'p');
        faults(end+1, :) = {name, pu, dur}; %#ok<SAGROW>
    end
    for k = 1:numel(hvrtDepths)
        pu = hvrtDepths(k);
        name = sprintf('hvrt_%03dms_%0.3fpu', durMs, pu);
        name = strrep(name, '.', 'p');
        faults(end+1, :) = {name, pu, dur}; %#ok<SAGROW>
    end
end

hpt_compare_topology = "all";
hpt_compare_scenario_type = "fault";
hpt_compare_case_name = "all";
hpt_compare_modes = "conventional_dq";
hpt_compare_energy_enable = 1.0;
hpt_compare_conventional_profile = "tuned_v1";
hpt_compare_conventional_params = struct();
hpt_compare_faults = faults;
hpt_compare_fault_start = 0.035;
hpt_compare_fault_stop_margin = 0.125;
hpt_compare_run_label = "conventional_boundary";

eval_hpt_v2_control_comparison;
