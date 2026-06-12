function diag_cause()
% diag_cause.m — in Simulink, isolate WHICH actuator command collapses Vdc on a mild 1ph_g
% (dq survives Vdc 0.76, asym expert collapses 0.58). Uses mode 10 to inject fixed setpoints.
% HLC mode-10 mapping: iq_ref_applied = blk(iq_ref);  mse_d_applied = -blk(mse_d);  mse_q_applied = -blk(mse_q)
% We parametrize by the action vector a=[a1(unused) a2(iq) a3 a4] and set blocks to replicate HLC:
%   blk(iq_ref)=a2*173.2 ;  blk(mse_d)=-a3 ;  blk(mse_q)=-a4
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Vnom=326.6; Imax=173.2;
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.625; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));

% EMF calib
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom); set_param([M '/Grid'],'Voltage',num2str(emfV));

% 1ph_g R_fault calib to ~0.81 residual
cfg=struct('A','on','B','off','C','off','G','on');
set_param(M,'StopTime',num2str(t_f+0.2)); cand=[2 5 12 30 80 200]; best=12;
set_fault(M,cfg,best,t_f,t_f+dur);

% scenarios: [a2(iq)  a3   a4   label]
S = { 0,     0,    0,   'nothing (iq=0,mse=0)';
      0.15,  0,    0,   'dq-like reactive (iq=+0.15)';
      0.28,  0,    0,   'strong reactive (iq=+0.28)';
     -0.04,  0,    0,   'asym reactive only (iq=-0.04)';
      0,     0.19, 0,   'series-d only (mse_d=-0.19)';
      0,     0,    0.16,'series-q only (mse_q=-0.16)';
     -0.04,  0.19, 0.16,'ASYM replica (iq-0.04,mse 0.19/0.16)';
      0.28,  0.07, 0.05,'SYM replica  (iq+0.28,mse 0.07/0.05)'};

fprintf('\n1ph_g mild fault (dq baseline survives ~0.76). mode-10 fixed setpoints:\n');
fprintf('%-38s | %-7s %-7s %-6s\n','command','Vdcmin','Vdcmax','LVflt');
fprintf('%s\n',repmat('-',64,1));
set_param([M '/mode'],'Value','10'); set_param(M,'StopTime',num2str(Tsim));
set_fault(M,cfg,best,t_f,t_f+dur);
for k=1:size(S,1)
  a2=S{k,1}; a3=S{k,2}; a4=S{k,3};
  set_param([M '/iq_ref'],'Value',num2str(a2*Imax));
  set_param([M '/mse_d'],'Value',num2str(-a3));
  set_param([M '/mse_q'],'Value',num2str(-a4));
  o=sim(M); Vdc=o.get('Vdc'); nV=numel(Vdc); tV=linspace(0,Tsim,nV)';
  Vlv=o.get('Vlv_abc'); tL=linspace(0,Tsim,size(Vlv,1))';
  vmin=min(Vdc(tV>=t_f&tV<t_f+dur))/800; vmax=max(Vdc(tV>=t_f&tV<t_f+dur+0.1))/800;
  lvf=seqpos(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  fprintf('%-38s | %6.3f  %6.3f  %5.3f %s\n', S{k,4}, vmin,vmax,lvf, tern(vmin>=0.75,'surv','COLLAPSE'));
end
fprintf('\nAttribution: compare which single command drives Vdcmin below 0.75.\n');
end
function set_fault(M,cfg,Rf,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function m=seqpos(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
