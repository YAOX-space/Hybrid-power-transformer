function build_hpt_frt_full(stage, gridmode)
% build_hpt_frt_full.m  — reproducible, from-scratch FULL HPT switching model for
% standard grid FRT (GB/T), built up in stages and validated at each step.
%
%   stage 1 : MV weak grid + MV fault + main transformer (D-Yg) + LV load   (backbone)
%   stage 2 : + shunt 取能 VSC via Tsh + shared DC bus + conditional chopper + dq control
%   stage 3 : + series 调控 VSC via Tse (winding2 in series in LV line)
%   stage 4 : dual control mode  (Mode10 SAC 4-D action / Mode4 dq dual-loop PI)
%
% Real two voltage levels (10 kV MV / 400 V LV).  Specialized Power Systems.
% Reuses the debugged shunt control (PLL + dq current loop + reactive priority +
% Vdc outer loop + anti-windup) from build_frt_statcom.m.
if nargin<1, stage=1; end
if nargin<2, gridmode='fault'; end   % 'fault'=LVRT (3φ source + fault) ; 'swell'=HVRT (programmable source + series Z)
M='hpt_frt_full';
if bdIsLoaded(M), close_system(M,0); end
new_system(M); load_system(M);

% ---- parameters (mirror parameters.m) ----
f0=50; Ts=20e-6;
Vmv=10e3; Vlv=400; Srated=400e3;
% weak-grid default SCR=3 at 10 kV: Zbase=Vmv^2/Srated=250 ohm; |Z|=250/3=83.3, X/R=7
Zb=Vmv^2/Srated; scr=3; Zg=Zb/scr; Rg=Zg/sqrt(1+49); Lg=7*Rg/(2*pi*f0);

set_param(M,'Solver','ode23tb','StopTime','0.6');
pos=@(x,y,w,h)[x y x+w y+h];

add_block('powerlib/powergui',[M '/powergui'],'Position',pos(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

% ---- MV grid ----
if strcmp(gridmode,'swell')
    % HVRT: ideal Programmable Voltage Source (amplitude table → swell) + external series Z (weak grid)
    add_block('powerlib/Electrical Sources/Three-Phase Programmable Voltage Source',[M '/Grid'],'Position',pos(60,120,70,90));
    set_param([M '/Grid'],'PositiveSequence',['[' num2str(Vmv*1.125) ' 0 ' num2str(f0) ']'], ...
        'VariationEntity','None');   % amplitude table set per-scenario by the harness
    add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Zg'],'Position',pos(160,120,50,70));
    set_param([M '/Zg'],'BranchType','RL','Resistance',num2str(Rg),'Inductance',num2str(Lg));
else
    % LVRT: 3φ source with internal impedance; fault block creates the sag
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
      'VariableName',nm{1},'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
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
        'VariableName',nm{1},'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
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
end

save_system(M);
fprintf('built %s (stage %d)\n', M, stage);
end

% ---- high-level controller: mode 4 dq-traditional / 10 SAC-setpoint / 11 SAC-CLOSED-LOOP ----
function s = hlc_code()
L = {
'function [iq_ref, mse_d, mse_q] = hlc(mode, Vlv, sac_iq, sac_msed, sac_mseq, Vdc, t, fclass, tf, fdur)'
'%#codegen'
'persistent ba bb bi la'   % declared unconditionally at top (codegen requirement)
'if isempty(ba); ba=zeros(250,1); bb=zeros(250,1); bi=1; la=zeros(4,1); end'
'Imax=173.2; Vnom=326.6;'
'iq_ref=0; mse_d=0; mse_q=0;'   % default-init outputs (fixes size/type inference)
'Va=Vlv(1); Vb=Vlv(2); Vc=Vlv(3);'
'Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);'
'Vpu=sqrt(Valpha*Valpha+Vbeta*Vbeta)/Vnom;'
'if int32(mode)==11'
'    % ===== closed-loop SAC: reconstruct 21-D obs, run actor MLP, act each step ====='
'    NB=250;'  % T/4 delay buffer @20us = 5ms
'    W=coder.load(''sac_actor_weights.mat'');'   % compile-time constant

'    Vad=ba(bi); Vbd=bb(bi); ba(bi)=Valpha; bb(bi)=Vbeta; bi=bi+1; if bi>NB; bi=1; end'
'    V1a=0.5*(Valpha-Vbd); V1b=0.5*(Vbeta+Vad);'   % positive sequence (alpha-beta)
'    V2a=0.5*(Valpha+Vbd); V2b=0.5*(Vbeta-Vad);'   % negative sequence
'    V2p=sqrt(V1a*V1a+V1b*V1b)/Vnom; V2n=sqrt(V2a*V2a+V2b*V2b)/Vnom;'
'    iqp=la(2);'   % last applied reactive (pu) proxy for measured iq
'    vdev=0.9-V2p;'
'    if V2p<0.9; idr=1.5*(0.9-V2p); if idr>0.3; idr=0.3; end; elseif V2p>1.1; idr=-1.5*(V2p-1.1); if idr<-0.3; idr=-0.3; end; else; idr=0; end'
'    iqerr=idr-iqp;'
'    infault=double(t>=tf && t<=tf+fdur);'
'    probs=zeros(6,1);'
'    if infault>0.5; ci=round(fclass)+1; if ci<1; ci=1; elseif ci>6; ci=6; end; probs(ci)=0.92; probs(1)=probs(1)+0.08; else; probs(1)=1; end'
'    tfrac=(t-tf)/0.5; if tfrac<0; tfrac=0; elseif tfrac>1; tfrac=1; end'
'    obs=reshape([Vdc/800; V2p; V2n; abs(iqp); 0; 0; vdev; iqerr; iqp; probs; tfrac; infault; la(1); la(2); la(3); la(4)],21,1);'
'    W0=reshape(W.latent_pi_0_weight,256,21); b0=reshape(W.latent_pi_0_bias,256,1);'
'    W2=reshape(W.latent_pi_2_weight,256,256); b2=reshape(W.latent_pi_2_bias,256,1);'
'    W4=reshape(W.latent_pi_4_weight,256,256); b4=reshape(W.latent_pi_4_bias,256,1);'
'    Wm=reshape(W.mu_weight,4,256); bm=reshape(W.mu_bias,4,1);'
'    alo=reshape(W.act_low,4,1); ahi=reshape(W.act_high,4,1);'
'    h=max(0, W0*obs + b0); h=max(0, W2*h + b2); h=max(0, W4*h + b4);'
'    mu=Wm*h + bm; at=tanh(mu); act=alo + 0.5*(at+1).*(ahi-alo);'
'    la=act;'   % store for next-step obs
'    iq_ref=act(2)*Imax; mse_d=-act(3); mse_q=-act(4);'   % series sign flip (ODE vs Simulink)
'elseif int32(mode)==10'
'    iq_ref=sac_iq; mse_d=-sac_msed; mse_q=-sac_mseq;'
'else'
'    % dq traditional: GB/T reactive droop + proportional series voltage support'
'    if Vpu<0.9; iqp=1.5*(0.9-Vpu); if iqp>0.3; iqp=0.3; end; iq_ref=iqp*Imax;'
'    elseif Vpu>1.1; iqp=-1.5*(Vpu-1.1); if iqp<-0.3; iqp=-0.3; end; iq_ref=iqp*Imax;'
'    else; iq_ref=0; end'
'    md=-0.6*(1-Vpu); if md>0.2; md=0.2; elseif md<-0.2; md=-0.2; end'
'    mse_d=md; mse_q=0;'
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
L = {
'function [g, gchop, dq] = ctrl(t, Vabc, Ish, Vdc, Vdc_ref, iq_ref, t_fault)'
'%#codegen'
'persistent th wint idi iqi vdi tprev en idr'
'if isempty(th) || t < 1e-9'
'    th=0; wint=0; idi=0; iqi=0; vdi=0; tprev=0; en=0; idr=0;'
'end'
'if Vdc > 620; en = 1; end'
'dt = t - tprev; if dt<0; dt=0; end; if dt>1e-3; dt=1e-3; end; tprev=t;'
'w0 = 2*pi*50; Lsh = 3e-3; Imax = 173.2;'
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
'iqr=iq_ref; if iqr>0.3*Imax; iqr=0.3*Imax; elseif iqr<-0.3*Imax; iqr=-0.3*Imax; end'
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
