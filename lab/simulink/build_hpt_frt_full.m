function build_hpt_frt_full(stage, gridmode)
% build_hpt_frt_full.m  - reproducible, from-scratch FULL HPT switching model for
% standard grid FRT (GB/T), built up in stages and validated at each step.
%
%   stage 1 : MV weak grid + MV fault + main transformer (D-Yg) + LV load   (backbone)
%   stage 2 : + shunt energy VSC via Tsh + shared DC bus + conditional chopper + dq control
%   stage 3 : + series regulating VSC via Tse (winding2 in series in LV line)
%   stage 4 : dual control mode  (Mode10 SAC 4-D action / Mode4 dq dual-loop PI)
%
% Real two voltage levels (10 kV MV / 400 V LV).  Specialized Power Systems.
% Reuses the debugged shunt control (PLL + dq current loop + reactive priority +
% Vdc outer loop + anti-windup) from build_frt_statcom.m.
if nargin<1, stage=1; end
if nargin<2, gridmode='fault'; end   % 'fault'=LVRT (3-phase source + fault); 'swell'=HVRT (programmable source + series Z)
M='hpt_frt_full';
if bdIsLoaded(M), close_system(M,0); end
new_system(M); load_system(M);

% ---- parameters (mirror parameters.m) ----
f0=50; Ts=20e-6;
Vmv=10e3; Vlv=400; Srated=400e3;
p = pu_params();   % SINGLE SOURCE of base values (mirror of src/hpt_frt/common/pu.py); embedded HLC
                   % literals are interpolated from p so there is no second copy of 173.2/326.6.
% P3 (CHANGE_REPORT): the HLC `Imax` historically = I_pe_rms (173.2) and conflates the pu->amp
% SCALE with the converter current LIMIT, while the Simscape dq currents are PEAK amplitudes. The
% physically-correct command path uses a PEAK scale (p.I_sys_peak) so iq=0.3 system-pu -> 244.9 A
% peak (=PE full), with a SEPARATE converter limit p.I_conv_max_pu*p.I_sys_peak. Switching to that
% is a controller redesign that REQUIRES re-tuning + re-validation -> deferred to P3. Here the value
% is preserved (p.I_pe_rms) and only SINGLE-SOURCED, to avoid an unvalidated behaviour change.
% weak-grid default SCR=3 at 10 kV: Zbase=Vmv^2/Srated=250 ohm; |Z|=250/3=83.3, X/R=7
Zb=Vmv^2/Srated; scr=3; Zg=Zb/scr; Rg=Zg/sqrt(1+49); Lg=7*Rg/(2*pi*f0);

set_param(M,'Solver','ode23tb','StopTime','0.6');
pos=@(x,y,w,h)[x y x+w y+h];

add_block('powerlib/powergui',[M '/powergui'],'Position',pos(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

% ---- MV grid ----
if strcmp(gridmode,'swell')
    % HVRT: ideal Programmable Voltage Source (amplitude table to swell) + external series Z (weak grid)
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source',[M '/Grid'],'Position',pos(60,120,70,90));
    set_param([M '/Grid'],'PositiveSequence',['[' num2str(Vmv*1.125) ' 0 ' num2str(f0) ']'], ...
        'VariationEntity','None');   % amplitude table set per-scenario by the harness
    add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Zg'],'Position',pos(160,120,50,70));
    set_param([M '/Zg'],'BranchType','RL','Resistance',num2str(Rg),'Inductance',num2str(Lg));
else
    % LVRT: 3-phase source with internal impedance; fault block creates the sag
    add_block('powerlib/Electrical Sources/Three-Phase Source',[M '/Grid'],'Position',pos(120,120,60,90));
    % EMF boosted ~12.5% so pre-fault LV ~ 1.0 pu despite weak-grid droop (calibrate per SCR)
    set_param([M '/Grid'],'Voltage',num2str(Vmv*1.125),'Frequency',num2str(f0),'PhaseAngle','0', ...
        'InternalConnection','Yg','SpecifyImpedance','off', ...
        'Resistance',num2str(Rg),'Inductance',num2str(Lg));
end

% ---- MV bus measurement ----
add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasMV'],'Position',pos(240,120,70,90));
set_param([M '/MeasMV'],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','no');

% ---- MV grid fault ----
add_block('powerlib/Elements/Three-Phase Fault',[M '/GridFault'],'Position',pos(240,270,50,70));
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off', ...
    'SwitchTimes','[99 100]','FaultResistance','1','GroundResistance','0.01');

% ---- main transformer  Delta(10kV) / Yg(400V), 400 kVA ----
add_block('powerlib/Elements/Three-Phase Transformer (Two Windings)',[M '/Main_Tx'],'Position',pos(380,110,80,120));
set_param([M '/Main_Tx'],'NominalPower',['[' num2str(Srated) ',' num2str(f0) ']'], ...
    'Winding1Connection','Delta (D11)','Winding1',['[' num2str(Vmv) ',0.005,0.025]'], ...
    'Winding2Connection','Yg',          'Winding2',['[' num2str(Vlv) ',0.005,0.025]']);

% ---- LV bus measurement ----
add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasLV'],'Position',pos(520,110,70,90));
set_param([M '/MeasLV'],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','no');

% ---- LV rated load ----
add_block('powerlib/Elements/Three-Phase Series RLC Load',[M '/Load'],'Position',pos(660,270,60,70));
set_param([M '/Load'],'NominalVoltage',num2str(Vlv),'NominalFrequency',num2str(f0), ...
    'ActivePower',num2str(Srated),'InductivePower','0','CapacitivePower','0','Configuration','Y (grounded)');

% ---- logging ----
for nm = {'Vmv_abc','Vlv_abc'}
  add_block('simulink/Sinks/To Workspace',[M '/' nm{1}],'Position',pos(720,120,90,26), ...
      'VariableName',nm{1},'SaveFormat','Array','SampleTime',num2str(Ts));
  try, set_param([M '/' nm{1}],'MaxDataPoints','inf'); catch, end   % param name varies by release; default already keeps all points
end

% ---- electrical wiring (backbone) ----
for k=1:3
  if strcmp(gridmode,'swell')
    add_line(M, ph([M '/Grid'],'RConn',k), ph([M '/Zg'],'LConn',k),'autorouting','on');   % source -> series Z
    add_line(M, ph([M '/Zg'],'RConn',k),   ph([M '/MeasMV'],'LConn',k),'autorouting','on'); % Z -> MV bus
  else
    add_line(M, ph([M '/Grid'],'RConn',k), ph([M '/MeasMV'],'LConn',k),'autorouting','on');
  end
  add_line(M, ph([M '/MeasMV'],'RConn',k),  ph([M '/GridFault'],'LConn',k),'autorouting','on');
  add_line(M, ph([M '/MeasMV'],'RConn',k),  ph([M '/Main_Tx'],'LConn',k),'autorouting','on');     % MV->primary(Delta)
  add_line(M, ph([M '/Main_Tx'],'RConn',k), ph([M '/MeasLV'],'LConn',k),'autorouting','on');       % secondary(Yg)->LV
  add_line(M, ph([M '/MeasLV'],'RConn',k),  ph([M '/Load'],'LConn',k),'autorouting','on');
end
add_line(M,'MeasMV/1','Vmv_abc/1','autorouting','on');
add_line(M,'MeasLV/1','Vlv_abc/1','autorouting','on');

if stage>=2
  Spe=120e3; Rsh=0.05; Lsh=3e-3; Cdc=2200e-6;
  Rchop=Vlv*0;  Rchop=(800^2)/Spe;   % chopper burns ~ rated PE at 800V
  % --- Tsh coupling transformer: Delta(10kV) / Yg(400V), 120 kVA, parallel on MV bus ---
  add_block('powerlib/Elements/Three-Phase Transformer (Two Windings)',[M '/Tsh'],'Position',pos(380,420,80,110));
  set_param([M '/Tsh'],'NominalPower',['[' num2str(Spe) ',' num2str(f0) ']'], ...
      'Winding1Connection','Delta (D11)','Winding1',['[' num2str(Vmv) ',0.005,0.02]'], ...
      'Winding2Connection','Yg',          'Winding2',['[' num2str(Vlv) ',0.005,0.02]']);
  % --- shunt POC V-I measurement (V for PLL, I = current into VSC branch) ---
  add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasSh'],'Position',pos(520,420,70,90));
  set_param([M '/MeasSh'],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','yes');
  % --- shunt filter ---
  add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Lsh'],'Position',pos(640,420,55,60));
  set_param([M '/Lsh'],'BranchType','RL','Resistance',num2str(Rsh),'Inductance',num2str(Lsh));
  % --- shunt VSC (2-level IGBT bridge) ---
  add_block('powerlib/Power Electronics/Universal Bridge',[M '/ShVSC'],'Position',pos(740,420,80,110));
  set_param([M '/ShVSC'],'Arms','3','Device','IGBT / Diodes');
  % --- shared DC bus: cap (init 800) + conditional chopper ---
  add_block('powerlib/Elements/Series RLC Branch',[M '/Cdc'],'Position',pos(900,440,40,60));
  set_param([M '/Cdc'],'BranchType','C','Capacitance',num2str(Cdc),'Setx0','on','InitialVoltage','800');
  add_block('powerlib/Power Electronics/IGBT',[M '/Chop'],'Position',pos(980,440,40,55));
  add_block('powerlib/Elements/Series RLC Branch',[M '/Rchop'],'Position',pos(980,520,40,50));
  set_param([M '/Rchop'],'BranchType','R','Resistance',num2str(Rchop));
  add_block('powerlib/Measurements/Voltage Measurement',[M '/MeasVdc'],'Position',pos(900,550,40,40));
  % --- shunt controller ---
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRL_sh'],'Position',pos(560,650,180,140));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRL_sh']); ch.Script=ctrl_shunt_code();
  add_block('simulink/Sources/Constant',[M '/Vdc_ref'],'Position',pos(340,640,50,24),'Value','800');
  add_block('simulink/Sources/Constant',[M '/iq_ref'], 'Position',pos(340,680,50,24),'Value','0');
  add_block('simulink/Sources/Clock',   [M '/Clock'],  'Position',pos(340,720,40,24));
  add_block('simulink/Sources/Constant',[M '/t_fault'],'Position',pos(340,760,50,24),'Value','0.30');
  for nm={'Vdc','Ish_abc','dq'}
    add_block('simulink/Sinks/To Workspace',[M '/' nm{1}],'Position',pos(980,650,80,26), ...
        'VariableName',nm{1},'SaveFormat','Array','SampleTime',num2str(Ts));
    try, set_param([M '/' nm{1}],'MaxDataPoints','inf'); catch, end   % param name varies by release
  end
  % electrical wiring (shunt branch)
  for k=1:3
    add_line(M, ph([M '/MeasMV'],'RConn',k), ph([M '/Tsh'],'LConn',k),'autorouting','on');   % MV bus -> Tsh primary
    add_line(M, ph([M '/Tsh'],'RConn',k),    ph([M '/MeasSh'],'LConn',k),'autorouting','on'); % Tsh sec -> shunt POC
    add_line(M, ph([M '/MeasSh'],'RConn',k), ph([M '/Lsh'],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/Lsh'],'RConn',k),    ph([M '/ShVSC'],'LConn',k),'autorouting','on');  % -> VSC AC
  end
  % DC bus
  add_line(M, ph([M '/ShVSC'],'RConn',1), ph([M '/Cdc'],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Cdc'],'RConn',1),   ph([M '/ShVSC'],'RConn',2),'autorouting','on');
  add_line(M, ph([M '/ShVSC'],'RConn',1), ph([M '/MeasVdc'],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/ShVSC'],'RConn',2), ph([M '/MeasVdc'],'LConn',2),'autorouting','on');
  add_line(M, ph([M '/ShVSC'],'RConn',1), ph([M '/Chop'],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Chop'],'RConn',1),  ph([M '/Rchop'],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Rchop'],'RConn',1), ph([M '/ShVSC'],'RConn',2),'autorouting','on');
  % signals: MeasSh has 2 outports? V-I measurement with V+I yes -> outports Vabc(1) and Iabc(2)
  add_line(M,'MeasSh/1','CTRL_sh/2','autorouting','on');   % Vsh_abc -> PLL
  add_line(M,'MeasSh/2','CTRL_sh/3','autorouting','on');   % Ish_abc -> current loop
  add_line(M,'MeasSh/2','Ish_abc/1','autorouting','on');
  add_line(M,'MeasVdc/1','CTRL_sh/4','autorouting','on');
  add_line(M,'MeasVdc/1','Vdc/1','autorouting','on');
  add_line(M,'Clock/1','CTRL_sh/1','autorouting','on');
  add_line(M,'Vdc_ref/1','CTRL_sh/5','autorouting','on');
  add_line(M,'iq_ref/1','CTRL_sh/6','autorouting','on');
  add_line(M,'t_fault/1','CTRL_sh/7','autorouting','on');
  add_line(M,'CTRL_sh/1','ShVSC/1','autorouting','on');   % g
  add_line(M,'CTRL_sh/2','Chop/1','autorouting','on');    % gchop
  add_line(M,'CTRL_sh/3','dq/1','autorouting','on');
end

if stage>=3
  Vse_w1=400; Vse_w2=46.2; Sse=30e3;   % Tse: 400V(VSC) : 46.2V(series), ~30kVA/phase
  % --- 3 single-phase series-injection transformers Tse_1/2/3 ---
  for k=1:3
    blk=[M sprintf('/Tse_%d',k)];
    add_block('powerlib/Elements/Linear Transformer',blk,'Position',pos(380,620+(k-1)*70,70,55));
    set_param(blk,'ThreeWindings','off','NominalPower',['[' num2str(Sse) ',' num2str(f0) ']'], ...
        'winding1',['[' num2str(Vse_w1) ',0.002,0.03]'], ...
        'winding2',['[' num2str(Vse_w2) ',0.002,0.03]']);
  end
  % --- series VSC (3-phase 2-level bridge, shares DC bus) ---
  add_block('powerlib/Power Electronics/Universal Bridge',[M '/SeVSC'],'Position',pos(200,620,70,110));
  set_param([M '/SeVSC'],'Arms','3','Device','IGBT / Diodes');
  % --- series controller (open-loop voltage injection at LV angle) ---
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRL_se'],'Position',pos(60,760,160,110));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRL_se']); ch.Script=ctrl_series_code();
  add_block('simulink/Sources/Constant',[M '/mse_d'],'Position',pos(60,900,50,24),'Value','0');
  add_block('simulink/Sources/Constant',[M '/mse_q'],'Position',pos(60,940,50,24),'Value','0');

  % insert Tse winding2 in series in the LV line (break Main_Tx -> MeasLV)
  for k=1:3
    delete_line(M, ph([M '/Main_Tx'],'RConn',k), ph([M '/MeasLV'],'LConn',k));
    add_line(M, ph([M '/Main_Tx'],'RConn',k), ph([M sprintf('/Tse_%d',k)],'RConn',1),'autorouting','on'); % w2 term1
    add_line(M, ph([M sprintf('/Tse_%d',k)],'RConn',2), ph([M '/MeasLV'],'LConn',k),'autorouting','on');  % w2 term2 -> LV
  end
  % series VSC AC -> Tse primaries (winding1 term1); primaries' term2 commoned (floating star)
  for k=1:3
    add_line(M, ph([M '/SeVSC'],'LConn',k), ph([M sprintf('/Tse_%d',k)],'LConn',1),'autorouting','on');
  end
  add_line(M, ph([M '/Tse_1'],'LConn',2), ph([M '/Tse_2'],'LConn',2),'autorouting','on');
  add_line(M, ph([M '/Tse_2'],'LConn',2), ph([M '/Tse_3'],'LConn',2),'autorouting','on');
  % series VSC shares DC bus with shunt
  add_line(M, ph([M '/SeVSC'],'RConn',1), ph([M '/ShVSC'],'RConn',1),'autorouting','on');
  add_line(M, ph([M '/SeVSC'],'RConn',2), ph([M '/ShVSC'],'RConn',2),'autorouting','on');
  % signals
  add_line(M,'Clock/1','CTRL_se/1','autorouting','on');
  add_line(M,'MeasLV/1','CTRL_se/2','autorouting','on');   % Vlv for PLL
  add_line(M,'mse_d/1','CTRL_se/3','autorouting','on');
  add_line(M,'mse_q/1','CTRL_se/4','autorouting','on');
  add_line(M,'CTRL_se/1','SeVSC/1','autorouting','on');    % gates
end

if stage>=4
  % High-Level Controller: selects dq-traditional baseline vs SAC setpoints.
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/HLC'],'Position',pos(120,560,150,90));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/HLC']); ch.Script=hlc_code();
  add_block('simulink/Sources/Constant',[M '/mode'],'Position',pos(60,520,40,24),'Value','4');
  add_block('simulink/Sources/Constant',[M '/fclass'],'Position',pos(60,470,40,24),'Value','0');  % fault class 0..5 (closed-loop obs)
  add_block('simulink/Sources/Constant',[M '/fdur'],'Position',pos(60,420,40,24),'Value','0.15'); % fault duration (closed-loop obs)
  % repurpose existing constants as SAC setpoints feeding HLC; rewire HLC outputs to controllers
  delete_line(M,'iq_ref/1','CTRL_sh/6');
  delete_line(M,'mse_d/1','CTRL_se/3');
  delete_line(M,'mse_q/1','CTRL_se/4');
  add_line(M,'mode/1','HLC/1','autorouting','on');
  add_line(M,'MeasLV/1','HLC/2','autorouting','on');     % Vlv (droop/PI + sequence extraction)
  add_line(M,'iq_ref/1','HLC/3','autorouting','on');     % sac_iq setpoint (mode 10)
  add_line(M,'mse_d/1','HLC/4','autorouting','on');      % sac_mse_d (mode 10)
  add_line(M,'mse_q/1','HLC/5','autorouting','on');      % sac_mse_q (mode 10)
  add_line(M,'MeasVdc/1','HLC/6','autorouting','on');    % Vdc (closed-loop obs)
  add_line(M,'Clock/1','HLC/7','autorouting','on');      % t
  add_line(M,'fclass/1','HLC/8','autorouting','on');     % fault class
  add_line(M,'t_fault/1','HLC/9','autorouting','on');    % t_fault
  add_line(M,'fdur/1','HLC/10','autorouting','on');      % fault duration
  add_line(M,'HLC/1','CTRL_sh/6','autorouting','on');    % -> iq_ref
  add_line(M,'HLC/2','CTRL_se/3','autorouting','on');    % -> mse_d
  add_line(M,'HLC/3','CTRL_se/4','autorouting','on');    % -> mse_q
  % Diagnostic only: log HLC outputs without feeding back into control.
  add_block('simulink/Signal Routing/Mux',[M '/HLC_cmd_mux'],'Position',pos(300,520,35,65),'Inputs','3');
  add_block('simulink/Sinks/To Workspace',[M '/HLC_cmd'],'Position',pos(360,530,85,35), ...
      'VariableName','HLC_cmd','SaveFormat','Timeseries');
  add_block('simulink/Sinks/To Workspace',[M '/HLC_obs'],'Position',pos(360,585,85,35), ...
      'VariableName','HLC_obs','SaveFormat','Timeseries');
  add_line(M,'HLC/1','HLC_cmd_mux/1','autorouting','on');
  add_line(M,'HLC/2','HLC_cmd_mux/2','autorouting','on');
  add_line(M,'HLC/3','HLC_cmd_mux/3','autorouting','on');
  add_line(M,'HLC_cmd_mux/1','HLC_cmd/1','autorouting','on');
  add_line(M,'HLC/4','HLC_obs/1','autorouting','on');
end

save_system(M);
fprintf('built %s (stage %d)\n', M, stage);
end

% ---- high-level controller: mode 4 dq-traditional / 10 SAC-setpoint / 11 SAC-CLOSED-LOOP ----
function s = hlc_code()
p = pu_params();   % subfunctions don't inherit the caller's workspace - re-read the single source
L = {
'% ===== INTERNAL HLC integer (mi) -> CANONICAL Mode (0-6) map (see CONTROL_MODES.md / controller_modes.m) ====='
'%   mi==7  -> Mode 1  Tuned fixed-law controller (strongest fixed law)'
'%   mi==8  -> Mode 2  One-step explicit MPC'
'%   mi==11 -> Mode 3  Unified SAC (single policy)'
'%   mi==12 -> Mode 5  Online-gated multi-expert SAC  ===== MAIN METHOD ====='
'%   mi==14 -> Mode 6  MPC-assisted residual SAC  (EXTENSION; NOT the main method, NOT pure SAC)'
'%   mi==20 -> Mode 6A residual SAC + HVRT recovery fallback gate (experiment)'
'%   mi==21..208 -> Mode 6A fallback/restoration sweeps for Simulink alignment only'
'%   mi==209..321 -> Mode 6B narrow weak-HVRT shallow-swell fallback probes (experiment)'
'%   mi==322 -> Mode 6C combined strong LVRT guard + weak-HVRT mi271 probe (experiment)'
'%   mi==323 -> Mode 6C plus strong-HVRT high clamp + single-HVRT Vdc gate (experiment)'
'%   mi==324 -> Mode 6C plus stronger strong-HVRT high clamp (experiment)'
'%   mi==325 -> Mode 6C plus HVRT sign projection and weak-grid Vdc floor (experiment)'
'%   mi==326 -> Mode 6C plus single-HVRT sign projection, preserving mi324 strong-HVRT clamp (experiment)'
'%   mi==327..328 -> Mode 6C plus stronger three-phase HVRT clamp sweep (experiment)'
'%   mi==329..330 -> Mode 6C plus in-fault three-phase HVRT clamp sweep (experiment)'
'%   mi==331..335 -> Mode 6C strong-HVRT action direction sweep (experiment)'
'%   mi==336..338 -> Mode 6C broad in-fault HVRT takeover sweep (experiment)'
'%   mi==339..342 -> Mode 6C strong-HVRT takeover threshold sweep (experiment)'
'%   mi==343 -> Mode 6C in-fault-only strong-HVRT takeover plus mi324 post-clear clamp (experiment)'
'%   mi==344..348 -> Mode 6C deep-LVRT action direction sweep (experiment)'
'%   mi==349..352 -> Mode 6C deep-LVRT iq balance sweep (experiment)'
'%   mi==353..355 -> Mode 6C deep-LVRT post-clear recovery boost sweep (experiment)'
'%   mi==356..357 -> Mode 6C deep-LVRT high post-clear recovery boost sweep (experiment)'
'%   mi==358 -> Mode 6C mi343 HVRT clamp + mi357 deep-LVRT recovery/survive boost (experiment)'
'%   mi==359..363 -> Mode 6C mi358 plus target-0.20 Vdc-survive reactive sweep (experiment)'
'%   mi==364..368 -> Mode 6C forced in-fault target-0.20 feasibility sweep (experiment)'
'%   mi==369..372 -> Mode 6C forced in-fault target-0.20 fine reactive/Vdc sweep (experiment)'
'%   mi==4 dq-legacy / mi==5 Song-style / mi==6 Jia-style / mi==13 SAC-MPC hybrid / mi==10 fixed-setpoint'
'%        = DEPRECATED historical (no canonical 0-6 id; must not appear in papers) - see CONTROL_MODES.md section 2.'
'% Internal integers and frt320_m{N}_* filenames kept UNCHANGED for reproducibility; canonical naming in CONTROL_MODES.md.'
'function [iq_ref, mse_d, mse_q, obs_log] = hlc(mode, Vlv, sac_iq, sac_msed, sac_mseq, Vdc, t, fclass, tf, fdur)'
'%#codegen'
['% build-nonce ' datestr(now,'yyyymmdd-HHMMSS-FFF') ': forces fresh codegen so coder.load re-reads weight .mat files']
'persistent ba bb bi la vpf vnf kstep ahold onset esign hvrt_seen hvrt_last'
'if isempty(ba); ba=zeros(250,1); bb=zeros(250,1); bi=1; la=zeros(3,1); vpf=1; vnf=0; kstep=int32(0); ahold=zeros(3,1); onset=-1; esign=0; hvrt_seen=0; hvrt_last=-1; end'
% frt-v2 current base (audit #3): action SCALE = I_action_peak (I_sys_peak); Imax kept = I_pe_rms only
% for the legacy dq variant branches below. Vnom for the alpha-beta magnitude.
sprintf('Imax=%.6g; Vnom=%.6g; Iact=%.6g;', p.I_pe_rms, p.VLN_peak, p.I_action_peak)
'iq_ref=0; mse_d=0; mse_q=0; obs_log=zeros(20,1);'
'Va=Vlv(1); Vb=Vlv(2); Vc=Vlv(3);'
'Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);'
'Vpu=sqrt(Valpha*Valpha+Vbeta*Vbeta)/Vnom;'
'mi=int32(mode);'
'weak_hvrt_en=0; weak_hvrt_mode=int32(0);'
'proj_en=0; guard_en=0; if mi==int32(16); proj_en=1; mi=int32(14); elseif mi==int32(18); proj_en=1; guard_en=1; mi=int32(14); elseif mi==int32(19); proj_en=1; guard_en=2; mi=int32(14); elseif mi>=int32(20) && mi<=int32(208); proj_en=1; guard_en=2; elseif mi>=int32(209) && mi<=int32(321); weak_hvrt_en=1; weak_hvrt_mode=mi; mi=int32(14); elseif mi==int32(322); proj_en=1; guard_en=3; weak_hvrt_en=1; weak_hvrt_mode=int32(271); mi=int32(14); elseif mi>=int32(323) && mi<=int32(372); proj_en=1; guard_en=3; weak_hvrt_en=1; weak_hvrt_mode=mi; mi=int32(14); end'   % mode 16 = reactive projection; mode 18/19 = guarded mode14 experiments; mode 20..208 = guarded fallback experiments; mode 209..321 = narrow HVRT probes on plain mode14; mode 322..372 = combined LVRT/HVRT probes
'if mi==11 || mi==12 || mi==13 || mi==14 || mi==15 || mi==17 || (mi>=20 && mi<=208)'
'    % ===== closed-loop SAC (11=single/Mode3, 12=online-gated 4-expert/Mode5, 15=ORACLE-gated/Mode4 ablation, 17=4-expert+residual hybrid), frt-v2 20-D obs / 3-D action / de-privileged online detector ====='
'    NB=250;'
'    Vad=ba(bi); Vbd=bb(bi); ba(bi)=Valpha; bb(bi)=Vbeta; bi=bi+1; if bi>NB; bi=1; end'
'    V1a=0.5*(Valpha-Vbd); V1b=0.5*(Vbeta+Vad);'
'    V2a=0.5*(Valpha+Vbd); V2b=0.5*(Vbeta-Vad);'
'    V2p=sqrt(V1a*V1a+V1b*V1b)/Vnom; V2n=sqrt(V2a*V2a+V2b*V2b)/Vnom;'
'    af=0.005; vpf=vpf+af*(V2p-vpf); vnf=vnf+af*(V2n-vnf); V2p=vpf; V2n=vnf;'   % match ODE TAU_V2 smoothing -> kill ripple-driven chatter
'    if V2p>1.06; hvrt_seen=1; hvrt_last=t; end'
'    recent_hvrt=0; if hvrt_seen>0.5 && hvrt_last>=0 && (t-hvrt_last)<=0.45 && abs(V2p-1)>0.025; recent_hvrt=1; end'
'    fc_label=fclass; fc=fclass;'
'    if mi==11 || mi==12 || mi==13 || mi==14 || mi==17 || (mi>=20 && mi<=208)'   % DE-PRIVILEGED online fault class from measured (V2p,V2n)
'        if recent_hvrt>0.5 || V2p>1.06; fc=5; elseif V2n>0.05; fc=2; else; fc=1; end'   % mi==15 = ORACLE keeps true fclass (ablation)
'    end'
'    piq=0; pmb=0;'   % mode-14 MPC prior (recomputed every 20us from filtered V2p + measured Vdc)
'    if V2p<0.9'
'        piq=1.5*(0.9-V2p); if piq>0.27; piq=0.27; end'
'        sgi=0.08*piq/max(0.3,V2p); fb=(Vdc/800-0.80)/0.04; if fb<0; fb=0; elseif fb>1; fb=1; end'
'        pmb=(0.18-sgi)/1.9; if pmb<0; pmb=0; elseif pmb>0.2; pmb=0.2; end; pmb=pmb*fb;'
'    elseif V2p>1.1'
'        piq=-1.5*(V2p-1.1); if piq<-0.27; piq=-0.27; end'
'        pmb=-1.5*(V2p-1.1); if pmb<-0.2; pmb=-0.2; end'
'    end'
'    if mi==13 && V2p>1.1'
'        % hybrid mode: HVRT domain -> analytic MPC law (mode-8 logic); LVRT -> SAC experts below'
'        iqp13=-1.5*(V2p-1.1); if iqp13<-0.27; iqp13=-0.27; end'
'        iq_ref=iqp13*Iact;'   % frt-v2 current base (audit #3)
'        mb13=1.5*(V2p-1.1); if mb13>0.2; mb13=0.2; end'
'        mse_d=mb13; mse_q=0;'
'    else'
'    kstep=kstep+int32(1); if kstep>int32(100); kstep=int32(1); end'   % decimate net update to 2ms (training DT); hold between
'    if kstep==int32(1)'
'    iqp=la(2); vdev=0.9-V2p;'
'    if V2p<0.9; idr=1.5*(0.9-V2p); if idr>0.3; idr=0.3; end; elseif V2p>1.06; idr=-1.5*(V2p-1.06); if idr<-0.3; idr=-0.3; end; else; idr=0; end'
'    iqerr=idr-iqp;'
'    % DE-PRIVILEGED online detector (audit #3): in_fault + elapsed from MEASURED (V2p,V2n) only,'
'    % NEVER the true tf/fdur (those input ports are now vestigial). Latches onset, resets on recovery.'
'    faulted = (V2p<0.9) || (V2p>1.06) || (V2n>0.05) || (recent_hvrt>0.5);'
'    if faulted; if onset<0; onset=t; end; if V2p>1.06 || recent_hvrt>0.5; esign=1; elseif V2p<0.9; esign=-1; end; else; onset=-1; if V2p>0.97 && V2p<1.03; esign=0; hvrt_seen=0; hvrt_last=-1; end; end'
'    infault=double(faulted); elapsed=0; if faulted; elapsed=max(0,t-onset); end'
'    probs=zeros(6,1);'
'    if infault>0.5; ci=round(fc)+1; if ci<1; ci=1; elseif ci>6; ci=6; end; probs(ci)=0.92; probs(1)=probs(1)+0.08; else; probs(1)=1; end'
'    tfrac=elapsed*0.2/0.5; if tfrac<0; tfrac=0; elseif tfrac>1; tfrac=1; end'   % elapsed since DETECTED onset; x0.2=TSCALE

'    obs=reshape([Vdc/800; V2p; V2n; abs(iqp); 0; 0; vdev; iqerr; iqp; probs; tfrac; infault; la(1); la(2); la(3)],20,1);'
'    obs_log=obs;'
'    if mi==11'
'        W=coder.load(''sac_actor_weights.mat'');'
'    elseif mi==14 || (mi>=20 && mi<=208)'
'        W=coder.load(''sac_residual_weights.mat'');'   % single residual policy (MPC prior handles domains)
'    elseif mi==15'   % Mode 4 ORACLE: pick expert by TRUE class fc(=fclass), bypassing V2p/V2n inference
'        oc=round(fc);'
'        if oc==6; W=coder.load(''sac_hvrt_asym_weights.mat'');'
'        elseif oc==5; W=coder.load(''sac_hvrt_sym_weights.mat'');'
'        elseif oc==2; W=coder.load(''sac_asym_weights.mat'');'
'        else; W=coder.load(''sac_sym_weights.mat''); end'
'    else'   % real-time gated 4-expert routing by (V2p, V2n)
'        if recent_hvrt>0.5 || V2p>1.06'
'            if V2n>0.05; W=coder.load(''sac_hvrt_asym_weights.mat''); else; W=coder.load(''sac_hvrt_sym_weights.mat''); end'
'        elseif V2n>0.05; W=coder.load(''sac_asym_weights.mat'');'
'        else; W=coder.load(''sac_sym_weights.mat''); end'
'    end'
'    W0=reshape(W.latent_pi_0_weight,256,20); b0=reshape(W.latent_pi_0_bias,256,1);'   % 20-D obs input
'    W2=reshape(W.latent_pi_2_weight,256,256); b2=reshape(W.latent_pi_2_bias,256,1);'
'    W4=reshape(W.latent_pi_4_weight,256,256); b4=reshape(W.latent_pi_4_bias,256,1);'
'    Wm=reshape(W.mu_weight,3,256); bm=reshape(W.mu_bias,3,1);'   % 3-output actor [iq, mse_d, mse_q]
'    alo=reshape(W.act_low,3,1); ahi=reshape(W.act_high,3,1);'
'    h=max(0, W0*obs + b0); h=max(0, W2*h + b2); h=max(0, W4*h + b4);'
'    mu=Wm*h + bm; at=tanh(mu); act=alo + 0.5*(at+1).*(ahi-alo);'
'    if mi==17'   % 4-expert+residual: act so far = gated EXPERT prior; add the residual net forward on the SAME obs
'        Wr=coder.load(''sac_resexpert_weights.mat'');'
'        r0=reshape(Wr.latent_pi_0_weight,256,20); rb0=reshape(Wr.latent_pi_0_bias,256,1);'
'        r2=reshape(Wr.latent_pi_2_weight,256,256); rb2=reshape(Wr.latent_pi_2_bias,256,1);'
'        r4=reshape(Wr.latent_pi_4_weight,256,256); rb4=reshape(Wr.latent_pi_4_bias,256,1);'
'        rm=reshape(Wr.mu_weight,3,256); rbm=reshape(Wr.mu_bias,3,1);'
'        rlo=reshape(Wr.act_low,3,1); rhi=reshape(Wr.act_high,3,1);'
'        hr=max(0, r0*obs + rb0); hr=max(0, r2*hr + rb2); hr=max(0, r4*hr + rb4);'
'        mur=rm*hr + rbm; atr=tanh(mur); actr=rlo + 0.5*(atr+1).*(rhi-rlo);'
'        act=act+actr;'   % total = gated expert prior + bounded residual (caps applied below)
'    end'
'    if (mi==12 || mi==13 || mi==14 || mi==15 || mi==17 || (mi>=20 && mi<=208)) && V2p>=0.97 && V2p<=1.03 && infault<0.5; act=zeros(3,1); end'   % normal: hold
'    la=act; ahold=act;'
'    else'
'    act=ahold;'
'    end'
'    if mi==14 || (mi>=20 && mi<=208)'
'        % residual mode: total = receding MPC prior + held residual, clipped to physical caps.'
'        % asym-aware iq cap (0.24): measured peak = cmd x k_2w; ODE cannot see ripple (m14-v1 lesson)'
'        cap14=0.27; if V2n>0.05 && V2p<0.9; cap14=0.24; end'
'        a1=piq+act(1); if a1>cap14; a1=cap14; elseif a1<-cap14; a1=-cap14; end'
'        if V2n>0.05 && V2p<1.10'   % asym LVRT feed-forward: avoid measured-iq wrong-sign under negative sequence
'            ff=1.2*0.70*V2n + 0.003; if a1<ff; a1=ff; end'
'            if a1>cap14; a1=cap14; end'
'        end'
'        a2=pmb+act(2); if a2>0.2; a2=0.2; elseif a2<-0.2; a2=-0.2; end'
'        a3=act(3); if a3>0.2; a3=0.2; elseif a3<-0.2; a3=-0.2; end'
'        if proj_en>0.5 && fc_label<5'   % deployment-side reactive sign-consistent dead-band (mirrors src/hpt_frt/device/safety_projection.py); iq in pu, V2p=V+
'            if V2p<0.9 && a1<-1e-3; a1=0; end'
'            if V2p>1.1 && a1>1e-3; a1=0; end'
'        end'
'        if guard_en>0.5 && fc_label<5'
'            vpu=Vdc/800;'
'            der=(vpu-0.78)/0.08; if der<0; der=0; elseif der>1; der=1; end'
'            if guard_en>1.5; der=(vpu-0.80)/0.08; if der<0; der=0; elseif der>1; der=1; end; end'
'            if guard_en>2.5; der=(vpu-0.82)/0.08; if der<0; der=0; elseif der>1; der=1; end; end'
'            if a2>0; a2=a2*der; end'   % LVRT boost drains the DC link; derate it as Vdc approaches the survive floor.
'            if vpu<0.755 && a2>0; a2=0; end'
'            if guard_en>2.5 && vpu<0.765 && a2>0; a2=0; end'
'            if V2p>=0.90 && V2p<=1.10'
'                if abs(a1)<0.02; a1=0; end'
'                if abs(a3)<0.03; a3=0; end'
'                if guard_en>2.5 && V2p>1.03'
'                    a1=0; ab=1.8*(V2p-1.03); if ab>0.12; ab=0.12; end; if a2>-ab; a2=-ab; end'
'                elseif guard_en>1.5 && V2p>1.03 && esign<=0'
'                    a1=0; if a2>0; a2=0; end'
'                elseif guard_en>1.5 && V2p>1.07'
'                    a1=0; ab=0.8*(V2p-1.07); if ab>0.05; ab=0.05; end; if a2>-ab; a2=-ab; end'
'                elseif V2p<0.93 && vpu>0.79'   % post-clear low-voltage recovery trim, bounded by the Vdc guard above.
'                    rb=0.6*(0.93-V2p); if rb>0.035; rb=0.035; end'
'                    if guard_en>1.5; rb=1.0*(0.93-V2p); if rb>0.08; rb=0.08; end; end'
'                    if a2<rb; a2=rb; end'
'                elseif abs(a2)<0.03'
'                    a2=0;'
'                end'
'            end'
'        end'
'        if mi>=20 && mi<=208'
'            vpu20=Vdc/800;'
'            fb_iq=0.27; fb_md=0.12; fb_mq=0.00; fb_vdc=0.75; fb_vhi=1.00; fb_vmin=0.82; fb_vmax=0.97; fb_postonly=0; fb_pdelay=0.002;'
'            if mi==21'
'                fb_md=0.16; fb_vdc=0.78;'
'            elseif mi==22'
'                fb_md=0.20; fb_vdc=0.82;'
'            elseif mi==23'
'                fb_iq=0.00; fb_md=0.16; fb_vdc=0.78;'
'            elseif mi==24'
'                fb_iq=0.12; fb_md=0.16; fb_vdc=0.78;'
'            elseif mi==25'
'                fb_iq=0.27; fb_md=0.08; fb_vdc=0.75;'
'            elseif mi==26'
'                fb_iq=-0.08; fb_md=0.16; fb_vdc=0.78;'
'            elseif mi==27'
'                fb_iq=0.00; fb_md=0.20; fb_vdc=0.82;'
'            elseif mi==28'
'                fb_iq=0.00; fb_md=-0.12; fb_vdc=0.75;'
'            elseif mi==29'
'                fb_iq=0.12; fb_md=0.16; fb_vdc=0.75; fb_vmin=0.75;'
'            elseif mi==30'
'                fb_iq=0.12; fb_md=0.18; fb_vdc=0.75; fb_vmin=0.75;'
'            elseif mi==31'
'                fb_iq=0.15; fb_md=0.18; fb_vdc=0.75; fb_vmin=0.75;'
'            elseif mi==32'
'                fb_iq=0.18; fb_md=0.18; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==33'
'                fb_iq=0.15; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==34'
'                fb_iq=0.12; fb_md=0.22; fb_vdc=0.80; fb_vmin=0.75;'
'            elseif mi==35'
'                fb_iq=0.20; fb_md=0.16; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==36'
'                fb_iq=0.10; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==37'
'                fb_iq=0.24; fb_md=0.16; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==38'
'                fb_iq=0.27; fb_md=0.16; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==39'
'                fb_iq=0.22; fb_md=0.18; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==40'
'                fb_iq=0.24; fb_md=0.18; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==41'
'                fb_iq=0.20; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==42'
'                fb_iq=0.25; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==43'
'                fb_iq=0.22; fb_md=0.14; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==44'
'                fb_iq=0.27; fb_md=0.14; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==45'
'                fb_iq=0.27; fb_md=0.25; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==46'
'                fb_iq=0.27; fb_md=0.30; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==47'
'                fb_iq=0.27; fb_md=0.40; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==48'
'                fb_iq=0.20; fb_md=0.30; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==49'
'                fb_iq=0.15; fb_md=0.30; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==50'
'                fb_iq=0.27; fb_md=0.25; fb_vdc=0.75; fb_vmin=0.75;'
'            elseif mi==51'
'                fb_iq=0.00; fb_md=0.30; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==52'
'                fb_iq=0.30; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75;'
'            elseif mi==53'
'                fb_iq=0.20; fb_md=0.16; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==54'
'                fb_iq=0.25; fb_md=0.20; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==55'
'                fb_iq=0.27; fb_md=0.30; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==56'
'                fb_iq=0.12; fb_md=0.16; fb_vdc=0.75; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==57'
'                fb_iq=0.20; fb_md=0.16; fb_vdc=0.75; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==58'
'                fb_iq=0.27; fb_md=0.40; fb_vdc=0.75; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==59'
'                fb_iq=0.25; fb_md=0.20; fb_mq=0.10; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==60'
'                fb_iq=0.25; fb_md=0.20; fb_mq=-0.10; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==61'
'                fb_iq=0.27; fb_md=0.30; fb_mq=0.10; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==62'
'                fb_iq=0.27; fb_md=0.30; fb_mq=-0.10; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==63'
'                fb_iq=0.20; fb_md=0.16; fb_mq=0.20; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==64'
'                fb_iq=0.20; fb_md=0.16; fb_mq=-0.20; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==65'
'                fb_iq=0.20; fb_md=0.16; fb_mq=0.30; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==66'
'                fb_iq=0.20; fb_md=0.16; fb_mq=0.40; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==67'
'                fb_iq=0.20; fb_md=0.16; fb_mq=0.50; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==68'
'                fb_iq=0.25; fb_md=0.20; fb_mq=0.30; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==69'
'                fb_iq=0.27; fb_md=0.30; fb_mq=0.30; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi==70'
'                fb_iq=0.30; fb_md=0.20; fb_mq=0.30; fb_vdc=0.78; fb_vmin=0.75; fb_vmax=1.05;'
'            elseif mi>=71 && mi<=80'
'                er=1.0-V2p; if er<0; er=0; end'
'                fb_vdc=0.78; fb_vmin=0.72; fb_vmax=1.08;'
'                fb_iq=2.2*er; if fb_iq>0.27; fb_iq=0.27; end'
'                fb_md=0.12+0.9*er; if fb_md>0.30; fb_md=0.30; end'
'                fb_mq=0.15+0.7*er; if fb_mq>0.30; fb_mq=0.30; end'
'                if mi==72; fb_iq=0.27; fb_md=0.16+1.2*er; if fb_md>0.40; fb_md=0.40; end; fb_mq=0.20; end'
'                if mi==73; fb_iq=0.20+0.8*er; if fb_iq>0.27; fb_iq=0.27; end; fb_md=0.10+0.6*er; if fb_md>0.22; fb_md=0.22; end; fb_mq=0.25; end'
'                if mi==74; fb_iq=0.27; fb_md=0.00; fb_mq=0.25+0.5*er; if fb_mq>0.35; fb_mq=0.35; end; end'
'                if mi==75; fb_iq=0.00; fb_md=0.20+1.0*er; if fb_md>0.40; fb_md=0.40; end; fb_mq=0.25; end'
'                if mi==76; fb_iq=0.27; fb_md=-0.10; fb_mq=0.30; end'
'                if mi==77; fb_iq=-0.10; fb_md=0.30; fb_mq=0.30; end'
'                if mi==78; fb_iq=0.27; fb_md=0.30; fb_mq=-0.25; end'
'                if mi==79; fb_iq=0.27; fb_md=0.45; fb_mq=0.25; fb_vdc=0.75; end'
'                if mi==80; fb_iq=0.35; fb_md=0.20; fb_mq=0.30; fb_vdc=0.78; end'
'            elseif mi>=81 && mi<=88'
'                fb_vdc=0.72; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10;'
'                if mi==81; fb_iq=0.27; fb_md=0.30; fb_mq=0.30; end'
'                if mi==82; fb_iq=0.35; fb_md=0.30; fb_mq=0.30; end'
'                if mi==83; fb_iq=0.27; fb_md=0.45; fb_mq=0.45; end'
'                if mi==84; fb_iq=0.35; fb_md=0.45; fb_mq=0.45; end'
'                if mi==85; fb_iq=0.27; fb_md=0.60; fb_mq=0.60; end'
'                if mi==86; fb_iq=0.27; fb_md=0.30; fb_mq=0.60; end'
'                if mi==87; fb_iq=0.27; fb_md=0.60; fb_mq=0.30; end'
'                if mi==88; fb_iq=0.40; fb_md=0.45; fb_mq=0.30; end'
'            elseif mi>=89 && mi<=96'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==89; fb_iq=0.35; fb_md=0.45; fb_mq=0.45; end'
'                if mi==90; fb_iq=0.27; fb_md=0.45; fb_mq=0.45; end'
'                if mi==91; fb_iq=0.27; fb_md=0.60; fb_mq=0.60; end'
'                if mi==92; fb_iq=0.40; fb_md=0.45; fb_mq=0.30; end'
'                if mi==93; fb_iq=0.27; fb_md=0.60; fb_mq=0.30; end'
'                if mi==94; fb_iq=0.35; fb_md=0.60; fb_mq=0.45; end'
'                if mi==95; fb_iq=0.30; fb_md=0.50; fb_mq=0.50; end'
'                if mi==96; fb_iq=0.27; fb_md=0.45; fb_mq=0.60; end'
'            elseif mi>=97 && mi<=104'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==97; fb_iq=0.50; fb_md=0.30; fb_mq=0.30; end'
'                if mi==98; fb_iq=0.70; fb_md=0.30; fb_mq=0.30; end'
'                if mi==99; fb_iq=0.50; fb_md=0.20; fb_mq=0.40; end'
'                if mi==100; fb_iq=0.70; fb_md=0.20; fb_mq=0.40; end'
'                if mi==101; fb_iq=0.50; fb_md=0.10; fb_mq=0.50; end'
'                if mi==102; fb_iq=0.70; fb_md=0.10; fb_mq=0.50; end'
'                if mi==103; fb_iq=0.50; fb_md=0.00; fb_mq=0.60; end'
'                if mi==104; fb_iq=0.70; fb_md=0.00; fb_mq=0.60; end'
'            elseif mi>=105 && mi<=112'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==105; fb_iq=0.50; fb_md=0.18; fb_mq=0.45; end'
'                if mi==106; fb_iq=0.50; fb_md=0.16; fb_mq=0.50; end'
'                if mi==107; fb_iq=0.50; fb_md=0.14; fb_mq=0.55; end'
'                if mi==108; fb_iq=0.50; fb_md=0.22; fb_mq=0.45; end'
'                if mi==109; fb_iq=0.50; fb_md=0.24; fb_mq=0.45; end'
'                if mi==110; fb_iq=0.50; fb_md=0.20; fb_mq=0.45; end'
'                if mi==111; fb_iq=0.50; fb_md=0.20; fb_mq=0.50; end'
'                if mi==112; fb_iq=0.50; fb_md=0.18; fb_mq=0.50; end'
'            elseif mi>=113 && mi<=128'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==113; fb_iq=0.50; fb_md=0.26; fb_mq=0.35; end'
'                if mi==114; fb_iq=0.50; fb_md=0.26; fb_mq=0.40; end'
'                if mi==115; fb_iq=0.50; fb_md=0.26; fb_mq=0.45; end'
'                if mi==116; fb_iq=0.50; fb_md=0.26; fb_mq=0.50; end'
'                if mi==117; fb_iq=0.50; fb_md=0.28; fb_mq=0.35; end'
'                if mi==118; fb_iq=0.50; fb_md=0.28; fb_mq=0.40; end'
'                if mi==119; fb_iq=0.50; fb_md=0.28; fb_mq=0.45; end'
'                if mi==120; fb_iq=0.50; fb_md=0.28; fb_mq=0.50; end'
'                if mi==121; fb_iq=0.50; fb_md=0.30; fb_mq=0.35; end'
'                if mi==122; fb_iq=0.50; fb_md=0.30; fb_mq=0.40; end'
'                if mi==123; fb_iq=0.50; fb_md=0.30; fb_mq=0.45; end'
'                if mi==124; fb_iq=0.50; fb_md=0.30; fb_mq=0.50; end'
'                if mi==125; fb_iq=0.50; fb_md=0.32; fb_mq=0.35; end'
'                if mi==126; fb_iq=0.50; fb_md=0.32; fb_mq=0.40; end'
'                if mi==127; fb_iq=0.50; fb_md=0.32; fb_mq=0.45; end'
'                if mi==128; fb_iq=0.50; fb_md=0.32; fb_mq=0.50; end'
'            elseif mi>=129 && mi<=140'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==129; fb_iq=0.70; fb_md=0.24; fb_mq=0.45; end'
'                if mi==130; fb_iq=0.90; fb_md=0.24; fb_mq=0.45; end'
'                if mi==131; fb_iq=0.70; fb_md=0.26; fb_mq=0.45; end'
'                if mi==132; fb_iq=0.90; fb_md=0.26; fb_mq=0.45; end'
'                if mi==133; fb_iq=0.70; fb_md=0.28; fb_mq=0.50; end'
'                if mi==134; fb_iq=0.90; fb_md=0.28; fb_mq=0.50; end'
'                if mi==135; fb_iq=0.70; fb_md=0.30; fb_mq=0.50; end'
'                if mi==136; fb_iq=0.90; fb_md=0.30; fb_mq=0.50; end'
'                if mi==137; fb_iq=1.10; fb_md=0.24; fb_mq=0.45; end'
'                if mi==138; fb_iq=1.10; fb_md=0.26; fb_mq=0.45; end'
'                if mi==139; fb_iq=1.10; fb_md=0.28; fb_mq=0.50; end'
'                if mi==140; fb_iq=1.10; fb_md=0.30; fb_mq=0.50; end'
'            elseif mi>=141 && mi<=152'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==141; fb_iq=0.50; fb_md=0.24; fb_mq=0.55; end'
'                if mi==142; fb_iq=0.50; fb_md=0.24; fb_mq=0.60; end'
'                if mi==143; fb_iq=0.50; fb_md=0.26; fb_mq=0.55; end'
'                if mi==144; fb_iq=0.50; fb_md=0.26; fb_mq=0.60; end'
'                if mi==145; fb_iq=0.50; fb_md=0.28; fb_mq=0.55; end'
'                if mi==146; fb_iq=0.50; fb_md=0.28; fb_mq=0.60; end'
'                if mi==147; fb_iq=0.50; fb_md=0.30; fb_mq=0.55; end'
'                if mi==148; fb_iq=0.50; fb_md=0.30; fb_mq=0.60; end'
'                if mi==149; fb_iq=0.50; fb_md=0.32; fb_mq=0.55; end'
'                if mi==150; fb_iq=0.50; fb_md=0.32; fb_mq=0.60; end'
'                if mi==151; fb_iq=0.50; fb_md=0.28; fb_mq=0.65; end'
'                if mi==152; fb_iq=0.50; fb_md=0.30; fb_mq=0.65; end'
'            elseif mi>=153 && mi<=160'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                er=0.93-V2p; if er<0; er=0; end'
'                if mi==153; fb_iq=0.50; fb_md=0.28+0.8*er; if fb_md>0.36; fb_md=0.36; end; fb_mq=0.55+1.0*er; if fb_mq>0.70; fb_mq=0.70; end; end'
'                if mi==154; fb_iq=0.50; fb_md=0.30+0.8*er; if fb_md>0.38; fb_md=0.38; end; fb_mq=0.55+1.0*er; if fb_mq>0.70; fb_mq=0.70; end; end'
'                if mi==155; fb_iq=0.50; fb_md=0.28+1.2*er; if fb_md>0.38; fb_md=0.38; end; fb_mq=0.60+1.2*er; if fb_mq>0.75; fb_mq=0.75; end; end'
'                if mi==156; fb_iq=0.50; fb_md=0.30+1.2*er; if fb_md>0.40; fb_md=0.40; end; fb_mq=0.60+1.2*er; if fb_mq>0.75; fb_mq=0.75; end; end'
'                if mi==157; fb_iq=0.50; fb_md=0.32+0.8*er; if fb_md>0.40; fb_md=0.40; end; fb_mq=0.55+0.8*er; if fb_mq>0.70; fb_mq=0.70; end; end'
'                if mi==158; fb_iq=0.50; fb_md=0.28+1.6*er; if fb_md>0.42; fb_md=0.42; end; fb_mq=0.65+1.2*er; if fb_mq>0.78; fb_mq=0.78; end; end'
'                if mi==159; fb_iq=0.50; fb_md=0.30+1.6*er; if fb_md>0.42; fb_md=0.42; end; fb_mq=0.65+1.2*er; if fb_mq>0.78; fb_mq=0.78; end; end'
'                if mi==160; fb_iq=0.50; fb_md=0.32+1.2*er; if fb_md>0.42; fb_md=0.42; end; fb_mq=0.60+1.2*er; if fb_mq>0.78; fb_mq=0.78; end; end'
'            elseif mi>=161 && mi<=172'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1;'
'                if mi==161; fb_iq=0.50; fb_md=0.32; fb_mq=0.55; fb_pdelay=0.001; end'
'                if mi==162; fb_iq=0.50; fb_md=0.32; fb_mq=0.55; fb_pdelay=0.000; end'
'                if mi==163; fb_iq=0.50; fb_md=0.30; fb_mq=0.60; fb_pdelay=0.001; end'
'                if mi==164; fb_iq=0.50; fb_md=0.30; fb_mq=0.60; fb_pdelay=0.000; end'
'                if mi==165; fb_iq=0.50; fb_md=0.28; fb_mq=0.50; fb_pdelay=0.001; end'
'                if mi==166; fb_iq=0.50; fb_md=0.28; fb_mq=0.50; fb_pdelay=0.000; end'
'                if mi==167; fb_iq=0.50; fb_md=0.32; fb_mq=0.55; fb_vmax=1.15; fb_pdelay=0.001; end'
'                if mi==168; fb_iq=0.50; fb_md=0.32; fb_mq=0.55; fb_vmax=1.15; fb_pdelay=0.000; end'
'                if mi==169; fb_iq=0.50; fb_md=0.30; fb_mq=0.60; fb_vmax=1.15; fb_pdelay=0.001; end'
'                if mi==170; fb_iq=0.50; fb_md=0.30; fb_mq=0.60; fb_vmax=1.15; fb_pdelay=0.000; end'
'                if mi==171; fb_iq=0.50; fb_md=0.28; fb_mq=0.50; fb_vmax=1.15; fb_pdelay=0.001; end'
'                if mi==172; fb_iq=0.50; fb_md=0.28; fb_mq=0.50; fb_vmax=1.15; fb_pdelay=0.000; end'
'            elseif mi>=173 && mi<=184'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1; fb_pdelay=0.001;'
'                if mi==173; fb_iq=0.50; fb_md=0.34; fb_mq=0.55; end'
'                if mi==174; fb_iq=0.50; fb_md=0.34; fb_mq=0.60; end'
'                if mi==175; fb_iq=0.50; fb_md=0.34; fb_mq=0.65; end'
'                if mi==176; fb_iq=0.50; fb_md=0.36; fb_mq=0.55; end'
'                if mi==177; fb_iq=0.50; fb_md=0.36; fb_mq=0.60; end'
'                if mi==178; fb_iq=0.50; fb_md=0.36; fb_mq=0.65; end'
'                if mi==179; fb_iq=0.50; fb_md=0.38; fb_mq=0.55; end'
'                if mi==180; fb_iq=0.50; fb_md=0.38; fb_mq=0.60; end'
'                if mi==181; fb_iq=0.50; fb_md=0.38; fb_mq=0.65; end'
'                if mi==182; fb_iq=0.50; fb_md=0.40; fb_mq=0.55; end'
'                if mi==183; fb_iq=0.50; fb_md=0.40; fb_mq=0.60; end'
'                if mi==184; fb_iq=0.50; fb_md=0.42; fb_mq=0.60; end'
'            elseif mi>=185 && mi<=196'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1; fb_pdelay=0.001;'
'                if mi==185; fb_iq=0.50; fb_md=0.38; fb_mq=0.70; end'
'                if mi==186; fb_iq=0.50; fb_md=0.38; fb_mq=0.75; end'
'                if mi==187; fb_iq=0.50; fb_md=0.38; fb_mq=0.80; end'
'                if mi==188; fb_iq=0.50; fb_md=0.40; fb_mq=0.70; end'
'                if mi==189; fb_iq=0.50; fb_md=0.40; fb_mq=0.75; end'
'                if mi==190; fb_iq=0.50; fb_md=0.40; fb_mq=0.80; end'
'                if mi==191; fb_iq=0.50; fb_md=0.42; fb_mq=0.70; end'
'                if mi==192; fb_iq=0.50; fb_md=0.42; fb_mq=0.75; end'
'                if mi==193; fb_iq=0.50; fb_md=0.42; fb_mq=0.80; end'
'                if mi==194; fb_iq=0.50; fb_md=0.44; fb_mq=0.75; end'
'                if mi==195; fb_iq=0.50; fb_md=0.44; fb_mq=0.80; end'
'                if mi==196; fb_iq=0.50; fb_md=0.46; fb_mq=0.80; end'
'            elseif mi>=197 && mi<=208'
'                fb_vdc=0.70; fb_vhi=1.25; fb_vmin=0.70; fb_vmax=1.10; fb_postonly=1; fb_pdelay=0.001;'
'                if mi==197; fb_iq=0.50; fb_md=0.48; fb_mq=0.80; end'
'                if mi==198; fb_iq=0.50; fb_md=0.50; fb_mq=0.80; end'
'                if mi==199; fb_iq=0.50; fb_md=0.52; fb_mq=0.80; end'
'                if mi==200; fb_iq=0.50; fb_md=0.54; fb_mq=0.80; end'
'                if mi==201; fb_iq=0.50; fb_md=0.48; fb_mq=0.90; end'
'                if mi==202; fb_iq=0.50; fb_md=0.50; fb_mq=0.90; end'
'                if mi==203; fb_iq=0.50; fb_md=0.52; fb_mq=0.90; end'
'                if mi==204; fb_iq=0.50; fb_md=0.54; fb_mq=0.90; end'
'                if mi==205; fb_iq=0.50; fb_md=0.56; fb_mq=0.90; end'
'                if mi==206; fb_iq=0.50; fb_md=0.58; fb_mq=0.90; end'
'                if mi==207; fb_iq=0.50; fb_md=0.60; fb_mq=1.00; end'
'                if mi==208; fb_iq=0.50; fb_md=0.65; fb_mq=1.00; end'
'            end'
'            postok=1; if fb_postonly>0.5 && t<=tf+fdur+fb_pdelay; postok=0; end'
'            if postok>0.5 && fc_label>=5 && V2n<=0.025 && V2p>=fb_vmin && V2p<fb_vmax && vpu20>=fb_vdc && vpu20<=fb_vhi'
'                a1=fb_iq; a2=fb_md; a3=fb_mq;'
'            end'
'        end'
'        if weak_hvrt_en>0.5'
'            vpu209=Vdc/800;'
'            wh_iq=0.50; wh_md=0.38; wh_mq=0.65; wh_delay=0.001; wh_vmin=0.70; wh_vmax=0.98; wh_vdc=0.74;'
'            if weak_hvrt_mode==int32(210); wh_md=0.40; wh_mq=0.65; end'
'            if weak_hvrt_mode==int32(211); wh_md=0.42; wh_mq=0.65; end'
'            if weak_hvrt_mode==int32(212); wh_md=0.44; wh_mq=0.65; end'
'            if weak_hvrt_mode==int32(213); wh_md=0.38; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(214); wh_md=0.40; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(215); wh_md=0.42; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(216); wh_md=0.44; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(217); wh_md=0.46; wh_mq=0.80; end'
'            if weak_hvrt_mode==int32(218); wh_md=0.50; wh_mq=0.90; end'
'            if weak_hvrt_mode==int32(219); wh_md=0.55; wh_mq=0.90; end'
'            if weak_hvrt_mode==int32(220); wh_md=0.60; wh_mq=1.00; end'
'            if weak_hvrt_mode==int32(221); wh_md=0.38; wh_mq=0.65; wh_delay=0.000; end'
'            if weak_hvrt_mode==int32(222); wh_md=0.42; wh_mq=0.75; wh_delay=0.000; end'
'            if weak_hvrt_mode==int32(223); wh_md=0.46; wh_mq=0.80; wh_delay=0.000; end'
'            if weak_hvrt_mode==int32(224); wh_md=0.50; wh_mq=0.90; wh_delay=0.000; end'
'            if weak_hvrt_mode>=int32(225); wh_md=0.40; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(241); wh_md=0.385; wh_mq=0.68; end'
'            if weak_hvrt_mode==int32(242); wh_md=0.385; wh_mq=0.72; end'
'            if weak_hvrt_mode==int32(243); wh_md=0.385; wh_mq=0.76; end'
'            if weak_hvrt_mode==int32(244); wh_md=0.385; wh_mq=0.80; end'
'            if weak_hvrt_mode==int32(245); wh_md=0.400; wh_mq=0.68; end'
'            if weak_hvrt_mode==int32(246); wh_md=0.400; wh_mq=0.72; end'
'            if weak_hvrt_mode==int32(247); wh_md=0.400; wh_mq=0.76; end'
'            if weak_hvrt_mode==int32(248); wh_md=0.400; wh_mq=0.80; end'
'            if weak_hvrt_mode==int32(249); wh_md=0.415; wh_mq=0.68; end'
'            if weak_hvrt_mode==int32(250); wh_md=0.415; wh_mq=0.72; end'
'            if weak_hvrt_mode==int32(251); wh_md=0.415; wh_mq=0.76; end'
'            if weak_hvrt_mode==int32(252); wh_md=0.415; wh_mq=0.80; end'
'            if weak_hvrt_mode==int32(253); wh_md=0.430; wh_mq=0.68; end'
'            if weak_hvrt_mode==int32(254); wh_md=0.430; wh_mq=0.72; end'
'            if weak_hvrt_mode==int32(255); wh_md=0.430; wh_mq=0.76; end'
'            if weak_hvrt_mode==int32(256); wh_md=0.430; wh_mq=0.80; end'
'            if weak_hvrt_mode==int32(257); wh_iq=0.00; wh_md=0.400; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(258); wh_iq=0.27; wh_md=0.400; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(259); wh_iq=-0.10; wh_md=0.400; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(260); wh_iq=0.80; wh_md=0.400; wh_mq=0.75; end'
'            if weak_hvrt_mode==int32(261); wh_md=0.392; wh_mq=0.744; end'
'            if weak_hvrt_mode==int32(262); wh_md=0.392; wh_mq=0.752; end'
'            if weak_hvrt_mode==int32(263); wh_md=0.392; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(264); wh_md=0.392; wh_mq=0.768; end'
'            if weak_hvrt_mode==int32(265); wh_md=0.396; wh_mq=0.744; end'
'            if weak_hvrt_mode==int32(266); wh_md=0.396; wh_mq=0.752; end'
'            if weak_hvrt_mode==int32(267); wh_md=0.396; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(268); wh_md=0.396; wh_mq=0.768; end'
'            if weak_hvrt_mode==int32(269); wh_md=0.400; wh_mq=0.744; end'
'            if weak_hvrt_mode==int32(270); wh_md=0.400; wh_mq=0.752; end'
'            if weak_hvrt_mode==int32(271); wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(272); wh_md=0.400; wh_mq=0.768; end'
'            if weak_hvrt_mode==int32(273); wh_md=0.404; wh_mq=0.744; end'
'            if weak_hvrt_mode==int32(274); wh_md=0.404; wh_mq=0.752; end'
'            if weak_hvrt_mode==int32(275); wh_md=0.404; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(276); wh_md=0.404; wh_mq=0.768; end'
'            if weak_hvrt_mode==int32(277); wh_md=0.408; wh_mq=0.744; end'
'            if weak_hvrt_mode==int32(278); wh_md=0.408; wh_mq=0.752; end'
'            if weak_hvrt_mode==int32(279); wh_md=0.408; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(280); wh_md=0.408; wh_mq=0.768; end'
'            if weak_hvrt_mode==int32(281); wh_iq=0.44; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(282); wh_iq=0.48; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(283); wh_iq=0.52; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(284); wh_iq=0.56; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(285); wh_iq=0.60; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(286); wh_iq=0.64; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(287); wh_iq=0.68; wh_md=0.400; wh_mq=0.760; end'
'            if weak_hvrt_mode==int32(288); wh_md=0.400; wh_mq=0.760; wh_vmax=1.01; end'
'            if weak_hvrt_mode==int32(289); wh_md=0.400; wh_mq=0.760; wh_vdc=0.70; end'
'            if weak_hvrt_mode==int32(290); wh_md=0.400; wh_mq=0.760; wh_delay=0.000; end'
'            if weak_hvrt_mode==int32(291); wh_md=0.400; wh_mq=0.760; wh_vdc=0.80; end'
'            if weak_hvrt_mode==int32(292); wh_md=0.396; wh_mq=0.760; wh_vmax=1.01; end'
'            if weak_hvrt_mode==int32(321); wh_iq=0.30; wh_md=0.118; wh_mq=0.00; wh_delay=0.000; wh_vmin=0.90; wh_vmax=0.965; wh_vdc=0.75; end'
'            if weak_hvrt_mode>=int32(323) && weak_hvrt_mode<=int32(372); wh_md=0.400; wh_mq=0.760; end'
'            if fc_label==5 && t>tf+fdur+wh_delay && V2n<=0.025 && V2p>=wh_vmin && V2p<wh_vmax && vpu209>=wh_vdc && vpu209<=1.25'
'                a1=wh_iq; a2=wh_md; a3=wh_mq;'
'            end'
'            if weak_hvrt_mode==int32(323) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.07 && vpu209>0.85'
'                a1=0; ab=1.8*(V2p-1.03); if ab>0.12; ab=0.12; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(324) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.85'
'                a1=0; ab=2.4*(V2p-1.02); if ab>0.16; ab=0.16; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(326) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.85'
'                a1=0; ab=2.4*(V2p-1.02); if ab>0.16; ab=0.16; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(327) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.82'
'                a1=0; ab=3.2*(V2p-1.015); if ab>0.22; ab=0.22; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(328) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.80'
'                a1=0; ab=4.0*(V2p-1.010); if ab>0.28; ab=0.28; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(329) && fc_label==5 && V2n<=0.025 && V2p>1.25 && vpu209>0.76'
'                a1=0; ab=2.4*(V2p-1.02); if ab>0.16; ab=0.16; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(330) && fc_label==5 && V2n<=0.025 && V2p>1.25 && vpu209>0.76'
'                a1=0; ab=3.2*(V2p-1.015); if ab>0.22; ab=0.22; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(331) && fc_label==5 && V2n<=0.025 && V2p>1.25'
'                a1=0; a2=0.20; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(332) && fc_label==5 && V2n<=0.025 && V2p>1.25'
'                a1=-0.10; a2=0.20; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(333) && fc_label==5 && V2n<=0.025 && V2p>1.25'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(334) && fc_label==5 && V2n<=0.025 && V2p>1.25'
'                a1=0; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(335) && fc_label==5 && V2n<=0.025 && V2p>1.25'
'                a1=0; a2=-0.40; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(336) && fc_label==5 && V2n<=0.025 && V2p>1.10'
'                a1=0; a2=-0.16; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(337) && fc_label==5 && V2n<=0.025 && V2p>1.10'
'                a1=0; a2=0.20; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(338) && fc_label==5 && V2n<=0.025 && V2p>1.10'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(339) && fc_label==5 && V2n<=0.025 && V2p>1.14'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(340) && fc_label==5 && V2n<=0.025 && V2p>1.18'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(341) && fc_label==5 && V2n<=0.025 && V2p>1.22'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(342) && fc_label==5 && V2n<=0.025 && V2p>1.24'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if (weak_hvrt_mode==int32(343) || (weak_hvrt_mode>=int32(358) && weak_hvrt_mode<=int32(372))) && fc_label==5 && V2n<=0.025 && V2p>1.14 && t<=tf+fdur+0.005'
'                a1=-0.20; a2=0; a3=0;'
'            end'
'            if (weak_hvrt_mode==int32(343) || (weak_hvrt_mode>=int32(358) && weak_hvrt_mode<=int32(372))) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.85'
'                a1=0; ab=2.4*(V2p-1.02); if ab>0.16; ab=0.16; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(325) && fc_label==5 && t>tf+fdur && V2n<=0.025 && V2p>1.065 && vpu209>0.78'
'                a1=-0.06; ab=1.4*(V2p-1.04); if ab>0.10; ab=0.10; end; a2=-ab; a3=0;'
'            end'
'            if weak_hvrt_mode==int32(325) && fc_label==5 && V2n<=0.025 && V2p>1.18 && vpu209<0.80'
'                if a2<0; a2=0; end; if a1>0; a1=0; end'
'            end'
'            if weak_hvrt_mode==int32(325) && fc_label>=5 && V2p>1.06 && a1>0'
'                a1=-0.04;'
'            end'
'            if ((weak_hvrt_mode>=int32(326) && weak_hvrt_mode<=int32(343)) || (weak_hvrt_mode>=int32(358) && weak_hvrt_mode<=int32(372))) && fc_label==6 && V2p>1.06 && a1>0'
'                a1=-0.04;'
'            end'
'            sp_iq=0.00; sp_md=0.16; sp_mq=0.00; sp_delay=0.001; sp_vdc=0.74;'
'            if weak_hvrt_mode==int32(226); sp_md=0.12; sp_mq=0.00; end'
'            if weak_hvrt_mode==int32(227); sp_md=0.20; sp_mq=0.00; end'
'            if weak_hvrt_mode==int32(228); sp_md=0.16; sp_mq=0.10; end'
'            if weak_hvrt_mode==int32(229); sp_md=0.16; sp_mq=0.20; end'
'            if weak_hvrt_mode==int32(230); sp_md=0.20; sp_mq=0.20; end'
'            if weak_hvrt_mode==int32(231); sp_md=0.16; sp_mq=0.00; sp_delay=0.000; end'
'            if weak_hvrt_mode==int32(232); sp_md=0.20; sp_mq=0.20; sp_delay=0.000; end'
'            if weak_hvrt_mode==int32(233); sp_md=0.12; sp_mq=0.00; sp_vdc=0.78; end'
'            if weak_hvrt_mode==int32(234); sp_md=0.16; sp_mq=0.00; sp_vdc=0.78; end'
'            if weak_hvrt_mode==int32(235); sp_md=0.20; sp_mq=0.00; sp_vdc=0.78; end'
'            if weak_hvrt_mode==int32(236); sp_md=0.16; sp_mq=0.10; sp_vdc=0.78; end'
'            if weak_hvrt_mode==int32(237); sp_md=0.20; sp_mq=0.20; sp_vdc=0.78; end'
'            if weak_hvrt_mode==int32(238); sp_md=0.12; sp_mq=0.00; sp_vdc=0.80; end'
'            if weak_hvrt_mode==int32(239); sp_md=0.16; sp_mq=0.00; sp_vdc=0.80; end'
'            if weak_hvrt_mode==int32(240); sp_md=0.20; sp_mq=0.20; sp_vdc=0.80; end'
'            if weak_hvrt_mode>=int32(323) && weak_hvrt_mode<=int32(372); sp_md=0.20; sp_mq=0.20; sp_vdc=0.80; end'
'            if weak_hvrt_mode>=int32(225) && fc_label==6 && t>tf+fdur+sp_delay && V2p>=0.70 && V2p<0.98 && vpu209>=sp_vdc && vpu209<=1.25'
'                a1=sp_iq; a2=sp_md; a3=sp_mq;'
'            end'
'        end'
'        if weak_hvrt_mode>=int32(344) && weak_hvrt_mode<=int32(358) && fc_label<5 && V2p<0.20'
'            if weak_hvrt_mode==int32(344); a1=0.15; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(345); a1=0.05; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(346); a1=0; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(347); a1=0.15; a2=-0.20; a3=0; end'
'            if weak_hvrt_mode==int32(348); a1=0.15; a2=0.20; a3=0; end'
'            if weak_hvrt_mode==int32(349); a1=0.20; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(350); a1=0.25; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(351); a1=0.30; a2=0; a3=0; end'
'            if weak_hvrt_mode==int32(352); a1=0.35; a2=0; a3=0; end'
'            if weak_hvrt_mode>=int32(353) && weak_hvrt_mode<=int32(358); a1=0.20; a2=0; a3=0; end'
'        end'
'        if weak_hvrt_mode>=int32(353) && weak_hvrt_mode<=int32(358) && fc_label<5 && t>tf+fdur && V2p<0.93 && Vdc/800>0.76'
'            if weak_hvrt_mode==int32(353); a1=0.20; a2=0.30; a3=0; end'
'            if weak_hvrt_mode==int32(354); a1=0.20; a2=0.50; a3=0; end'
'            if weak_hvrt_mode==int32(355); a1=0; a2=0.50; a3=0; end'
'            if weak_hvrt_mode==int32(356); a1=0.20; a2=0.80; a3=0; end'
'            if weak_hvrt_mode==int32(357) || weak_hvrt_mode==int32(358); a1=0.20; a2=1.00; a3=0; end'
'        end'
'        if weak_hvrt_mode>=int32(359) && weak_hvrt_mode<=int32(363) && fc_label<5'
'            if V2p<0.16'
'                a1=0.20; a2=0; a3=0;'
'            elseif V2p<0.30'
'                if weak_hvrt_mode==int32(359); a1=0.00; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(360); a1=0.06; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(361); a1=0.10; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(362); a1=0.14; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(363); a1=0.18; a2=0; a3=0; end'
'            end'
'        end'
'        if weak_hvrt_mode>=int32(359) && weak_hvrt_mode<=int32(363) && fc_label<5 && t>tf+fdur && V2p<0.16 && Vdc/800>0.76'
'            a1=0.20; a2=1.00; a3=0;'
'        end'
'        if ((weak_hvrt_mode>=int32(364) && weak_hvrt_mode<=int32(368)) || (weak_hvrt_mode>=int32(369) && weak_hvrt_mode<=int32(372))) && fc_label<5 && t>=tf && t<=tf+fdur+0.02 && V2p<0.45'
'            if V2p<0.12'
'                a1=0.20; a2=0; a3=0;'
'            else'
'                if weak_hvrt_mode==int32(364); a1=0.00; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(365); a1=0.08; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(366); a1=0.16; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(367); a1=0.24; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(368); a1=0.30; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(369); a1=0.18; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(370); a1=0.20; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(371); a1=0.22; a2=0; a3=0; end'
'                if weak_hvrt_mode==int32(372); a1=0.23; a2=0; a3=0; end'
'            end'
'        end'
'        if ((weak_hvrt_mode>=int32(364) && weak_hvrt_mode<=int32(368)) || (weak_hvrt_mode>=int32(369) && weak_hvrt_mode<=int32(372))) && fc_label<5 && t>tf+fdur && V2p<0.12 && Vdc/800>0.76'
'            a1=0.20; a2=1.00; a3=0;'
'        end'
'        iq_ref=a1*Iact; mse_d=-a2; mse_q=-a3;'   % current base = I_action_peak (audit #3)
'    elseif mi==17'
'        % 4-expert+residual hybrid: act = gated expert prior + residual (summed above). Apply the SAME'
'        % physical caps as mode-14 + the wrong-sign reactive dead-band (ALWAYS on = safety_projection Part-1).'
'        cap17=0.27; if V2n>0.05 && V2p<0.9; cap17=0.24; end'   % asym-aware iq cap (m14-v1 lesson)
'        a1=act(1); if a1>cap17; a1=cap17; elseif a1<-cap17; a1=-cap17; end'
'        a2=act(2); if a2>0.2; a2=0.2; elseif a2<-0.2; a2=-0.2; end'
'        a3=act(3); if a3>0.2; a3=0.2; elseif a3<-0.2; a3=-0.2; end'
'        if V2p<0.9 && a1<-1e-3; a1=0; end'   % under-voltage: iq must be >=0 (no absorbing)
'        if V2p>1.1 && a1>1e-3; a1=0; end'    % over-voltage:  iq must be <=0 (no sourcing)
'        iq_ref=a1*Iact; mse_d=-a2; mse_q=-a3;'
'    else'
'        iq_ref=act(1)*Iact; mse_d=-act(2); mse_q=-act(3);'   % [iq, mse_d, mse_q] x I_action_peak'
'    end'
'    end'   % end mi==13 HVRT/LVRT split
'elseif mi==10'
'    iq_ref=sac_iq; mse_d=-sac_msed; mse_q=-sac_mseq;'
'else'
'    % dq traditional variants. All share the GB/T reactive droop (K1=1.5, cap 0.3 pu):'
'    if Vpu<0.9; iqp=1.5*(0.9-Vpu); if iqp>0.3; iqp=0.3; end; iq_ref=iqp*Iact;'
'    elseif Vpu>1.1; iqp=-1.5*(Vpu-1.1); if iqp<-0.3; iqp=-0.3; end; iq_ref=iqp*Iact;'
'    else; iq_ref=0; end'
'    if mi==8'
'        % week3 decision-layer one-step MPC: constrained optimum on the CALIBRATED model, receding horizon @2ms.'
'        % max voltage support s.t. |iq|<=0.27, Vdc_eq>=0.82 (Vdc_eq = 1 - 0.08|iq|/max(0.3,V) - 1.9*boost), |mse|<=0.2.'
'        % Algebraic model => closed-form optimum: series boost used UP TO the DC-budget bound (vs mode5/7 zeroing).'
'        if iq_ref>0.27*Iact; iq_ref=0.27*Iact; elseif iq_ref<-0.27*Iact; iq_ref=-0.27*Iact; end'
'        iqpu=iq_ref/Iact;'
'        if Vpu<0.9'
'            sgi=0.08*abs(iqpu)/max(0.3,Vpu);'
'            mb=(1.0-0.82-sgi)/1.9; if mb<0; mb=0; elseif mb>0.2; mb=0.2; end'
'            fb=(Vdc/800-0.80)/0.04; if fb<0; fb=0; elseif fb>1; fb=1; end'   % measured-Vdc feedback (constraint enforcement)
'            mse_d=-mb*fb; mse_q=0;'
'        elseif Vpu>1.1'
'            mb=1.5*(Vpu-1.1); if mb>0.2; mb=0.2; end'
'            mse_d=mb; mse_q=0;'   % anti-boost: reduces LV, negligible DC drain
'        else'
'            mse_d=0; mse_q=0;'
'        end'
'    elseif mi==7'
'        % Song-style + RL-backported iq headroom cap (0.27): strongest fixed-law baseline'
'        if iq_ref>0.27*Iact; iq_ref=0.27*Iact; elseif iq_ref<-0.27*Iact; iq_ref=-0.27*Iact; end'
'        mse_d=0; mse_q=0;'
'    elseif mi==5'
'        % Song-style (HPT w/o storage, lit. default): NO series action during FRT'
'        mse_d=0; mse_q=0;'
'    elseif mi==6'
'        % Jia-style DC-budget-aware: proportional series, linearly derated as Vdc sags'
'        md=-0.6*(1-Vpu); if md>0.2; md=0.2; elseif md<-0.2; md=-0.2; end'
'        der=(Vdc/800-0.78)/(0.95-0.78); if der<0; der=0; elseif der>1; der=1; end'
'        mse_d=md*der; mse_q=0;'
'    else'
'        % mode 4 (legacy baseline): fixed proportional series support'
'        md=-0.6*(1-Vpu); if md>0.2; md=0.2; elseif md<-0.2; md=-0.2; end'
'        mse_d=md; mse_q=0;'
'    end'
'end'
};
s = char(strjoin(L, char(10)));
end

% ---- series controller: PLL on LV + open-loop dq voltage injection ----
function s = ctrl_series_code()
L = {
'function g = ctrl(t, Vlv, mse_d, mse_q)'
'%#codegen'
'persistent th wint tprev'
'if isempty(th) || t<1e-9; th=0; wint=0; tprev=0; end'
'dt=t-tprev; if dt<0;dt=0;end; if dt>1e-3;dt=1e-3;end; tprev=t;'
'w0=2*pi*50;'
'Va=Vlv(1); Vb=Vlv(2); Vc=Vlv(3);'
'Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);'
'Vd= cos(th)*Valpha+sin(th)*Vbeta; Vq=-sin(th)*Valpha+cos(th)*Vbeta;'
'Vm=sqrt(Vd*Vd+Vq*Vq); if Vm<50;Vm=50;end'
'wint=wint+1500*(Vq/Vm)*dt; if wint>150;wint=150;elseif wint<-150;wint=-150;end'
'w=w0+90*(Vq/Vm)+wint; th=th+w*dt; th=mod(th,2*pi);'
'% map SAC m_se (pu of LV phase, +/-0.2) -> VSC modulation index (+/-1): K=5'
'md=5*mse_d; mq=5*mse_q;'
'ma=md*cos(th)-mq*sin(th); mb=md*cos(th-2*pi/3)-mq*sin(th-2*pi/3); mc=md*cos(th+2*pi/3)-mq*sin(th+2*pi/3);'
'if ma>1;ma=1;elseif ma<-1;ma=-1;end'
'if mb>1;mb=1;elseif mb<-1;mb=-1;end'
'if mc>1;mc=1;elseif mc<-1;mc=-1;end'
'fc=5000; carrier=2*abs(2*(fc*t-floor(fc*t+0.5)))-1;'
'ga=ma>=carrier; gb=mb>=carrier; gc=mc>=carrier;'
'g=double([ga;~ga;gb;~gb;gc;~gc]);'
};
s = char(strjoin(L, char(10)));
end

% ---- shunt controller: PLL + dq current loop + reactive priority + Vdc outer loop ----
% (ported & validated from build_frt_statcom.m)
function s = ctrl_shunt_code()
p = pu_params();   % subfunctions don't inherit the caller's workspace - re-read the single source
L = {
'function [g, gchop, dq] = ctrl(t, Vabc, Ish, Vdc, Vdc_ref, iq_ref, t_fault)'
'%#codegen'
'persistent th wint idi iqi vdi tprev en idr'
'if isempty(th) || t < 1e-9'
'    th=0; wint=0; idi=0; iqi=0; vdi=0; tprev=0; en=0; idr=0;'
'end'
'if Vdc > 620; en = 1; end'
'dt = t - tprev; if dt<0; dt=0; end; if dt>1e-3; dt=1e-3; end; tprev=t;'
sprintf('w0 = 2*pi*50; Lsh = 3e-3; Imax = %.6g;', p.I_pe_peak)   % audit#3: inner-loop envelope = PHYSICAL converter PEAK (244.95A), NOT I_pe_rms - the HLC commands on the peak/action base, so the rms base here throttled reactive 4.7x
'Va=Vabc(1); Vb=Vabc(2); Vc=Vabc(3);'
'Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);'
'Vd =  cos(th)*Valpha + sin(th)*Vbeta;'
'Vq = -sin(th)*Valpha + cos(th)*Vbeta;'
'Vm = sqrt(Vd*Vd+Vq*Vq); if Vm<100; Vm=100; end'
'err = Vq/Vm;'
'Kp_pll=90; Ki_pll=1500;'
'wint = wint + Ki_pll*err*dt; if wint>150; wint=150; elseif wint<-150; wint=-150; end'
'w = w0 + Kp_pll*err + wint; th = th + w*dt; th = mod(th,2*pi);'
'Ia=Ish(1); Ib=Ish(2); Ic=Ish(3);'
'Ialpha=(2/3)*(Ia-0.5*Ib-0.5*Ic); Ibeta=(2/3)*(sqrt(3)/2)*(Ib-Ic);'
'id =  cos(th)*Ialpha + sin(th)*Ibeta;'
'iq = -sin(th)*Ialpha + cos(th)*Ibeta;'
'Kpv=0.50; Kiv=8.0; ev=(Vdc_ref-Vdc)/Vdc_ref;'
'vdi = vdi + Kiv*ev*dt; if vdi>1; vdi=1; elseif vdi<-1; vdi=-1; end'
'idtgt=(Kpv*ev+vdi)*Imax; if idtgt>0.9*Imax; idtgt=0.9*Imax; elseif idtgt<-0.9*Imax; idtgt=-0.9*Imax; end'
'dmax=4000*dt; ds=idtgt-idr; if ds>dmax; ds=dmax; elseif ds<-dmax; ds=-dmax; end; idr=idr+ds;'
'iqr=iq_ref; if iqr>Imax; iqr=Imax; elseif iqr<-Imax; iqr=-Imax; end'   % clip reactive at converter PEAK (Imax=I_pe_peak); HLC already caps iq_ref at 0.3*I_action_peak=I_pe_peak
'idm=sqrt(max(0,Imax*Imax-iqr*iqr)); if idr<-idm; idr=-idm; elseif idr>idm; idr=idm; end'
'Kp=2.5; Ki=150; ed=idr-id; eq=iqr-iq;'
'ud = Vd-(Kp*ed+idi)+w0*Lsh*iq;'
'uq = Vq-(Kp*eq+iqi)-w0*Lsh*id;'
'half=max(50,Vdc/2); md=ud/half; mq=uq/half;'
'ma=md*cos(th)-mq*sin(th); mb=md*cos(th-2*pi/3)-mq*sin(th-2*pi/3); mc=md*cos(th+2*pi/3)-mq*sin(th+2*pi/3);'
'if ma>1; ma=1; elseif ma<-1; ma=-1; end'
'if mb>1; mb=1; elseif mb<-1; mb=-1; end'
'if mc>1; mc=1; elseif mc<-1; mc=-1; end'
'fc=5000; carrier=2*abs(2*(fc*t-floor(fc*t+0.5)))-1;'
'ga=ma>=carrier; gb=mb>=carrier; gc=mc>=carrier;'
'g=double([ga;~ga;gb;~gb;gc;~gc]);'
'if en<0.5; g=zeros(6,1); idi=0; iqi=0; vdi=0; end'
'sat=(abs(md)>1)||(abs(mq)>1);'
'if ~sat; idi=idi+Ki*ed*dt; iqi=iqi+Ki*eq*dt; if idi>300;idi=300;elseif idi<-300;idi=-300;end; if iqi>300;iqi=300;elseif iqi<-300;iqi=-300;end; end'
'gchop = double(Vdc > 1.20*800);'
'dq = [id; iq; idr; iqr; Vd; Vm; th];'
};
s = char(strjoin(L, char(10)));
end

function h = ph(blk, kind, idx)
    P = get_param(blk,'PortHandles'); h = P.(kind)(idx);
end
