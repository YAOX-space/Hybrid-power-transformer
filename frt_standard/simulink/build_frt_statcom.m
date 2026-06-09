function build_frt_statcom()
% build_frt_statcom.m
% Script-built, fully reproducible SWITCHING-LEVEL testbench for the FRT shunt
% reactive channel: weak grid (R/L) -> PCC with grid fault -> rated load, plus a
% shunt VSC (2-level IGBT bridge) on an L filter, DC bus with a CONDITIONAL chopper,
% controlled by a dq current loop (PLL + reactive-priority limiting).
%
% Everything is at the 400 V shunt level (the VSC's native voltage); the MV grid is
% reflected to 400 V (Tsh is 1:1 reflection). This isolates and validates the shunt
% reactive channel that the full 108-block binary cannot reproduce without fragile
% structural edits. Simulink/Simscape Electrical (Specialized Power Systems).
%
% Action interface (set as Constant block 'Values' per scenario):
%   id_ref (A)  active current ref   (shunt i_sh_d, charges Vdc)
%   iq_ref (A)  reactive current ref (shunt i_sh_q, +cap supports voltage)
% Fault interface: GridFault block params + 'Grid' R/L (SCR) + 'Grid' Voltage (EMF).
%
% Logged (To Workspace, Array): Vpcc_abc, Ivsc_abc, Vdc, dq (id,iq,idr,iqr,Vd,Vmag,th)

M = 'frt_statcom';
if bdIsLoaded(M), close_system(M,0); end
new_system(M);
load_system(M);

% ---- base parameters (mirror parameters.m, at 400 V level) ----
Vll   = 400;             % bus line-line (V)
f0    = 50;  w0 = 2*pi*f0;
Ts    = 50e-6;           % discrete solver step
Csh   = 2200e-6;         % DC cap (F)
Rsh   = 0.05;  Lsh = 3e-3;   % shunt filter
Rchop = 0.6;             % DC braking-chopper resistor (Ohm) ~ burns ~1MW... sized below
% chopper sized to dissipate ~ rated PE (120 kW) at 800V: R = 800^2/120e3 = 5.33 ohm
Rchop = 5.33;
Sload = 400e3;           % rated load (resistive) at 400 V

set_param(M,'Solver','ode23tb','StopTime','0.6');

pos=@(x,y,w,h)[x y x+w y+h];

% ---- powergui (discrete) ----
add_block('powerlib/powergui',[M '/powergui'],'Position',pos(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

% ---- weak grid source (R/L impedance mode) ----
add_block('powerlib/Electrical Sources/Three-Phase Source',[M '/Grid'],'Position',pos(120,120,60,80));
set_param([M '/Grid'],'Voltage',num2str(Vll),'Frequency',num2str(f0), ...
    'PhaseAngle','0','InternalConnection','Yg', ...
    'SpecifyImpedance','off','Resistance','0.019','Inductance','0.42e-3');  % SCR~3 default

% ---- grid fault on PCC ----
add_block('powerlib/Elements/Three-Phase Fault',[M '/GridFault'],'Position',pos(260,260,50,70));
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off', ...
    'GroundFault','off','SwitchTimes','[99 100]','FaultResistance','1','GroundResistance','0.01');

% ---- PCC measurement (V phase-gnd, I into load+vsc node) ----
add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasPCC'], ...
    'Position',pos(260,120,70,90));
set_param([M '/MeasPCC'],'VoltageMeasurement','phase-to-ground','CurrentMeasurement','no');

% ---- rated resistive load ----
add_block('powerlib/Elements/Three-Phase Series RLC Load',[M '/Load'],'Position',pos(400,260,60,70));
set_param([M '/Load'],'NominalVoltage',num2str(Vll),'NominalFrequency',num2str(f0), ...
    'ActivePower',num2str(Sload),'InductivePower','0','CapacitivePower','0', ...
    'Configuration','Y (grounded)');

% ---- shunt filter (R+L series branch, 3-phase) between VSC and PCC ----
add_block('powerlib/Elements/Three-Phase Series RLC Branch',[M '/Lfilt'],'Position',pos(500,120,60,70));
set_param([M '/Lfilt'],'BranchType','RL','Resistance',num2str(Rsh),'Inductance',num2str(Lsh));

% ---- current measurement on VSC AC side ----
add_block('powerlib/Measurements/Three-Phase V-I Measurement',[M '/MeasVSC'], ...
    'Position',pos(600,120,70,90));
set_param([M '/MeasVSC'],'VoltageMeasurement','no','CurrentMeasurement','yes');

% ---- 2-level IGBT bridge ----
add_block('powerlib/Power Electronics/Universal Bridge',[M '/VSC'],'Position',pos(740,120,80,110));
set_param([M '/VSC'],'Arms','3','Device','IGBT / Diodes');

% ---- DC bus capacitor ----
add_block('powerlib/Elements/Series RLC Branch',[M '/Cdc'],'Position',pos(880,150,40,60));
set_param([M '/Cdc'],'BranchType','C','Capacitance',num2str(Csh), ...
    'Setx0','on','InitialVoltage','800');   % start DC bus at 800 V (no boost transient)
% set initial voltage via powergui later (or rely on steady-state). Use Initial cap voltage:
% (Series RLC Branch has no init; use a parallel small source-free; powergui sets IC)

% ---- DC braking chopper: IGBT in series with Rchop across the DC bus ----
add_block('powerlib/Power Electronics/IGBT',[M '/Chop'],'Position',pos(960,150,40,60));
add_block('powerlib/Elements/Series RLC Branch',[M '/Rchop'],'Position',pos(960,230,40,50));
set_param([M '/Rchop'],'BranchType','R','Resistance',num2str(Rchop));

% ---- DC voltage measurement ----
add_block('powerlib/Measurements/Voltage Measurement',[M '/MeasVdc'],'Position',pos(880,260,40,40));

% ---- control: MATLAB Function (PLL + dq current loop + SPWM + chopper) ----
add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CTRL'],'Position',pos(520,360,180,150));

% ---- action / scenario constants ----
add_block('simulink/Sources/Constant',[M '/Vdc_ref'],'Position',pos(300,380,50,24),'Value','800');
add_block('simulink/Sources/Constant',[M '/iq_ref'],'Position',pos(300,420,50,24),'Value','0');
add_block('simulink/Sources/Clock',[M '/Clock'],'Position',pos(300,460,40,24));
add_block('simulink/Sources/Constant',[M '/t_fault'],'Position',pos(300,500,50,24),'Value','0.30');

% ---- logging ----
logs = {'Vpcc_abc','Ivsc_abc','Vdc','dq'};
ly = [380 430 480 530];
for k=1:numel(logs)
  add_block('simulink/Sinks/To Workspace',[M '/' logs{k}],'Position',pos(1080,ly(k),90,26), ...
      'VariableName',logs{k},'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
end

% =================== control chart code ===================
c = ctrl_code();
% MATLAB Function block backing chart:
rt = sfroot; chart = rt.find('-isa','Stateflow.EMChart','Path',[M '/CTRL']);
chart.Script = c;

% =================== ELECTRICAL WIRING (physical ports) ===================
for k=1:3
    add_line(M, ph([M '/Grid'],'RConn',k),    ph([M '/MeasPCC'],'LConn',k),'autorouting','on'); % Grid->MeasPCC in
    add_line(M, ph([M '/MeasPCC'],'RConn',k), ph([M '/GridFault'],'LConn',k),'autorouting','on'); % PCC bus
    add_line(M, ph([M '/MeasPCC'],'RConn',k), ph([M '/Load'],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/MeasPCC'],'RConn',k), ph([M '/Lfilt'],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/Lfilt'],'RConn',k),   ph([M '/MeasVSC'],'LConn',k),'autorouting','on');
    add_line(M, ph([M '/MeasVSC'],'RConn',k),  ph([M '/VSC'],'LConn',k),'autorouting','on'); % VSC AC
end
% DC side: VSC RConn(1)=+, RConn(2)=-
add_line(M, ph([M '/VSC'],'RConn',1), ph([M '/Cdc'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Cdc'],'RConn',1), ph([M '/VSC'],'RConn',2),'autorouting','on');
add_line(M, ph([M '/VSC'],'RConn',1), ph([M '/MeasVdc'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/VSC'],'RConn',2), ph([M '/MeasVdc'],'LConn',2),'autorouting','on');
% chopper: DC+ -> IGBT(C) -> IGBT(E)->Rchop -> DC-
add_line(M, ph([M '/VSC'],'RConn',1), ph([M '/Chop'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Chop'],'RConn',1), ph([M '/Rchop'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Rchop'],'RConn',1), ph([M '/VSC'],'RConn',2),'autorouting','on');

% =================== SIGNAL WIRING ===================
% measurement signal outports: MeasPCC Vabc (Outport 1), MeasVSC Iabc (Outport 1), MeasVdc (Outport 1)
add_line(M,'MeasPCC/1','Vpcc_abc/1','autorouting','on');
add_line(M,'MeasVSC/1','Ivsc_abc/1','autorouting','on');
add_line(M,'MeasVdc/1','Vdc/1','autorouting','on');
% CTRL inputs: (t, Vabc, Ivsc, Vdc, Vdc_ref, iq_ref, t_fault)
add_line(M,'Clock/1','CTRL/1','autorouting','on');
add_line(M,'MeasPCC/1','CTRL/2','autorouting','on');
add_line(M,'MeasVSC/1','CTRL/3','autorouting','on');
add_line(M,'MeasVdc/1','CTRL/4','autorouting','on');
add_line(M,'Vdc_ref/1','CTRL/5','autorouting','on');
add_line(M,'iq_ref/1','CTRL/6','autorouting','on');
add_line(M,'t_fault/1','CTRL/7','autorouting','on');
% CTRL outputs: g, gchop, dq
add_line(M,'CTRL/1','VSC/1','autorouting','on');    % g -> bridge gates
add_line(M,'CTRL/2','Chop/1','autorouting','on');   % gchop -> IGBT gate
add_line(M,'CTRL/3','dq/1','autorouting','on');

save_system(M);
fprintf('built %s.slx\n', M);
end

% physical-port handle helper
function h = ph(blk, kind, idx)
    P = get_param(blk,'PortHandles');
    h = P.(kind)(idx);
end

% --------- control function source ----------
function s = ctrl_code()
L = {
'function [g, gchop, dq] = ctrl(t, Vabc, Ivsc, Vdc, Vdc_ref, iq_ref, t_fault)'
'%#codegen'
'persistent th wint idi iqi vdi tprev en idr'
'if isempty(th) || t < 1e-9'
'    th = 0; wint = 0; idi = 0; iqi = 0; vdi = 0; tprev = 0; en = 0; idr = 0;'
'end'
'if Vdc > 620; en = 1; end   % latch control ON once DC bus precharged'
'dt = t - tprev; if dt < 0; dt = 0; end; if dt > 1e-3; dt = 1e-3; end; tprev = t;'
'w0 = 2*pi*50; Lsh = 3e-3; Imax = 173.2;'
'Va=Vabc(1); Vb=Vabc(2); Vc=Vabc(3);'
'Valpha = (2/3)*(Va - 0.5*Vb - 0.5*Vc);'
'Vbeta  = (2/3)*(sqrt(3)/2)*(Vb - Vc);'
'% --- dq-PLL: drive Vq->0 ---'
'Vd =  cos(th)*Valpha + sin(th)*Vbeta;'
'Vq = -sin(th)*Valpha + cos(th)*Vbeta;'
'Vm = sqrt(Vd*Vd + Vq*Vq); if Vm < 100; Vm = 100; end'   % floor avoids startup blow-up
'err = Vq / Vm;'                                           % Vq=Vm*sin(th_grid-th): +err speeds up to lock
'Kp_pll = 90; Ki_pll = 1500;'
'wint = wint + Ki_pll*err*dt; if wint>150; wint=150; elseif wint<-150; wint=-150; end'
'w = w0 + Kp_pll*err + wint;'
'th = th + w*dt; th = mod(th, 2*pi);'
'% --- VSC current in dq (load convention: current INTO VSC from bus) ---'
'Ia=Ivsc(1); Ib=Ivsc(2); Ic=Ivsc(3);'
'Ialpha=(2/3)*(Ia-0.5*Ib-0.5*Ic); Ibeta=(2/3)*(sqrt(3)/2)*(Ib-Ic);'
'id =  cos(th)*Ialpha + sin(th)*Ibeta;'
'iq = -sin(th)*Ialpha + cos(th)*Ibeta;'
'% --- outer Vdc PI -> active current ref (charges DC); rate- & range-limited ---'
'Kpv = 0.50; Kiv = 8.0;'
'ev = (Vdc_ref - Vdc)/Vdc_ref;'
'vdi = vdi + Kiv*ev*dt; if vdi>1.0; vdi=1.0; elseif vdi<-1.0; vdi=-1.0; end'
'idtgt = (Kpv*ev + vdi) * Imax;'
'if idtgt > 0.9*Imax; idtgt = 0.9*Imax; elseif idtgt < -0.9*Imax; idtgt = -0.9*Imax; end'
'% rate-limit id_ref so the inner loop never sees a huge step (avoids saturation)'
'dmax = 4000*dt;'   % A/s slew
'dstep = idtgt - idr; if dstep>dmax; dstep=dmax; elseif dstep<-dmax; dstep=-dmax; end'
'idr = idr + dstep;'
'% --- reactive-priority current limit ---'
'iqr = iq_ref; if iqr>0.3*Imax; iqr=0.3*Imax; elseif iqr<-0.3*Imax; iqr=-0.3*Imax; end'
'idm = sqrt(max(0, Imax*Imax - iqr*iqr));'
'if idr<-idm; idr=-idm; elseif idr>idm; idr=idm; end'  % bidirectional (active front end)
'% --- dq current PI + decoupling + grid feedforward (gentler Kp; anti-windup) ---'
'Kp = 2.5; Ki = 150.0;'
'ed = idr - id; eq = iqr - iq;'
'ud = Vd - (Kp*ed + idi) + w0*Lsh*iq;'
'uq = Vq - (Kp*eq + iqi) - w0*Lsh*id;'
'% --- modulation (fraction of Vdc/2) ---'
'half = max(50, Vdc/2);'
'md = ud/half; mq = uq/half;'
'sat = (abs(md)>1) || (abs(mq)>1);'   % integrate only when not saturated (anti-windup)
'if ~sat'
'    idi = idi + Ki*ed*dt; iqi = iqi + Ki*eq*dt;'
'    if idi>300; idi=300; elseif idi<-300; idi=-300; end'
'    if iqi>300; iqi=300; elseif iqi<-300; iqi=-300; end'
'end'
'ma = md*cos(th)        - mq*sin(th);'
'mb = md*cos(th-2*pi/3) - mq*sin(th-2*pi/3);'
'mc = md*cos(th+2*pi/3) - mq*sin(th+2*pi/3);'
'if ma>1; ma=1; elseif ma<-1; ma=-1; end'
'if mb>1; mb=1; elseif mb<-1; mb=-1; end'
'if mc>1; mc=1; elseif mc<-1; mc=-1; end'
'% --- SPWM gates (fc = 5 kHz) ---'
'fc = 5000; carrier = 2*abs(2*(fc*t - floor(fc*t+0.5))) - 1;'
'ga = ma>=carrier; gb = mb>=carrier; gc = mc>=carrier;'
'g = double([ga; ~ga; gb; ~gb; gc; ~gc]);'
'% --- soft-start precharge: gates OFF (diode rectify) until latched ON ---'
'if en < 0.5'
'    g = zeros(6,1); idi = 0; iqi = 0; vdi = 0;'   % hold integrators during precharge
'end'
'% --- conditional DC chopper: engage above 1.20 pu (fault overvoltage only) ---'
'gchop = double(Vdc > 1.20*800);'
'dq = [id; iq; idr; iqr; Vd; Vm; th];'
};
s = char(strjoin(L, char(10)));
end
