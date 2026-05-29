%% validate_switching_model.m
% Computes basic sanity metrics for hpt_switching_model.slx.

MODEL = 'hpt_switching_model';
if ~exist([MODEL '.slx'], 'file')
    run('build_hpt_switching_model.m');
end

load_system(MODEL);

cases = {
% sc_id label       t_fault fault_switch
  0,    'normal',   99,     '[99 100]';
  3,    'igbt_sh',  0.025,  '[99 100]';
  4,    'igbt_se',  0.025,  '[99 100]';
  5,    'cap',      0.025,  '[99 100]';
  6,    'sc_1ph',   0.025,  '[0.025 0.040]';
  7,    'sc_3ph',   0.025,  '[0.025 0.040]';
  8,    'cascade',  0.025,  '[99 100]';
};

fprintf('\ncase       Vdc_mean  Vdc_final  Vdc_max   V2_LL_rms   P1_final   P2_final\n');
fprintf('--------------------------------------------------------------------------\n');

for i = 1:size(cases, 1)
    sc_id = cases{i, 1};
    label = cases{i, 2};
    t_fault = cases{i, 3};
    fault_times = cases{i, 4};

    configure_case(MODEL, sc_id, t_fault, fault_times);
    set_param(MODEL, 'StopTime', '0.05');
    out = sim(MODEL, 'CaptureErrors', 'on');
    assert(isempty(out.ErrorMessage), out.ErrorMessage);

    Vdc = out.V_dc(:);
    V2 = squeeze(out.V2_abc);
    if size(V2, 1) < size(V2, 2), V2 = V2.'; end
    Vab = V2(:,1) - V2(:,2);
    Vbc = V2(:,2) - V2(:,3);
    Vca = V2(:,3) - V2(:,1);
    v2_ll_rms = mean([rms(Vab), rms(Vbc), rms(Vca)]);

    fprintf('%-9s %9.1f %10.1f %8.1f %11.1f %10.1f %10.1f\n', ...
        label, mean(Vdc), Vdc(end), max(Vdc), v2_ll_rms, out.P1(end), out.P2(end));
end

close_system(MODEL, 0);

function configure_case(model, sc_id, t_fault, fault_times)
    set_param([model '/Sc_id'], 'Value', num2str(sc_id));
    set_param([model '/T_fault'], 'Value', num2str(t_fault));
    set_param([model '/LV_Load'], ...
        'ActivePower', '320e3', ...
        'InductivePower', '80e3', ...
        'CapacitivePower', '0');
    set_param([model '/DC_Link_Cap_Breaker'], 'InitialState', '1', 'SwitchingTimes', '[99]');
    set_param([model '/LV_AC_Fault'], ...
        'FaultA', 'off', 'FaultB', 'off', 'FaultC', 'off', 'GroundFault', 'off', ...
        'SwitchTimes', '[99 100]');

    if sc_id == 5
        set_param([model '/DC_Link_Cap_Breaker'], 'SwitchingTimes', num2str(t_fault));
    elseif sc_id == 6
        set_param([model '/LV_AC_Fault'], ...
            'FaultA', 'on', 'FaultB', 'off', 'FaultC', 'off', 'GroundFault', 'on', ...
            'SwitchTimes', fault_times);
    elseif sc_id == 7
        set_param([model '/LV_AC_Fault'], ...
            'FaultA', 'on', 'FaultB', 'on', 'FaultC', 'on', 'GroundFault', 'on', ...
            'SwitchTimes', fault_times);
    end
end
