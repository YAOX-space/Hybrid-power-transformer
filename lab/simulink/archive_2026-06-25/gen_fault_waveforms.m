function gen_fault_waveforms()
% gen_fault_waveforms.m — per-fault-type switching-level waveform comparison figures.
% Overlays canonical Mode 1 (tuned fixed-law, internal mi=7), Mode 2 (one-step explicit MPC,
% mi=8), Mode 5 (online-gated multi-expert SAC = MAIN METHOD, mi=12).
% 3 panels: LV positive-seq voltage / shared-DC Vdc / shunt reactive current iq.
% Coverage: all 6 fault types at deepest representative — LVRT {sym3ph,1ph_g,2ph,2ph_g} at
% residual 0.2 weak grid (SCR=3); HVRT {swell_3ph,swell_1ph} at 1.3 weak grid.
% Grid impedance = AUDITED validation口径 (X/R=3: weak Rg=26.35/Lg=0.2516), matching frt320_m* runs
% (NOTE: the older gen_allctrl_figs.m used a stale X/R=7 value — do not reuse for audited figures).
% Canonical modes per CONTROL_MODES.md. Saves results/figs/fig_wave_<fault>.png.
here=fileparts(mfilename('fullpath')); cd(here);
M='hpt_frt_full'; Vnom=400*sqrt(2)/sqrt(3);
figdir=fullfile(here,'..','..','results','figs');   % absolute -> immune to cwd drift during sim()
if ~isfolder(figdir), mkdir(figdir); end
USE=[7 8 12];
LAB={'Mode 1 fixed-law','Mode 2 one-step MPC','Mode 5 multi-expert SAC (main)'};
COLS=[0.55 0.55 0.55; 0.20 0.45 0.75; 0.85 0.30 0.30];   % grey / blue / red
Rg=26.35; Lg=0.2516; t_f=0.30; Tsim=1.0;                  % weak grid SCR=3 (X/R=3)

% ===== LVRT faults =====
build_hpt_frt_full(4); set_param(M,'SimulationMode','normal');
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
EMF=emfcal(M,Vnom); set_param([M '/Grid'],'Voltage',num2str(EMF));
LV={ {'sym3ph',struct('A','on','B','on','C','on','G','on'),1,'sym3ph symmetric 3-phase LVRT (residual 0.2, weak grid)','fig_wave_sym3ph.png'}, ...
     {'1ph_g', struct('A','on','B','off','C','off','G','on'),2,'1ph\_g single-line-ground LVRT (residual 0.2, weak grid; LV pos-seq floored ~0.78 by \Delta-Yg)','fig_wave_1phg.png'}, ...
     {'2ph',   struct('A','on','B','on','C','off','G','off'),2,'2ph phase-phase LVRT (residual 0.2, weak grid)','fig_wave_2ph.png'}, ...
     {'2ph_g', struct('A','on','B','on','C','off','G','on'),2,'2ph\_g two-phase-ground LVRT (residual 0.2, weak grid)','fig_wave_2phg.png'} };
dur=0.5;
for j=1:numel(LV)
  cfg=LV{j}{2}; fc=LV{j}{3}; ttl=LV{j}{4}; fn=LV{j}{5};
  Rf=rfcal(M,cfg,0.2,t_f,Vnom);
  set_param([M '/fclass'],'Value',num2str(fc)); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param(M,'StopTime',num2str(Tsim)); setflt(M,cfg,Rf,t_f,t_f+dur);
  D=cell(1,3);
  for m=1:3
    set_param([M '/mode'],'Value',num2str(USE(m)));
    set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
    o=sim(M); D{m}=collect(o,Tsim,Vnom);
  end
  plotN(D,COLS,LAB,t_f,dur,ttl,[figdir '/' fn],3);
  fprintf('saved %s (Rf=%g ohm)\n',fn,Rf);
end
Simulink.sdi.clear;

% ===== HVRT faults =====
build_hpt_frt_full(4,'swell'); set_param(M,'SimulationMode','normal');
set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
V0=emfcal_swell(M,Vnom); set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
HV={ {0,'swell\_3ph symmetric overvoltage HVRT (1.3 pu, weak grid)','fig_wave_swell3ph.png'}, ...
     {1,'swell\_1ph single-phase overvoltage HVRT (1.3 pu, weak grid)','fig_wave_swell1ph.png'} };
dur=0.30;
for j=1:numel(HV)
  is1=HV{j}{1}; ttl=HV{j}{2}; fn=HV{j}{3};
  amp=ampcal(M,1.3,t_f,Vnom,is1);
  set_param([M '/fclass'],'Value','5'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
  set_param(M,'StopTime',num2str(Tsim)); setswell(M,amp,t_f,t_f+dur,is1);
  D=cell(1,3);
  for m=1:3
    set_param([M '/mode'],'Value',num2str(USE(m)));
    set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
    o=sim(M); D{m}=collect(o,Tsim,Vnom);
  end
  plotN(D,COLS,LAB,t_f,dur,ttl,[figdir '/' fn],3);
  fprintf('saved %s\n',fn);
end
Simulink.sdi.clear;
fprintf('ALL 6 per-fault waveform figs done -> %s\n', figdir);
end

% ---------- helpers (canonical口径; X/R=3 grid) ----------
function D=collect(o,Tsim,Vnom)
Vlv=o.get('Vlv_abc'); Vdc=o.get('Vdc'); dq=squeeze(o.get('dq')).';
t=linspace(0,Tsim,size(Vlv,1))'; tv=linspace(0,Tsim,numel(Vdc))'; tq=linspace(0,Tsim,size(dq,1))';
Va=Vlv(:,1);Vb=Vlv(:,2);Vc=Vlv(:,3); al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc);
D=struct('t',t,'lv',sqrt(al.^2+be.^2)/Vnom,'tv',tv,'vdc',Vdc/800,'tq',tq,'iq',dq(:,2));
end
function plotN(D,cols,labs,t_f,dur,ttl,fn,n)
f=figure('Position',[60 60 920 720],'Color','w');
ax1=subplot(3,1,1); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.5 1.5],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.t,D{m}.lv,'-','Color',cols(m,:),'LineWidth',1.3); end
yline(0.9,'--k','HandleVisibility','off'); ylabel('LV pos-seq (pu)'); grid on; set(ax1,'FontSize',9);
ylim([0 max(1.35, max(D{n}.lv)*1.05)]);
legend(labs(1:n),'Location','eastoutside','FontSize',8); title(ttl,'Interpreter','tex','FontSize',10);
ax2=subplot(3,1,2); hold on;
fill([t_f t_f+dur t_f+dur t_f],[0 0 1.5 1.5],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.tv,D{m}.vdc,'-','Color',cols(m,:),'LineWidth',1.3); end
yline(0.75,'--k','HandleVisibility','off'); yline(1.25,'--k','HandleVisibility','off');
ylim([0.4 1.4]); ylabel('V_{dc} (pu)'); grid on; set(ax2,'FontSize',9);
legend(labs(1:n),'Location','eastoutside','FontSize',8);
ax3=subplot(3,1,3); hold on;
fill([t_f t_f+dur t_f+dur t_f],[-80 -80 80 80],[0.96 0.96 0.84],'EdgeColor','none','HandleVisibility','off');
for m=1:n, plot(D{m}.tq,D{m}.iq,'-','Color',cols(m,:),'LineWidth',1.1); end
yline(pu_params().I_conv_max_pu*pu_params().I_dq_base_peak,'--k','HandleVisibility','off'); yline(-pu_params().I_conv_max_pu*pu_params().I_dq_base_peak,'--k','HandleVisibility','off');
ylim([-80 80]); xlabel('time (s)'); ylabel('shunt i_q (A)'); grid on; set(ax3,'FontSize',9);
legend(labs(1:n),'Location','eastoutside','FontSize',8);
exportgraphics(f,fn,'Resolution',150); close(f);
end
function E=emfcal(M,Vnom)
set_param([M '/mode'],'Value','7'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.30'); E=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(E));
o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))'; lv=max(abs(V(t>0.2,:)),[],'all')/Vnom; E=E/max(0.5,lv);
end
function V0=emfcal_swell(M,Vnom)
set_param([M '/Grid'],'VariationEntity','None'); set_param([M '/mode'],'Value','7');
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime','0.30'); V0=10e3*1.125; set_param([M '/Grid'],'PositiveSequence',['[' num2str(V0) ' 0 50]']);
o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,0.30,size(V,1))'; lv=max(abs(V(t>0.2,:)),[],'all')/Vnom; V0=V0/max(0.5,lv);
end
function Rf=rfcal(M,cfg,tV,t_f,Vnom)
set_param([M '/mode'],'Value','7'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime',num2str(t_f+0.2)); best=15; berr=9;
for R=[2 5 12 30 80 200]
  setflt(M,cfg,R,t_f,t_f+0.12); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,t_f+0.2,size(V,1))';
  idx=t>=t_f+0.05&t<t_f+0.10; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc);be=(2/3)*(sqrt(3)/2)*(Vb-Vc); res=mean(sqrt(al.^2+be.^2))/Vnom;
  if abs(res-tV)<berr; berr=abs(res-tV); best=R; end
end
Rf=best;
end
function m=ampcal(M,tV,t_f,Vnom,is1)
set_param([M '/mode'],'Value','7'); set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param(M,'StopTime',num2str(t_f+0.2)); best=tV; berr=9;
for mm=[tV-0.05 tV tV+0.08 tV+0.16]
  setswell(M,mm,t_f,t_f+0.12,is1); o=sim(M); V=o.get('Vlv_abc'); t=linspace(0,t_f+0.2,size(V,1))';
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
function setswell(M,m,t1,t2,is1)
ph='off'; if is1, ph='on'; end
set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
  'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',m,m),'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-1e-3,t1,t2,t2+1e-3),'VariationPhaseA',ph);
end
