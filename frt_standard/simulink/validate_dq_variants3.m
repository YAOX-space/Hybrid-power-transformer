function validate_dq_variants3()
% validate_dq_variants.m — literature-grounded dq baseline comparison on the 32-scenario
% stratified subset. Modes: 4 = legacy dq (fixed proportional series, no lit. source),
% 5 = Song-style (no series action during FRT — lit. default for storage-less HPT),
% 6 = Jia-style (series derated by DC budget: full above Vdc 0.95pu, zero below 0.78pu).
% Same criteria as validate_frt_full / validate_hvrt. SAC mode-12 numbers come from the
% existing subset run (45.8% LVRT / 75% HVRT) for the final table.
here=fileparts(mfilename('fullpath')); cd(here);
modes=[8]; mlab={'MPC-mode8'};
Vnom=400*sqrt(2)/sqrt(3); M='hpt_frt_full';
crit={'connect','reactive','limit','recover','survive','frt'};

% ================= LVRT part =================
build_hpt_frt_full(4); set_param(M,'SimulationMode','normal');
A=readtable('../frt_scenarios_subset.csv','TextType','string'); A=A(A.category=="LVRT",:);
N=height(A);
emf=containers.Map('KeyType','double','ValueType','double');
rfa=containers.Map('KeyType','char','ValueType','double');
R=struct();
fprintf('\nLVRT %d scenarios x mode [8]\n',N);
for i=1:N
  ft=char(A.fault_type(i)); tV=A.target_V_pu(i); scr=A.scr(i);
  Rg=A.Rg_ohm(i); Lg=A.Lg_H(i); t_f=A.t_fault(i); dur=A.fault_dur(i); Tsim=min(A.T_sim(i),1.2);
  set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
  if ~isKey(emf,scr), emf(scr)=calib_emf(M,scr,Vnom); end
  set_param([M '/Grid'],'Voltage',num2str(emf(scr)));
  key=sprintf('%g_%g_%s',scr,tV,ft);
  if ~isKey(rfa,key), rfa(key)=calib_rfault(M,ft,tV,t_f,Tsim,Vnom); end
  cfg=ftcfg(ft); set_param(M,'StopTime',num2str(Tsim));
  set_param([M '/fclass'],'Value','1'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  row=sprintf('[%2d/%d] %-7s %.2f %3g |',i,N,ft,tV,scr);
  for k=1:1
    set_param([M '/mode'],'Value',num2str(modes(k)));
    set_fault(M,cfg,rfa(key),t_f,t_f+dur);
    o=sim(M); c=criteria(o,Tsim,t_f,dur,tV,Vnom);
    R.lv(i,k)=c; row=[row sprintf(' Vdc%.2f %s |',c.Vdcmin,tern(c.frt,'PASS','fail'))];
  end
  fprintf('%s\n',row);
end

% ================= HVRT part =================
build_hpt_frt_full(4,'swell'); set_param(M,'SimulationMode','normal');
B=readtable('../frt_scenarios_subset.csv','TextType','string'); B=B(B.category=="HVRT",:);
Nh=height(B);
base=containers.Map('KeyType','double','ValueType','double');
amp=containers.Map('KeyType','char','ValueType','double');
fprintf('\nHVRT %d scenarios x mode [8]\n',Nh);
for i=1:Nh
  ft=char(B.fault_type(i)); tV=B.target_V_pu(i); scr=B.scr(i); Rg=B.Rg_ohm(i); Lg=B.Lg_H(i);
  t_f=B.t_fault(i); dur=B.fault_dur(i); Tsim=min(B.T_sim(i),1.2); is1=strcmp(ft,'swell_1ph');
  set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
  if ~isKey(base,scr), base(scr)=calib_base(M,scr,Vnom); end
  set_param([M '/Grid'],'PositiveSequence',['[' num2str(base(scr)) ' 0 50]']);
  key=sprintf('%g_%g_%d',scr,tV,is1);
  if ~isKey(amp,key), amp(key)=calib_amp(M,tV,is1,t_f,Tsim,Vnom); end
  set_param([M '/fclass'],'Value','5'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(Tsim));
  row=sprintf('[%2d/%d] %-9s %.1f %3g |',i,Nh,ft,tV,scr);
  for k=1:1
    set_param([M '/mode'],'Value',num2str(modes(k)));
    set_swell(M,amp(key),is1,t_f,t_f+dur);
    o=sim(M); c=hvrt_criteria(o,Tsim,t_f,dur,tV,Vnom);
    R.hv(i,k)=c; row=[row sprintf(' %s |',tern(c.frt,'PASS','fail'))];
  end
  fprintf('%s\n',row);
end

% ================= summary =================
save('../results/dq_variants3_compare.mat','R','mlab');
fid=fopen('../results/dq_variants3_compare.txt','w');
emit=@(s)[fprintf('%s',s),fprintf(fid,'%s',s)];
emit(sprintf('\n=== dq baseline variants (subset 24 LVRT + 8 HVRT) ===\n'));
emit(sprintf('%-10s %18s %18s %18s\n','criterion',mlab{:}));
for c=1:6
  ln=sprintf('%-10s',crit{c});
  for k=1:1
    lv=100*mean(arrayfun(@(x)double(x.(crit{c})),R.lv(:,k)));
    ln=[ln sprintf('   LV %5.1f%%',lv)];
    hv=100*mean(arrayfun(@(x)double(x.(crit{c})),R.hv(:,k)));
    ln=[ln sprintf(' HV %5.1f%%',hv)];
  end
  emit([ln sprintf('\n')]);
end
for k=1:1
  lv=100*mean(arrayfun(@(x)double(x.frt),R.lv(:,k)));
  hv=100*mean(arrayfun(@(x)double(x.frt),R.hv(:,k)));
  all32=(lv*size(R.lv,1)+hv*size(R.hv,1))/(size(R.lv,1)+size(R.hv,1));
  emit(sprintf('%-22s LVRT %5.1f%%  HVRT %5.1f%%  ALL-32 %5.1f%%\n',mlab{k},lv,hv,all32));
end
fclose(fid); fprintf('\nsaved ../results/dq_variants3_compare.{mat,txt}\n');
end

% ---------- helpers (same as validate harnesses) ----------
function emfV=calib_emf(M,~,Vnom)
  set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
  set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
  o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
  emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom);
end
function Rf=calib_rfault(M,ft,tV,t_f,Tsim,Vnom)
  cfg=ftcfg(ft); set_param(M,'StopTime',num2str(min(Tsim,t_f+0.2)));
  set_param([M '/mode'],'Value','4'); best=30; berr=9;
  for Rc=[2 5 12 30 80 200]
    set_fault(M,cfg,Rc,t_f,t_f+0.12); o=sim(M); Vlv=o.get('Vlv_abc');
    tl=linspace(0,str2double(get_param(M,'StopTime')),size(Vlv,1))';
    res=mean_mag(Vlv,tl,t_f+0.05,t_f+0.10)/Vnom;
    if abs(res-tV)<berr, berr=abs(res-tV); best=Rc; end
  end
  Rf=best;
end
function V0=calib_base(M,~,Vnom)
  set_param([M '/Grid'],'VariationEntity','None'); set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime','0.30'); V0=10e3*1.125; set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
  o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))';
  V0=V0/max(0.5,max(abs(V(t>0.2,:)),[],'all')/Vnom);
end
function mlt=calib_amp(M,tV,is1,t_f,Tsim,Vnom)
  set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(min(Tsim,t_f+0.2))); best=tV; berr=9;
  for m=[tV-0.05 tV tV+0.08 tV+0.16]
    set_swell(M,m,is1,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc');
    t=linspace(0,str2double(get_param(M,'StopTime')),size(V,1))';
    vs=mean_mag(V,t,t_f+0.05,t_f+0.10)/Vnom; if abs(vs-tV)<berr, berr=abs(vs-tV); best=m; end
  end
  mlt=best;
end
function cfg=ftcfg(ft)
  switch ft
    case 'sym3ph', cfg=struct('A','on','B','on','C','on','G','on');
    case '1ph_g',  cfg=struct('A','on','B','off','C','off','G','on');
    case '2ph',    cfg=struct('A','on','B','on','C','off','G','off');
    case '2ph_g',  cfg=struct('A','on','B','on','C','off','G','on');
    otherwise,     cfg=struct('A','on','B','on','C','on','G','on');
  end
end
function set_fault(M,cfg,Rf,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function set_swell(M,m,is1,t1,t2)
  set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
    'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m,m), ...
    'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-1e-3,t1,t2,t2+1e-3), ...
    'VariationPhaseA',tern(is1,'on','off'));
end
function m=mean_mag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function c=criteria(o,Tsim,t_f,dur,tV,Vnom)
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  tL=linspace(0,Tsim,size(Vlv,1))'; tV2=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
  LVflt=mean_mag(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  LVpost=mean_mag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  Vdcmin=min(Vdc(tV2>=t_f&tV2<t_f+dur))/800; Vdcmax=max(Vdc(tV2>=t_f&tV2<t_f+dur+0.1))/800;
  iqf=mean(dq(tq>=t_f&tq<t_f+dur,2))/173.2;
  iqref=min(0.3,max(0,1.5*(0.9-LVflt)));
  c.connect=LVflt>=tV-0.07; c.reactive=abs(iqf-iqref)<=0.12;
  c.limit=max(abs(dq(:,2)))/173.2<=0.35; c.recover=abs(1-LVpost)<=0.07;
  c.survive=(Vdcmin>=0.75)&&(Vdcmax<=1.25);
  c.frt=c.connect&&c.reactive&&c.limit&&c.recover&&c.survive;
  c.Vdcmin=Vdcmin; c.Vdcmax=Vdcmax; c.LVflt=LVflt;
end
function c=hvrt_criteria(o,Tsim,t_f,dur,~,Vnom)
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  tL=linspace(0,Tsim,size(Vlv,1))'; tV2=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
  Vsw=mean_mag(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  Vpost=mean_mag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  Vdcmax=max(Vdc(tV2>=t_f&tV2<t_f+dur+0.1))/800; Vdcmin=min(Vdc(tV2>=t_f&tV2<t_f+dur))/800;
  iqf=mean(dq(tq>=t_f&tq<t_f+dur,2))/173.2;
  iqref=max(-0.3,min(0,-1.5*(Vsw-1.1)));
  c.connect=Vsw<=1.35; c.reactive=abs(iqf-iqref)<=0.12;
  c.limit=max(abs(dq(:,2)))/173.2<=0.35; c.recover=abs(1-Vpost)<=0.07;
  c.survive=(Vdcmin>=0.75)&&(Vdcmax<=1.25);
  c.frt=c.connect&&c.reactive&&c.limit&&c.recover&&c.survive;
  c.Vdcmin=Vdcmin; c.Vdcmax=Vdcmax; c.Vsw=Vsw;
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
