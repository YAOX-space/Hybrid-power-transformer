function diag_mode12()
% diag_mode12.m — does the Mode-12 ONLINE-GATED 3-expert reproduce / survive now?
% Runs asym (1ph_g, 2ph_g) scenarios at mode 12 and compares Vdcmin against mode 11 with the
% asym expert manually placed as sac_actor_weights.mat. Isolates whether the earlier 0.59
% collapse was (a) stale weights or (b) the pre-fault zeroing in mode-12 path.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4);
M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Vnom=326.6;
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.625; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));

% EMF calibration
set_param([M '/mode'],'Value','4');
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom);
set_param([M '/Grid'],'Voltage',num2str(emfV));

% ensure mode-11 uses the ASYM expert: place it as sac_actor_weights.mat
copyfile('sac_asym_weights.mat','sac_actor_weights.mat');
clear functions   % drop any cached coder.load constant

cases={'1ph_g',0.75; '1ph_g',0.5; '1ph_g',0.2; '2ph_g',0.5; '2ph_g',0.2};
fc_map=containers.Map({'sym3ph','1ph_g','2ph','2ph_g'},{1,2,3,4});
fprintf('\n%-7s %4s | %-22s | %-22s\n','fault','V','mode11 asym(manual)','mode12 gated');
fprintf('%s\n',repmat('-',60,1));
for c=1:size(cases,1)
  ft=cases{c,1}; tV=cases{c,2};
  cfg=ftcfg(ft); Rf=calib_rf(M,cfg,tV,t_f,Vnom);
  set_param(M,'StopTime',num2str(Tsim));
  set_fault(M,cfg,Rf,t_f,t_f+dur);
  set_param([M '/fclass'],'Value',num2str(fc_map(ft)));
  set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  R=containers.Map('KeyType','double','ValueType','any');
  for md=[4 11 12]
    set_param([M '/mode'],'Value',num2str(md));
    o=sim(M); Vdc=o.get('Vdc'); nV=numel(Vdc); tV2=linspace(0,Tsim,nV)';
    Vlv=o.get('Vlv_abc'); tL=linspace(0,Tsim,size(Vlv,1))';
    dq=squeeze(o.get('dq')).'; nq=size(dq,1); tq=linspace(0,Tsim,nq)';
    vmin=min(Vdc(tV2>=t_f & tV2<t_f+dur))/800;
    vmax=max(Vdc(tV2>=t_f & tV2<t_f+dur+0.1))/800;
    lvf=seqpos(Vlv,tL,t_f+0.3*dur,t_f+0.9*dur)/Vnom;
    iqf=mean(dq(tq>=t_f & tq<t_f+dur,2))/173.2;       % shunt iq command during fault (pu)
    iqpk=max(abs(dq(:,2)))/173.2;
    R(md)=[vmin vmax lvf iqf iqpk];
  end
  pr=@(v) sprintf('Vdc[%.2f,%.2f] LV%.2f iq%.2f/%.2f',v(1),v(2),v(3),v(4),v(5));
  fprintf('%-7s %.2f\n   dq  : %s\n   asym(m11): %s\n   gate(m12): %s\n', ...
    ft,tV, pr(R(4)), pr(R(11)), pr(R(12)));
end
fprintf('\niq = mean/peak shunt q-current (pu). Vdcmin<0.75 = collapse.\n');
end

function Rf=calib_rf(M,cfg,tV,t_f,Vnom)
  set_param([M '/mode'],'Value','4');
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  set_param(M,'StopTime',num2str(t_f+0.2));
  cand=[2 5 12 30 80 200]; best=30; berr=9;
  for R=cand
    set_fault(M,cfg,R,t_f,t_f+0.12);
    o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,t_f+0.2,size(V,1))';
    res=seqpos(V,tt,t_f+0.05,t_f+0.10)/Vnom; if abs(res-tV)<berr,berr=abs(res-tV);best=R;end
  end
  Rf=best;
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
function m=seqpos(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
