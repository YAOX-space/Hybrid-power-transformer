%% emt_compare_probe.m — Simulink reference outputs for EMT cross-validation.
% Same inputs as emt/run_emt.run_scenario: P=320k,Q=80k, t_fault=0.02, m_sh=0.90,
% m_se=0, SAC-direct control, fault window 15 ms, r_fault~0.3, StopTime=0.05.
run('parameters.m'); MODEL='hpt_switching_model';
if ~bdIsLoaded(MODEL); load_system('hpt_switching_model.slx'); end
set_param(MODEL,'SimulationMode','normal');
I2pk = (S_rated/(sqrt(3)*V_secondary))*sqrt(2);
tf=0.02; Tsim=0.05; fs=20000;
cases = {0,'normal'; 6,'sc_1ph'; 7,'sc_3ph'; 5,'cap_fault'};
fprintf('SIMULINK: sc_id name      Vdc_min Vdc_max I2_max V2LLmin\n');
for i=1:size(cases,1)
  sc=cases{i,1};
  set_param(MODEL,'FastRestart','off');
  set_param([MODEL '/Sc_id'],'Value',num2str(sc));
  set_param([MODEL '/T_fault'],'Value',num2str(tf));
  set_param([MODEL '/ControllerMode'],'Value','9');
  set_param([MODEL '/RL_Energy_Bias'],'Value','0.90');
  set_param([MODEL '/RL_Reg_Bias'],'Value','0');
  set_param([MODEL '/RL_Current_Bias'],'Value','0');
  set_param([MODEL '/LV_Load'],'ActivePower','320e3','InductivePower','80e3','CapacitivePower','0');
  set_param([MODEL '/DC_Link_Cap_Breaker'],'InitialState','1','SwitchingTimes','[99]');
  if sc==5; cap='680e-6'; else; cap='2200e-6'; end
  set_param([MODEL '/DC_Link_Capacitor'],'Capacitance',cap,'InitialVoltage','800');
  set_param([MODEL '/LV_AC_Fault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
  if sc==6
    set_param([MODEL '/LV_AC_Fault'],'FaultA','on','GroundFault','on', ...
      'FaultResistance','0.3','GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',tf,tf+0.015));
  elseif sc==7
    set_param([MODEL '/LV_AC_Fault'],'FaultA','on','FaultB','on','FaultC','on','GroundFault','on', ...
      'FaultResistance','0.3','GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',tf,tf+0.015));
  end
  set_param(MODEL,'StopTime',num2str(Tsim));
  out=sim(MODEL,'CaptureErrors','on');
  if ~isempty(out.ErrorMessage); fprintf('%d ERROR %s\n',sc,out.ErrorMessage); continue; end
  Vdc=out.V_dc(:); V2=squeeze(out.V2_abc); if size(V2,1)<size(V2,2); V2=V2.'; end
  I2=squeeze(out.I2_abc); if size(I2,1)<size(I2,2); I2=I2.'; end
  n=numel(Vdc); t=(0:n-1)'/fs; post=t>=tf;
  vll=sqrt(((real(V2(:,1))-real(V2(:,2))).^2+(real(V2(:,2))-real(V2(:,3))).^2+(real(V2(:,3))-real(V2(:,1))).^2)/3);
  pv=post(1:n); pi2=post(1:size(I2,1));
  fprintf('%6d %-9s %7.3f %7.3f %6.2f %7.1f\n', sc, cases{i,2}, ...
    min(Vdc(pv))/800, max(Vdc(pv))/800, max(abs(I2(pi2,:)),[],'all')/I2pk, min(vll(pv)));
end
fprintf('DONE\n');
