function frt_v2_spotcheck(ncase, MI)
% MI = deployment mode integer: 14 = residual champion (default), 12 = 4-expert gated, 11 = single SAC.
% frt_v2_spotcheck — SMALL frt-v2 switching-level GATE (audit round-5 F). Runs ~12-16 representative
% cases on hpt_frt_full.slx with the frt-v2 HLC (Mode 5, mi=12, 20-D obs / 3-D action / online
% detector), saves the REAL tout + signals, and scores each case with the AUTHORITATIVE evaluator
% frt_v2_evaluate.m (NOT a duplicated criteria block). NOT full-320 — this is the gate before P1.
%
% Each case MAT carries: tout, V1/V2, Vabc/Iabc, dq, Vdc, gate, criterion statuses, response, and the
% checkpoint provenance (run_id + sha) read from the exported weights. Gate conditions are checked at
% the end; if any fails the function errors (STOP — do not proceed to full-320).
here = fileparts(mfilename('fullpath')); cd(here);
assert_metrics_version('frt-v2');                         % pu single-source guard
p = pu_params(); Vnom = p.VLN_peak; M = 'hpt_frt_full';
outdir = '../results/frt_v2_spotcheck'; if ~exist(outdir,'dir'); mkdir(outdir); end
% provenance of the deployed weights (written by export_sac_actor; lab/ is the parent of simulink/).
% Default deployment = the residual champion (mi=14, MPC prior + residual). The provenance MAT MUST
% match the weights mi=14 actually loads (sac_residual_weights.mat) — else provenance is inconsistent.
if nargin<2 || isempty(MI); MI = 14; end
wfile = 'sac_residual_weights.mat';
if MI==11
    wfile='sac_actor_weights.mat';
elseif MI==12 || MI==15
    wfile='sac_sym_weights.mat';
elseif MI==17
    wfile='sac_resexpert_weights.mat';
end
W = load(fullfile('..',wfile)); run_id = char(W.run_id);

% case list: label, fault_type, Rfault(ohm) or swell mult, dur, postwin, SCR, expected category
C = {
 'S1_deep_sym',     'sym3ph', 2,   0.15, 0.40, 3,  'LVRT';
 'S2_mid_sym',      'sym3ph', 12,  0.30, 0.40, 3,  'LVRT';
 'S3_shallow_sym',  'sym3ph', 80,  0.30, 0.40, 3,  'LVRT';
 'S4_deep_sym_scr10','sym3ph',2,   0.15, 0.40, 10, 'LVRT';
 'S5_1phg',         '1ph_g',  5,   0.15, 0.40, 3,  'LVRT';
 'S6_2ph',          '2ph',    5,   0.15, 0.40, 3,  'LVRT';
 'S7_2phg',         '2ph_g',  5,   0.15, 0.40, 3,  'LVRT';
 'S8_1phg_scr10',   '1ph_g',  5,   0.15, 0.40, 10, 'LVRT';
 'S9_recwin',       'sym3ph', 12,  0.30, 0.60, 3,  'LVRT';   % long recovery window
 'S10_swell3',      'swell',  1.75,0.40, 0.40, 3,  'HVRT';   % terminal V+ ~1.17: clean HVRT ride-through (survive PASS); absorption verified by direct iq (~-0.11). A 2.2x swell makes |demand|>0.12 so reactive formally PASSES too, but the abrupt deep-swell clear adds a post-clear Vdc transient — that severe case is reported separately, not the authoritative point.
 'S11_swell1',      'swell',  1.75,0.40, 0.40, 3,  'HVRT';
 'S12_vbound',      '1ph_g',  30,  0.20, 0.40, 3,  'LVRT';   % near 0.9 gate boundary
};
if nargin>=1, C = C(1:min(ncase,size(C,1)),:); end
% LVRT (3ph source + GridFault) and HVRT (programmable swell source) are DIFFERENT builds — sort so each
% grid-mode is built once. mode/fdur/t_fault/iq_ref control blocks exist in both builds.
isH = strcmp(C(:,7),'HVRT'); C = [C(~isH,:); C(isH,:)];

rows = struct([]); curmode = '';
for i = 1:size(C,1)
    lab=C{i,1}; ft=C{i,2}; rfa=C{i,3}; dur=C{i,4}; postw=C{i,5}; scr=C{i,6}; cat=C{i,7};
    need = 'fault'; if strcmp(cat,'HVRT'); need='swell'; end
    if ~strcmp(need,curmode)
        if strcmp(need,'swell'); build_hpt_frt_full(4,'swell'); else; build_hpt_frt_full(4); end
        set_param(M,'SimulationMode','normal'); curmode = need;
    end
    Tsim = dur + postw + 0.1; t_f = 0.05;
    set_param([M '/mode'],'Value',num2str(MI));          % deployment mode (default 14 = residual champion; provenance MAT matches the weights mi loads)
    set_param([M '/fdur'],'Value',num2str(dur)); set_param([M '/t_fault'],'Value',num2str(t_f));
    set_param([M '/iq_ref'],'Value','0'); set_param([M '/mse_d'],'Value','0'); set_param([M '/mse_q'],'Value','0');
    set_param(M,'StopTime',num2str(Tsim));
    if strcmp(cat,'HVRT'); set_swell_local(M,rfa,strcmp(ft,'swell'),t_f,t_f+dur,scr,Vnom);
    else; set_lvrt_local(M,ft,rfa,t_f,t_f+dur,scr,Vnom); end
    o = sim(M);
    tout0 = o.get('tout'); if isempty(tout0); tout0 = o.tout; end
    Vlv0 = o.get('Vlv_abc'); Vdc0 = o.get('Vdc'); dq0 = squeeze(o.get('dq')).'; Ish0 = o.get('Ish_abc');
    % EXCLUDE the simulation cold-start (DC-link/PLL settling): the FRT test evaluates from pre-fault
    % steady state, exactly like the ODE env. Keep 1 cycle of pre-fault for the envelope pre-fault floor.
    m = tout0 >= t_f - 0.02;
    tout = tout0(m); Vlv = Vlv0(m,:); Vdc = Vdc0(m); dq = dq0(m,:); Ish = Ish0(m,:);
    dt = median(diff(tout)); ncyc = max(1, round(0.02/dt));   % 1-cycle (RMS) averaging window
    % sequence VOLTAGE and negative-seq CURRENT from the REAL 3-phase (quarter-cycle delay at true dt).
    % The GB/T envelope is defined on cycle-averaged (RMS) sequence quantities, not the instantaneous
    % estimate (which rings to 0 at a stiff 3ph fault) — so smooth over one cycle.
    [V1,V2] = seqmag(Vlv, Vnom, dt);
    [~,i2]  = seqmag(Ish, p.I_action_peak, dt);              % negative-seq CURRENT (pu of the action base)
    V1 = movmean(V1, ncyc); V2 = movmean(V2, ncyc); i2 = movmean(i2, ncyc);
    iq = movmean(dq(:,2)/p.I_dq_base_peak, ncyc);
    idq = hypot(dq(:,1)/p.I_dq_base_peak, iq);
    Iabc_peak = movmean(max(abs(Ish),[],2)/p.I_dq_base_peak, ncyc);  % cycle-avg current (ignore onset spike)
    opts = struct('V2',V2,'Vdc',Vdc(:)/800,'iq',iq,'i_peak',Iabc_peak,'idq_mag',idq,'i2',i2);
    % residual = RETAINED V+ (deepest imposed sag, small switching-glitch skip) = the GB/T hold floor
    wf = tout>=t_f+0.005 & tout<=t_f+dur-0.005; residual = min(V1(wf));
    res = frt_v2_evaluate(tout(:), V1(:), cat, residual, t_f, dur, opts);
    S = struct('label',lab,'fault_type',ft,'category',cat,'scr',scr,'t_fault',t_f,'dur',dur, ...
        'tout',tout,'V1',V1,'V2',V2,'Vlv_abc',Vlv,'Ish_abc',Ish,'dq',dq,'Vdc',Vdc, ...
        'crit',res,'metrics_version','frt-v2','run_id',run_id,'checkpoint_sha256',char(W.checkpoint_sha256));
    save(fullfile(outdir,[lab '.mat']),'-struct','S');
    rows(i).lab=lab; rows(i).res=res; rows(i).tout=tout; rows(i).nan=any(~isfinite(V1))||any(~isfinite(Vdc));
    fprintf('%-16s %-6s con=%s rea=%s lim=%s rec=%s sur=%s | frt=%s | resp=%s\n', lab, ft, ...
        res.connect.status, res.reactive.status, res.limit.status, res.recover.status, ...
        res.survive.status, res.frt_pass_str, res.response.response_status);
end

% ── GATE conditions (audit F) ──
gate_ok = true; reasons = {};
for i=1:numel(rows)
    if rows(i).nan, gate_ok=false; reasons{end+1}=[rows(i).lab ': NaN']; end
    if any(diff(rows(i).tout)<=0), gate_ok=false; reasons{end+1}=[rows(i).lab ': non-monotonic tout']; end
    if ~strcmp(rows(i).res.metrics_version,'frt-v2'), gate_ok=false; reasons{end+1}=[rows(i).lab ': not frt-v2']; end
end
fprintf('\n=== frt-v2 switching GATE: %d cases, run=%s ===\n', numel(rows), run_id);
if gate_ok, fprintf('GATE PASS: no NaN, real monotonic tout, all frt-v2, provenance attached.\n');
else, fprintf('GATE FAIL:\n'); for k=1:numel(reasons); fprintf('  - %s\n', reasons{k}); end
    error('frt_v2_spotcheck GATE FAILED — STOP, do not run full-320'); end
end

% ---------- helpers ----------
function [V1,V2] = seqmag(Vabc, Vnom, dt)
a = (2/3)*(Vabc(:,1)-0.5*Vabc(:,2)-0.5*Vabc(:,3)); b=(2/3)*(sqrt(3)/2)*(Vabc(:,2)-Vabc(:,3));
q = max(1, round(0.005/dt));   % quarter cycle (5 ms @ 50 Hz) in SAMPLES at the real dt
% 1/4-cycle delay on alpha/beta to split +/- seq (matches the deployment recon)
ad=[zeros(q,1);a(1:end-q)]; bd=[zeros(q,1);b(1:end-q)];
V1=sqrt((0.5*(a-bd)).^2+(0.5*(b+ad)).^2)/Vnom; V2=sqrt((0.5*(a+bd)).^2+(0.5*(b-ad)).^2)/Vnom;
end
function set_lvrt_local(M,ft,Rf,t1,t2,scr,Vnom)
switch ft                                   % field names can't start with a digit -> switch, not struct
  case 'sym3ph', c=[1 1 1 1];
  case '1ph_g',  c=[1 0 0 1];
  case '2ph',    c=[1 1 0 0];
  case '2ph_g',  c=[1 1 0 1];
  otherwise,     c=[1 1 1 1];
end
set_param([M '/GridFault'],'FaultA',onoff(c(1)),'FaultB',onoff(c(2)),'FaultC',onoff(c(3)), ...
    'GroundFault',onoff(c(4)),'FaultResistance',num2str(Rf),'SwitchTimes',['[' num2str(t1) ' ' num2str(t2) ']']);
end
function set_swell_local(M,mult,is1,t1,t2,scr,Vnom)
% programmable source amplitude table -> swell (mirror of validate_mode_full.m set_swell)
% swell onset over ~1 cycle, decay over ~1 cycle (real swells don't snap off in 1ms — an abrupt step
% injects a non-physical post-clear Vdc transient that survive then flags)
set_param([M '/Grid'],'VariationEntity','Amplitude','VariationType','Table of time-amplitude pairs', ...
    'Amplitudes',sprintf('[1 1 %.4f %.4f 1]',mult,mult), ...
    'TimeValues',sprintf('[0 %.4f %.4f %.4f %.4f]',t1-0.005,t1,t2,t2+0.01), ...
    'VariationPhaseA',onoff(is1));
end
function s=onoff(b), if b, s='on'; else, s='off'; end, end
