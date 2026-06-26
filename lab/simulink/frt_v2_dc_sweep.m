function frt_v2_dc_sweep(tag, scrlist, depthlist, ftlist, cmdgrid)
% frt_v2_dc_sweep — Stage A: characterise the SWELL DC-bus undershoot at the switching layer as a
% function of (swell depth, SCR, converter command), to test whether the averaged ODE can be extended
% to SEE it (the swell_3ph survive=FAIL cluster the ODE proxy is blind to). Open-loop: HLC mode 10
% (external setpoint) commands a fixed (iq, mse_d, mse_q); we impose the swell and capture the Vdc
% trajectory. Mirrors the LVRT Vdc calibration that fitted the 1.9*V_se_d drain coefficient.
%
%   cmdgrid: N x 3 rows of [iq_pu, mse_d, mse_q]  (iq scaled by I_action_peak, like the SAC branch)
% Saves ../results/dc_sweep_<tag>.mat and prints Vdc_min / t_min(rel clear) / Vdc_settle per case.
here=fileparts(mfilename('fullpath')); cd(here); p=pu_params(); M='hpt_frt_full';
build_hpt_frt_full(4,'swell'); set_param(M,'SimulationMode','normal');
set_param([M '/mode'],'Value','10');                       % external setpoint (open-loop)
tf=0.08; dur=0.40;                                          % long enough swell to settle DC before clear
set_param([M '/t_fault'],'Value',num2str(tf)); set_param([M '/fdur'],'Value',num2str(dur));
set_param(M,'StopTime',num2str(tf+dur+0.35));

rows=struct('ft',{},'scr',{},'depth',{},'iq',{},'msed',{},'mseq',{}, ...
            'Vdc_min',{},'t_min_rel',{},'Vdc_settle',{},'Vdc_clear',{});
for si=1:numel(scrlist)
  scr=scrlist(si);
  if scr==10, Rg=7.9057; Lg=0.075494; else, Rg=26.3523; Lg=0.251646; end
  set_param([M '/Zg'],'Resistance',num2str(Rg),'Inductance',num2str(Lg));
  for di=1:numel(depthlist)
    dep=depthlist(di);
    for fi=1:numel(ftlist)
      ft=ftlist{fi}; is1=strcmp(ft,'swell_1ph');
      set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
        'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',dep,dep), ...
        'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',tf-1e-3,tf,tf+dur,tf+dur+1e-3), ...
        'VariationPhaseA',oo(is1));
      for ci=1:size(cmdgrid,1)
        iq=cmdgrid(ci,1); msed=cmdgrid(ci,2); mseq=cmdgrid(ci,3);
        set_param([M '/iq_ref'],'Value',num2str(iq*p.I_action_peak));
        set_param([M '/mse_d'],'Value',num2str(msed));
        set_param([M '/mse_q'],'Value',num2str(mseq));
        o=sim(M); t=o.get('tout'); Vdc=o.get('Vdc')/800;
        wf = t>=tf & t<=tf+dur+0.35;
        [vmin,im]=min(Vdc(wf)); tw=t(wf); tmin=tw(im)-(tf+dur);     % t_min relative to CLEAR instant
        clr = abs(t-(tf+dur))<2e-3; vclr = mean(Vdc(clr));
        st  = t>=tf+dur-0.02 & t<=tf+dur; vset = mean(Vdc(st));     % settled-during-swell (pre-clear)
        rows(end+1)=struct('ft',ft,'scr',scr,'depth',dep,'iq',iq,'msed',msed,'mseq',mseq, ...
          'Vdc_min',vmin,'t_min_rel',tmin,'Vdc_settle',vset,'Vdc_clear',vclr); %#ok<AGROW>
        fprintf('%-9s scr%-2g d%.2f | iq=%+.2f msed=%+.2f mseq=%+.2f | Vdc_settle=%.3f Vdc_min=%.3f @%+.3fs(clr) \n', ...
          ft,scr,dep,iq,msed,mseq,vset,vmin,tmin);
      end
    end
  end
end
metrics_version='frt-v2'; %#ok<NASGU> % switching-layer calibration artifact (governance: active dirs require frt-v2 tag)
save(sprintf('../results/dc_sweep_%s.mat',tag),'rows','metrics_version');
fprintf('=== %d cases -> ../results/dc_sweep_%s.mat ===\n', numel(rows), tag);
end
function s=oo(b), if b, s='on'; else, s='off'; end, end
