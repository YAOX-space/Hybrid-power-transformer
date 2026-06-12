function validate_frt_full(nmax, srcfile, ftypes)
if nargin<1 || isempty(nmax), nmax=inf; end
if nargin<2 || isempty(srcfile), srcfile='../frt_scenarios.csv'; end
if nargin<3, ftypes={}; end   % optional cell of fault_type to keep (e.g. {'sym3ph'} or {'1ph_g','2ph','2ph_g'})
% validate_frt_full.m — standard grid-FRT comparison: dq (mode 4) vs closed-loop SAC (mode 11)
% on the COMPLETE HPT switching model (hpt_frt_full.slx). Pass srcfile='../frt_scenarios.csv'
% to run the full scenario set (LVRT rows). Results saved incrementally.

here = fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4);
M = 'hpt_frt_full'; set_param(M,'SimulationMode','normal');
A = readtable(srcfile,'TextType','string');
if any(strcmp(A.Properties.VariableNames,'category'))   % full scenario file: keep LVRT only
    A = A(A.category=="LVRT",:);
end
if ~isempty(ftypes)   % optional fault-type filter (for per-expert routing)
    A = A(ismember(string(A.fault_type), string(ftypes)),:);
end
N = min(height(A), nmax);
Vlv_pk_nom = 400*sqrt(2)/sqrt(3);      % 326.6 V

% --- per-SCR EMF calibration (so pre-fault LV = 1.0 pu) ---
emf = containers.Map('KeyType','double','ValueType','double');
rfa = containers.Map('KeyType','char','ValueType','double');
faultcfg = @(ft) ftcfg(ft);

results = struct([]);
fprintf('\n%-7s %4s %3s | %-22s | %-22s\n','fault','V','scr','dq-traditional','SAC');
fprintf('%s\n', repmat('-',74,1));

for i = 1:N
  ft = char(A.fault_type(i)); tV = A.target_V_pu(i); scr = A.scr(i);
  Rg = A.Rg_ohm(i); Lg = A.Lg_H(i); t_f = A.t_fault(i);
  dur = A.fault_dur(i); Tsim = min(A.T_sim(i), 1.2);
  set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
  % EMF for this SCR
  if ~isKey(emf, scr)
    emf(scr) = calib_emf(M, scr, Vlv_pk_nom);
  end
  set_param([M '/Grid'],'Voltage',num2str(emf(scr)));
  % R_fault for this (scr,target) under this fault type
  key = sprintf('%g_%g_%s', scr, tV, ft);
  if ~isKey(rfa, key)
    rfa(key) = calib_rfault(M, ft, tV, t_f, Tsim, Vlv_pk_nom);
  end
  Rf = rfa(key);
  cfg = faultcfg(ft);
  set_param(M,'StopTime',num2str(Tsim));

  % closed-loop SAC (mode 11) needs fault-class/dur/t_fault for the in-model obs
  fcmap = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'},{1,2,3,4});
  fcl = 1; if isKey(fcmap, ft), fcl = fcmap(ft); end
  set_param([M '/fclass'],'Value',num2str(fcl));
  set_param([M '/fdur'],'Value',num2str(dur));
  set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  out = struct();
  for md = [4 12]    % 4 = dq-traditional, 12 = closed-loop SAC 4-expert (real-time gated by V2p/V2n)
    set_param([M '/mode'],'Value',num2str(md));
    set_fault(M, cfg, Rf, t_f, t_f+dur);
    o = sim(M);
    c = criteria(o, Tsim, t_f, dur, tV, Vlv_pk_nom);
    if md==4, out.dq=c; else, out.sac=c; end
  end
  results(i).ft=ft; results(i).tV=tV; results(i).scr=scr; results(i).dq=out.dq; results(i).sac=out.sac;
  fprintf('[%3d/%d] %-7s %.2f %3g | LV%.2f Vdc[%.2f,%.2f] %s | LV%.2f Vdc[%.2f,%.2f] %s\n', ...
    i, N, ft, tV, scr, out.dq.LVflt, out.dq.Vdcmin, out.dq.Vdcmax, passmark(out.dq), ...
    out.sac.LVflt, out.sac.Vdcmin, out.sac.Vdcmax, passmark(out.sac));
  if mod(i,5)==0, save('../results/frt_full_compare_partial.mat','results','i'); end
end

% --- summary ---
save('../results/frt_full_compare.mat','results');
crit = {'connect','reactive','limit','recover','survive','frt'};
fid = fopen('../results/frt_full_compare.txt','w');
emit = @(ln) [fprintf('%s',ln), fprintf(fid,'%s',ln)];
emit(sprintf('\n=== Full-HPT standard-FRT: SAC vs dq-traditional (%d LVRT scenarios) ===\n', N));
emit(sprintf('%-9s %8s %8s\n','criterion','dq','SAC'));
for k=1:numel(crit)
  dqp = 100*mean(arrayfun(@(r) double(r.dq.(crit{k})), results));
  scp = 100*mean(arrayfun(@(r) double(r.sac.(crit{k})), results));
  emit(sprintf('%-9s %7.1f%% %7.1f%%\n', crit{k}, dqp, scp));
end
fclose(fid);
fprintf('\nsaved ../results/frt_full_compare.{mat,txt}\n');
end

% ---------- helpers ----------
function emfV = calib_emf(M, scr, Vnom)
  set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
  set_param(M,'StopTime','0.35');
  V0 = 10e3*1.125;
  set_param([M '/Grid'],'Voltage',num2str(V0));
  o = sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
  lvpu = max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom;
  emfV = V0 / max(0.5,lvpu);   % rescale to hit 1.0 pu
end

function Rf = calib_rfault(M, ft, tV, t_f, Tsim, Vnom)
  cfg = ftcfg(ft);
  set_param([M '/mode'],'Value','4');   % FIX: calibration must NOT inherit the previous scenario's controller
  set_param(M,'StopTime',num2str(min(Tsim,t_f+0.2)));
  cand = [2 5 12 30 80 200];
  best = 30; berr = 9;
  for R = cand
    set_fault(M, cfg, R, t_f, t_f+0.12);
    o = sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,str2double(get_param(M,'StopTime')),size(Vlv,1))';
    res = mean_mag(Vlv, tl, t_f+0.05, t_f+0.10)/Vnom;
    if abs(res-tV) < berr, berr=abs(res-tV); best=R; end
  end
  Rf = best;
end

function cfg = ftcfg(ft)
  switch ft
    case 'sym3ph', cfg = struct('A','on','B','on','C','on','G','on');
    case '1ph_g',  cfg = struct('A','on','B','off','C','off','G','on');
    case '2ph',    cfg = struct('A','on','B','on','C','off','G','off');
    case '2ph_g',  cfg = struct('A','on','B','on','C','off','G','on');
    otherwise,     cfg = struct('A','on','B','on','C','on','G','on');
  end
end

function set_fault(M, cfg, Rf, t1, t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end

function m = mean_mag(Vabc, t, a, b)
  idx = t>=a & t<b; V=Vabc(idx,:);
  Va=V(:,1); Vb=V(:,2); Vc=V(:,3);
  Valpha=(2/3)*(Va-0.5*Vb-0.5*Vc); Vbeta=(2/3)*(sqrt(3)/2)*(Vb-Vc);
  m = mean(sqrt(Valpha.^2+Vbeta.^2));
end

function c = criteria(o, Tsim, t_f, dur, tV, Vnom)
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
  nL=size(Vlv,1); tL=linspace(0,Tsim,nL)';
  nV=numel(Vdc); tVv=linspace(0,Tsim,nV)';
  nq=size(dq,1); tq=linspace(0,Tsim,nq)';
  LVflt  = mean_mag(Vlv, tL, t_f+0.3*dur, t_f+0.9*dur)/Vnom;   % pos-seq LV during fault
  LVpost = mean_mag(Vlv, tL, Tsim-0.12, Tsim-0.02)/Vnom;        % recovery
  Vdcmin = min(Vdc(tVv>=t_f & tVv<t_f+dur))/800;
  Vdcmax = max(Vdc(tVv>=t_f & tVv<t_f+dur+0.1))/800;
  iqf    = mean(dq(tq>=t_f & tq<t_f+dur, 2))/173.2;             % shunt iq (pu)
  iqref  = min(0.3, max(0, 1.5*(0.9-LVflt)));                   % GB/T droop requirement
  c.connect  = LVflt >= tV-0.07;
  c.reactive = abs(iqf - iqref) <= 0.12;
  c.limit    = max(abs(dq(:,2)))/173.2 <= 0.35;
  c.recover  = abs(1-LVpost) <= 0.07;
  c.survive  = (Vdcmin>=0.75) && (Vdcmax<=1.25);
  c.frt = c.connect && c.reactive && c.limit && c.recover && c.survive;
  c.LVflt=LVflt; c.Vdcmin=Vdcmin; c.Vdcmax=Vdcmax;
end

function s = passmark(c)
  if c.frt, s='PASS'; else, s='fail'; end
end
