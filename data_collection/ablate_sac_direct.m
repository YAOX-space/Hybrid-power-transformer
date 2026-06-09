%% ablate_sac_direct.m
% Flexible SAC-direct LVRT validation for SAC attribution ablation (#9, 2026-06-06).
%
% Unlike validate_sac_direct.m, this:
%   - ALWAYS uses the SAC-direct controller (no per-class controller swap to dq-PI),
%   - applies whatever (m_sh, m_se_d, m_se_q) the action CSV specifies,
% so different action sources can be compared on identical footing:
%   * fixed-command baselines (no SAC)   -> isolates protection floors
%   * raw SAC actions (no overrides)      -> net SAC contribution
%   * SAC + hand-coded overrides          -> the published pipeline
%
% Writes ONE ROW PER SCENARIO to out_csv (appends when i0>1), so a long arm can be
% run in timeout-safe chunks; aggregate with ai/aggregate_ablation.py.
%
% Usage (MATLAB):
%   ablate_sac_direct('../results/ablation/fixed_090.csv', '../results/ablation/fixed_090_res.csv')
%   ablate_sac_direct(csv, out_csv, 120, 1)    % first 120
%   ablate_sac_direct(csv, out_csv, 120, 121)  % next 120 (appends)

function ablate_sac_direct(action_csv, out_csv, n_max, i0)

if nargin < 3 || isempty(n_max); n_max = inf; end
if nargin < 4 || isempty(i0);    i0 = 1; end

addpath('../simulink');
run('../simulink/parameters.m');

MODEL    = 'hpt_switching_model';
SCEN_CSV = '../data_collection/scenario_table_hpt_v2.csv';
% Controller-selector interface code for the SAC-direct controller. This integer is
% the contract the compiled .slx branches on — it is an interface code, not a label.
CTRL_SAC_DIRECT = 9;
f_sample = 20000;
I2_nom_pk = (S_rated/(sqrt(3)*V_secondary)) * sqrt(2);   % 816.5 A peak

actions = readtable(action_csv, 'TextType','string');
scen    = readtable(SCEN_CSV,   'TextType','string');
assert(height(actions) == height(scen), 'Action/scenario count mismatch')
i_end = min(height(scen), i0 + n_max - 1);

if ~bdIsLoaded(MODEL); load_system('../simulink/hpt_switching_model.slx'); end
set_param(MODEL, 'SimulationMode', 'normal');
set_param(MODEL, 'FastRestart', 'off');

% open results CSV (write header if starting fresh)
if i0 == 1
    fid = fopen(out_csv, 'w');
    fprintf(fid, 'scenario_idx,sc_id,m_sh,m_se_d,m_se_q,vdc_min,vdc_max,i2_max,lvrt_pass\n');
else
    fid = fopen(out_csv, 'a');
end

t_start = tic; npass = 0;
for ri = i0:i_end
    row=scen(ri,:); act=actions(ri,:);
    sc_id=double(row.sc_id); t_f=double(row.t_fault); T_sim=double(row.T_sim);
    m_sh=double(act.m_sh); m_se_d=double(act.m_se_d); m_se_q=double(act.m_se_q);
    t_ax=(0:1/f_sample:T_sim)'; post=t_ax>=t_f;

    set_param(MODEL,'FastRestart','off')   % allow structural set_param this iteration
    set_param([MODEL '/Sc_id'],'Value',num2str(sc_id))
    set_param([MODEL '/T_fault'],'Value',num2str(t_f))
    set_param([MODEL '/FaultVariant'],'Value',num2str(row.fault_variant))
    set_param([MODEL '/FaultMag'],'Value',num2str(row.fault_mag))
    set_param([MODEL '/ControllerMode'],'Value',num2str(CTRL_SAC_DIRECT))   % SAC-direct, no swap
    set_param([MODEL '/RL_Energy_Bias'],'Value',num2str(m_sh))
    set_param([MODEL '/RL_Reg_Bias'],'Value',num2str(m_se_d))
    set_param([MODEL '/RL_Current_Bias'],'Value',num2str(m_se_q))
    set_param([MODEL '/LV_Load'],'ActivePower',num2str(row.P_load), ...
        'InductivePower',num2str(row.Q_load),'CapacitivePower','0')
    set_param([MODEL '/DC_Link_Cap_Breaker'],'InitialState','1','SwitchingTimes','[99]')
    if sc_id==5; cap='680e-6'; else; cap='2200e-6'; end
    set_param([MODEL '/DC_Link_Capacitor'],'Capacitance',cap,'InitialVoltage','800')
    set_param([MODEL '/LV_AC_Fault'],'FaultA','off','FaultB','off','FaultC','off', ...
        'GroundFault','off','SwitchTimes','[99 100]')
    if sc_id==6
        set_param([MODEL '/LV_AC_Fault'],'FaultA','on','GroundFault','on', ...
            'FaultResistance',num2str(row.fault_resistance), ...
            'GroundResistance',num2str(row.ground_resistance), ...
            'SwitchTimes',sprintf('[%.6f %.6f]',t_f,t_f+0.015))
    elseif sc_id==7
        set_param([MODEL '/LV_AC_Fault'],'FaultA','on','FaultB','on','FaultC','on', ...
            'GroundFault','on','FaultResistance',num2str(row.fault_resistance), ...
            'GroundResistance',num2str(row.ground_resistance), ...
            'SwitchTimes',sprintf('[%.6f %.6f]',t_f,t_f+0.015))
    end
    set_param(MODEL,'StopTime',num2str(T_sim))

    in_k=Simulink.SimulationInput(MODEL);
    in_k=in_k.setModelParameter('FastRestart','on');
    out_k=sim(in_k);
    if ~isempty(out_k.ErrorMessage)
        fprintf('ERROR sc=%d ri=%d: %s\n',sc_id,ri,out_k.ErrorMessage);
        fprintf(fid,'%d,%d,%.4f,%.4f,%.4f,0,2,0,0\n',ri,sc_id,m_sh,m_se_d,m_se_q);
        continue
    end
    Vdc_k=out_k.get('V_dc'); I2_k=out_k.get('I2_abc');
    pv=post(1:size(Vdc_k,1)); pii=post(1:size(I2_k,1));
    vmin=double(min(Vdc_k(pv)))/800; vmax=double(max(Vdc_k(pv)))/800;
    i2m=double(max(abs(I2_k(pii,:)),[],'all'))/I2_nom_pk;
    ok=(vmin>=0.75)&(vmax<=1.25)&(i2m<=3.0); npass=npass+ok;
    fprintf(fid,'%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%d\n', ...
        ri,sc_id,m_sh,m_se_d,m_se_q,vmin,vmax,i2m,ok);
    if mod(ri,25)==0
        fprintf('[%3d/%d] %.0fs pass=%d\n',ri,i_end,toc(t_start),npass)
    end
end
fclose(fid);
set_param(MODEL,'FastRestart','off')
fprintf('chunk [%d..%d] done, %.0fs, pass=%d -> %s\n', i0, i_end, toc(t_start), npass, out_csv)
end
