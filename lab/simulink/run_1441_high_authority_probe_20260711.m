cd(fileparts(mfilename('fullpath')));
faults = [
   -0.10 0.00 0.00
    0.10 0.10 0.20
];
posts = [
    0.30 0.30 0.25
    0.30 0.30 0.30
    0.30 0.35 0.30
    0.30 0.30 0.35
    0.30 0.35 0.35
    0.30 0.40 0.35
    0.30 0.40 0.40
];
delays = [0.08 0.18 0.25 0.35 0.45];
cmdgrid = [];
for i = 1:size(faults, 1)
    for j = 1:size(posts, 1)
        for k = 1:numel(delays)
            cmdgrid(end + 1, :) = [faults(i, :) posts(j, :) delays(k)]; %#ok<SAGROW>
        end
    end
end
frt_v2_selected_control_sweep([1441], '1441_high_authority_probe_20260711', cmdgrid);
