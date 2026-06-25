function sim_compare()
% sim_compare.m — Simulink side of the ODE-vs-Simulink head-to-head. mode-10 fixed setpoints,
% sym3ph at 3 depths x 3 reactive levels (no series), then series sweep. Record Vdc_min during fault.
% Matched 1:1 with env_compare.py.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
p=pu_params(); Vnom=p.VLN_peak; Imax=p.I_pe_rms;  % single-source (P3: peak-base redesign deferred)
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.625; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
cfg=struct('A','on','B','on','C','on','G','on');   % sym3ph
% EMF calib
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom); set_param([M '/Grid'],'Voltage',num2str(emfV));

depths=[0.75 0.50 0.20]; Rf=zeros(1,3);
for i=1:3, Rf(i)=calib(M,cfg,depths(i),t_f,Vnom); end

fprintf('\n=== Simulink (mode-10): sym3ph, fixed [iq, no series] ===\n');
fprintf('%6s | %7s %8s %8s\n','depth','iq=0.0','iq=0.15','iq=0.30');
set_param([M '/mode'],'Value','10'); set_param(M,'StopTime',num2str(Tsim));
for i=1:3
  set_fault(M,cfg,Rf(i),t_f,t_f+dur); row=zeros(1,3); iqs=[0 0.15 0.30];
  for j=1:3
    set_param([M '/iq_ref'],'Value',num2str(iqs(j)*Imax));
    set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
    row(j)=vdcmin(M,t_f,dur,Tsim);
  end
  fprintf('%6.2f | %7.3f %8.3f %8.3f\n',depths(i),row(1),row(2),row(3));
end
fprintf('\n=== Simulink: sym3ph 0.50, effect of series (iq=0.15) ===\n');
set_fault(M,cfg,Rf(2),t_f,t_f+dur);
% NOTE (2026-06-17): the mode-10 HLC outputs controller mse_d = -block; the ODE convention is
% +m_se_d = boost. So to emulate the ODE's +ms boost (which drains Vdc per the 1.9 coeff) the
% block must be set POSITIVE (+ms), not -ms. A prior version used -ms here, which silently tested
% the BUCK direction (no drain) and made the head-to-head look broken. Fixed to +ms.
for ms=[0 0.10 0.20]
  set_param([M '/iq_ref'],'Value',num2str(0.15*Imax));
  set_param([M '/mse_d'],'Value',num2str(ms)); set_param([M '/mse_q'],'Value','0');
  fprintf('  series mse_d=%.2f -> Vdc_min=%.3f\n',ms,vdcmin(M,t_f,dur,Tsim));
end
end
function v=vdcmin(M,t_f,dur,Tsim)
  o=sim(M); Vdc=o.get('Vdc'); n=numel(Vdc); tv=linspace(0,Tsim,n)';
  v=min(Vdc(tv>=t_f+0.02 & tv<t_f+dur))/800;
end
function Rf=calib(M,cfg,tV,t_f,Vnom)
  set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
  set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(t_f+0.2)); cand=[2 5 12 30 80 200]; best=12; berr=9;
  for R=cand
    set_fault(M,cfg,R,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,t_f+0.2,size(V,1))';
    idx=tt>=t_f+0.05&tt<t_f+0.10; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
    al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); res=mean(sqrt(al.^2+be.^2))/Vnom;
    if abs(res-tV)<berr, berr=abs(res-tV); best=R; end
  end
  Rf=best;
end
function set_fault(M,cfg,Rf,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
