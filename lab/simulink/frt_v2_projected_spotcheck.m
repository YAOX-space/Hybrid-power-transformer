function frt_v2_projected_spotcheck(sids)
% frt_v2_projected_spotcheck — SMALL switching spotcheck of the deployment-side reactive projection.
% For each selected reactive-FAIL scenario it runs the SAME calibrated fault TWICE: mode 14 (baseline,
% deployed residual SAC) and mode 16 (= mode 14 + reactive sign-consistent dead-band, see
% build_hpt_frt_full.m / src/hpt_frt/device/safety_projection.py), evaluates both with the authoritative
% frt_v2_evaluate, and compares. This is a SPOTCHECK, NOT full-320; it never touches p3_full320_sw_mi14.
%   default sids = [161 171 224 227 311 312] (2ph scr10/scr3, 2ph_g scr10, swell_1ph scr3).
here=fileparts(mfilename('fullpath')); cd(here); p=pu_params(); M='hpt_frt_full';
if nargin<1, sids=[161 171 224 227 311 312]; end
fp=jsondecode(fileread('../results/p3_scenario_faultparams.json'));
cfg=containers.Map({'sym3ph','1ph_g','2ph','2ph_g'},{[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});
% order so each (grid-mode, scr) builds once
meta=arrayfun(@(s) getfield(fp,sprintf('x%d',s)), sids);
isH=arrayfun(@(m) strcmp(m.category,'HVRT'), meta);
key=double(isH)*100 + arrayfun(@(m) m.scr, meta); [~,o]=sort(key); sids=sids(o); meta=meta(o);

rows=struct([]); curbuild='';
for n=1:numel(sids)
  sid=sids(n); m=meta(n); isHv=strcmp(m.category,'HVRT'); scr=m.scr;
  bkey=sprintf('%d_%g',isHv,scr);
  if ~strcmp(bkey,curbuild)
    if isHv, build_hpt_frt_full(4,'swell'); else, build_hpt_frt_full(4); end
    set_param(M,'SimulationMode','normal');
    if scr==10, Rg=7.9057; Lg=0.075494; else, Rg=26.3523; Lg=0.251646; end
    if isHv, set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
    else,    set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg)); end
    curbuild=bkey;
  end
  tf=0.08; dur=min(m.fault_dur,0.5);
  set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(tf));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(tf+dur+0.35));
  if isHv
    is1=strcmp(m.fault_type,'swell_1ph');
    set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
      'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m.fault_param,m.fault_param), ...
      'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',tf-1e-3,tf,tf+dur,tf+dur+1e-3),'VariationPhaseA',oo(is1));
  else
    c=cfg(m.fault_type);
    set_param([M '/GridFault'],'FaultA',oo(c(1)),'FaultB',oo(c(2)),'FaultC',oo(c(3)),'GroundFault',oo(c(4)), ...
      'FaultResistance',num2str(m.fault_param),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',tf,tf+dur));
  end
  % BASELINE mode 14 vs PROJECTED mode 16 (identical fault)
  set_param([M '/mode'],'Value','14'); ob=sim(M); [rb,wb,iqb]=eval_case(ob,tf,dur,m.category,p);
  set_param([M '/mode'],'Value','16'); op=sim(M); [rp,wp,iqp]=eval_case(op,tf,dur,m.category,p);
  rows(n).sid=sid; rows(n).ft=m.fault_type; rows(n).cat=m.category; rows(n).scr=scr; rows(n).Vg_p=m.Vg_p;
  rows(n).base=rb; rows(n).proj=rp; rows(n).wrong_base=wb; rows(n).wrong_proj=wp;
  rows(n).iq_base=iqb; rows(n).iq_proj=iqp;
  fprintf(['sid%3d %-9s scr%g V+=%.3f | BASE rea=%-4s frt=%-5s wrong=%d | PROJ rea=%-4s frt=%-5s wrong=%d ' ...
           '| iq(base med=%.3f) (proj med=%.3f)\n'], sid, m.fault_type, scr, m.Vg_p, ...
           rb.reactive.status(1:min(4,end)), rb.frt_pass_str, wb, rp.reactive.status(1:min(4,end)), rp.frt_pass_str, wp, iqb, iqp);
end
% save (NEW files only; never p3_full320_sw_mi14)
S.rows=rows; S.metrics_version='frt-v2'; S.note='projected spotcheck (mode16=mode14+reactive dead-band); NOT full-320';
save('../results/projection_spotcheck_reactive.mat','-struct','S');
% ---- per-criterion comparison -> JSON + CSV (NEW files only) ----
crits={'connect','reactive','limit','recover','survive'};
cmp=struct([]);
for n=1:numel(rows)
  r=rows(n); cs=struct(); cs.sid=r.sid; cs.fault_type=r.ft; cs.category=r.cat; cs.scr=r.scr; cs.Vg_p=r.Vg_p;
  cs.base_frt=r.base.frt_pass_str; cs.proj_frt=r.proj.frt_pass_str;
  cs.base_wrong_sign=double(r.wrong_base); cs.proj_wrong_sign=double(r.wrong_proj);
  cs.iq_base_med=r.iq_base; cs.iq_proj_med=r.iq_proj;
  nf={};
  for k=1:numel(crits), cc=crits{k};
    bs=r.base.(cc).status; ps=r.proj.(cc).status;
    cs.(['base_' cc])=bs; cs.(['proj_' cc])=ps;
    if ~strcmp(cc,'reactive') && ~strcmp(bs,'FAIL') && strcmp(ps,'FAIL'), nf{end+1}=cc; end %#ok<AGROW>
  end
  cs.new_fail_criteria=strjoin(nf,';');
  cs.reactive_fixed=double(strcmp(r.base.reactive.status,'FAIL') && ~strcmp(r.proj.reactive.status,'FAIL'));
  if isempty(cmp), cmp=cs; else, cmp(n)=cs; end %#ok<AGROW>
end
J.metrics_version='frt-v2';
J.note=['SMALL switching spotcheck of the deployment-side reactive projection (mode16=mode14+sign dead-band). ' ...
        'NOT a full-320 run; does NOT modify p3_full320_sw_mi14/mi7 or the certified result. ' ...
        'no-fail/effective is NOT a strict grid-code pass rate; NOT_EVALUATED is never counted as PASS.'];
J.baseline_mode=14; J.projected_mode=16; J.n_scenarios=numel(cmp); J.scenarios=cmp;
fid=fopen('../results/projection_spotcheck_reactive.json','w'); fwrite(fid,jsonencode(J)); fclose(fid);
hdr={'sid','fault_type','category','scr','Vg_p','base_frt','proj_frt','base_reactive','proj_reactive', ...
     'base_wrong_sign','proj_wrong_sign','reactive_fixed','new_fail_criteria','iq_base_med','iq_proj_med', ...
     'base_connect','proj_connect','base_limit','proj_limit','base_recover','proj_recover','base_survive','proj_survive'};
fid=fopen('../results/projection_spotcheck_reactive.csv','w'); fprintf(fid,'%s\n',strjoin(hdr,','));
for n=1:numel(cmp), c=cmp(n);
  fprintf(fid,'%d,%s,%s,%g,%.4f,%s,%s,%s,%s,%d,%d,%d,%s,%.4f,%.4f,%s,%s,%s,%s,%s,%s,%s,%s\n', ...
    c.sid,c.fault_type,c.category,c.scr,c.Vg_p,c.base_frt,c.proj_frt,c.base_reactive,c.proj_reactive, ...
    c.base_wrong_sign,c.proj_wrong_sign,c.reactive_fixed,c.new_fail_criteria,c.iq_base_med,c.iq_proj_med, ...
    c.base_connect,c.proj_connect,c.base_limit,c.proj_limit,c.base_recover,c.proj_recover,c.base_survive,c.proj_survive);
end
fclose(fid);
fprintf('wrote ../results/projection_spotcheck_reactive.{mat,json,csv} (%d scenarios)\n', numel(rows));
end

function [res,wrong,iqmed]=eval_case(o,t_f,dur,cat,p)
t0=o.get('tout'); if isempty(t0); t0=o.tout; end
Vlv0=o.get('Vlv_abc'); Vdc0=o.get('Vdc'); dq0=squeeze(o.get('dq')).'; Ish0=o.get('Ish_abc');
m=t0>=t_f-0.02; t=t0(m); Vlv=Vlv0(m,:); Vdc=Vdc0(m); dq=dq0(m,:); Ish=Ish0(m,:);
dt=median(diff(t)); nc=max(1,round(0.02/dt)); q=max(1,round(0.005/dt));
[V1,V2]=seqmag(Vlv,p.VLN_peak,q); [~,i2]=seqmag(Ish,p.I_action_peak,q);
V1=movmean(V1,nc); V2=movmean(V2,nc); i2=movmean(i2,nc);
iq=movmean(dq(:,2)/p.I_dq_base_peak,nc); idq=hypot(dq(:,1)/p.I_dq_base_peak,iq);
Ipk=movmean(max(abs(Ish),[],2)/p.I_dq_base_peak,nc);
wf=t>=t_f+0.005 & t<=t_f+dur-0.005; residual=min(V1(wf));
opts=struct('V2',V2,'Vdc',Vdc(:)/800,'iq',iq,'i_peak',Ipk,'idq_mag',idq,'i2',i2);
res=frt_v2_evaluate(t(:),V1(:),cat,residual,t_f,dur,opts);
% wrong-sign present in the in-fault assessment window? (V+<0.9 & iq<-eps) or (V+>1.1 & iq>eps)
asw=t>=t_f+0.06 & t<=t_f+dur; eps=1e-3;
wrong=any((V1(asw)<0.9 & iq(asw)<-eps) | (V1(asw)>1.1 & iq(asw)>eps));
iqmed=median(iq(t>=t_f+0.06 & t<=t_f+dur));
end
function [V1,V2]=seqmag(Vabc,Vnom,q)
a=(2/3)*(Vabc(:,1)-0.5*Vabc(:,2)-0.5*Vabc(:,3)); b=(2/3)*(sqrt(3)/2)*(Vabc(:,2)-Vabc(:,3));
ad=[zeros(q,1);a(1:end-q)]; bd=[zeros(q,1);b(1:end-q)];
V1=sqrt((0.5*(a-bd)).^2+(0.5*(b+ad)).^2)/Vnom; V2=sqrt((0.5*(a+bd)).^2+(0.5*(b-ad)).^2)/Vnom;
end
function s=oo(b), if b, s='on'; else, s='off'; end, end
