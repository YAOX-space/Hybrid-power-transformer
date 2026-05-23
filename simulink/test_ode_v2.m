% test_ode_v2.m — verify fault asymmetry in updated model
addpath(fileparts(mfilename('fullpath')));

scenarios = {0, 3, 4, 5, 6, 7, 8};
sc_names  = {'normal','igbt_oc_sh','igbt_oc_se','cap_fault','sc_1ph','sc_3ph','cascade'};

t0 = tic;
fprintf('%-12s  %-8s  %-8s  %-8s  %-10s  %-10s  %-10s\n', ...
    'Scenario','I2a_n','I2a_f','I2b_f','Vdc_n','Vdc_f','fault_n');
fprintf('%s\n', repmat('-',1,80));

for i = 1:length(scenarios)
    sc = scenarios{i};
    [~, ~, Y] = hpt_ode_model(sc, 2.0, 1.0, sc*13+i);
    N = length(Y.t_uniform);
    fi = round(1.0*20000);  % fault onset index

    % Before fault (normal window)
    I2a_n = rms(Y.I2_abc(fi-2000:fi-1, 1));
    Vdc_n = mean(Y.V_dc(fi-2000:fi-1));

    % During fault
    if sum(Y.fault_labels > 0) > 100
        fi2 = fi + 1000;
        I2a_f = rms(Y.I2_abc(fi2:fi2+2000, 1));
        I2b_f = rms(Y.I2_abc(fi2:fi2+2000, 2));
        Vdc_f = mean(Y.V_dc(fi2:fi2+2000));
    else
        I2a_f = I2a_n; I2b_f = I2a_n; Vdc_f = Vdc_n;
    end

    fprintf('%-12s  %8.1f  %8.1f  %8.1f  %10.1f  %10.1f  %10d\n', ...
        sc_names{i}, I2a_n, I2a_f, I2b_f, Vdc_n, Vdc_f, sum(Y.fault_labels>0));
end
fprintf('\nTime: %.2f s\n', toc(t0));
