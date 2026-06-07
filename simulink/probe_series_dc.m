%% probe_series_dc.m — map series modulation (m_se_d, m_se_q) -> DC bus & V2 in Simulink
run('parameters.m'); MODEL='hpt_switching_model';
if ~bdIsLoaded(MODEL); load_system('hpt_switching_model.slx'); end
set_param(MODEL,'SimulationMode','normal'); set_param(MODEL,'FastRestart','off');
tf=0.02;
set_param([MODEL '/Sc_id'],'Value','0'); set_param([MODEL '/T_fault'],'Value',num2str(tf));
set_param([MODEL '/ControllerMode'],'Value','9');
set_param([MODEL '/RL_Energy_Bias'],'Value','0.82');
set_param([MODEL '/LV_Load'],'ActivePower','320e3','InductivePower','80e3','CapacitivePower','0');
set_param([MODEL '/LV_AC_Fault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param([MODEL '/DC_Link_Capacitor'],'Capacitance','2200e-6','InitialVoltage','800');
set_param(MODEL,'StopTime','0.08');

md_list=[-0.20 -0.10 0 0.10 0.20];
mq_list=[-0.20 0 0.20];
fprintf('m_se_d sweep (m_se_q=0, m_sh=0.82):\n  m_se_d   Vdc_end  V2ll_end\n');
for md=md_list
  set_param([MODEL '/RL_Reg_Bias'],'Value',num2str(md));
  set_param([MODEL '/RL_Current_Bias'],'Value','0');
  o=sim(MODEL,'CaptureErrors','on');
  if ~isempty(o.ErrorMessage); fprintf('  %+.2f ERROR\n',md); continue; end
  V=o.V_dc(:); V2=squeeze(o.V2_abc); if size(V2,1)<size(V2,2); V2=V2.'; end
  vll=sqrt(((real(V2(:,1))-real(V2(:,2))).^2+(real(V2(:,2))-real(V2(:,3))).^2+(real(V2(:,3))-real(V2(:,1))).^2)/3);
  fprintf('  %+.2f   %7.1f  %7.1f\n',md,V(end),vll(end));
end
fprintf('m_se_q sweep (m_se_d=0):\n  m_se_q   Vdc_end  V2ll_end\n');
for mq=mq_list
  set_param([MODEL '/RL_Reg_Bias'],'Value','0');
  set_param([MODEL '/RL_Current_Bias'],'Value',num2str(mq));
  o=sim(MODEL,'CaptureErrors','on');
  if ~isempty(o.ErrorMessage); fprintf('  %+.2f ERROR\n',mq); continue; end
  V=o.V_dc(:); V2=squeeze(o.V2_abc); if size(V2,1)<size(V2,2); V2=V2.'; end
  vll=sqrt(((real(V2(:,1))-real(V2(:,2))).^2+(real(V2(:,2))-real(V2(:,3))).^2+(real(V2(:,3))-real(V2(:,1))).^2)/3);
  fprintf('  %+.2f   %7.1f  %7.1f\n',mq,V(end),vll(end));
end
fprintf('DONE\n');
