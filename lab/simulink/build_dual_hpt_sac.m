function build_dual_hpt_sac()
% build_dual_hpt_sac.m — Phase-2 B-stage STAGE 3: TWO full HPTs (real shunt VSC + real series VSC
% injecting into the LV line + real load), DC buses linked, BOTH running the real mode-14 residual
% SAC HLC. Demonstrates the synthesis: pooled DC holds a sagged HPT's Vdc up, so its SAC series
% boost is NOT DC-budget-throttled -> deeper load-voltage recovery than solo. LV-source backbone
% (MV grid + main Tx dropped — irrelevant to the DC-pool+SAC physics under test); validated
% shunt/series/HLC controllers reused verbatim; Stage-2 grounding recipe (floating-Y src + 1 ground).
%
% CANONICAL NAMING (see CONTROL_MODES.md / controller_modes.m): the internal "mode-14" HLC integer
% used here == canonical Mode 6 (MPC-assisted residual SAC), an EXTENSION (not the main method, not
% pure SAC). The main method is canonical Mode 5 (online-gated multi-expert SAC, internal mi==12).
% This is the B-stage dual-HPT (shared DC-pool) test model. Internal integer kept unchanged for
% reproducibility.
p = pu_params();  % single-source base values (mirror pu.py); see build_hpt_frt_full P3 note
M='hpt_dual_hpt_sac';
if bdIsLoaded(M), close_system(M,0); end
new_system(M); load_system(M);
f0=50; Ts=20e-6; Vlv=400; Cdc=2200e-6; Rsh=0.05; Lsh=3e-3; Srated=400e3;
Vse_w1=400; Vse_w2=46.2; Sse=30e3;
set_param(M,'Solver','ode23tb','StopTime','0.6');
P=@(x,y,w,h)[x y x+w y+h];
add_block('powerlib/powergui',[M '/powergui'],'Position',P(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

for u=1:2
  tag=char('A'+u-1); yo=(u-1)*520;
  % --- LV 3φ source (floating Y; amplitude = local sag, set per-run) ---
  add_block('powerlib/Electrical Sources/Three-Phase Source',[M '/Src' tag],'Position',P(60,120+yo,60,90));
  set_param([M '/Src' tag],'Voltage',num2str(Vlv),'Frequency',num2str(f0),'PhaseAngle','0', ...
    'InternalConnection','Y','SpecifyImpedance','off','Resistance','1e-3','Inductance','1e-5');
  % --- 3 single-phase series-injection transformers Tse_1/2/3 (winding2 in series in the LV line) ---
  for k=1:3
    blk=[M sprintf('/Tse%s_%d',tag,k)];
    add_block('powerlib/Elements/Linear Transformer',blk,'Position',P(280,120+yo+(k-1)*55,70,50));
    set_param(blk,'ThreeWindings','off','NominalPower',['[' num2str(Sse) ',' num2str(f0) ']'], ...
      'winding1',['[' num2str(Vse_w1) ',0.002,0.03]'],'winding2',['[' num2str(Vse_w2) ',0.002,0.03]']);
  end
  % --- protected load bus (node Y) voltage + load ---
  add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasY' tag],'Position',P(420,120+yo,70,90));
  set_param([M '/MeasY' tag],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','no');
  add_block('powerlib/Elements/Three-Phase Series RLC Load',[M '/Load' tag],'Position',P(560,120+yo,60,70));
  set_param([M '/Load' tag],'NominalVoltage',num2str(Vlv),'NominalFrequency',num2str(f0), ...
    'ActivePower',num2str(Srated),'InductivePower','0','CapacitivePower','0','Configuration','Y (floating)');
  % --- shunt branch off node X (source side): V-I meas + filter + IGBT VSC ---
  add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasSh' tag],'Position',P(140,300+yo,70,90));
  set_param([M '/MeasSh' tag],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','yes');
  add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Lsh' tag],'Position',P(250,300+yo,55,60));
  set_param([M '/Lsh' tag],'BranchType','RL','Resistance',num2str(Rsh),'Inductance',num2str(Lsh));
  add_block('powerlib/Power Electronics/Universal Bridge',[M '/ShVSC' tag],'Position',P(350,300+yo,80,110));
  set_param([M '/ShVSC' tag],'Arms','3','Device','IGBT / Diodes');
  % --- shared DC bus: cap(init 800) + Vdc meas (floats; one system ground added after the loop) ---
  add_block('powerlib/Elements/Series RLC Branch',[M '/Cdc' tag],'Position',P(500,310+yo,40,70));
  set_param([M '/Cdc' tag],'BranchType','C','Capacitance',num2str(Cdc),'Setx0','on','InitialVoltage','800');
  add_block('powerlib/Measurements/Voltage Measurement',[M '/MeasVdc' tag],'Position',P(580,315+yo,40,40));
  % --- series VSC (shares DC bus) ---
  add_block('powerlib/Power Electronics/Universal Bridge',[M '/SeVSC' tag],'Position',P(180,430+yo,70,100));
  set_param([M '/SeVSC' tag],'Arms','3','Device','IGBT / Diodes');
  % --- controllers (validated, reused verbatim) ---
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRLsh' tag],'Position',P(660,300+yo,170,120));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRLsh' tag]); ch.Script=ctrl_shunt_code();
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRLse' tag],'Position',P(60,560+yo,150,90));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRLse' tag]); ch.Script=ctrl_series_code();
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/HLC' tag],'Position',P(420,430+yo,150,110));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/HLC' tag]); ch.Script=hlc_code();
  % --- HLC constants ---
  add_block('simulink/Sources/Constant',[M '/mode' tag],'Position',P(360,430+yo,40,20),'Value','14');
  add_block('simulink/Sources/Constant',[M '/fclass' tag],'Position',P(360,455+yo,40,20),'Value','1');
  add_block('simulink/Sources/Constant',[M '/fdur' tag],'Position',P(360,480+yo,40,20),'Value','0.40');
  add_block('simulink/Sources/Constant',[M '/Vref' tag],'Position',P(880,300+yo,40,20),'Value','800');
  add_block('simulink/Sources/Constant',[M '/iqref' tag],'Position',P(880,325+yo,40,20),'Value','0');
  add_block('simulink/Sources/Clock',[M '/Clk' tag],'Position',P(880,350+yo,40,20));
  add_block('simulink/Sources/Constant',[M '/tf' tag],'Position',P(880,375+yo,40,20),'Value','0.15');
  add_block('simulink/Sources/Constant',[M '/msed' tag],'Position',P(60,520+yo,40,20),'Value','0');
  add_block('simulink/Sources/Constant',[M '/mseq' tag],'Position',P(60,540+yo,40,20),'Value','0');
  % --- logging ---
  add_block('simulink/Sinks/To Workspace',[M '/VyOut' tag],'Position',P(520,120+yo,70,26), ...
    'VariableName',['Vy' tag],'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
  add_block('simulink/Sinks/To Workspace',[M '/VdcOut' tag],'Position',P(660,315+yo,70,26), ...
    'VariableName',['Vdc' tag],'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');

  % ---- electrical wiring (per unit) ----
  for k=1:3
    % main line: Src -> node X -> Tse w2(term1->term2) -> node Y -> Load
    add_line(M, ph([M '/Src' tag],'RConn',k), ph([M sprintf('/Tse%s_%d',tag,k)],'RConn',1),'autorouting','on');
    add_line(M, ph([M sprintf('/Tse%s_%d',tag,k)],'RConn',2), ph([M '/MeasY' tag],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/MeasY' tag],'RConn',k), ph([M '/Load' tag],'LConn',k),'autorouting','on');
    % shunt branch taps node X (= Src RConn)
    add_line(M, ph([M '/Src' tag],'RConn',k), ph([M '/MeasSh' tag],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/MeasSh' tag],'RConn',k), ph([M '/Lsh' tag],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/Lsh' tag],'RConn',k), ph([M '/ShVSC' tag],'LConn',k),'autorouting','on');
    % series VSC AC -> Tse primaries (winding1 term1)
    add_line(M, ph([M '/SeVSC' tag],'LConn',k), ph([M sprintf('/Tse%s_%d',tag,k)],'LConn',1),'autorouting','on');
  end
  % series Tse primaries' term2 commoned (floating star)
  add_line(M, ph([M sprintf('/Tse%s_1',tag)],'LConn',2), ph([M sprintf('/Tse%s_2',tag)],'LConn',2),'autorouting','on');
  add_line(M, ph([M sprintf('/Tse%s_2',tag)],'LConn',2), ph([M sprintf('/Tse%s_3',tag)],'LConn',2),'autorouting','on');
  % DC bus: ShVSC(+/-) = SeVSC(+/-) = Cdc, Vdc meas
  pos=ph([M '/ShVSC' tag],'RConn',1); neg=ph([M '/ShVSC' tag],'RConn',2);
  add_line(M, pos, ph([M '/Cdc' tag],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Cdc' tag],'RConn',1), neg,'autorouting','on');
  add_line(M, ph([M '/SeVSC' tag],'RConn',1), pos,'autorouting','on');
  add_line(M, ph([M '/SeVSC' tag],'RConn',2), neg,'autorouting','on');
  add_line(M, ph([M '/MeasVdc' tag],'LConn',1), pos,'autorouting','on');
  add_line(M, ph([M '/MeasVdc' tag],'LConn',2), neg,'autorouting','on');

  % ---- signal wiring (per unit) ----
  % shunt controller: ctrl(t,Vabc,Ish,Vdc,Vdc_ref,iq_ref,t_fault)
  add_line(M,['Clk' tag '/1'],['CTRLsh' tag '/1'],'autorouting','on');
  add_line(M,['MeasSh' tag '/1'],['CTRLsh' tag '/2'],'autorouting','on');
  add_line(M,['MeasSh' tag '/2'],['CTRLsh' tag '/3'],'autorouting','on');
  add_line(M,['MeasVdc' tag '/1'],['CTRLsh' tag '/4'],'autorouting','on');
  add_line(M,['Vref' tag '/1'],['CTRLsh' tag '/5'],'autorouting','on');
  add_line(M,['iqref' tag '/1'],['CTRLsh' tag '/6'],'autorouting','on');   % overwritten by HLC below
  add_line(M,['tf' tag '/1'],['CTRLsh' tag '/7'],'autorouting','on');
  add_line(M,['CTRLsh' tag '/1'],['ShVSC' tag '/1'],'autorouting','on');   % gates
  % series controller: ctrl(t,Vlv,mse_d,mse_q)
  add_line(M,['Clk' tag '/1'],['CTRLse' tag '/1'],'autorouting','on');
  add_line(M,['MeasY' tag '/1'],['CTRLse' tag '/2'],'autorouting','on');
  add_line(M,['msed' tag '/1'],['CTRLse' tag '/3'],'autorouting','on');    % overwritten by HLC below
  add_line(M,['mseq' tag '/1'],['CTRLse' tag '/4'],'autorouting','on');    % overwritten by HLC below
  add_line(M,['CTRLse' tag '/1'],['SeVSC' tag '/1'],'autorouting','on');   % gates
  % HLC: hlc(mode,Vlv,sac_iq,sac_msed,sac_mseq,Vdc,t,fclass,tf,fdur) -> iq_ref,mse_d,mse_q
  delete_line(M,['iqref' tag '/1'],['CTRLsh' tag '/6']);
  delete_line(M,['msed' tag '/1'],['CTRLse' tag '/3']);
  delete_line(M,['mseq' tag '/1'],['CTRLse' tag '/4']);
  add_line(M,['mode' tag '/1'],['HLC' tag '/1'],'autorouting','on');
  add_line(M,['MeasY' tag '/1'],['HLC' tag '/2'],'autorouting','on');
  add_line(M,['iqref' tag '/1'],['HLC' tag '/3'],'autorouting','on');     % sac_iq (unused in mode14)
  add_line(M,['msed' tag '/1'],['HLC' tag '/4'],'autorouting','on');
  add_line(M,['mseq' tag '/1'],['HLC' tag '/5'],'autorouting','on');
  add_line(M,['MeasVdc' tag '/1'],['HLC' tag '/6'],'autorouting','on');
  add_line(M,['Clk' tag '/1'],['HLC' tag '/7'],'autorouting','on');
  add_line(M,['fclass' tag '/1'],['HLC' tag '/8'],'autorouting','on');
  add_line(M,['tf' tag '/1'],['HLC' tag '/9'],'autorouting','on');
  add_line(M,['fdur' tag '/1'],['HLC' tag '/10'],'autorouting','on');
  add_line(M,['HLC' tag '/1'],['CTRLsh' tag '/6'],'autorouting','on');    % -> iq_ref
  % allocator-granted series-budget multiplier (1 = raw single-device SAC cap; >1 = pool budget granted)
  add_block('simulink/Math Operations/Gain',[M '/SEg' tag],'Position',P(280,560+yo,40,24),'Gain','1');
  add_line(M,['HLC' tag '/2'],['SEg' tag '/1'],'autorouting','on');
  add_line(M,['SEg' tag '/1'],['CTRLse' tag '/3'],'autorouting','on');    % -> mse_d (via allocator gain)
  add_line(M,['HLC' tag '/3'],['CTRLse' tag '/4'],'autorouting','on');    % -> mse_q
  % logging
  add_line(M,['MeasY' tag '/1'],['VyOut' tag '/1'],'autorouting','on');
  add_line(M,['MeasVdc' tag '/1'],['VdcOut' tag '/1'],'autorouting','on');
end

% ---- DC interlink: A(+) -> Rlink -> Ilink -> B(+); tie DC- rails; single system ground ----
add_block('powerlib/Elements/Series RLC Branch',[M '/Rlink'],'Position',P(500,460,60,30), ...
  'BranchType','R','Resistance','0.5');
add_block('powerlib/Measurements/Current Measurement',[M '/Ilink'],'Position',P(580,460,40,30));
add_block('simulink/Sinks/To Workspace',[M '/IlinkOut'],'Position',P(640,460,70,26), ...
  'VariableName','Ilink','SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
add_line(M, ph([M '/ShVSCA'],'RConn',1), ph([M '/Rlink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Rlink'],'RConn',1), ph([M '/Ilink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Ilink'],'RConn',1), ph([M '/ShVSCB'],'RConn',1),'autorouting','on');
add_line(M, ph([M '/ShVSCA'],'RConn',2), ph([M '/ShVSCB'],'RConn',2),'autorouting','on');
add_block('powerlib/Elements/Ground',[M '/Gnd'],'Position',P(460,430,30,30));
add_line(M, ph([M '/Gnd'],'LConn',1), ph([M '/ShVSCA'],'RConn',2),'autorouting','on');
add_line(M,'Ilink/1','IlinkOut/1','autorouting','on');

save_system(M);
fprintf('built %s (stage-3 dual HPT + DC link + mode-14 SAC)\n', M);
end

% ---- high-level controller: mode 4 dq-traditional / 10 SAC-setpoint / 11 SAC-CLOSED-LOOP ----
function s = hlc_code()
L = {
'function [iq_ref, mse_d, mse_q] = hlc(mode, Vlv, sac_iq, sac_msed, sac_mseq, Vdc, t, fclass, tf, fdur)'
'%#codegen'
['% build-nonce ' datestr(now,'yyyymmdd-HHMMSS-FFF') ': forces fresh codegen so coder.load re-reads weight .mat files']
'persistent ba bb bi la vpf vnf kstep ahold onset'
'if isempty(ba); ba=zeros(250,1); bb=zeros(250,1); bi=1; la=zeros(3,1); vpf=1; vnf=0; kstep=int32(0); ahold=zeros(3,1); onset=-1; end'
sprintf('Imax=%.6g; Vnom=%.6g; Iact=%.6g;', p.I_pe_rms, p.VLN_peak, p.I_action_peak)
'iq_ref=0; mse_d=0; mse_q=0;'
'Va=Vlv(1); Vb=Vlv(2); Vc=Vlv(3);'
'Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);'
'Vpu=sqrt(Valpha*Valpha+Vbeta*Vbeta)/Vnom;'
'mi=int32(mode);'
'if mi==11 || mi==12 || mi==13 || mi==14'
'    % ===== closed-loop SAC (11=single, 12=gated 4-expert), frt-v2 20-D obs / 3-D action / de-privileged online detector ====='
'    NB=250;'
'    Vad=ba(bi); Vbd=bb(bi); ba(bi)=Valpha; bb(bi)=Vbeta; bi=bi+1; if bi>NB; bi=1; end'
'    V1a=0.5*(Valpha-Vbd); V1b=0.5*(Vbeta+Vad);'
'    V2a=0.5*(Valpha+Vbd); V2b=0.5*(Vbeta-Vad);'
'    V2p=sqrt(V1a*V1a+V1b*V1b)/Vnom; V2n=sqrt(V2a*V2a+V2b*V2b)/Vnom;'
'    af=0.005; vpf=vpf+af*(V2p-vpf); vnf=vnf+af*(V2n-vnf); V2p=vpf; V2n=vnf;'   % match ODE TAU_V2 smoothing -> kill ripple-driven chatter
'    fc=fclass;'
'    if mi==11 || mi==12 || mi==13 || mi==14'   % DE-PRIVILEGED online fault class from measured (V2p,V2n)
'        if V2p>1.1; fc=5; elseif V2n>0.05; fc=2; else; fc=1; end'
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
'    if V2p<0.9; idr=1.5*(0.9-V2p); if idr>0.3; idr=0.3; end; elseif V2p>1.1; idr=-1.5*(V2p-1.1); if idr<-0.3; idr=-0.3; end; else; idr=0; end'
'    iqerr=idr-iqp;'
'    % DE-PRIVILEGED online detector (audit #3): in_fault + elapsed from MEASURED (V2p,V2n), not true tf/fdur.'
'    faulted = (V2p<0.9) || (V2p>1.1) || (V2n>0.05);'
'    if faulted; if onset<0; onset=t; end; else; onset=-1; end'
'    infault=double(faulted); elapsed=0; if faulted; elapsed=max(0,t-onset); end'
'    probs=zeros(6,1);'
'    if infault>0.5; ci=round(fc)+1; if ci<1; ci=1; elseif ci>6; ci=6; end; probs(ci)=0.92; probs(1)=probs(1)+0.08; else; probs(1)=1; end'
'    tfrac=elapsed*0.2/0.5; if tfrac<0; tfrac=0; elseif tfrac>1; tfrac=1; end'   % elapsed since DETECTED onset; x0.2=TSCALE

'    obs=reshape([Vdc/800; V2p; V2n; abs(iqp); 0; 0; vdev; iqerr; iqp; probs; tfrac; infault; la(1); la(2); la(3)],20,1);'
'    if mi==11'
'        W=coder.load(''sac_actor_weights.mat'');'
'    elseif mi==14'
'        W=coder.load(''sac_residual_weights.mat'');'   % single residual policy (MPC prior handles domains)
'    else'   % real-time gated 4-expert routing by (V2p, V2n)
'        if V2p>1.1'
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
'    if (mi==12 || mi==13 || mi==14) && V2p>=0.9 && V2p<=1.1 && infault<0.5; act=zeros(3,1); end'   % normal: hold
'    la=act; ahold=act;'
'    else'
'    act=ahold;'
'    end'
'    if mi==14'
'        % residual mode: total = receding MPC prior + held residual, clipped to physical caps.'
'        % asym-aware iq cap (0.24): measured peak = cmd x k_2w; ODE cannot see ripple (m14-v1 lesson)'
'        cap14=0.27; if V2n>0.05 && V2p<0.9; cap14=0.24; end'
'        a1=piq+act(1); if a1>cap14; a1=cap14; elseif a1<-cap14; a1=-cap14; end'
'        a2=pmb+act(2); if a2>0.2; a2=0.2; elseif a2<-0.2; a2=-0.2; end'
'        a3=act(3); if a3>0.2; a3=0.2; elseif a3<-0.2; a3=-0.2; end'
'        iq_ref=a1*Iact; mse_d=-a2; mse_q=-a3;'   % current base = I_action_peak (audit #3)
'    else'
'        iq_ref=act(1)*Iact; mse_d=-act(2); mse_q=-act(3);'   % [iq, mse_d, mse_q] x I_action_peak'
'    end'
'    end'   % end mi==13 HVRT/LVRT split
'elseif mi==10'
'    iq_ref=sac_iq; mse_d=-sac_msed; mse_q=-sac_mseq;'
'else'
'    % dq traditional variants. All share the GB/T reactive droop (K1=1.5, cap 0.3 pu):'
'    if Vpu<0.9; iqp=1.5*(0.9-Vpu); if iqp>0.3; iqp=0.3; end; iq_ref=iqp*Imax;'
'    elseif Vpu>1.1; iqp=-1.5*(Vpu-1.1); if iqp<-0.3; iqp=-0.3; end; iq_ref=iqp*Imax;'
'    else; iq_ref=0; end'
'    if mi==8'
'        % week3 decision-layer one-step MPC: constrained optimum on the CALIBRATED model, receding horizon @2ms.'
'        % max voltage support s.t. |iq|<=0.27, Vdc_eq>=0.82 (Vdc_eq = 1 - 0.08|iq|/max(0.3,V) - 1.9*boost), |mse|<=0.2.'
'        % Algebraic model => closed-form optimum: series boost used UP TO the DC-budget bound (vs mode5/7 zeroing).'
'        if iq_ref>0.27*Imax; iq_ref=0.27*Imax; elseif iq_ref<-0.27*Imax; iq_ref=-0.27*Imax; end'
'        iqpu=iq_ref/Imax;'
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
'        if iq_ref>0.27*Imax; iq_ref=0.27*Imax; elseif iq_ref<-0.27*Imax; iq_ref=-0.27*Imax; end'
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
L = {
'function [g, gchop, dq] = ctrl(t, Vabc, Ish, Vdc, Vdc_ref, iq_ref, t_fault)'
'%#codegen'
'persistent th wint idi iqi vdi tprev en idr'
'if isempty(th) || t < 1e-9'
'    th=0; wint=0; idi=0; iqi=0; vdi=0; tprev=0; en=0; idr=0;'
'end'
'if Vdc > 620; en = 1; end'
'dt = t - tprev; if dt<0; dt=0; end; if dt>1e-3; dt=1e-3; end; tprev=t;'
sprintf('w0 = 2*pi*50; Lsh = 3e-3; Imax = %.6g;', p.I_pe_rms)
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
