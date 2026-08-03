cd('E:/research_space/Hybrid-power-transformer/lab/simulink');
logdir = fullfile('..', 'results', 'background_runs');
if ~exist(logdir, 'dir'), mkdir(logdir); end
run_tag = datestr(now, 'yyyymmdd_HHMMSS');
diary(fullfile(logdir, ['simulink_mi324_full320_' run_tag '.log']));
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>
fprintf('=== run_mi324_full320_20260709 %s ===\n', run_tag);
frt_v2_full320_switching(324, 1, 320);
fprintf('=== done %s ===\n', datestr(now, 'yyyymmdd_HHMMSS'));
