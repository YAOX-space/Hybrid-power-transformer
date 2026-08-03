cd('E:/research_space/Hybrid-power-transformer/lab/simulink');

logdir = fullfile('..', 'results', 'background_runs');
if ~exist(logdir, 'dir'), mkdir(logdir); end

run_tag = datestr(now, 'yyyymmdd_HHMMSS');
diary(fullfile(logdir, ['simulink_mi343_expanded2040_' run_tag '.log']));
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>

fprintf('=== run_mi343_expanded2040_20260709 %s ===\n', run_tag);

A = readtable('../frt_scenarios_expanded.csv', 'TextType', 'string');
sids = unique(A.scenario_id(:).', 'stable');
chunk_size = 120;

for k = 1:chunk_size:numel(sids)
    chunk = sids(k:min(k + chunk_size - 1, numel(sids)));
    chunk_tag = sprintf('mi343_expanded2040_%s_%04d_%04d', run_tag, k, k + numel(chunk) - 1);
    fprintf('=== chunk %d:%d (%d scenarios) %s ===\n', k, k + numel(chunk) - 1, numel(chunk), datestr(now, 'yyyy-mm-dd HH:MM:SS'));
    frt_v2_selected_expanded_switching(chunk, 343, chunk_tag);
end

fprintf('=== done %s ===\n', datestr(now, 'yyyymmdd_HHMMSS'));
