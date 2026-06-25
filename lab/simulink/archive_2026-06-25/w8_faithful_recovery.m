function w8_faithful_recovery()
% w8_faithful_recovery.m — FAITHFUL (switching-level) test of the REAL m14-v2 SAC under
% NETWORK-specific conditions the phase-1 320 never covered, on the authoritative model:
%   (1) ultra-deep sags 0.05-0.15 (phase-1 floor was 0.2);
%   (2) SLOW recovery window (voltage rebounds 0.6->1.0 over ~1 s, FIDVR-like) instead of the
%       instant snap-back phase-1 used.
% Uses the programmable-source ('swell' gridmode) for an arbitrary amplitude-vs-time profile.
% Catches what OpenDSS quasi-static could NOT: 2ω/measured-peak ripple (limit), Vdc transient,
% recovery-window behavior. mode 14 = real residual-SAC.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4,'swell'); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
p=pu_params(); Vnom=p.VLN_peak; Imax=p.I_pe_rms;  % single-source (P3 peak-base deferred)
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
% EMF base calib (programmable source so pre-fault LV=1.0)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/Grid'],'VariationEntity','None'); set_param(M,'StopTime','0.3');
V0=10e3*1.125; set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.3,size(V,1))';
lv=max(abs(V(t>0.2,:)),[],'all')/Vnom; V0=V0/max(0.5,lv);
set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
fprintf('base EMF=%.0f V; LV pre-fault=%.3f\n', V0, lv);

t_f=0.10; Tsim=1.6;
fprintf('\n%6s | %-22s | %5s %5s %5s %5s %5s | %s\n','sag','profile','con','rea','lim','rec','sur','FRT');
profs = {
  struct('tV',0.10,'recov',0.0,'name','deep 0.10, instant recov'), ...
  struct('tV',0.10,'recov',1.0,'name','deep 0.10, SLOW recov 1s'), ...
  struct('tV',0.20,'recov',1.0,'name','0.20, slow recov 1s'), ...
  struct('tV',0.35,'recov',1.0,'name','0.35, slow recov 1s'), ...
  struct('tV',0.50,'recov',1.0,'name','0.50, slow recov 1s')};
for k=1:numel(profs)
  p=profs{k}; dur=0.30;
  % amplitude table: 1 (pre), tV (during fault), then ramp tV->1 over recov, then 1
  if p.recov<=0
    amps=sprintf('[1 1 %.3f %.3f 1 1]',p.tV,p.tV);
    tms =sprintf('[0 %.4f %.4f %.4f %.4f %.4f]',t_f-1e-3,t_f,t_f+dur,t_f+dur+1e-3,Tsim-0.1);
  else
    amps=sprintf('[1 1 %.3f %.3f 1 1]',p.tV,p.tV);
    tms =sprintf('[0 %.4f %.4f %.4f %.4f %.4f]',t_f-1e-3,t_f,t_f+dur,t_f+dur+p.recov,Tsim-0.1);
  end
  set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
    'Amplitudes',amps,'TimeValues',tms,'VariationPhaseA','off');
  set_param([M '/fclass'],'Value','1'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param([M '/mode'],'Value','14'); set_param(M,'StopTime',num2str(Tsim));
  o=sim(M);
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  tL=linspace(0,Tsim,size(Vlv,1))'; tV2=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
  LVf=mmag(Vlv,tL,t_f+0.1*dur,t_f+0.9*dur)/Vnom;
  LVpost=mmag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  win=tV2>=t_f & tV2<t_f+dur+max(0,p.recov);     % include recovery window in Vdc check
  Vdcmin=min(Vdc(win))/800; Vdcmax=max(Vdc(win))/800;
  iqf=mean(dq(tq>=t_f&tq<t_f+dur,2))/pu_params().I_dq_base_peak; iqr=min(0.3,max(0,1.5*(0.9-LVf)));
  iqpk=max(abs(dq(:,2)))/pu_params().I_dq_base_peak;
  c1=LVf>=p.tV-0.07; c2=abs(iqf-iqr)<=0.12; c3=iqpk<=0.35; c4=abs(1-LVpost)<=0.07;
  c5=(Vdcmin>=0.75)&&(Vdcmax<=1.25); frt=c1&&c2&&c3&&c4&&c5;
  fprintf('%6.2f | %-22s | %5d %5d %5d %5d %5d | %s  (iqpk%.2f Vdc[%.2f,%.2f])\n', ...
    p.tV,p.name,c1,c2,c3,c4,c5,tern(frt,'PASS','FAIL'),iqpk,Vdcmin,Vdcmax);
end
fprintf('\n(switching-level; ripple/limit/Vdc-transient now IN the loop — the axes OpenDSS could not see)\n');
end
function m=mmag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
