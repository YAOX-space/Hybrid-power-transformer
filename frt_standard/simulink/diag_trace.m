function diag_trace()
% diag_trace.m — log the closed-loop expert's command time-series (mode 11, asym weights) on a
% mild 1ph_g, to test the "closed-loop oscillation/instability" hypothesis for Vdc collapse.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Vnom=326.6; Imax=173.2;
copyfile('sac_asym_weights.mat','sac_actor_weights.mat');   % mode 11 uses asym
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.625; Tsim=0.9;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
set_param([M '/mode'],'Value','4'); set_param([M '/iq_ref'],'Value','0');
set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom); set_param([M '/Grid'],'Voltage',num2str(emfV));

% add To-Workspace taps on the 3 HLC outputs (branch existing lines)
taps={'iqlog','HLC/1';'msedlog','HLC/2';'mseqlog','HLC/3'};
for k=1:3
  nm=taps{k,1};
  if getSimulinkBlockHandle([M '/' nm])<0
    add_block('simulink/Sinks/To Workspace',[M '/' nm],'Position',[900 300+40*k 960 320+40*k], ...
      'VariableName',nm,'SaveFormat','Array');
    add_line(M,taps{k,2},[nm '/1'],'autorouting','on');
  end
end

cfg=struct('A','on','B','off','C','off','G','on');
set_fault(M,cfg,12,t_f,t_f+dur);
set_param([M '/fclass'],'Value','2'); set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/mode'],'Value','11'); set_param(M,'StopTime',num2str(Tsim));
clear functions
o=sim(M);
iq=o.get('iqlog'); md=o.get('msedlog'); mq=o.get('mseqlog');
Vdc=o.get('Vdc'); nV=numel(Vdc); tV=linspace(0,Tsim,nV)';
fwin=tV>=t_f & tV<t_f+dur;
% resample command logs onto a common length for stats
getcol=@(x) x(:,end);
iqc=getcol(iq)/Imax; mdc=getcol(md); mqc=getcol(mq);
nf=@(x) [min(x) max(x) mean(x) std(x)];
fprintf('\n1ph_g mild, mode-11 asym closed loop. Command stats during fault:\n');
fprintf('%-8s  min     max     mean    std\n','signal');
fprintf('iq(pu)  %7.3f %7.3f %7.3f %7.3f\n', nf(iqc));
fprintf('mse_d   %7.3f %7.3f %7.3f %7.3f\n', nf(mdc));
fprintf('mse_q   %7.3f %7.3f %7.3f %7.3f\n', nf(mqc));
fprintf('Vdc(pu) %7.3f %7.3f %7.3f %7.3f\n', nf(Vdc(fwin)/800));
% count zero-crossings / direction reversals of iq as a chatter proxy
s=sign(iqc-mean(iqc)); flips=sum(abs(diff(s))>0);
fprintf('\niq reversals about its mean: %d (high => chattering/oscillating command)\n', flips);
fprintf('Vdc swing (max-min) during fault: %.3f pu\n', max(Vdc(fwin))/800-min(Vdc(fwin))/800);
end
function set_fault(M,cfg,Rf,t1,t2)
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(Rf),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t1,t2));
end
