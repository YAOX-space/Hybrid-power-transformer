function build_dual_dcpool()
% build_dual_dcpool.m — Phase-2 stage-B: dual HPT DC-bus + DC interlink (STAGE 1: DC power
% transfer validation). Two real 2200uF caps (init 800V) with phase-1-calibrated shunt import
% (charging, limited by sagged terminal) and series drain (1.9*boost), linked by a DC line.
% Validates the §5 pool claim at the DC-circuit level: does a healthy bus hold up a sagged,
% draining bus through the link, reproducing the calibrated Vdc_eq? (Stage 2 = add switching.)
M='hpt_dual_dcpool';
if bdIsLoaded(M), close_system(M,0); end
new_system(M); load_system(M);
Ts=20e-6; Cdc=2200e-6; Rchop=1e5;          % chopper OFF during sag (only fires at Vdc>1.20); negligible standing load
set_param(M,'Solver','ode23tb','StopTime','0.4');
P=@(x,y,w,h)[x y x+w y+h];
add_block('powerlib/powergui',[M '/powergui'],'Position',P(20,20,70,40));
set_param([M '/powergui'],'SimulationMode','Discrete','SampleTime',num2str(Ts));

% inputs (set per-run by the harness)
add_block('simulink/Sources/Constant',[M '/VtA'],'Position',P(20,120,40,20),'Value','0.30');
add_block('simulink/Sources/Constant',[M '/bA'], 'Position',P(20,150,40,20),'Value','0.18');
add_block('simulink/Sources/Constant',[M '/VtB'],'Position',P(20,300,40,20),'Value','1.00');
add_block('simulink/Sources/Constant',[M '/bB'], 'Position',P(20,330,40,20),'Value','0.00');

% per-bus electrical: cap(init800) + bleeder + controlled current src(net) + Vdc meas + ground
for s=1:2
  yo=(s-1)*220; tag=char('A'+s-1);
  add_block('powerlib/Elements/Series RLC Branch',[M '/Cdc' tag],'Position',P(400,120+yo,40,70));
  set_param([M '/Cdc' tag],'BranchType','C','Capacitance',num2str(Cdc),'Setx0','on','InitialVoltage','800');
  add_block('powerlib/Elements/Series RLC Branch',[M '/Rb' tag],'Position',P(480,120+yo,40,70));
  set_param([M '/Rb' tag],'BranchType','R','Resistance',num2str(Rchop));
  add_block('powerlib/Electrical Sources/Controlled Current Source',[M '/Is' tag],'Position',P(300,120+yo,50,60));
  add_block('powerlib/Measurements/Voltage Measurement',[M '/Vdc' tag],'Position',P(560,125+yo,40,40));
  add_block('powerlib/Elements/Ground',[M '/Gnd' tag],'Position',P(400,210+yo,30,30));
  add_block('simulink/Sinks/To Workspace',[M '/VdcOut' tag],'Position',P(640,125+yo,70,26), ...
    'VariableName',['Vdc' tag],'SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');
end

% DC interlink: Rlink + current measurement (B+ -> A+)
add_block('powerlib/Elements/Series RLC Branch',[M '/Rlink'],'Position',P(420,250,60,30), ...
  'BranchType','R','Resistance','0.5');
add_block('powerlib/Measurements/Current Measurement',[M '/Ilink'],'Position',P(500,250,40,30));
add_block('simulink/Sinks/To Workspace',[M '/IlinkOut'],'Position',P(560,250,70,26), ...
  'VariableName','Ilink','SaveFormat','Array','SampleTime',num2str(Ts),'MaxDataPoints','inf');

% net-current calculator (shunt import - series drain), per bus
add_block('simulink/User-Defined Functions/MATLAB Function',[M '/CALC'],'Position',P(120,180,140,120));
rt=sfroot; ch=rt.find('-isa','Stateflow.EMChart','Path',[M '/CALC']); ch.Script=calc_code();
% Vdc low-pass (0.1 ms) into CALC: breaks the algebraic loop (Vdc<->I_source) + filters
add_block('simulink/Continuous/Transfer Fcn',[M '/FiltA'],'Position',P(120,120,60,30),'Numerator','[1]','Denominator','[1e-4 1]');
add_block('simulink/Continuous/Transfer Fcn',[M '/FiltB'],'Position',P(120,330,60,30),'Numerator','[1]','Denominator','[1e-4 1]');

% ---- signal wiring ----
add_line(M,'VtA/1','CALC/1','autorouting','on'); add_line(M,'bA/1','CALC/2','autorouting','on');
add_line(M,'VtB/1','CALC/3','autorouting','on'); add_line(M,'bB/1','CALC/4','autorouting','on');
add_line(M,'VdcA/1','FiltA/1','autorouting','on'); add_line(M,'FiltA/1','CALC/5','autorouting','on');
add_line(M,'VdcB/1','FiltB/1','autorouting','on'); add_line(M,'FiltB/1','CALC/6','autorouting','on');
add_line(M,'CALC/1','IsA/1','autorouting','on'); add_line(M,'CALC/2','IsB/1','autorouting','on');
add_line(M,'VdcA/1','VdcOutA/1','autorouting','on'); add_line(M,'VdcB/1','VdcOutB/1','autorouting','on');
add_line(M,'Ilink/1','IlinkOut/1','autorouting','on');

% ---- electrical wiring (node anchor = CdcX LConn1 = DC+, CdcX RConn1 = DC-) ----
for s=1:2
  tag=char('A'+s-1);
  pos=ph([M '/Cdc' tag],'LConn',1); neg=ph([M '/Cdc' tag],'RConn',1);
  add_line(M, pos, ph([M '/Rb' tag],'LConn',1),'autorouting','on');
  add_line(M, ph([M '/Rb' tag],'RConn',1), neg,'autorouting','on');
  add_line(M, ph([M '/Is' tag],'RConn',1), pos,'autorouting','on');   % inject into DC+
  add_line(M, ph([M '/Is' tag],'LConn',1), neg,'autorouting','on');
  add_line(M, ph([M '/Vdc' tag],'LConn',1), pos,'autorouting','on');
  add_line(M, ph([M '/Vdc' tag],'LConn',2), neg,'autorouting','on');
  add_line(M, ph([M '/Gnd' tag],'LConn',1), neg,'autorouting','on');
end
% link: A+ -> Rlink -> Ilink -> B+
add_line(M, ph([M '/CdcA'],'LConn',1), ph([M '/Rlink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Rlink'],'RConn',1), ph([M '/Ilink'],'LConn',1),'autorouting','on');
add_line(M, ph([M '/Ilink'],'RConn',1), ph([M '/CdcB'],'LConn',1),'autorouting','on');

save_system(M);
fprintf('built %s (stage-1 DC pool)\n', M);
end

function s=calc_code()
% physical DC model: shunt = Vdc REGULATOR (to 800V, saturated by sag-limited available current);
% series = constant DC-current drain (converter at fixed modulation, P=m*Vdc*Iline => I_dc=m*Iline).
L={
'function [IA,IB] = calc(VtA,bA,VtB,bB,VdcA,VdcB)'
'%#codegen'
'Pb=400e3; idav=0.28; Kp=20; Vref=800;'
'va=max(50,VdcA); vb=max(50,VdcB);'
'ImaxA=max(0,VtA)*idav*Pb/va; ImaxB=max(0,VtB)*idav*Pb/vb;'   % available import (sag-limited)
'IinA=min(ImaxA, max(0, Kp*(Vref-va)));'                       % shunt regulates Vdc->800
'IinB=min(ImaxB, max(0, Kp*(Vref-vb)));'
'IseA=max(0,bA)*1.9*Pb/Vref; IseB=max(0,bB)*1.9*Pb/Vref;'      % series drain (constant DC current)
'IA=IinA-IseA; IB=IinB-IseB;'                                  % net injected into each DC bus
};
s=char(strjoin(L,char(10)));
end

function h=ph(blk,kind,idx)
  Q=get_param(blk,'PortHandles'); h=Q.(kind)(idx);
end
