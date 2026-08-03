cd('E:/research_space/Hybrid-power-transformer/lab/simulink');
tag = ['mi322_tsim_fullspot_' datestr(now, 'yyyymmdd_HHMMSS')];
sids = unique([217:240 1441 1443 1444 1456 1500 1873 1875], 'stable');
frt_v2_selected_expanded_switching(sids, 322, tag);
