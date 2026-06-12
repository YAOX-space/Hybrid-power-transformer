function make_subset()
% make_subset.m — write a stratified representative subset of frt_scenarios.csv:
% one scenario per (category, fault_type, target_V_pu, scr) cell. Covers the whole matrix
% (4 LVRT types x 3 depths x 2 grids = 24 LVRT; 2 HVRT types x 2 amps x 2 grids = 8 HVRT).
here=fileparts(mfilename('fullpath')); cd(here);
A=readtable('../frt_scenarios.csv','TextType','string');
key=strcat(A.category,'|',A.fault_type,'|',string(A.target_V_pu),'|',string(A.scr));
[~,ia]=unique(key,'stable');
S=A(sort(ia),:);
writetable(S,'../frt_scenarios_subset.csv');
fprintf('subset: %d rows (LVRT %d, HVRT %d)\n', height(S), sum(S.category=="LVRT"), sum(S.category=="HVRT"));
end
