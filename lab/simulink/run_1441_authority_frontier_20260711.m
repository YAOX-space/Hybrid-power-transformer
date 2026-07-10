cd(fileparts(mfilename('fullpath')));
faults = [
    0.10 0.10 0.20
    0.00 0.10 0.20
   -0.10 0.00 0.00
];
posts = [
    0.27 0.20 0.20
    0.30 0.20 0.20
    0.35 0.20 0.20
    0.27 0.25 0.20
    0.27 0.30 0.20
    0.30 0.25 0.20
    0.30 0.30 0.20
    0.35 0.25 0.20
    0.35 0.30 0.20
    0.30 0.30 0.25
    0.35 0.30 0.25
];
delays = [0 0.08 0.18 0.25 0.35];
cmdgrid = [];
for i = 1:size(faults, 1)
    for j = 1:size(posts, 1)
        for k = 1:numel(delays)
            cmdgrid(end + 1, :) = [faults(i, :) posts(j, :) delays(k)]; %#ok<SAGROW>
        end
    end
end
frt_v2_selected_control_sweep([1441], '1441_authority_frontier_20260711', cmdgrid);
