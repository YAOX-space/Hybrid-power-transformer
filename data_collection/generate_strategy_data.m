%% generate_strategy_data.m
% Batch Simulink: 350 scenarios x 4 FAHC strategies = 1400 sims
% Mode 6 (RCN delta setpoints) + FastRestart (~0.4s per strategy after first)
%
% Strategy → RCN deltas (from dq baseline):
%   S0: dVdc=  0  dV2=  0  dIlim= 0.0  →  Vdc=800V  V2=400V  Ilim=3.0pu
%   S1: dVdc=-40  dV2=  0  dIlim=-0.2  →  Vdc=760V  V2=400V  Ilim=2.8pu
%   S2: dVdc=-60  dV2=-20  dIlim=-0.2  →  Vdc=740V  V2=380V  Ilim=2.8pu
%   S3: dVdc=-80  dV2=-40  dIlim=-0.5  →  Vdc=720V  V2=360V  Ilim=2.5pu

clear; clc;
addpath('../simulink');
run('../simulink/parameters.m');

MODEL    = 'hpt_switching_model';
SCEN_CSV = '../data_collection/scenario_table_hpt_v2.csv';
OUT_CSV  = '../results/strategy_lvrt_data.csv';

STRAT_DVDC  = [   0, -40, -60, -80];
STRAT_DV2   = [   0,   0, -20, -40];
STRAT_DILIM = [ 0.0,-0.2,-0.2,-0.5];
N_STRAT = 4;

f_sample = 20000;
I2_nom   = S_rated / (sqrt(3) * V_secondary);

T = readtable(SCEN_CSV, 'TextType', 'string');
N = height(T);
fprintf('Running %d x %d = %d simulations...\n', N, N_STRAT, N*N_STRAT)

if ~bdIsLoaded(MODEL)
    load_system('../simulink/hpt_switching_model.slx');
end
set_param(MODEL, 'SimulationMode', 'accelerator');
set_param(MODEL, 'FastRestart', 'off');

n_rows  = N * N_STRAT;
scen_col = zeros(n_rows,1,'int32');
scid_col = zeros(n_rows,1,'int32');
str_col  = zeros(n_rows,1,'int32');
vmin_col = zeros(n_rows,1);
vmax_col = zeros(n_rows,1);
i2m_col  = zeros(n_rows,1);
pass_col = false(n_rows,1);

t_total = tic;
row_out = 0;
n_fail  = 0;

for ri = 1:N
    row   = T(ri,:);
    sc_id = row.sc_id;
    t_f   = row.t_fault;
    T_sim = row.T_sim;
    t_ax  = (0:1/f_sample:T_sim)';
    post  = t_ax >= t_f;

    % Configure non-tunable params (before FastRestart)
    set_param(MODEL, 'FastRestart', 'off')
    set_param([MODEL '/Sc_id'],          'Value', num2str(sc_id))
    set_param([MODEL '/T_fault'],        'Value', num2str(t_f))
    set_param([MODEL '/FaultVariant'],   'Value', num2str(row.fault_variant))
    set_param([MODEL '/FaultMag'],       'Value', num2str(row.fault_mag))
    set_param([MODEL '/ControllerMode'], 'Value', '6')
    set_param([MODEL '/LV_Load'], ...
        'ActivePower',   num2str(row.P_load), ...
        'InductivePower', num2str(row.Q_load), ...
        'CapacitivePower', '0')
    set_param([MODEL '/DC_Link_Cap_Breaker'], ...
        'InitialState','1','SwitchingTimes','[99]')
    if sc_id == 5
        set_param([MODEL '/DC_Link_Capacitor'], 'Capacitance','680e-6','InitialVoltage','800')
    else
        set_param([MODEL '/DC_Link_Capacitor'], 'Capacitance','2200e-6','InitialVoltage','800')
    end
    set_param([MODEL '/LV_AC_Fault'], ...
        'FaultA','off','FaultB','off','FaultC','off','GroundFault','off', ...
        'SwitchTimes','[99 100]')
    if sc_id == 6
        set_param([MODEL '/LV_AC_Fault'], ...
            'FaultA','on','GroundFault','on', ...
            'FaultResistance',num2str(row.fault_resistance), ...
            'GroundResistance',num2str(row.ground_resistance), ...
            'SwitchTimes',sprintf('[%.6f %.6f]',t_f,t_f+0.015))
    elseif sc_id == 7
        set_param([MODEL '/LV_AC_Fault'], ...
            'FaultA','on','FaultB','on','FaultC','on','GroundFault','on', ...
            'FaultResistance',num2str(row.fault_resistance), ...
            'GroundResistance',num2str(row.ground_resistance), ...
            'SwitchTimes',sprintf('[%.6f %.6f]',t_f,t_f+0.015))
    end
    set_param(MODEL,'StopTime',num2str(T_sim))

    % Strategy loop: FastRestart reuses compiled model
    for strat = 0:(N_STRAT-1)
        row_out = row_out + 1;
        set_param([MODEL '/VDC_Ref_Delta'],'Value',num2str(STRAT_DVDC(strat+1)))
        set_param([MODEL '/V2_Ref_Delta'], 'Value',num2str(STRAT_DV2(strat+1)))
        set_param([MODEL '/ILim_Delta'],   'Value',num2str(STRAT_DILIM(strat+1)))

        in_k = Simulink.SimulationInput(MODEL);
        in_k = in_k.setModelParameter('FastRestart','on');

        try
            out_k = sim(in_k);
            if ~isempty(out_k.ErrorMessage), error(out_k.ErrorMessage); end
            Vdc_k = out_k.get('V_dc');
            I2_k  = out_k.get('I2_abc');
            vmin  = min(Vdc_k(post)) / 800;
            vmax  = max(Vdc_k(post)) / 800;
            i2m   = max(max(abs(I2_k(post,:)))) / (sqrt(2)*I2_nom);
            lvrt  = vmin>=0.75 && vmax<=1.25 && i2m<=3.0;
        catch e
            warning('FAIL ri=%d s=%d: %s', ri, strat, e.message)
            n_fail = n_fail+1;
            vmin=0; vmax=1; i2m=0; lvrt=false;
        end

        scen_col(row_out) = ri;
        scid_col(row_out) = sc_id;
        str_col(row_out)  = strat;
        vmin_col(row_out) = vmin;
        vmax_col(row_out) = vmax;
        i2m_col(row_out)  = i2m;
        pass_col(row_out) = lvrt;
    end

    if mod(ri,10)==0
        el  = toc(t_total);
        rem = el/row_out * (n_rows-row_out);
        fprintf('[%3d/%3d]  %.0fs elapsed  ~%.0f min left  pass=%d/%d\n', ...
            ri, N, el, rem/60, sum(pass_col(1:row_out)), row_out)
    end
end

set_param(MODEL,'FastRestart','off')

results = table(scen_col,scid_col,str_col,vmin_col,vmax_col,i2m_col,pass_col, ...
    'VariableNames',{'scenario_idx','sc_id','strategy','vdc_min_pu','vdc_max_pu','i2_max_pu','lvrt_pass'});
writetable(results, OUT_CSV)

el = toc(t_total);
fprintf('\n=== %d sims done in %.0f min ===\n', n_rows, el/60)
fprintf('Failed: %d\n', n_fail)
for s = 0:3
    m = str_col==s;
    fprintf('  S%d LVRT: %.2f%%\n', s, 100*mean(pass_col(m)))
end
fprintf('Saved -> %s\n', OUT_CSV)
