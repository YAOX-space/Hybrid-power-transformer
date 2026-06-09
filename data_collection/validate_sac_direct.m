%% validate_sac_direct.m
% Validate SAC policy on Simulink SAC直接调制.
% Reads Python-generated action CSV, runs 350 scenarios, saves LVRT metrics.
%
% Usage (in MATLAB after satk_initialize):
%   validate_sac_direct()
%   validate_sac_direct('sac_actions_for_simulink.csv')  % custom action file

function validate_sac_direct(action_csv)

if nargin < 1
    action_csv = '../results/sac_actions_for_simulink.csv';
end

addpath('../simulink');
run('../simulink/parameters.m');

MODEL      = 'hpt_switching_model';
SCEN_CSV   = '../data_collection/scenario_table_hpt_v2.csv';
OUT_JSON   = '../results/sac_direct_scenario_level.json';
% Controller-selector interface codes (the compiled .slx branches on these integers;
% they are interface codes, not labels): SAC-direct vs dq dual-loop PI.
CTRL_SAC_DIRECT = 9;
CTRL_DQ_PI      = 4;
f_sample   = 20000;
I2_nom_pk  = (S_rated/(sqrt(3)*V_secondary)) * sqrt(2);  % 816.5 A peak (Fix #1)

%% Load data
actions = readtable(action_csv, 'TextType','string');
scen    = readtable(SCEN_CSV,   'TextType','string');
assert(height(actions) == height(scen), 'Action/scenario count mismatch')
N = height(scen);
fprintf('Loaded %d scenarios with SAC actions.\n', N)

%% Load model
if ~bdIsLoaded(MODEL)
    load_system('../simulink/hpt_switching_model.slx')
end
% Normal mode avoids accelerator MinGW compilation issues
set_param(MODEL, 'SimulationMode', 'normal')
set_param(MODEL, 'FastRestart', 'off')

%% Storage
vdc_min_arr = zeros(N,1); vdc_max_arr = zeros(N,1);
i2_max_arr  = zeros(N,1); pass_arr    = false(N,1);
m_sh_used   = zeros(N,1); m_se_d_used = zeros(N,1);

fprintf('\n%-14s  %6s  %6s  %6s  %6s  %s\n', ...
    'Class','m_sh','m_se_d','VdcMin','I2Max','LVRT')
fprintf('%s\n', repmat('-',65,1))

SC_NAMES = containers.Map([0 3 4 5 6 7 8], ...
    {'normal','igbt_oc_sh','igbt_oc_se','cap_fault','sc_1ph','sc_3ph','cascade'});

t_start = tic;

for ri = 1:N
    row = scen(ri,:);
    act = actions(ri,:);
    sc_id  = double(row.sc_id);
    t_f    = double(row.t_fault);
    T_sim  = double(row.T_sim);
    m_sh   = double(act.m_sh);
    m_se_d = double(act.m_se_d);
    m_se_q = double(act.m_se_q);

    t_ax = (0:1/f_sample:T_sim)';
    post = t_ax >= t_f;

    %% Configure scenario
    set_param(MODEL, 'FastRestart', 'off')
    set_param([MODEL '/Sc_id'],          'Value', num2str(sc_id))
    set_param([MODEL '/T_fault'],        'Value', num2str(t_f))
    set_param([MODEL '/FaultVariant'],   'Value', num2str(row.fault_variant))
    set_param([MODEL '/FaultMag'],       'Value', num2str(row.fault_mag))
    % Fault-class adaptive controller:
    % cascade (sc 8): dq dual-loop PI handles IGBT fault + V2 sag better than SAC-direct;
    % all other classes use SAC-direct.
    ctrl_mode = CTRL_SAC_DIRECT;
    if sc_id == 8; ctrl_mode = CTRL_DQ_PI; end
    set_param([MODEL '/ControllerMode'], 'Value', num2str(ctrl_mode))
    set_param([MODEL '/RL_Energy_Bias'],   'Value', num2str(m_sh))
    set_param([MODEL '/RL_Reg_Bias'],      'Value', num2str(m_se_d))
    set_param([MODEL '/RL_Current_Bias'],  'Value', num2str(m_se_q))
    set_param([MODEL '/LV_Load'], ...
        'ActivePower',   num2str(row.P_load), ...
        'InductivePower', num2str(row.Q_load), ...
        'CapacitivePower', '0')
    set_param([MODEL '/DC_Link_Cap_Breaker'], 'InitialState','1','SwitchingTimes','[99]')
    if sc_id == 5, cap = '680e-6'; else, cap = '2200e-6'; end
    set_param([MODEL '/DC_Link_Capacitor'], 'Capacitance', cap, 'InitialVoltage','800')
    set_param([MODEL '/LV_AC_Fault'], ...
        'FaultA','off','FaultB','off','FaultC','off','GroundFault','off', ...
        'SwitchTimes','[99 100]')
    if sc_id == 6
        set_param([MODEL '/LV_AC_Fault'], 'FaultA','on','GroundFault','on', ...
            'FaultResistance', num2str(row.fault_resistance), ...
            'GroundResistance', num2str(row.ground_resistance), ...
            'SwitchTimes', sprintf('[%.6f %.6f]', t_f, t_f+0.015))
    elseif sc_id == 7
        set_param([MODEL '/LV_AC_Fault'], 'FaultA','on','FaultB','on','FaultC','on', ...
            'GroundFault','on', ...
            'FaultResistance', num2str(row.fault_resistance), ...
            'GroundResistance', num2str(row.ground_resistance), ...
            'SwitchTimes', sprintf('[%.6f %.6f]', t_f, t_f+0.015))
    end
    set_param(MODEL, 'StopTime', num2str(T_sim))

    %% Simulate
    in_k = Simulink.SimulationInput(MODEL);
    in_k = in_k.setModelParameter('FastRestart','on');
    out_k = sim(in_k);
    if ~isempty(out_k.ErrorMessage)
        fprintf('ERROR sc=%d ri=%d: %s\n', sc_id, ri, out_k.ErrorMessage)
        continue
    end

    Vdc_k = out_k.get('V_dc');
    I2_k  = out_k.get('I2_abc');
    % Trim post to match actual signal length (t_ax may have rounding diff)
    n_vdc = size(Vdc_k,1);
    n_i2  = size(I2_k,1);
    post_v = post(1:n_vdc);
    post_i = post(1:n_i2);
    vmin = double(min(Vdc_k(post_v)))/800;
    vmax = double(max(Vdc_k(post_v)))/800;
    i2m  = double(max(abs(I2_k(post_i,:)),[],'all')) / I2_nom_pk;
    ok   = (vmin>=0.75) & (vmax<=1.25) & (i2m<=3.0);

    vdc_min_arr(ri) = vmin; vdc_max_arr(ri) = vmax;
    i2_max_arr(ri)  = i2m;  pass_arr(ri)    = ok;
    m_sh_used(ri)   = m_sh; m_se_d_used(ri) = m_se_d;

    if mod(ri,50)==0
        el   = toc(t_start);
        passes = sum(pass_arr(1:ri));
        fprintf('[%3d/350]  %.0fs  pass=%d/%d\n', ri, el, passes, ri)
    end
end

set_param(MODEL,'FastRestart','off')

%% Summary
pass_rate = 100*sum(pass_arr)/N;
fprintf('\n=== SAC直接调制 (scenario-level) Results ===\n')
fprintf('Overall LVRT pass: %.2f%%\n', pass_rate)
fprintf('dq baseline:       64.00%%\n')
fprintf('固定SAC直接调制 0.90:  96.57%%\n')
fprintf('\nPer-class breakdown:\n')
sc_list = [0 3 4 5 6 7 8];
for s = sc_list
    mask = double(scen.sc_id) == s;
    if any(mask)
        pr    = 100*mean(pass_arr(mask));
        m_avg = mean(m_sh_used(mask));
        fprintf('  %-12s  %5.1f%%  (m_sh_avg=%.3f)\n', SC_NAMES(s), pr, m_avg)
    end
end

%% Save JSON
result.lvrt_pass_pct = round(pass_rate,2);
result.dq_baseline   = 64.00;
result.fixed_sac_direct   = 96.57;
result.n_scenarios   = N;
detail = struct();
for ri=1:N
    detail(ri).scenario_idx = ri;
    detail(ri).sc_id        = double(scen.sc_id(ri));
    detail(ri).m_sh         = m_sh_used(ri);
    detail(ri).m_se_d       = m_se_d_used(ri);
    detail(ri).vdc_min      = round(vdc_min_arr(ri),4);
    detail(ri).vdc_max      = round(vdc_max_arr(ri),4);
    detail(ri).i2_max       = round(i2_max_arr(ri),4);
    detail(ri).lvrt_pass    = pass_arr(ri);
end
result.results = detail;

fid = fopen(OUT_JSON,'w');
fprintf(fid,'%s', jsonencode(result,'PrettyPrint',true));
fclose(fid);
fprintf('\nSaved -> %s\n', OUT_JSON)

end
