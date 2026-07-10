function frt_v2_selected_control_sweep(sids, tag, cmdgrid)
% frt_v2_selected_control_sweep
% Small mode-10 fixed-control feasibility sweep for selected expanded scenarios.
% This is diagnostic only: use it to find actions for pure-SAC training labels.
% cmdgrid columns:
%   3 cols: [iq md mq] fixed for the whole run.
%   6 cols: [iq_fault md_fault mq_fault iq_post md_post mq_post], switch at clearing.
%   7 cols: same as 6 plus post-delay seconds after clearing.
here = fileparts(mfilename('fullpath')); cd(here); p = pu_params(); M = 'hpt_frt_full';
if nargin < 1 || isempty(sids), sids = [225 237 1873 1884]; end
if nargin < 2 || isempty(tag), tag = datestr(now, 'yyyymmdd_HHMMSS'); end
if nargin < 3 || isempty(cmdgrid)
    [IQ, MD, MQ] = ndgrid([-0.27 -0.20 -0.12 0.00 0.12 0.20 0.27], ...
                          [-0.30 -0.20 -0.10 0.00 0.10 0.20 0.30], ...
                          [-0.30 -0.15 0.00 0.15 0.30]);
    cmdgrid = [IQ(:), MD(:), MQ(:)];
end
is_dynamic = size(cmdgrid, 2) >= 6;

A = readtable('../frt_scenarios_expanded.csv', 'TextType', 'string');
cfg = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'}, ...
                     {[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});
R = struct('sid',{},'frt',{},'iq',{},'mse_d',{},'mse_q',{}, ...
    'iq_post',{},'mse_d_post',{},'mse_q_post',{},'post_delay',{}, ...
    'crit',{},'prov',{});
curbuild = '';
emf_cache = containers.Map('KeyType', 'char', 'ValueType', 'double');
for n = 1:numel(sids)
    sid = sids(n);
    ix = find(A.scenario_id == sid, 1);
    if isempty(ix), warning('scenario id %d not found', sid); continue; end
    ft = char(A.fault_type(ix)); cat = char(A.category(ix)); isH = strcmp(cat, 'HVRT');
    scr = double(A.scr(ix)); Rg = double(A.Rg_ohm(ix)); Lg = double(A.Lg_H(ix));
    tf = 0.08; dur = min(double(A.fault_dur(ix)), 0.5);
    post_window = max(0.35, double(A.T_sim(ix)) - (double(A.t_fault(ix)) + dur));
    target = double(A.target_V_pu(ix));
    bkey = sprintf('%d_%g_%g', isH, Rg, Lg);
    if ~strcmp(curbuild, bkey)
        if isH, build_hpt_frt_full(4, 'swell'); else, build_hpt_frt_full(4); end
        set_param(M, 'SimulationMode', 'normal');
        if is_dynamic, install_dynamic_inputs(M); end
        curbuild = bkey;
    end
    if isH
        set_param([M '/Zg'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
    else
        set_param([M '/Grid'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
        set_param([M '/Grid'], 'Voltage', num2str(calibrated_emf(M, p.VLN_peak, scr, Rg, Lg, emf_cache)));
    end
    [fault_param, param_source, calib_scr] = calibrated_param(cat, ft, target, scr);
    set_param([M '/mode'], 'Value', '10');
    set_param([M '/fclass'], 'Value', num2str(fclass_code(cat, ft)));
    set_param([M '/fdur'], 'Value', num2str(dur));
    set_param([M '/t_fault'], 'Value', num2str(tf));
    set_param(M, 'StopTime', num2str(tf + dur + post_window));
    if isH
        is1 = strcmp(ft, 'swell_1ph');
        set_param([M '/Grid'], 'VariationEntity', 'Amplitude', ...
            'VariationType', 'Table of time-amplitude pairs', ...
            'Amplitudes', sprintf('[1 1 %.4f %.4f 1]', fault_param, fault_param), ...
            'TimeValues', sprintf('[0 %.4f %.4f %.4f %.4f]', tf-1e-3, tf, tf+dur, tf+dur+1e-3), ...
            'VariationPhaseA', oo(is1));
    else
        c = cfg(ft);
        set_param([M '/GridFault'], 'FaultA', oo(c(1)), 'FaultB', oo(c(2)), ...
            'FaultC', oo(c(3)), 'GroundFault', oo(c(4)), ...
            'FaultResistance', num2str(fault_param), 'GroundResistance', '0.001', ...
            'SwitchTimes', sprintf('[%.4f %.4f]', tf, tf+dur));
    end
    stop_t = tf + dur + post_window;
    for i = 1:size(cmdgrid,1)
        iq = cmdgrid(i,1); md = cmdgrid(i,2); mq = cmdgrid(i,3);
        if is_dynamic
            iqp = cmdgrid(i,4); mdp = cmdgrid(i,5); mqp = cmdgrid(i,6);
            pdelay = 0;
            if size(cmdgrid,2) >= 7, pdelay = cmdgrid(i,7); end
            set_twostage_inputs(p, tf, dur, stop_t, iq, md, mq, iqp, mdp, mqp, pdelay);
        else
            iqp = nan; mdp = nan; mqp = nan; pdelay = nan;
            set_param([M '/iq_ref'], 'Value', num2str(iq * p.I_action_peak));
            set_param([M '/mse_d'], 'Value', num2str(md));
            set_param([M '/mse_q'], 'Value', num2str(mq));
        end
        rec = struct('sid', sid, 'frt', 'ERROR', 'iq', iq, 'mse_d', md, 'mse_q', mq, ...
            'iq_post', iqp, 'mse_d_post', mdp, 'mse_q_post', mqp, 'post_delay', pdelay, ...
            'crit', empty_crit('not run'), ...
            'prov', struct('mode', 10, 'category', cat, 'fault_type', ft, 'scr', scr, ...
            'Rg_ohm', Rg, 'Lg_H', Lg, 'target_V_pu', target, 'fault_param', fault_param, ...
            'fault_param_source', param_source, 'calibration_scr', calib_scr));
        try
            o = sim(M);
            res = eval_case(o, tf, dur, cat, p);
            rec.frt = res.frt_pass_str; rec.crit = res;
            fprintf('sid%4d cmd%03d iq=%+.3f md=%+.3f mq=%+.3f -> iq=%+.3f md=%+.3f mq=%+.3f | con=%s rea=%s lim=%s rec=%s sur=%s Vdc=%.4f final=%+.4f frt=%s\n', ...
                sid, i, iq, md, mq, iqp, mdp, mqp, res.connect.status(1:min(4,end)), ...
                res.reactive.status(1:min(4,end)), res.limit.status(1:min(4,end)), ...
                res.recover.status(1:min(4,end)), res.survive.status(1:min(4,end)), ...
                res.switching_summary.Vdc_min, res.switching_summary.V1_final_worst_signed, res.frt_pass_str);
        catch ME
            rec.frt = 'ERROR'; rec.crit = empty_crit(ME.message);
            fprintf('sid%4d cmd%03d iq=%+.3f md=%+.3f mq=%+.3f | ERROR: %s\n', sid, i, iq, md, mq, ME.message);
        end
        R(end+1) = rec; %#ok<AGROW>
    end
end

metrics_version = 'frt-v2'; %#ok<NASGU>
note = 'selected mode-10 fixed-control feasibility sweep; diagnostic only';
base = fullfile('..', 'results', sprintf('control_sweep_selected_%s', tag));
save([base '.mat'], 'R', 'metrics_version', 'note', 'cmdgrid');
write_json_csv(base, R, tag, note);
fprintf('wrote %s.{mat,json,csv} (%d records)\n', base, numel(R));
end

function [param, source, calib_scr] = calibrated_param(cat, ft, target, scr)
exact = fullfile('..', 'results', sprintf('calib_%s_scr%g.mat', cat, scr));
if isfile(exact)
    calib_scr = scr; calfile = exact;
else
    candidates = dir(fullfile('..', 'results', sprintf('calib_%s_scr*.mat', cat)));
    if isempty(candidates), error('no calibration files for %s', cat); end
    scrs = nan(size(candidates));
    for i = 1:numel(candidates)
        tok = regexp(candidates(i).name, sprintf('calib_%s_scr([0-9.]+)\\.mat', cat), 'tokens', 'once');
        if ~isempty(tok), scrs(i) = str2double(tok{1}); end
    end
    [~, ix] = min(abs(scrs - scr));
    calib_scr = scrs(ix); calfile = fullfile(candidates(ix).folder, candidates(ix).name);
end
S = load(calfile); curves = S.curves;
k = find(strcmp({curves.ft}, ft), 1);
if isempty(k), error('no calibration curve for %s %s scr%d', cat, ft, calib_scr); end
vp = curves(k).Vplus(:); pp = curves(k).param(:);
[vp, ord] = sort(vp); pp = pp(ord);
[vp, keep] = unique(vp, 'stable'); pp = pp(keep);
param = interp1(vp, pp, target, 'linear', 'extrap');
if abs(scr - calib_scr) < 1e-9, source = sprintf('calib_scr%g', calib_scr);
else, source = sprintf('nearest_calib_scr%g', calib_scr); end
end

function emfV = calibrated_emf(M, Vnom, scr, Rg, Lg, cache)
key = sprintf('scr%g_R%.12g_L%.12g', scr, Rg, Lg);
if isKey(cache, key), emfV = cache(key); return; end
set_param([M '/mode'], 'Value', '4');
set_param([M '/iq_ref'], 'Value', '0');
set_param([M '/mse_d'], 'Value', '0');
set_param([M '/mse_q'], 'Value', '0');
set_param([M '/GridFault'], 'FaultA', 'off', 'FaultB', 'off', ...
    'FaultC', 'off', 'GroundFault', 'off', 'SwitchTimes', '[99 100]');
set_param(M, 'StopTime', '0.35');
V0 = 10e3 * 1.125;
set_param([M '/Grid'], 'Voltage', num2str(V0));
o = sim(M);
t = o.get('tout'); Vlv = o.get('Vlv_abc');
if isempty(t), t = linspace(0, 0.35, size(Vlv, 1))'; end
idx = t > 0.25;
measured = max(max(abs(Vlv(idx, :)))) / Vnom;
emfV = V0 / max(0.5, measured);
cache(key) = emfV;
fprintf('  LVRT EMF calib scr%g R=%.4g L=%.4g: Vsrc %.3f -> %.3f V (LV=%.4f pu)\n', ...
    scr, Rg, Lg, V0, emfV, measured);
end

function write_json_csv(base, R, tag, note)
J = struct('metrics_version', 'frt-v2', 'layer', 'Simulink switching', ...
    'mode', 10, 'tag', tag, 'note', note, 'n_records', numel(R), 'records', R);
fid = fopen([base '.json'], 'w'); fwrite(fid, jsonencode(J)); fclose(fid);
hdr = {'sid','category','fault_type','scr','target_V_pu','iq','mse_d','mse_q', ...
       'iq_post','mse_d_post','mse_q_post','post_delay','frt', ...
       'connect','reactive','limit','recover','survive','recover_worst', ...
       'Vdc_min','Vdc_max','V1_final_mean','V1_final_worst_signed'};
fid = fopen([base '.csv'], 'w'); fprintf(fid, '%s\n', strjoin(hdr, ','));
for i = 1:numel(R)
    r = R(i); c = r.crit; p = r.prov; sm = get_summary(c);
    fprintf(fid, '%d,%s,%s,%g,%.4f,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%s,%s,%s,%s,%s,%s,%.8g,%.8g,%.8g,%.8g,%.8g\n', ...
        r.sid, p.category, p.fault_type, p.scr, p.target_V_pu, r.iq, r.mse_d, r.mse_q, ...
        r.iq_post, r.mse_d_post, r.mse_q_post, r.post_delay, ...
        r.frt, c.connect.status, c.reactive.status, c.limit.status, c.recover.status, ...
        c.survive.status, c.recover.worst, sm.Vdc_min, sm.Vdc_max, ...
        sm.V1_final_mean, sm.V1_final_worst_signed);
end
fclose(fid);
end

function install_dynamic_inputs(M)
for nm = {'iq_ref','mse_d','mse_q'}
    name = nm{1};
    try, delete_line(M, [name '/1'], 'HLC/3'); catch, end
    try, delete_line(M, [name '/1'], 'HLC/4'); catch, end
    try, delete_line(M, [name '/1'], 'HLC/5'); catch, end
    try, delete_block([M '/' name]); catch, end
end
add_block('simulink/Sources/From Workspace',[M '/iq_ref'], 'Position',[340 680 410 704], ...
    'VariableName','iq_ref_ts');
add_block('simulink/Sources/From Workspace',[M '/mse_d'], 'Position',[60 900 130 924], ...
    'VariableName','mse_d_ts');
add_block('simulink/Sources/From Workspace',[M '/mse_q'], 'Position',[60 940 130 964], ...
    'VariableName','mse_q_ts');
add_line(M,'iq_ref/1','HLC/3','autorouting','on');
add_line(M,'mse_d/1','HLC/4','autorouting','on');
add_line(M,'mse_q/1','HLC/5','autorouting','on');
end

function set_twostage_inputs(p, tf, dur, stop_t, iqf, mdf, mqf, iqp, mdp, mqp, pdelay)
tsw = tf + dur + pdelay;
eps_t = 1e-5;
t = [0; max(0, tsw - eps_t); tsw; stop_t];
assignin('base', 'iq_ref_ts', timeseries([iqf; iqf; iqp; iqp] * p.I_action_peak, t));
assignin('base', 'mse_d_ts', timeseries([mdf; mdf; mdp; mdp], t));
assignin('base', 'mse_q_ts', timeseries([mqf; mqf; mqp; mqp], t));
end

function sm = get_summary(c)
if isfield(c, 'switching_summary')
    sm = c.switching_summary;
else
    sm = struct('Vdc_min', nan, 'Vdc_max', nan, 'V1_final_mean', nan, ...
        'V1_final_worst_signed', nan);
end
end

function res = eval_case(o, t_f, dur, cat, p)
tout0 = o.get('tout'); if isempty(tout0), tout0 = o.tout; end
Vlv0 = o.get('Vlv_abc'); Vdc0 = o.get('Vdc'); dq0 = squeeze(o.get('dq')).'; Ish0 = o.get('Ish_abc');
m = tout0 >= t_f - 0.02; tout = tout0(m); Vlv = Vlv0(m,:); Vdc = Vdc0(m); dq = dq0(m,:); Ish = Ish0(m,:);
dt = median(diff(tout)); nc = max(1, round(0.02/dt)); q = max(1, round(0.005/dt));
[V1,V2] = seqmag(Vlv, p.VLN_peak, q); [~,i2c] = seqmag(Ish, p.I_action_peak, q);
V1 = movmean(V1, nc); V2 = movmean(V2, nc); i2c = movmean(i2c, nc);
iq = movmean(dq(:,2) / p.I_dq_base_peak, nc); idq = hypot(dq(:,1) / p.I_dq_base_peak, iq);
Ipk = movmean(max(abs(Ish), [], 2) / p.I_dq_base_peak, nc);
wf = tout >= t_f + 0.005 & tout <= t_f + dur - 0.005; residual = min(V1(wf));
opts = struct('V2', V2, 'Vdc', Vdc(:)/800, 'iq', iq, 'i_peak', Ipk, 'idq_mag', idq, 'i2', i2c);
res = frt_v2_evaluate(tout(:), V1(:), cat, residual, t_f, dur, opts);
fin = tout >= tout(end) - 0.12; dev = V1(fin) - 1.0; [~, ki] = max(abs(dev));
res.switching_summary = struct('Vdc_min', min(Vdc(:))/800, 'Vdc_max', max(Vdc(:))/800, ...
    'V1_fault_min', min(V1(wf)), 'V1_fault_max', max(V1(wf)), ...
    'V1_final_mean', mean(V1(fin)), 'V1_final_min', min(V1(fin)), ...
    'V1_final_max', max(V1(fin)), 'V1_final_worst_signed', dev(ki), ...
    'iq_fault_median', median(iq(tout>=t_f+0.06 & tout<=t_f+dur)), ...
    'residual', residual);
end

function [V1,V2] = seqmag(Vabc, Vnom, q)
a = (2/3) * (Vabc(:,1) - 0.5*Vabc(:,2) - 0.5*Vabc(:,3));
b = (2/3) * (sqrt(3)/2) * (Vabc(:,2) - Vabc(:,3));
ad = [zeros(q,1); a(1:end-q)]; bd = [zeros(q,1); b(1:end-q)];
V1 = sqrt((0.5*(a-bd)).^2 + (0.5*(b+ad)).^2) / Vnom;
V2 = sqrt((0.5*(a+bd)).^2 + (0.5*(b-ad)).^2) / Vnom;
end

function res = empty_crit(reason)
c = struct('status', 'ERROR', 'worst', nan, 't_worst', nan, 'reason', reason);
res = struct('metrics_version', 'frt-v2', 'connect', c, 'reactive', c, 'limit', c, ...
    'recover', c, 'survive', c, 'frt_pass', nan, 'frt_pass_str', 'ERROR', ...
    'evaluation_complete', false);
end

function s = oo(b)
if b, s = 'on'; else, s = 'off'; end
end

function fc = fclass_code(cat, ft)
if strcmp(cat, 'HVRT')
    if strcmp(ft, 'swell_1ph'), fc = 6; else, fc = 5; end
elseif strcmp(ft, 'sym3ph')
    fc = 1;
else
    fc = 2;
end
end
