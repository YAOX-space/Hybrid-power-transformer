function run_spotcheck()
% run_spotcheck — Phase-2 L1 switching-level spot-check of Mode 5 (mi==12) on the
% representative network cases exported by src/hpt_frt/network/experiments... (export_simulink_cases.py).
%
% Each network scenario is reproduced at SWITCHING LEVEL by driving the single-HPT model
% hpt_frt_full.slx with the SAME local terminal sequence depth (target residual Vp) + fault TYPE
% + duration the OpenDSS/L2 layer produced, with the closed-loop online-gated 4-expert HLC
% (mode=12). This is the standard FRT-testbench L1 methodology (validate_mode_full.m): it captures
% the local sequence-voltage depth + type at SPWM/IGBT level (2w ripple, measured peaks, real Vdc),
% which the quasi-static phasor twin cannot see. It does NOT replay the exact network Vabc waveform
% (same sequence content in quasi-static) and is a SAMPLE audit, not a full-system switching run.
%
% Saves ../../src/hpt_frt/network/results/simulink_cases/<label>_sw_result.mat (raw signals +
% criteria) for each case; Python (fill_spotcheck.py) does 2w-ripple / gate reconstruction / plots.

here=fileparts(mfilename('fullpath')); cd(here);
% LEGACY frt-v1 criteria (c.connect = LVflt>=tV-0.07, linspace time) -> fail-fast unless the legacy
% flag is set; output forced into a legacy_pre_audit subfolder, tagged frt-v1-INVALIDATED.
frt_v2_guard('run_spotcheck');
metrics_version = 'frt-v1-INVALIDATED';
outdir='../../src/hpt_frt/network/results/simulink_cases/legacy_pre_audit';
if ~exist(outdir,'dir'); mkdir(outdir); end
Vnom=400*sqrt(2)/sqrt(3); M='hpt_frt_full'; scr=3;
build_hpt_frt_full(4); set_param(M,'SimulationMode','normal');

% Fixed Rfault per case (avoids fragile residual-search; achieved residual reported per case).
% Sym3ph residual-vs-R map (validated-consistent harness, emf-calibrated): R2~0.03 R5~0.07 R12~0.15
% R30~0.33 R80~0.56 R200~0.78. Asym (1ph_g) positive-seq cannot go below ~0.5 (single-phase fault).
% label, fault_type, Rfault(ohm), dur(s), postwin(s), expected bare residual (tV), category
C = {
 'S1_superdeep_sym',  'sym3ph',  2, 0.15, 0.40, 0.03, 'super-deep sym (Vp~0.03, worst-Vdc region)';
 'S2_superdeep_sym',  'sym3ph',  5, 0.15, 0.40, 0.07, 'super-deep sym (Vp~0.07)';
 'S3_boundary_sym',   'sym3ph', 30, 0.30, 0.40, 0.33, 'near-boundary sym (Vp~0.33)';
 'S4_superdeep_1phg', '1ph_g',   2, 0.15, 0.40, 0.50, 'deep asym 1ph_g (asym-cap headroom)';
 'S5_boundary_1phg',  '1ph_g',  12, 0.30, 0.40, 0.62, 'asym 1ph_g (gate-crossing on recovery)';
 'S6_asym_2ph',       '2ph',     8, 0.30, 0.40, 0.55, 'asym 2ph';
 'S7_asym_2phg',      '2ph_g',   8, 0.30, 0.40, 0.45, 'asym 2ph_g';
 'S8_deep_sym_rec',   'sym3ph',  3, 0.15, 0.60, 0.05, 'deep sym + post-clear withdrawal (long window)';
 'S9_deep_1phg_rec',  '1ph_g',   3, 0.30, 0.60, 0.55, 'deep asym + post-clear withdrawal + gate-crossing';
 'S10_mid_sym',       'sym3ph', 80, 0.30, 0.40, 0.56, 'mid-depth sym (Vp~0.56, pass reference)';
};

% calibrate grid emf once for this SCR (validate_mode_full-consistent peak-phase formula)
set_param([M '/Grid'],'Resistance',num2str(gridR(scr)),'Inductance',num2str(gridL(scr)));
emf = calib_emf(M,Vnom,scr);
fprintf('grid emf=%.0f (scr=%d, Rg=%.2f)\n',emf,scr,gridR(scr));
t_f=0.1; rows=struct([]);
for i=1:size(C,1)
  label=C{i,1}; ft=C{i,2}; Rf=C{i,3}; dur=C{i,4}; postwin=C{i,5}; tVexp=C{i,6}; cat=C{i,7};
  set_param([M '/Grid'],'Resistance',num2str(gridR(scr)),'Inductance',num2str(gridL(scr)),'Voltage',num2str(emf));
  set_param([M '/fclass'],'Value','0'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param([M '/mode'],'Value','12');

  Tsim=t_f+dur+postwin;
  set_fault(M,ftcfg(ft),Rf,t_f,t_f+dur);
  set_param(M,'StopTime',num2str(Tsim));
  o=sim(M); clear_fault(M);
  rec=tern(postwin>0.5,'long-window','instant');

  c = crit_full(o,Tsim,t_f,dur,tVexp,Vnom);
  % save raw signals for Python analysis
  Vlv=o.get('Vlv_abc'); Vmv=o.get('Vmv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).'; Ish=o.get('Ish_abc');
  S=struct('label',label,'category',cat,'fault_type',ft,'Rfault',Rf,'target_Vp',tVexp,'dur',dur,'recovery',rec, ...
    'scr',scr,'Tsim',Tsim,'t_fault',t_f,'Vnom',Vnom, ...
    'Vlv_abc',Vlv,'Vmv_abc',Vmv,'Vdc',Vdc,'dq',dq,'Ish_abc',Ish, ...
    'crit',c,'metrics_version',metrics_version);
  save(fullfile(outdir,[label '_sw_result.mat']),'-struct','S');
  rows(i).label=label; rows(i).c=c;
  fprintf('[%2d/%d] %-18s %-7s R=%3g LVflt=%.3f | Vdc %.3f-%.3f iqpk %.3f Ishpk %.1f | %s\n', ...
    i,size(C,1),label,ft,Rf,c.LVflt,c.Vdcmin,c.Vdcmax,c.iqpeak,c.Ishpeak,tern(c.frt,'PASS','fail'));
end
fprintf('\nrun_spotcheck DONE: %d cases -> %s\n',size(C,1),outdir);
end

% ---------- helpers ----------
function R=gridR(scr), if scr>=10, R=7.9057; else, R=26.3523; end, end   % frt_scenarios.csv weak-grid R
function L=gridL(scr), if scr>=10, L=0.075494; else, L=0.251646; end, end % frt_scenarios.csv weak-grid L
function emfV=calib_emf(M,Vnom,scr)
  set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
  set_param([M '/Grid'],'Resistance',num2str(gridR(scr)),'Inductance',num2str(gridL(scr)));
  set_param(M,'StopTime','0.30'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
  o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.30,size(Vlv,1))';
  % validate_mode_full-consistent: peak INSTANTANEOUS phase voltage (NOT alpha-beta magnitude),
  % else emf is ~12% low -> grid source too weak -> spurious Vdc collapse under fault.
  emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom);
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
function clear_fault(M)
  set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
end
function m=mean_mag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function c=crit_full(o,Tsim,t_f,dur,tV,Vnom)
  Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).'; Ish=o.get('Ish_abc');
  tL=linspace(0,Tsim,size(Vlv,1))'; tV2=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
  LVflt=mean_mag(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
  LVpost=mean_mag(Vlv,tL,Tsim-0.12,Tsim-0.02)/Vnom;
  win=tV2>=t_f & tV2<t_f+dur; winp=tV2>=t_f & tV2<t_f+dur+0.15;
  Vdcmin=min(Vdc(win))/800; Vdcmax=max(Vdc(winp))/800;
  iqf=mean(dq(tq>=t_f&tq<t_f+dur,2))/pu_params().I_dq_base_peak;
  iqpeak=max(abs(dq(:,2)))/pu_params().I_dq_base_peak; idpeak=max(abs(dq(:,1)))/pu_params().I_dq_base_peak;
  Ishpeak=max(abs(Ish(:)));
  iqref=min(0.3,max(0,1.5*(0.9-LVflt)));
  c.connect=LVflt>=tV-0.07; c.reactive=abs(iqf-iqref)<=0.12;
  c.limit=iqpeak<=0.35; c.recover=abs(1-LVpost)<=0.07;
  c.survive=(Vdcmin>=0.75)&&(Vdcmax<=1.25);
  c.frt=c.connect&&c.reactive&&c.limit&&c.recover&&c.survive;
  c.Vdcmin=Vdcmin; c.Vdcmax=Vdcmax; c.LVflt=LVflt; c.LVpost=LVpost;
  c.iqf=iqf; c.iqpeak=iqpeak; c.idpeak=idpeak; c.Ishpeak=Ishpeak;
  c.vdc_lt075=Vdcmin<0.75; c.vdc_gt125=Vdcmax>1.25;
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
