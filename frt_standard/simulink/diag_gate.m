function diag_gate()
% diag_gate.m — diagnose the Mode-12 online gate (V2n>0.05) reliability on asym faults.
% Runs representative 1ph_g scenarios at mode 4 (dq), reconstructs V2n(t) with the EXACT
% T/4 sequence extraction used inside the HLC, and reports whether the gate would robustly
% route to the asym expert (V2n>0.05) or mis-fire / flicker.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4);
M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Ts=20e-6; Vnom=326.6;

% representative 1ph_g scenarios at scr=3 (weak grid): shallow / medium / deep
targets=[0.75 0.5 0.2];
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.625; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));

% calibrate EMF so pre-fault LV = 1.0 pu
set_param([M '/mode'],'Value','4');
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35');
V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
lvpu=max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom; emfV=V0/max(0.5,lvpu);
set_param([M '/Grid'],'Voltage',num2str(emfV));
fprintf('EMF calibrated: %.0f V (pre-fault LV=%.3f pu)\n', emfV, lvpu);

fprintf('\n%-6s | %-30s | %-28s\n','tgtV','V2n during fault (min/mean/max)','gate verdict');
fprintf('%s\n',repmat('-',72,1));
for tV=targets
  % calibrate R_fault for 1ph_g to hit target residual LV
  set_param(M,'StopTime',num2str(t_f+0.2));
  cand=[2 5 12 30 80 200]; best=30; berr=9;
  for R=cand
    set_param([M '/GridFault'],'FaultA','on','FaultB','off','FaultC','off','GroundFault','on', ...
      'FaultResistance',num2str(R),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t_f,t_f+0.12));
    o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,t_f+0.2,size(V,1))';
    res=seqpos(V,tt,t_f+0.05,t_f+0.10)/Vnom; if abs(res-tV)<berr,berr=abs(res-tV);best=R;end
  end
  Rf=best;
  % full run at mode 4
  set_param(M,'StopTime',num2str(Tsim));
  set_param([M '/GridFault'],'FaultA','on','FaultB','off','FaultC','off','GroundFault','on', ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t_f,t_f+dur));
  o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,Tsim,size(V,1))';

  % --- replicate HLC T/4 sequence extraction on a 20us grid ---
  tg=(0:Ts:Tsim)'; Vg=interp1(tt,V,tg,'linear','extrap');
  N=numel(tg); NB=250; ba=zeros(NB,1); bb=zeros(NB,1); bi=1;
  V2n=zeros(N,1); V2p=zeros(N,1);
  for k=1:N
    Va=Vg(k,1); Vb=Vg(k,2); Vc=Vg(k,3);
    Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);
    Vad=ba(bi); Vbd=bb(bi); ba(bi)=Valpha; bb(bi)=Vbeta; bi=bi+1; if bi>NB,bi=1;end
    V1a=0.5*(Valpha-Vbd); V1b=0.5*(Vbeta+Vad);
    V2a=0.5*(Valpha+Vbd); V2b=0.5*(Vbeta-Vad);
    V2p(k)=sqrt(V1a*V1a+V1b*V1b)/Vnom; V2n(k)=sqrt(V2a*V2a+V2b*V2b)/Vnom;
  end
  % analyze during fault (skip first 6ms for buffer/transient settle)
  win = tg>=t_f+0.006 & tg<t_f+dur;
  v2n_f=V2n(win);
  frac_below=mean(v2n_f<=0.05)*100;
  % flicker: sign changes of (V2n-0.05) within fault
  s=sign(v2n_f-0.05); flips=sum(abs(diff(s))>0);
  if frac_below>50, verdict=sprintf('MISFIRE→sym (%.0f%% below)',frac_below);
  elseif frac_below>1 || flips>5, verdict=sprintf('FLICKER (%.0f%% below,%d flips)',frac_below,flips);
  else, verdict=sprintf('OK asym (%.0f%% below)',frac_below); end
  fprintf('%-6.2f | %5.3f / %5.3f / %5.3f%14s | %s\n', tV, min(v2n_f),mean(v2n_f),max(v2n_f),'', verdict);
end
fprintf('\n(gate routes to asym expert iff V2n>0.05; sym expert otherwise)\n');
end

function m=seqpos(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
