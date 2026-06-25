function build_dual_dcpool_sw()
% build_dual_dcpool_sw.m — Phase-2 B-stage STAGE 2: dual HPT DC-interlink with REAL switching
% shunt converters. Upgrades stage-1 (current-source import) to two real IGBT shunt VSCs running
% the validated PLL + dq current loop + Vdc outer loop, each fed from a 3φ LV source scaled by the
% local sag, charging a real 2200µF DC cap. Series boost drain stays a calibrated constant-current
% DC load (the deficit). Two DC buses linked by Rlink + current meas. This exposes what stage-1
% abstracted away: real IGBT switching, DC ripple, dq control under sag, and converter-to-converter
% electromagnetic coupling through the shared DC link.
p = pu_params();  % single-source base values (mirror pu.py); see build_hpt_frt_full P3 note
M='hpt_dual_dcpool_sw';
if bdIsLoaded(M), close_system(M,0); end
new_system(M); load_system(M);
f0=50; Ts=20e-6; Vlv=400; Cdc=2200e-6; Rsh=0.05; Lsh=3e-3;
set_param(M,'Solver','ode23tb','StopTime','0.5');
P=@(x,y,w,h)[x y x+w y+h];
add_block('powerlib/powergui',[M '/powergui'],'Position',P(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

for u=1:2
  tag=char('A'+u-1); yo=(u-1)*420;
  % --- LV 3φ source (amplitude = local sag, set per-run by harness) ---
  add_block('powerlib/Electrical Sources/Three-Phase Source',[M '/Src' tag],'Position',P(80,120+yo,60,90));
  set_param([M '/Src' tag],'Voltage',num2str(Vlv),'Frequency',num2str(f0),'PhaseAngle','0', ...
    'InternalConnection','Y','SpecifyImpedance','off','Resistance','1e-3','Inductance','1e-5');
  % --- shunt POC V-I measurement (V for PLL, I for current loop) ---
  add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasSh' tag],'Position',P(200,120+yo,70,90));
  set_param([M '/MeasSh' tag],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','yes');
  % --- shunt filter ---
  add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Lsh' tag],'Position',P(320,120+yo,55,60));
  set_param([M '/Lsh' tag],'BranchType','RL','Resistance',num2str(Rsh),'Inductance',num2str(Lsh));
  % --- shunt VSC (real 2-level IGBT bridge) ---
  add_block('powerlib/Power Electronics/Universal Bridge',[M '/ShVSC' tag],'Position',P(420,120+yo,80,110));
  set_param([M '/ShVSC' tag],'Arms','3','Device','IGBT / Diodes');
  % --- DC bus: cap(init 800) + high-R bleeder + Vdc meas + ground on DC- ---
  add_block('powerlib/Elements/Series RLC Branch',[M '/Cdc' tag],'Position',P(580,130+yo,40,70));
  set_param([M '/Cdc' tag],'BranchType','C','Capacitance',num2str(Cdc),'Setx0','on','InitialVoltage','800');
  add_block('powerlib/Elements/Series RLC Branch',[M '/Rb' tag],'Position',P(650,130+yo,40,70));
  set_param([M '/Rb' tag],'BranchType','R','Resistance','1e4');
  add_block('powerlib/Electrical Sources/Controlled Current Source',[M '/Ise' tag],'Position',P(500,260+yo,50,60));
  add_block('powerlib/Measurements/Voltage Measurement',[M '/MeasVdc' tag],'Position',P(720,135+yo,40,40));
  % NOTE: DC bus floats (referenced via Yg AC source through the VSC, like the single-HPT model).
  % Grounding DC- with an Yg AC source = common-mode short through the bridge -> crashes the bus.
  % --- series drain command (constant DC current = boost*1.9*Pb/Vref), set per-run ---
  add_block('simulink/Sources/Constant',[M '/IseCmd' tag],'Position',P(400,290+yo,50,20),'Value','0');
  % --- shunt controller (validated PLL + dq current + Vdc outer) ---
  add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRL' tag],'Position',P(200,300+yo,180,120));
  rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRL' tag]); ch.Script=ctrl_shunt_code();
  add_block('simulink/Sources/Constant',[M '/Vref' tag],'Position',P(60,300+yo,50,20),'Value','800');
  add_block('simulink/Sources/Constant',[M '/iqref' tag],'Position',P(60,330+yo,50,20),'Value','0');
  add_block('simulink/Sources/Clock',[M '/Clk' tag],'Position',P(60,360+yo,40,20));
  add_block('simulink/Sources/Constant',[M '/tf' tag],'Position',P(60,390+yo,50,20),'Value','999');
  % --- logging ---
  add_block('simulink/Sinks/To Workspace',[M '/VdcOut' tag],'Position',P(800,135+yo,70,26), ...
    'VariableName',['Vdc' tag],'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');

  % electrical wiring (per unit)
  for k=1:3
    add_line(M, ph([M '/Src' tag],'RConn',k), ph([M '/MeasSh' tag],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/MeasSh' tag],'RConn',k), ph([M '/Lsh' tag],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/Lsh' tag],'RConn',k), ph([M '/ShVSC' tag],'LConn',k),'autorouting','on');
  end
  pos=ph([M '/ShVSC' tag],'RConn',1); neg=ph([M '/ShVSC' tag],'RConn',2);   % DC+ / DC-
  add_line(M, pos, ph([M '/Cdc' tag],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Cdc' tag],'RConn',1), neg,'autorouting','on');
  add_line(M, pos, ph([M '/Rb' tag],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Rb' tag],'RConn',1), neg,'autorouting','on');
  add_line(M, ph([M '/Ise' tag],'RConn',1), neg,'autorouting','on');   % flipped: +command pulls I out of DC+ = drain
  add_line(M, ph([M '/Ise' tag],'LConn',1), pos,'autorouting','on');
  add_line(M, ph([M '/MeasVdc' tag],'LConn',1), pos,'autorouting','on');
  add_line(M, ph([M '/MeasVdc' tag],'LConn',2), neg,'autorouting','on');

  % signal wiring (per unit)
  add_line(M,['Clk' tag '/1'],['CTRL' tag '/1'],'autorouting','on');
  add_line(M,['MeasSh' tag '/1'],['CTRL' tag '/2'],'autorouting','on');   % Vabc -> PLL
  add_line(M,['MeasSh' tag '/2'],['CTRL' tag '/3'],'autorouting','on');   % Iabc -> current loop
  add_line(M,['MeasVdc' tag '/1'],['CTRL' tag '/4'],'autorouting','on');
  add_line(M,['Vref' tag '/1'],['CTRL' tag '/5'],'autorouting','on');
  add_line(M,['iqref' tag '/1'],['CTRL' tag '/6'],'autorouting','on');
  add_line(M,['tf' tag '/1'],['CTRL' tag '/7'],'autorouting','on');
  add_line(M,['CTRL' tag '/1'],['ShVSC' tag '/1'],'autorouting','on');    % gates
  add_line(M,['IseCmd' tag '/1'],['Ise' tag '/1'],'autorouting','on');
  add_line(M,['MeasVdc' tag '/1'],['VdcOut' tag '/1'],'autorouting','on');
end

% --- DC interlink: A(+) -> Rlink -> Ilink -> B(+) ---
add_block('powerlib/Elements/Series RLC Branch',[M '/Rlink'],'Position',P(580,360,60,30), ...
  'BranchType','R','Resistance','0.5');
add_block('powerlib/Measurements/Current Measurement',[M '/Ilink'],'Position',P(660,360,40,30));
add_block('simulink/Sinks/To Workspace',[M '/IlinkOut'],'Position',P(720,360,70,26), ...
  'VariableName','Ilink','SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
add_line(M, ph([M '/ShVSCA'],'RConn',1), ph([M '/Rlink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Rlink'],'RConn',1), ph([M '/Ilink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Ilink'],'RConn',1), ph([M '/ShVSCB'],'RConn',1),'autorouting','on');
% DC- return: tie the two buses' negative rails (link needs both rails)
add_line(M, ph([M '/ShVSCA'],'RConn',2), ph([M '/ShVSCB'],'RConn',2),'autorouting','on');
% single system ground on the common DC- rail (AC sources are floating Y -> exactly one earth, no loop)
add_block('powerlib/Elements/Ground',[M '/Gnd'],'Position',P(540,330,30,30));
add_line(M, ph([M '/Gnd'],'LConn',1), ph([M '/ShVSCA'],'RConn',2),'autorouting','on');
add_line(M,'Ilink/1','IlinkOut/1','autorouting','on');

save_system(M);
fprintf('built %s (stage-2 switching DC pool)\n', M);
end

% ---- shunt controller: PLL + dq current loop + reactive priority + Vdc outer loop ----
function s = ctrl_shunt_code()
L = {
'function [g, gchop, dq] = ctrl(t, Vabc, Ish, Vdc, Vdc_ref, iq_ref, t_fault)'
'%#codegen'
'persistent th wint idi iqi vdi tprev en idr'
'if isempty(th) || t < 1e-9'
'    th=0; wint=0; idi=0; iqi=0; vdi=0; tprev=0; en=0; idr=0;'
'end'
'if t > 0.15; en = 1; end'
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
    Q = get_param(blk,'PortHandles'); h = Q.(kind)(idx);
end
