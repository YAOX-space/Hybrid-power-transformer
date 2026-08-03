function run_mi322_fullspot_20260709()
% Launcher used by Codex overnight run; avoids Windows -batch quoting issues.
cd(fileparts(mfilename('fullpath')));
tag = ['mi322_tsim_fullspot_' datestr(now, 'yyyymmdd_HHMMSS')];
sids = unique([217:240 1441 1443 1444 1456 1500 1873 1875], 'stable');
frt_v2_selected_expanded_switching(sids, 322, tag);
end
