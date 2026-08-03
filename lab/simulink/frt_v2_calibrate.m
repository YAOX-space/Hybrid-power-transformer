function frt_v2_calibrate(category, scrval)
% frt_v2_calibrate — build the OPEN-LOOP (converter-idle) fault-severity calibration curve for the
% switching model, so the full-320 switching run can reproduce each ODE scenario's imposed sag (Vg_p =
% fault_sequence(ft,target_V_pu)). For each fault_type at one SCR, sweep the fault resistance (LVRT) or
% source swell amplitude (HVRT) with the HLC in mode 10 (external setpoint) commanding ZERO injection,
% and record the settled LV-terminal positive-seq V+. Saves ../results/calib_<category>_scr<scr>.mat.
%   frt_v2_calibrate('LVRT',3) / ('LVRT',10) / ('HVRT',2) / ('HVRT',15)
here=fileparts(mfilename('fullpath')); cd(here); p=pu_params(); Vnom=p.VLN_peak; M='hpt_frt_full';
[Rg,Lg] = grid_impedance_for_scr(scrval);

isH = strcmp(category,'HVRT');
if isH, build_hpt_frt_full(4,'swell'); fts={'swell_3ph','swell_1ph'}; sweep=linspace(1.10,2.40,9);
else,   build_hpt_frt_full(4);         fts={'sym3ph','1ph_g','2ph','2ph_g'}; sweep=logspace(log10(0.5),log10(400),10); end
set_param(M,'SimulationMode','normal');
% grid impedance lives on different blocks: /Zg (swell build) vs the 3φ Source /Grid (fault build)
if isH, set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
else,   set_param([M '/Grid'],'Resistance',num2str(Rg),'Inductance',num2str(Lg)); end
set_param([M '/mode'],'Value','10');                 % external setpoint
set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
tf=0.08; dur=0.20; set_param([M '/t_fault'],'Value',num2str(tf)); set_param([M '/fdur'],'Value',num2str(dur));
set_param(M,'StopTime',num2str(tf+dur+0.05));
cfg = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'},{[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});

curves = struct('ft',{},'param',{},'Vplus',{});   % struct array (field names can't start with a digit)
for fi=1:numel(fts)
  ft=fts{fi}; Vp=zeros(size(sweep));
  for k=1:numel(sweep)
    if isH
      is1=strcmp(ft,'swell_1ph');
      set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
        'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',sweep(k),sweep(k)), ...
        'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',tf-1e-3,tf,tf+dur,tf+dur+1e-3), ...
        'VariationPhaseA',tern(is1,'on','off'));
    else
      c=cfg(ft);
      set_param([M '/GridFault'],'FaultA',oo(c(1)),'FaultB',oo(c(2)),'FaultC',oo(c(3)),'GroundFault',oo(c(4)), ...
        'FaultResistance',num2str(sweep(k)),'GroundResistance','0.001','SwitchTimes',sprintf('[%.4f %.4f]',tf,tf+dur));
    end
    o=sim(M); t=o.get('tout'); V=o.get('Vlv_abc'); dt=median(diff(t)); q=max(1,round(0.005/dt));
    a=(2/3)*(V(:,1)-0.5*V(:,2)-0.5*V(:,3)); b=(2/3)*(sqrt(3)/2)*(V(:,2)-V(:,3));
    ad=[zeros(q,1);a(1:end-q)]; bd=[zeros(q,1);b(1:end-q)];
    V1=movmean(sqrt((0.5*(a-bd)).^2+(0.5*(b+ad)).^2)/Vnom, max(1,round(0.02/dt)));
    w=t>=tf+0.08 & t<=tf+dur; Vp(k)=median(V1(w));
    fprintf('  %-9s scr%g  param=%.4g -> V+=%.3f\n', ft, scrval, sweep(k), Vp(k));
  end
  curves(fi) = struct('ft',ft,'param',sweep,'Vplus',Vp);
end
out=sprintf('../results/calib_%s_scr%g.mat',category,scrval);
metrics_version='frt-v2'; %#ok<NASGU>
calibration = struct('category',category,'scr',scrval,'Rg_ohm',Rg,'Lg_H',Lg, ...
    'source','frt_scenarios_expanded.csv/frt_scenarios.csv');
save(out,'curves','metrics_version','calibration'); fprintf('wrote %s\n', out);
end
function [Rg,Lg]=grid_impedance_for_scr(scrval)
  files={'../frt_scenarios_expanded.csv','../frt_scenarios.csv'};
  for fi=1:numel(files)
    if isfile(files{fi})
      A=readtable(files{fi});
      ix=find(abs(A.scr-scrval)<1e-9,1);
      if ~isempty(ix), Rg=A.Rg_ohm(ix); Lg=A.Lg_H(ix); return; end
    end
  end
  error('No grid impedance found for SCR=%g in scenario CSV files', scrval);
end
function s=oo(b), if b, s='on'; else, s='off'; end, end
function s=tern(c,a,b), if c, s=a; else, s=b; end, end
