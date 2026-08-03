function frt_v2_full320_switching(mi, i0, i1)
% frt_v2_full320_switching — FAITHFUL switching-layer full-320 frt-v2 run. Each scenario's fault is
% CALIBRATED (p3_scenario_faultparams.json) so the open-loop sag reproduces the ODE Vg_p. Evaluates with
% the authoritative frt_v2_evaluate + the validated 4-fix measurement pipeline (cold-start trim, 1-cycle
% RMS smoothing, retained-min residual, i2 from Ish). RESUMABLE: appends to a per-mode results MAT and
% skips scenarios already done. Builds once per (grid-mode, SCR).
%   mi: 14 = deployed residual SAC ; 7 = dq fixed-law baseline.   i0,i1: scenario index range (1..320).
here=fileparts(mfilename('fullpath')); cd(here); p=pu_params(); M='hpt_frt_full';
if nargin<2, i0=1; end, if nargin<3, i1=320; end
wfile = 'sac_actor_weights.mat';
if mi==12 || mi==15
    wfile='sac_sym_weights.mat';
elseif mi==14 || (mi>=322 && mi<=372) || (mi>=209 && mi<=321) || (mi>=20 && mi<=208)
    wfile='sac_residual_weights.mat';
elseif mi==17
    wfile='sac_resexpert_weights.mat';
end
W=load(fullfile('..',wfile)); run_id=char(W.run_id);
fp = jsondecode(fileread('../results/p3_scenario_faultparams.json'));
T  = readtable('../frt_scenarios.csv');
resfile = sprintf('../results/p3_full320_sw_mi%d.mat', mi);
if isfile(resfile), S=load(resfile); R=S.R; else, R=struct('sid',{},'frt',{},'crit',{},'prov',{}); end
done = arrayfun(@(x) x.sid, R);
cfg = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'},{[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});
% order scenarios so each (grid-mode, scr) builds once
ids = i0:i1; meta = arrayfun(@(s) getfield(fp, sprintf('x%d', s)), ids);
key = arrayfun(@(m) (strcmp(m.category,'HVRT'))*100 + m.scr, meta);
[~,ord]=sort(key); ids=ids(ord); meta=meta(ord);
curbuild='';
for n=1:numel(ids)
  sid=ids(n); m=meta(n);
  if any(done==sid), continue; end
  isH=strcmp(m.category,'HVRT'); scr=m.scr;
  bkey=sprintf('%d_%g', isH, scr);
  if ~strcmp(bkey,curbuild)
    if isH, build_hpt_frt_full(4,'swell'); else, build_hpt_frt_full(4); end
    set_param(M,'SimulationMode','normal');
    if scr==10, Rg=7.9057; Lg=0.075494; else, Rg=26.3523; Lg=0.251646; end
    if isH, set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
    else,   set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg)); end
    curbuild=bkey;
  end
  tf=0.08; dur=min(m.fault_dur,0.5); cat=m.category;
  row_ix=find(T.scenario_id==sid,1);
  post_window=max(0.35, double(T.T_sim(row_ix)) - (double(T.t_fault(row_ix)) + dur));
  set_param([M '/mode'],'Value',num2str(mi));
  set_param([M '/fclass'],'Value',num2str(fclass_code(cat, m.fault_type)));
  set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(tf));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(tf+dur+post_window));
  if isH
    is1=strcmp(m.fault_type,'swell_1ph');
    set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
      'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m.fault_param,m.fault_param), ...
      'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',tf-1e-3,tf,tf+dur,tf+dur+1e-3), ...
      'VariationPhaseA',oo(is1));
  else
    c=cfg(m.fault_type);
    set_param([M '/GridFault'],'FaultA',oo(c(1)),'FaultB',oo(c(2)),'FaultC',oo(c(3)),'GroundFault',oo(c(4)), ...
      'FaultResistance',num2str(m.fault_param),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',tf,tf+dur));
  end
  o=sim(M);
  res=eval_case(o,tf,dur,cat,p);
  rec.sid=sid; rec.frt=res.frt_pass_str; rec.crit=res;
  rec.prov=struct('mi',mi,'fault_type',m.fault_type,'scr',scr,'Vg_p',m.Vg_p,'fault_param',m.fault_param, ...
                  'target_V_pu',m.target_V_pu,'run_id',run_id,'metrics_version','frt-v2');
  R(end+1)=rec; %#ok<AGROW>
  metrics_version='frt-v2'; %#ok<NASGU>  % top-level tag (governance: active result dirs require frt-v2)
  save(resfile,'R','metrics_version');   % incremental save (resume safe)
  fprintf('mi%d sid%3d %-9s scr%g Vg_p=%.2f | con=%s rea=%s lim=%s rec=%s sur=%s | frt=%s\n', ...
    mi, sid, m.fault_type, scr, m.Vg_p, res.connect.status(1:4),res.reactive.status(1:4),res.limit.status(1:4), ...
    res.recover.status(1:4),res.survive.status(1:4), res.frt_pass_str);
end
fprintf('=== mi%d: %d/%d scenarios in %s ===\n', mi, numel(R), 320, resfile);
end

function res = eval_case(o, t_f, dur, cat, p)
tout0=o.get('tout'); if isempty(tout0); tout0=o.tout; end
Vlv0=o.get('Vlv_abc'); Vdc0=o.get('Vdc'); dq0=squeeze(o.get('dq')).'; Ish0=o.get('Ish_abc');
m=tout0>=t_f-0.02; tout=tout0(m); Vlv=Vlv0(m,:); Vdc=Vdc0(m); dq=dq0(m,:); Ish=Ish0(m,:);
dt=median(diff(tout)); nc=max(1,round(0.02/dt)); q=max(1,round(0.005/dt));
[V1,V2]=seqmag(Vlv,p.VLN_peak,q); [~,i2c]=seqmag(Ish,p.I_action_peak,q);
V1=movmean(V1,nc); V2=movmean(V2,nc); i2c=movmean(i2c,nc);
iq=movmean(dq(:,2)/p.I_dq_base_peak,nc); idq=hypot(dq(:,1)/p.I_dq_base_peak,iq);
Ipk=movmean(max(abs(Ish),[],2)/p.I_dq_base_peak,nc);
wf=tout>=t_f+0.005 & tout<=t_f+dur-0.005; residual=min(V1(wf));
opts=struct('V2',V2,'Vdc',Vdc(:)/800,'iq',iq,'i_peak',Ipk,'idq_mag',idq,'i2',i2c);
res=frt_v2_evaluate(tout(:),V1(:),cat,residual,t_f,dur,opts);
end
function [V1,V2]=seqmag(Vabc,Vnom,q)
a=(2/3)*(Vabc(:,1)-0.5*Vabc(:,2)-0.5*Vabc(:,3)); b=(2/3)*(sqrt(3)/2)*(Vabc(:,2)-Vabc(:,3));
ad=[zeros(q,1);a(1:end-q)]; bd=[zeros(q,1);b(1:end-q)];
V1=sqrt((0.5*(a-bd)).^2+(0.5*(b+ad)).^2)/Vnom; V2=sqrt((0.5*(a+bd)).^2+(0.5*(b-ad)).^2)/Vnom;
end
function s=oo(b), if b, s='on'; else, s='off'; end, end

function fc=fclass_code(cat, ft)
if strcmp(cat,'HVRT')
  if strcmp(ft,'swell_1ph'), fc=6; else, fc=5; end
elseif strcmp(ft,'sym3ph')
  fc=1;
else
  fc=2;
end
end
