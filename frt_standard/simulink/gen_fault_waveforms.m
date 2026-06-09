function gen_fault_waveforms()
% Generate one waveform figure per fault type (sym3ph/1ph_g/2ph/2ph_g) at a
% representative operating point (residual ~0.5, weak grid SCR=3), comparing
% dq-traditional (mode 4) vs closed-loop SAC (mode 11):
%   panel 1: LV three-phase instantaneous voltage (shows the fault signature)
%   panel 2: DC bus Vdc (dq vs SAC) with survive band
%   panel 3: shunt reactive current iq (dq vs SAC)
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
figdir='../../results/figs';
Vnom=400*sqrt(2)/sqrt(3);
% weak grid SCR=3 (10kV): R/L
Rg=11.79; Lg=0.2626;
set_param([M '/Grid'],'SpecifyImpedance','off','Resistance',num2str(Rg),'Inductance',num2str(Lg));
% EMF calibration (pre-fault LV=1.0pu)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); V=o.get('Vlv_abc'); tl=linspace(0,0.35,size(V,1))'; lvpu=max(abs(V(tl>0.25,:)),[],'all')/Vnom;
EMF=V0/lvpu; set_param([M '/Grid'],'Voltage',num2str(EMF));

types={'sym3ph','1ph_g','2ph','2ph_g'};
fclassmap=[1 2 3 4];
cfgs={struct('A','on','B','on','C','on','G','on'), struct('A','on','B','off','C','off','G','on'), ...
      struct('A','on','B','on','C','off','G','off'), struct('A','on','B','on','C','off','G','on')};
t_f=0.30; dur=0.20; Tsim=0.8;
cdq=[0.4 0.6 0.85]; csac=[0.85 0.45 0.35];

for k=1:4
  cfg=cfgs{k};
  % calibrate R for pos-seq residual ~0.5
  set_param(M,'StopTime',num2str(t_f+0.2)); bestR=15; berr=9;
  for R=[5 10 20 40 80]
    setflt(M,cfg,R,t_f,t_f+0.12); o=sim(M); Vv=o.get('Vlv_abc'); tt=linspace(0,t_f+0.2,size(Vv,1))';
    res=seqmag(Vv,tt,t_f+0.05,t_f+0.10)/Vnom; if abs(res-0.5)<berr; berr=abs(res-0.5); bestR=R; end
  end
  set_param(M,'StopTime',num2str(Tsim)); setflt(M,cfg,bestR,t_f,t_f+dur);
  set_param([M '/fclass'],'Value',num2str(fclassmap(k))); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  D=struct();
  for md=[4 11]
    set_param([M '/mode'],'Value',num2str(md));
    o=sim(M); Vv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
    tv=linspace(0,Tsim,size(Vv,1))'; td=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
    if md==4; D.tv=tv;D.V=Vv;D.td=td;D.vdc=Vdc/800;D.tq=tq;D.iq4=dq(:,2); else; D.vdc11=Vdc/800;D.iq11=dq(:,2); end
  end
  f=figure('Position',[100 100 820 640],'Color','w');
  % panel 1: LV abc (dq run) - fault signature
  ax1=subplot(3,1,1); hold on;
  fill([t_f t_f+dur t_f+dur t_f],[-1.3 -1.3 1.3 1.3],[0.95 0.95 0.8],'EdgeColor','none');
  plot(D.tv,D.V(:,1)/Vnom,'r-',D.tv,D.V(:,2)/Vnom,'g-',D.tv,D.V(:,3)/Vnom,'b-','LineWidth',0.6);
  ylim([-1.3 1.3]); xlim([t_f-0.04 t_f+0.10]);  % zoom ~7 cycles around onset to show fault signature
  ylabel('LV v_{abc} (pu)'); grid on; set(ax1,'FontSize',9);
  title(sprintf('%s fault (weak grid SCR=3, R_f=%g\\Omega) — LV phase voltages [zoom @ onset]', types{k}, bestR),'Interpreter','tex');
  legend({'fault','v_a','v_b','v_c'},'Location','eastoutside','FontSize',7);
  % panel 2: Vdc
  ax2=subplot(3,1,2); hold on;
  fill([t_f t_f+dur t_f+dur t_f],[0 0 1.4 1.4],[0.95 0.95 0.8],'EdgeColor','none');
  plot(D.td,D.vdc,'-','Color',cdq,'LineWidth',1.2); plot(D.td,D.vdc11,'-','Color',csac,'LineWidth',1.2);
  yline(0.75,'--k'); yline(1.25,'--k'); ylim([0 1.45]); ylabel('V_{dc} (pu)'); grid on; set(ax2,'FontSize',9);
  legend({'fault','dq','SAC','survive'},'Location','eastoutside','FontSize',7);
  % panel 3: reactive current
  ax3=subplot(3,1,3); hold on;
  fill([t_f t_f+dur t_f+dur t_f],[-60 -60 60 60],[0.95 0.95 0.8],'EdgeColor','none');
  plot(D.tq,D.iq4,'-','Color',cdq,'LineWidth',1.0); plot(D.tq,D.iq11,'-','Color',csac,'LineWidth',1.0);
  ylim([-60 60]); xlabel('time (s)'); ylabel('shunt i_q (A)'); grid on; set(ax3,'FontSize',9);
  legend({'fault','dq','SAC'},'Location','eastoutside','FontSize',7);
  exportgraphics(f,sprintf('%s/fig_wave_%s.png',figdir,types{k}),'Resolution',150); close(f);
  fprintf('saved fig_wave_%s.png (R_f=%g)\n', types{k}, bestR);
end
end

function setflt(M,cfg,R,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G,...
    'FaultResistance',num2str(R),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function m=seqmag(V,t,a,b)
  idx=t>=a&t<b; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); m=mean(sqrt(al.^2+be.^2));
end
