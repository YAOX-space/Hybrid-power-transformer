%% test_switching_quick.m
% Smoke test for hpt_switching_model.slx.

MODEL = 'hpt_switching_model';
if ~exist([MODEL '.slx'], 'file')
    run('build_hpt_switching_model.m');
end

load_system(MODEL);
set_param(MODEL, 'StopTime', '0.02');

% Normal condition
set_param([MODEL '/LV_AC_Fault'], 'SwitchTimes', '[99 100]');
out = sim(MODEL, 'CaptureErrors', 'on');
assert(isempty(out.ErrorMessage), out.ErrorMessage);
fprintf('normal: samples=%d  Vdc_final=%.2f  P1_final=%.2f\n', ...
    numel(out.V_dc), out.V_dc(end), out.P1(end));

% Three-phase AC fault in the final 5 ms.
set_param([MODEL '/LV_AC_Fault'], 'SwitchTimes', '[0.015 0.02]');
out = sim(MODEL, 'CaptureErrors', 'on');
assert(isempty(out.ErrorMessage), out.ErrorMessage);
fprintf('3ph fault: samples=%d  Vdc_final=%.2f  P1_final=%.2f\n', ...
    numel(out.V_dc), out.V_dc(end), out.P1(end));

close_system(MODEL, 0);
