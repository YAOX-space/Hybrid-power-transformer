function gen_allctrl_figs()
% gen_allctrl_figs.m — FINAL all-controller comparison figures (consistent calibration).
%  1 fig_all_320_bar.png    per-domain FRT bars, 5 controllers, from frt320_m*_*.mat (real data)
%  2 fig_all_criteria.png   criterion-level bars (LVRT 240 + HVRT 80), 5 controllers
%  3 fig_wave_sym_deep_all  waveform sym3ph 0.2 weak — m4/m7/m8/m12 (m13≡m12 on LVRT)
%  4 fig_wave_2phg_all      waveform 2ph_g 0.5 weak — m4/m7/m8/m12
%  5 fig_wave_hvrt_all      waveform swell_3ph 1.3 weak — m4/m7/m8/m12/m13
%  6 fig_sac_convergence    SAC 4-expert training curves (parsed from train_experts_v2.log)
here=fileparts(mfilename('fullpath')); cd(here);
figdir='../../results/figs'; if ~exist(figdir,'dir'); mkdir(figdir); end
Vnom=400*sqrt(2)/sqrt(3); M='hpt_frt_full';
MODES=[4 7 8 12 13 14];
MLAB={'dq-legacy','strongest fixed (m7)','MPC (m8)','SAC 4-expert (m12)','Hybrid SAC+MPC (m13)','Residual-SAC (m14)'};
COLS=[0.45 0.55 0.75; 0.35 0.65 0.40; 0.55 0.40 0.75; 0.85 0.40 0.30; 0.95 0.65 0.15; 0.20 0.20 0.20];
chunks={'sym3ph','1ph_g','2ph','2ph_g'}; crit={'connect','reactive','limit','recover','survive','frt'};

% ============ data from consistent-calibration runs ============
% m13 LVRT == m12 (code-equivalent; verified row-identical on sym3ph) -> reuse m12 chunk files
src=@(md,ck) sprintf('../results/frt320_m%d_%s.mat', md, ck);
NM=numel(MODES);
dom=zeros(NM,6); critLV=zeros(NM,6); critHV=zeros(NM,6); nLV=0;
for m=1:NM
  md=MODES(m); nlv=0; npass=0;
  for k=1:4
    f=src(md,chunks{k}); if md==13, f=src(12,chunks{k}); end
    S=load(f); r=[S.results.c];
    dom(m,k)=100*mean([r.frt]); nlv=nlv+numel(r); npass=npass+sum([r.frt]);
    for c=1:6, critLV(m,c)=critLV(m,c)+sum([r.(crit{c})]); end
  end
  H=load(src(md,'hvrt')); rh=[H.results.c];
  dom(m,5)=100*mean([rh.frt]);
  for c=1:6, critHV(m,c)=100*mean([rh.(crit{c})]); end
  dom(m,6)=100*(npass+sum([rh.frt]))/(nlv+numel(rh));
  critLV(m,:)=100*critLV(m,:)/nlv; nLV=nlv;
end

% ---- Fig 1: per-domain bars ----
f=figure('Position',[60 60 1100 460],'Color','w');
b=bar(dom','grouped'); for m=1:NM, b(m).FaceColor=COLS(m,:); end
set(gca,'XTickLabel',{'sym3ph','1ph\_g','2ph','2ph\_g','HVRT','ALL 320'},'FontSize',11);
ylabel('FRT pass rate (%)'); ylim([0 118]); grid on;
legend(MLAB,'Location','northoutside','Orientation','horizontal','FontSize',9);
title('Full 320 standard FRT — all controllers (consistent calibration, switching-level Simulink)');
for g=1:6, for m=1:NM
  text(g+(m-(NM+1)/2)*0.78/NM, dom(m,g)+3, sprintf('%.0f',dom(m,g)),'Hor','center','FontSize',7);
end, end
exportgraphics(f,[figdir '/fig_all_320_bar.png'],'Resolution',150); close(f);
fprintf('Fig1 saved. ALL-320: %s\n', sprintf('%.1f%% ',dom(:,6)));

% ---- Fig 2: criterion-level ----
f=figure('Position',[60 60 1100 700],'Color','w');
subplot(2,1,1);
b=bar(critLV','grouped'); for m=1:NM, b(m).FaceColor=COLS(m,:); end
set(gca,'XTickLabel',crit,'FontSize',10); ylabel('pass (%)'); ylim([0 115]); grid on;
title(sprintf('Criterion-level — LVRT %d',nLV)); legend(MLAB,'Location','southwest','FontSize',8);
subplot(2,1,2);
b=bar(critHV','grouped'); for m=1:NM, b(m).FaceColor=COLS(m,:); end
set(gca,'XTickLabel',crit,'FontSize',10); ylabel('pass (%)'); ylim([0 115]); grid on;
title('Criterion-level — HVRT 80');
exportgraphics(f,[figdir '/fig_all_criteria.png'],'Resolution',150); close(f);
fprintf('Fig2 saved\n');

% ============ waveform comparisons ============
Rg=11.79; Lg=0.2626; t_f=0.30; Tsim=1.0;   % weak grid SCR=3
% --- LVRT scenarios (modes 4 7 8 12; m13≡m12) ---
build_hpt_frt_full(4); set_param(M,'SimulationMode','normal');
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
EMF=emfcal(M,Vnom); set_param([M '/Grid'],'Voltage',num2str(EMF));
wjobs={ struct('ft','sym3ph','cfg',struct('A','on','B','on','C','on','G','on'),'tV',0.2,'dur',0.5,'fc',1, ...
        'ttl','sym3ph deep LVRT (residual 0.2, weak grid) — all controllers','fn','fig_wave_sym_deep_all.png'), ...
        struct('ft','2ph_g','cfg',struct('A','on','B','on','C','off','G','on'),'tV',0.5,'dur',0.5,'fc',4, ...
        'ttl','2ph\_g asymmetric LVRT (residual ~0.5, weak grid) — all controllers','fn','fig_wave_2phg_all.png') };
for j=1:2
  w=wjobs{j}; Rf=rfcal(M,w.cfg,w.tV,t_f,Vnom);
  set_param([M '/fclass'],'Value',num2str(w.fc)); set_param([M '/fdur'],'Value',num2str(w.dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param(M,'StopTime',num2str(Tsim)); setflt(M,w.cfg,Rf,t_f,t_f+w.dur);
  D=cell(1,5); use=[4 7 8 12 14];
  for m=1:5
    set_param([M '/mode'],'Value',num2str(use(m)));
    set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
    o=sim(M); D{m}=collect(o,Tsim,Vnom);
  end
  plotN(D,COLS([1 2 3 4 6],:),MLAB([1 2 3 4 6]),t_f,w.dur,w.ttl,[figdir '/' w.fn],5);
  fprintf('waveform %s saved\n', w.fn);
end
Simulink.sdi.clear;
% --- HVRT scenario (all 5 modes) ---
build_hpt_frt_full(4,'swell'); set_param(M,'SimulationMode','normal');
set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
V0=emfcal_swell(M,Vnom); set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
dur=0.30; amp=ampcal(M,1.3,t_f,Vnom);
set_param([M '/fclass'],'Value','5'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
set_param(M,'StopTime',num2str(Tsim)); setswell(M,amp,t_f,t_f+dur);
D=cell(1,NM);
for m=1:NM
  set_param([M '/mode'],'Value',num2str(MODES(m)));
  set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
  o=sim(M); D{m}=collect(o,Tsim,Vnom);
end
plotN(D,COLS,MLAB,t_f,dur,'swell\_3ph deep HVRT (1.3 pu, weak grid) — all controllers', ...
      [figdir '/fig_wave_hvrt_all.png'],NM);
fprintf('waveform fig_wave_hvrt_all saved\n');
Simulink.sdi.clear;

% ============ Fig 6: SAC convergence from training log ============
try
  L=readlines('../train_experts_v2.log');
  exps={'sym','asym','hvrt_sym','hvrt_asym'}; econ=containers.Map;
  for e=1:4, econ(exps{e})=[]; end
  cur='';
  for i=1:numel(L)
    ln=char(L(i));
    t1=regexp(ln,'=== expert "(\w+)"','tokens');
    if ~isempty(t1), cur=t1{1}{1}; continue; end
    t2=regexp(ln,'step=\s*([\d,]+)\s+FRT=(\d+)%','tokens');
    if ~isempty(t2) && ~isempty(cur) && isKey(econ,cur)
      st=str2double(strrep(t2{1}{1},',','')); fr=str2double(t2{1}{2});
      econ(cur)=[econ(cur); st fr];
    end
  end
  f=figure('Position',[60 60 860 460],'Color','w'); hold on;
  ec=[0.85 0.40 0.30; 0.35 0.65 0.40; 0.55 0.40 0.75; 0.45 0.55 0.75];
  for e=1:4
    d=econ(exps{e});
    if ~isempty(d)
      plot(d(:,1)/1e3, d(:,2),'-o','Color',ec(e,:),'LineWidth',1.4,'MarkerSize',4);
      bs=cummax(d(:,2)); plot(d(:,1)/1e3, bs,'--','Color',ec(e,:),'LineWidth',0.8,'HandleVisibility','off');
    end
  end
  xlabel('training steps (\times10^3)'); ylabel('ODE FRT pass rate (%)'); ylim([0 105]); grid on;
  legend({'sym','asym','hvrt\_sym','hvrt\_asym'},'Location','southeast','FontSize',10);
  title('SAC 4-expert training convergence (faithful ODE; solid=eval every 25k, dashed=best-so-far checkpoint)');
  exportgraphics(f,[figdir '/fig_sac_convergence.png'],'Resolution',150); close(f);
  fprintf('Fig6 (convergence) saved\n');
catch ME
  fprintf('convergence fig failed: %s\n', ME.message);
end
fprintf('ALL FIGS DONE -> %s\n', figdir);
end

% ---------- helpers ----------
function D=collect(o,Tsim,Vnom)
Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
t=linspace(0,Tsim,size(Vlv,1))'; tv=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
Va=Vlv(:,1);Vb=Vlv(:,2);Vc=Vlv(:,3); al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc);
D=struct('t',t,'lv',sqrt(al.^2+be.^2)/Vnom,'tv',tv,'vdc',Vdc/800,'tq',tq,'iq',dq(:,2));
end
function plotN(D,cols,labs,t_f,dur,ttl,fn,n)
f=figure('Position',[60 60 900 700],'Color','w');
ax1=subplot(3,1,1); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.5 1.5],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.t,D{m}.lv,'-','Color',cols(m,:),'LineWidth',1.2); end
yline(0.9,'--k','HandleVisibility','off'); ylabel('LV pos-seq (pu)'); grid on; set(ax1,'FontSize',9);
ylim([0 max(1.35, max(D{n}.lv)*1.05)]);
legend(labs(1:n),'Location','eastoutside','FontSize',8); title(ttl,'Interpreter','tex');
ax2=subplot(3,1,2); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.5 1.5],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.tv,D{m}.vdc,'-','Color',cols(m,:),'LineWidth',1.2); end
yline(0.75,'--k','HandleVisibility','off'); yline(1.25,'--k','HandleVisibility','off');
ylim([0.4 1.4]); ylabel('V_{dc} (pu)'); grid on; set(ax2,'FontSize',9);
legend(labs(1:n),'Location','eastoutside','FontSize',8);
ax3=subplot(3,1,3); hold on;
fill([t_f t_f+dur t_f+dur t_f],[-80 -80 80 80],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.tq,D{m}.iq,'-','Color',cols(m,:),'LineWidth',1.0); end
yline(0.35*173.2,'--k','HandleVisibility','off'); yline(-0.35*173.2,'--k','HandleVisibility','off');
ylim([-80 80]); xlabel('time (s)'); ylabel('shunt i_q (A)'); grid on; set(ax3,'FontSize',9);
legend(labs(1:n),'Location','eastoutside','FontSize',8);
exportgraphics(f,fn,'Resolution',150); close(f);
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
function Rf=rfcal(M,cfg,tV,t_f,Vnom)
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime',num2str(t_f+0.2)); best=15; berr=9;
for R=[2 5 12 30 80 200]
  setflt(M,cfg,R,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,t_f+0.2,size(V,1))';
  idx=t>=t_f+0.05&t<t_f+0.10; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc);be=(2/3)*(sqrt(3)/2)*(Vb-Vc); res=mean(sqrt(al.^2+be.^2))/Vnom;
  if abs(res-tV)<berr; berr=abs(res-tV); best=R; end
end
Rf=best;
end
function m=ampcal(M,tV,t_f,Vnom)
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
function setflt(M,cfg,R,t1,t2)
set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G,...
  'FaultResistance',num2str(R),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
function setswell(M,m,t1,t2)
set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
  'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m,m),'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-1e-3,t1,t2,t2+1e-3),'VariationPhaseA','off');
end
