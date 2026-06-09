function validate_hvrt(nmax)
% validate_hvrt.m — HVRT (voltage-swell ride-through) comparison dq vs closed-loop SAC
% on the COMPLETE HPT model built with gridmode='swell' (programmable source + series Z).
% Swell imposed at target 1.2/1.3 pu; 3φ = balanced amplitude step, 1ph = phase-A only.
% HVRT criteria: connect / reactive(absorb) / limit / recover / survive(Vdc≤1.25 binding).
if nargin<1, nmax=inf; end
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4,'swell');
M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
A=readtable('../frt_scenarios.csv','TextType','string');
A=A(A.category=="HVRT",:);
N=min(height(A),nmax); Vnom=400*sqrt(2)/sqrt(3);
base=containers.Map('KeyType','double','ValueType','double');   % per-SCR EMF base amplitude
amp =containers.Map('KeyType','char','ValueType','double');     % per (scr,target,type) amplitude mult
results=struct([]);
fprintf('\n%-9s %4s %3s | %-20s | %-20s\n','swell','V','scr','dq','SAC'); fprintf('%s\n',repmat('-',66,1));
for i=1:N
  ft=char(A.fault_type(i)); tV=A.target_V_pu(i); scr=A.scr(i); Rg=A.Rg_ohm(i); Lg=A.Lg_H(i);
  t_f=A.t_fault(i); dur=A.fault_dur(i); Tsim=min(A.T_sim(i),1.2);
  is1ph=strcmp(ft,'swell_1ph');
  set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
  if ~isKey(base,scr), base(scr)=calib_base(M,scr,Vnom); end
  V0=base(scr); set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
  key=sprintf('%g_%g_%d',scr,tV,is1ph);
  if ~isKey(amp,key), amp(key)=calib_amp(M,tV,is1ph,t_f,dur,Tsim,Vnom); end
  set_swell(M,amp(key),is1ph,t_f,t_f+dur);
  fcl=5; set_param([M '/fclass'],'Value','5');  % swell class index
  set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(Tsim));
  out=struct();
  for md=[4 11]
    set_param([M '/mode'],'Value',num2str(md));
    o=sim(M); c=hvrt_criteria(o,Tsim,t_f,dur,tV,Vnom);
    if md==4, out.dq=c; else, out.sac=c; end
  end
  results(i).ft=ft; results(i).tV=tV; results(i).scr=scr; results(i).dq=out.dq; results(i).sac=out.sac;
  fprintf('[%2d/%d] %-9s %.1f %3g | Vsw%.2f Vdc%.2f %s | Vsw%.2f Vdc%.2f %s\n', i,N, ft,tV,scr, ...
    out.dq.Vsw,out.dq.Vdcmax,pm(out.dq), out.sac.Vsw,out.sac.Vdcmax,pm(out.sac));
  if mod(i,5)==0, save('../results/hvrt_compare_partial.mat','results','i'); end
end
crit={'connect','reactive','limit','recover','survive','frt'};
save('../results/hvrt_compare.mat','results');
fid=fopen('../results/hvrt_compare.txt','w');
emit=@(s)[fprintf('%s',s),fprintf(fid,'%s',s)];
emit(sprintf('\n=== HVRT (%d scenarios): SAC vs dq ===\n',N));
emit(sprintf('%-9s %8s %8s\n','criterion','dq','SAC'));
for k=1:numel(crit)
  dqp=100*mean(arrayfun(@(r)double(r.dq.(crit{k})),results));
  scp=100*mean(arrayfun(@(r)double(r.sac.(crit{k})),results));
  emit(sprintf('%-9s %7.1f%% %7.1f%%\n',crit{k},dqp,scp));
end
fclose(fid); fprintf('\nsaved ../results/hvrt_compare.{mat,txt}\n');
end

function V0=calib_base(M,scr,Vnom)
  set_param([M '/Grid'],'VariationEntity','None'); set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime','0.30'); V0=10e3*1.125; set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
  o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))'; lv=max(abs(V(t>0.2,:)),[],'all')/Vnom;
  V0=V0/max(0.5,lv);
end

function mlt=calib_amp(M,tV,is1ph,t_f,dur,Tsim,Vnom)
  set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(min(Tsim,t_f+0.2))); best=tV; berr=9;
  for m=[tV-0.05 tV tV+0.08 tV+0.16]
    set_swell(M,m,is1ph,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,str2double(get_param(M,'StopTime')),size(V,1))';
    vs=seqmag(V,t,t_f+0.05,t_f+0.10)/Vnom; if abs(vs-tV)<berr, berr=abs(vs-tV); best=m; end
  end
  mlt=best;
end

function set_swell(M,m,is1ph,t1,t2)
  set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
    'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m,m), ...
    'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-1e-3,t1,t2,t2+1e-3), ...
    'VariationPhaseA', tern(is1ph,'on','off'));
end
function s=tern(c,a,b), if c, s=a; else, s=b; end, end

function c=hvrt_criteria(o,Tsim,t_f,dur,tV,Vnom)
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  nL=size(Vlv,1); tL=linspace(0,Tsim,nL)'; nV=numel(Vdc); tVv=linspace(0,Tsim,nV)'; nq=size(dq,1); tq=linspace(0,Tsim,nq)';
  Vsw=seqmag(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  Vpost=seqmag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  Vdcmax=max(Vdc(tVv>=t_f & tVv<t_f+dur+0.1))/800; Vdcmin=min(Vdc(tVv>=t_f & tVv<t_f+dur))/800;
  iqf=mean(dq(tq>=t_f & tq<t_f+dur,2))/173.2;
  iqref=max(-0.3,min(0,-1.5*(Vsw-1.1)));        % HVRT: absorb (negative) reactive
  c.connect=Vsw<=1.35;                           % rode the swell, stayed bounded
  c.reactive=abs(iqf-iqref)<=0.12;
  c.limit=max(abs(dq(:,2)))/173.2<=0.35;
  c.recover=abs(1-Vpost)<=0.07;
  c.survive=(Vdcmin>=0.75)&&(Vdcmax<=1.25);
  c.frt=c.connect&&c.reactive&&c.limit&&c.recover&&c.survive;
  c.Vsw=Vsw; c.Vdcmax=Vdcmax; c.Vdcmin=Vdcmin;
end
function m=seqmag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function s=pm(c), if c.frt, s='PASS'; else, s='fail'; end, end
