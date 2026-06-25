function diag_deepsag()
% diag_deepsag.m — Phase-2 W2 device-depth spot check: does m14-v2 survive LOCAL sags of
% 0.05-0.15 pu (network-fault regime, below the phase-1 scenario floor of 0.2)?
% sym3ph weak grid, mode 14. Criteria as usual; connect is trivially true at these depths
% (tV-0.07 <= 0.08), the real questions are survive/limit/reactive/recover.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Vnom=400*sqrt(2)/sqrt(3);
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.4; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
% EMF calib
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom); set_param([M '/Grid'],'Voltage',num2str(emfV));

cfg=struct('A','on','B','on','C','on','G','on');
fprintf('\nm14-v2 deep-sag spot check (sym3ph, weak grid, dur=%.1fs):\n', dur);
fprintf('%6s | %5s | %7s %7s %7s %7s %7s | %s\n','target','LVflt','connect','reactive','limit','recover','survive','FRT');
for tV=[0.05 0.10 0.15]
  % calibrate R_fault with extended low-R candidates
  set_param([M '/mode'],'Value','4'); set_param(M,'StopTime',num2str(t_f+0.2));
  best=2; berr=9;
  for R=[0.3 0.7 1.2 2 3.5 5]
    set_fault(M,cfg,R,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,t_f+0.2,size(V,1))';
    res=mmag(V,tt,t_f+0.05,t_f+0.10)/Vnom; if abs(res-tV)<berr, berr=abs(res-tV); best=R; end
  end
  set_param(M,'StopTime',num2str(Tsim)); set_fault(M,cfg,best,t_f,t_f+dur);
  set_param([M '/fclass'],'Value','1'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/mode'],'Value','14');
  o=sim(M);
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  tL=linspace(0,Tsim,size(Vlv,1))'; tV2=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
  LVflt=mmag(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  LVpost=mmag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  Vdcmin=min(Vdc(tV2>=t_f&tV2<t_f+dur))/800; Vdcmax=max(Vdc(tV2>=t_f&tV2<t_f+dur+0.1))/800;
  iqf=mean(dq(tq>=t_f&tq<t_f+dur,2))/pu_params().I_dq_base_peak; iqr=min(0.3,max(0,1.5*(0.9-LVflt)));
  c1=LVflt>=tV-0.07; c2=abs(iqf-iqr)<=0.12; c3=max(abs(dq(:,2)))/pu_params().I_dq_base_peak<=0.35;
  c4=abs(1-LVpost)<=0.07; c5=(Vdcmin>=0.75)&&(Vdcmax<=1.25);
  frt=c1&&c2&&c3&&c4&&c5;
  fprintf('%6.2f | %5.3f | %7d %7d %7d %7d %7d | %s   (Vdc[%.2f,%.2f] iq=%.2f/ref%.2f)\n', ...
    tV,LVflt,c1,c2,c3,c4,c5,tern(frt,'PASS','FAIL'),Vdcmin,Vdcmax,iqf,iqr);
end
end
function set_fault(M,cfg,Rf,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function m=mmag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
