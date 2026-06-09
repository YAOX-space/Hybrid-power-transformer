function gen_compare_figs()
% Generate SAC-vs-dq comparison figures for the report:
%   A: 3-expert per-subclass + overall FRT bar (full 320)
%   B: asymmetric LVRT (1ph_g 0.5, weak grid) waveform — dq vs asym-expert SAC
%   C: HVRT swell (swell_3ph 1.2, weak grid) waveform — dq vs hvrt-expert SAC
here=fileparts(mfilename('fullpath')); cd(here);
figdir='../../results/figs'; if ~exist(figdir,'dir'); mkdir(figdir); end
Vnom=400*sqrt(2)/sqrt(3); M='hpt_frt_full';
cdq=[0.30 0.55 0.85]; csac=[0.85 0.40 0.30];

% ===================== Fig A: 3-expert bar =====================
dq=[0 12.8 81.2 27.5]; sac=[15 40 75 44.1];
f=figure('Position',[100 100 760 430],'Color','w');
b=bar([dq;sac]','grouped'); b(1).FaceColor=cdq; b(2).FaceColor=csac;
set(gca,'XTickLabel',{'sym (sym-LVRT)','asym (asym-LVRT)','hvrt (swell)','ALL 320'},'FontSize',10);
ylabel('FRT pass rate (%)'); ylim([0 100]); grid on;
legend({'dq-traditional','SAC (3-expert)'},'Location','northwest','FontSize',10);
title('Hierarchical 3-expert SAC vs dq — per-subclass FRT (full 320)');
for i=1:4
  text(i-0.15,dq(i)+2.5,sprintf('%.1f',dq(i)),'Hor','center','FontSize',9);
  text(i+0.15,sac(i)+2.5,sprintf('%.0f',sac(i)),'Hor','center','FontSize',9,'FontWeight','bold');
end
exportgraphics(f,[figdir '/fig_experts_bar.png'],'Resolution',150); close(f);
fprintf('Fig A (experts bar) saved\n');

% ===================== Fig B: asym LVRT waveform =====================
build_hpt_frt_full(4,'fault'); set_param(M,'SimulationMode','normal');
copyfile('../sac_asym_weights.mat','sac_actor_weights.mat'); build_hpt_frt_full(4,'fault'); % asym weights
Rg=11.79; Lg=0.2626; t_f=0.30; dur=0.20; Tsim=0.8;
set_param([M '/Grid'],'SpecifyImpedance','off','Resistance',num2str(Rg),'Inductance',num2str(Lg));
EMF=emfcal(M,Vnom); set_param([M '/Grid'],'Voltage',num2str(EMF));
cfg=struct('A','on','B','off','C','off','G','on');  % 1ph_g
Rf=rfcal(M,cfg,0.5,t_f,Tsim,Vnom);                  % calibrate (1ph_g pos-seq has a floor)
set_param([M '/fclass'],'Value','2'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
D=runpair(M,cfg,Rf,t_f,dur,Tsim,Vnom,false);
plot3panel(D,t_f,dur,'1ph\_g LVRT (residual~0.78, weak grid) — dq vs asymmetric-expert SAC', ...
           [figdir '/fig_cmp_lvrt_asym.png'],cdq,csac);
fprintf('Fig B (asym LVRT waveform) saved\n');

% ===================== Fig C: HVRT swell waveform =====================
copyfile('../sac_hvrt_weights.mat','sac_actor_weights.mat'); build_hpt_frt_full(4,'swell');
set_param(M,'SimulationMode','normal');
set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
V0=emfcal_swell(M,Vnom); set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
amp=ampcal(M,1.2,t_f,dur,Tsim,Vnom);
set_param([M '/fclass'],'Value','5'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
D=runpair_swell(M,amp,t_f,dur,Tsim,Vnom);
plot3panel(D,t_f,dur,'swell\_3ph HVRT (1.2 pu, weak grid) — dq vs HVRT-expert SAC', ...
           [figdir '/fig_cmp_hvrt.png'],cdq,csac);
fprintf('Fig C (HVRT waveform) saved\n');
% restore single weights
copyfile('../sac_actor_weights_v1.mat','sac_actor_weights.mat');
end

% ---------- helpers ----------
function plot3panel(D,t_f,dur,ttl,fn,cdq,csac)
f=figure('Position',[100 100 820 620],'Color','w');
ax1=subplot(3,1,1); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.4 1.4],[0.96 0.96 0.82],'EdgeColor','none');
plot(D.t,D.lv4,'-','Color',cdq,'LineWidth',1.3); plot(D.t,D.lv11,'-','Color',csac,'LineWidth',1.3);
yline(0.9,'--k'); ylim([0 max(1.2,max(D.lv11)*1.1)]); ylabel('LV pos-seq (pu)'); grid on; set(ax1,'FontSize',9);
legend({'fault window','dq','SAC','0.9 pu'},'Location','eastoutside','FontSize',8); title(ttl,'Interpreter','tex');
ax2=subplot(3,1,2); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.4 1.4],[0.96 0.96 0.82],'EdgeColor','none');
plot(D.tv,D.vdc4,'-','Color',cdq,'LineWidth',1.3); plot(D.tv,D.vdc11,'-','Color',csac,'LineWidth',1.3);
yline(0.75,'--k'); yline(1.25,'--k'); ylim([0 1.45]); ylabel('V_{dc} (pu)'); grid on; set(ax2,'FontSize',9);
legend({'fault','dq','SAC','survive'},'Location','eastoutside','FontSize',8);
ax3=subplot(3,1,3); hold on;
fill([t_f t_f+dur t_f+dur t_f],[-70 -70 70 70],[0.96 0.96 0.82],'EdgeColor','none');
plot(D.tq,D.iq4,'-','Color',cdq,'LineWidth',1.0); plot(D.tq,D.iq11,'-','Color',csac,'LineWidth',1.0);
ylim([-70 70]); xlabel('time (s)'); ylabel('shunt i_q (A)'); grid on; set(ax3,'FontSize',9);
legend({'fault','dq','SAC'},'Location','eastoutside','FontSize',8);
exportgraphics(f,fn,'Resolution',150); close(f);
end

function D=runpair(M,cfg,Rf,t_f,dur,Tsim,Vnom,~)
set_param(M,'StopTime',num2str(Tsim)); setflt(M,cfg,Rf,t_f,t_f+dur);
D=struct();
for md=[4 11]
  set_param([M '/mode'],'Value',num2str(md));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  o=sim(M); D=collect(D,o,md,Tsim,Vnom);
end
end
function D=runpair_swell(M,amp,t_f,dur,Tsim,Vnom)
set_param(M,'StopTime',num2str(Tsim)); setswell(M,amp,t_f,t_f+dur);
D=struct();
for md=[4 11]
  set_param([M '/mode'],'Value',num2str(md));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  o=sim(M); D=collect(D,o,md,Tsim,Vnom);
end
end
function D=collect(D,o,md,Tsim,Vnom)
Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
t=linspace(0,Tsim,size(Vlv,1))'; tv=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
Va=Vlv(:,1);Vb=Vlv(:,2);Vc=Vlv(:,3); al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); lv=sqrt(al.^2+be.^2)/Vnom;
if md==4; D.t=t;D.lv4=lv;D.tv=tv;D.vdc4=Vdc/800;D.tq=tq;D.iq4=dq(:,2);
else; D.lv11=lv;D.vdc11=Vdc/800;D.iq11=dq(:,2); end
end
function setflt(M,cfg,R,t1,t2)
set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G,...
  'FaultResistance',num2str(R),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function setswell(M,m,t1,t2)
set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
  'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m,m),'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-1e-3,t1,t2,t2+1e-3),'VariationPhaseA','off');
end
function E=emfcal(M,Vnom)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.30'); E=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(E));
o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))'; lv=max(abs(V(t>0.2,:)),[],'all')/Vnom; E=E/max(0.5,lv);
end
function V0=emfcal_swell(M,Vnom)
set_param([M '/Grid'],'VariationEntity','None'); set_param([M '/mode'],'Value','4');
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime','0.30'); V0=10e3*1.125; set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))'; lv=max(abs(V(t>0.2,:)),[],'all')/Vnom; V0=V0/max(0.5,lv);
end
function Rf=rfcal(M,cfg,tV,t_f,Tsim,Vnom)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime',num2str(t_f+0.2)); best=15; berr=9;
for R=[2 5 12 30 80]
  setflt(M,cfg,R,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,t_f+0.2,size(V,1))';
  idx=t>=t_f+0.05&t<t_f+0.10; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc);be=(2/3)*(sqrt(3)/2)*(Vb-Vc); res=mean(sqrt(al.^2+be.^2))/Vnom;
  if abs(res-tV)<berr; berr=abs(res-tV); best=R; end
end
Rf=best;
end
function m=ampcal(M,tV,t_f,dur,Tsim,Vnom)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime',num2str(t_f+0.2)); best=tV; berr=9;
for mm=[tV-0.05 tV tV+0.08 tV+0.16]
  setswell(M,mm,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,t_f+0.2,size(V,1))';
  idx=t>=t_f+0.05&t<t_f+0.10; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc);be=(2/3)*(sqrt(3)/2)*(Vb-Vc); vs=mean(sqrt(al.^2+be.^2))/Vnom;
  if abs(vs-tV)<berr; berr=abs(vs-tV); best=mm; end
end
m=best;
end
