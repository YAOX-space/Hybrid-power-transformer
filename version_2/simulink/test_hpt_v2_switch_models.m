% test_hpt_v2_switch_models
% Runs the final successful pure switch-level HPT regressions.

rootDir = fileparts(mfilename('fullpath'));

oldDir = pwd;
cleanup = onCleanup(@() cd(oldDir));

cd(rootDir);
run('test_hpt_v2_sac_interface.m');

cd(fullfile(rootDir, 'topoloty1'));
run('test_hpt_v2_1to1_pure_switchlevel.m');

rootDir = fileparts(mfilename('fullpath'));
cd(fullfile(rootDir, 'topology2'));
run('test_hpt_v2_topology2_pure_switchlevel.m');

fprintf('Both final pure switch-level HPT models passed.\\n');
