function w23_emt_crosscheck()
% w23_emt_crosscheck.m — Phase-2 W2.3: EMT (phase-1 switching model) vs phasor sag, same
% impedance divider. Sweep fault resistance at MV; record fundamental residual at LV during
% fault with the HPT PASSIVE (mode 10, zero commands) so this is a pure network comparison.
% The OpenDSS twin (w23_opendss_twin.py) solves the identical source-Z/fault-r/transformer
% divider in phasor domain. Agreement bound -> phasor-approximation credibility for sag studies.
here=fileparts(mfilename('fullpath')); cd(here);
build_hpt_frt_full(4); M='hpt_frt_full'; set_param(M,'SimulationMode','normal');
Vnom=400*sqrt(2)/sqrt(3);
scr=3; Zb=10e3^2/400e3; Zg=Zb/scr; Rg=Zg/sqrt(50); Lg=7*Rg/(2*pi*50);
t_f=0.10; dur=0.3; Tsim=0.5;
set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
set_param([M '/mode'],'Value','10');
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
set_param([M '/GridFault'],'FaultA','off','FaultB','off','FaultC','off','GroundFault','off','SwitchTimes','[99 100]');
set_param(M,'StopTime','0.35'); V0=10e3*1.125; set_param([M '/Grid'],'Voltage',num2str(V0));
o=sim(M); Vlv=o.get('Vlv_abc'); tl=linspace(0,0.35,size(Vlv,1))';
emfV=V0/max(0.5,max(abs(Vlv(tl>0.25,:)),[],'all')/Vnom); set_param([M '/Grid'],'Voltage',num2str(emfV));
fprintf('EMF=%.0f V (Rg=%.3f ohm, Lg=%.4f H)\n', emfV, Rg, Lg);
cfg=struct('A','on','B','on','C','on','G','on');
fprintf('\n%8s | %12s\n','r_fault','EMT LV resid');
R=[0.5 2 5 12 30];
out=zeros(numel(R),2);
for i=1:numel(R)
  set_param(M,'StopTime',num2str(Tsim));
  set_param([M '/GridFault'],'FaultA',cfg.A,'FaultB',cfg.B,'FaultC',cfg.C,'GroundFault',cfg.G, ...
    'FaultResistance',num2str(R(i)),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',t_f,t_f+dur));
  o=sim(M); V=o.get('Vlv_abc'); tt=linspace(0,Tsim,size(V,1))';
  idx=tt>=t_f+0.1&tt<t_f+0.25; Va=V(idx,1);Vb=V(idx,2);Vc=V(idx,3);
  al=(2/3)*(Va-0.5*Vb-0.5*Vc); be=(2/3)*(sqrt(3)/2)*(Vb-Vc); res=mean(sqrt(al.^2+be.^2))/Vnom;
  out(i,:)=[R(i) res];
  fprintf('%8.1f | %10.4f\n', R(i), res);
end
writematrix(out, '../../phase2/w23_emt_residuals.csv');
fprintf('saved ../../phase2/w23_emt_residuals.csv  (EMF=%.1f V); run w23_opendss_twin.py to compare\n', emfV);
end
