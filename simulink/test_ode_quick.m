% quick test: 5 scenarios, check speed and output format
addpath(fileparts(mfilename('fullpath')));
RAW_DIR = fullfile(fileparts(fileparts(mfilename('fullpath'))), 'data', 'raw_ode');
if ~exist(RAW_DIR, 'dir'), mkdir(RAW_DIR); end

scenarios = {0, 3, 5, 6, 8};
t0 = tic;
for i = 1:5
    sc = scenarios{i};
    [~, ~, Y] = hpt_ode_model(sc, 2.0, 1.0, sc*7+i);
    fname = fullfile(RAW_DIR, sprintf('test_sc%d.mat', sc));
    save(fname, '-struct', 'Y');
    n_fault = sum(Y.fault_labels > 0);
    fprintf('sc=%d  N=%d  fault_samples=%d  Vdc_mean=%.1f  V_dc_final=%.1f\n', ...
        sc, length(Y.t_uniform), n_fault, mean(Y.V_dc), Y.V_dc(end));
end
fprintf('\n5 scenarios in %.2f s  (%.1f ms each)\n', toc(t0), toc(t0)/5*1000);
