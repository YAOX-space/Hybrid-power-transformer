function frt_v2_overnight_auto_1441()
% frt_v2_overnight_auto_1441
% Overnight supervisor for the remaining selected-HVRT bottleneck.
%
% It keeps the search narrow:
%   1. sweep new weak-HVRT HLC probes mi261..mi292 on scenario 1441;
%   2. automatically spotcheck any no-fail/recover-pass candidate on hard24+HVRT;
%   3. run a fixed-control mode-10 feasibility angle sweep for physics guidance.

here = fileparts(mfilename('fullpath'));
cd(here);
run_tag = datestr(now, 'yyyymmdd_HHMMSS');
logdir = fullfile('..', 'results', 'background_runs');
if ~exist(logdir, 'dir'), mkdir(logdir); end
diary(fullfile(logdir, ['simulink_overnight_auto_1441_' run_tag '.log']));
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>

fprintf('=== frt_v2_overnight_auto_1441 %s ===\n', run_tag);
fprintf('cwd=%s\n', pwd);

modes = 261:292;
summary = struct('mode', {}, 'frt', {}, 'recover_status', {}, 'recover_worst', {}, ...
    'survive_status', {}, 'limit_status', {}, 'Vdc_min', {}, 'Vdc_max', {}, ...
    'V1_final_min', {}, 'V1_final_mean', {}, 'V1_final_worst_signed', {}, ...
    'artifact', {});
best_mode = nan;
best_recover = inf;
best_artifact = '';
best_nofail = false;

for mi = modes
    tag = sprintf('overnight_auto_1441_mi%d_%s', mi, run_tag);
    fprintf('\n--- single-case sweep mi%d ---\n', mi);
    try
        frt_v2_selected_expanded_switching(1441, mi, tag);
        artifact = fullfile('..', 'results', sprintf('selected_expanded_switching_%s_mi%d.mat', tag, mi));
        row = read_single_result(artifact, mi);
        summary(end+1) = row; %#ok<AGROW>
        fprintf('mi%d recover=%s %.6f survive=%s limit=%s V1min=%.6f Vdcmin=%.6f frt=%s\n', ...
            mi, row.recover_status, row.recover_worst, row.survive_status, row.limit_status, ...
            row.V1_final_min, row.Vdc_min, row.frt);

        nofail = row_has_no_fail(row);
        if row.recover_worst < best_recover
            best_recover = row.recover_worst;
            best_mode = mi;
            best_artifact = artifact;
            best_nofail = nofail;
        end

        if nofail || strcmp(row.recover_status, 'PASS')
            run_spotcheck(mi, run_tag);
        end
    catch ME
        fprintf(2, 'mi%d ERROR: %s\n', mi, ME.message);
    end
end

if isfinite(best_recover)
    fprintf('\n=== best single-case candidate mi%d recover=%.6f nofail=%d ===\n', ...
        best_mode, best_recover, best_nofail);
    fprintf('best artifact: %s\n', best_artifact);
    run_spotcheck(best_mode, run_tag);
end

fprintf('\n=== fixed-control feasibility angle sweep ===\n');
cmdgrid = make_feasibility_grid();
try
    frt_v2_1441_control_sweep(['overnight_auto_angle_' run_tag], cmdgrid);
catch ME
    fprintf(2, 'mode-10 feasibility sweep ERROR: %s\n', ME.message);
end

out = struct('run_tag', run_tag, 'modes', modes, 'best_mode', best_mode, ...
    'best_recover', best_recover, 'best_artifact', best_artifact, ...
    'summary', summary);
base = fullfile('..', 'results', ['simulink_overnight_auto_1441_' run_tag]);
save([base '.mat'], 'out');
fid = fopen([base '.json'], 'w');
fwrite(fid, jsonencode(out));
fclose(fid);
fprintf('\nwrote %s.{mat,json}\n', base);
fprintf('=== done %s ===\n', datestr(now, 'yyyymmdd_HHMMSS'));
end

function row = read_single_result(artifact, mi)
S = load(artifact, 'R');
r = S.R(1);
c = r.crit;
sm = c.switching_summary;
row = struct('mode', mi, 'frt', r.frt, ...
    'recover_status', c.recover.status, 'recover_worst', c.recover.worst, ...
    'survive_status', c.survive.status, 'limit_status', c.limit.status, ...
    'Vdc_min', sm.Vdc_min, 'Vdc_max', sm.Vdc_max, ...
    'V1_final_min', sm.V1_final_min, 'V1_final_mean', sm.V1_final_mean, ...
    'V1_final_worst_signed', sm.V1_final_worst_signed, ...
    'artifact', artifact);
end

function tf = row_has_no_fail(row)
tf = ~strcmp(row.recover_status, 'FAIL') && ~strcmp(row.survive_status, 'FAIL') && ...
     ~strcmp(row.limit_status, 'FAIL');
end

function run_spotcheck(mi, run_tag)
spot_sids = unique([217:240 1441 1456 1873 1875], 'stable');
tag = sprintf('overnight_auto_spot_mi%d_%s', mi, run_tag);
fprintf('running spotcheck mi%d on %d scenarios...\n', mi, numel(spot_sids));
try
    frt_v2_selected_expanded_switching(spot_sids, mi, tag);
catch ME
    fprintf(2, 'spotcheck mi%d ERROR: %s\n', mi, ME.message);
end
end

function cmdgrid = make_feasibility_grid()
iqs = [0.40 0.46 0.50 0.54 0.60 0.66];
base_angle = atan2(0.760, 0.400);
angles = base_angle + linspace(-0.20, 0.20, 11);
mags = [0.80 0.86 0.92 1.00];
cmdgrid = zeros(numel(iqs) * numel(angles) * numel(mags) + 1, 3);
k = 0;
for iq = iqs
    for mag = mags
        for ang = angles
            k = k + 1;
            cmdgrid(k, :) = [iq, mag * cos(ang), mag * sin(ang)];
        end
    end
end
k = k + 1;
cmdgrid(k, :) = [0.50, 0.400, 0.760];
cmdgrid = round(cmdgrid(1:k, :) * 1e4) / 1e4;
cmdgrid = unique(cmdgrid, 'rows', 'stable');
end
