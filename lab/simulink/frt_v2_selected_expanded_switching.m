function frt_v2_selected_expanded_switching(sids, mi, tag)
% frt_v2_selected_expanded_switching
% Runs selected expanded-2040 scenarios through the switching Simulink model.
% This is a spotcheck artifact only: SCR values without direct calibration use the nearest calibrated
% SCR curve and are recorded as such. It never writes p3_full320_sw_mi*.mat.
here = fileparts(mfilename('fullpath')); cd(here); p = pu_params(); M = 'hpt_frt_full';
if nargin < 1 || isempty(sids)
    sids = unique([217:240 1441 1456 1481 1500 1873 1875 1884], 'stable');
end
if nargin < 2 || isempty(mi), mi = 14; end
if nargin < 3 || isempty(tag), tag = datestr(now, 'yyyymmdd_HHMMSS'); end

wfile = 'sac_actor_weights.mat';
if mi == 12
    wfile = 'sac_sym_weights.mat';
elseif mi == 14 || mi == 16 || mi == 18 || mi == 19 || (mi >= 322 && mi <= 372) || (mi >= 209 && mi <= 321) || (mi >= 20 && mi <= 208)
    wfile = 'sac_residual_weights.mat';
elseif mi == 17
    wfile = 'sac_resexpert_weights.mat';
end
W = load(fullfile('..', wfile)); run_id = char(W.run_id);
A = readtable('../frt_scenarios_expanded.csv', 'TextType', 'string');
cfg = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'}, ...
                     {[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});

R = struct('sid',{},'frt',{},'crit',{},'prov',{},'trace',{});
curbuild = '';
emf_cache = containers.Map('KeyType', 'char', 'ValueType', 'double');
for n = 1:numel(sids)
    sid = sids(n);
    ix = find(A.scenario_id == sid, 1);
    if isempty(ix)
        warning('scenario id %d not found in frt_scenarios_expanded.csv', sid);
        continue;
    end
    ft = char(A.fault_type(ix)); cat = char(A.category(ix)); isH = strcmp(cat, 'HVRT');
    scr = double(A.scr(ix)); Rg = double(A.Rg_ohm(ix)); Lg = double(A.Lg_H(ix));
    tf = 0.08; dur = min(double(A.fault_dur(ix)), 0.5);
    post_window = max(0.35, double(A.T_sim(ix)) - (double(A.t_fault(ix)) + dur));
    target = double(A.target_V_pu(ix));
    bkey = sprintf('%d_%g_%g', isH, Rg, Lg);
    if ~strcmp(bkey, curbuild)
        if isH, build_hpt_frt_full(4, 'swell'); else, build_hpt_frt_full(4); end
        set_param(M, 'SimulationMode', 'normal');
        curbuild = bkey;
    end
    grid_emf_V = nan;
    grid_emf_source = 'n/a';
    if isH
        set_param([M '/Zg'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
    else
        set_param([M '/Grid'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
        grid_emf_V = calibrated_emf(M, p.VLN_peak, scr, Rg, Lg, emf_cache);
        set_param([M '/Grid'], 'Voltage', num2str(grid_emf_V));
        grid_emf_source = 'per_scr_no_fault_calibration';
    end
    [fault_param, param_source, calib_scr] = calibrated_param(cat, ft, target, scr);
    rec = struct();
    rec.sid = sid; rec.frt = 'ERROR'; rec.crit = empty_crit('not run');
    rec.trace = struct();
    rec.prov = struct('mi', mi, 'fault_type', ft, 'category', cat, 'scr', scr, ...
        'Rg_ohm', Rg, 'Lg_H', Lg, 'target_V_pu', target, 'fault_param', fault_param, ...
        'fault_param_source', param_source, 'calibration_scr', calib_scr, ...
        'grid_emf_V', grid_emf_V, 'grid_emf_source', grid_emf_source, ...
        'run_id', run_id, 'metrics_version', 'frt-v2', ...
        'scenario_file', 'frt_scenarios_expanded.csv');
    try
        set_param([M '/mode'], 'Value', num2str(mi));
        set_param([M '/fclass'], 'Value', num2str(fclass_code(cat, ft)));
        set_param([M '/fdur'], 'Value', num2str(dur));
        set_param([M '/t_fault'], 'Value', num2str(tf));
        set_param([M '/iq_ref'], 'Value', '0');
        set_param([M '/mse_d'], 'Value', '0');
        set_param([M '/mse_q'], 'Value', '0');
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
        o = sim(M);
        res = eval_case(o, tf, dur, cat, p);
        rec.trace = trace_case(o, p);
        rec.frt = res.frt_pass_str; rec.crit = res;
        fprintf('mi%d sid%4d %-9s scr%-4g target=%.2f param=%.4g %-18s | con=%s rea=%s lim=%s rec=%s sur=%s | frt=%s\n', ...
            mi, sid, ft, scr, target, fault_param, param_source, ...
            res.connect.status(1:min(4,end)), res.reactive.status(1:min(4,end)), ...
            res.limit.status(1:min(4,end)), res.recover.status(1:min(4,end)), ...
            res.survive.status(1:min(4,end)), res.frt_pass_str);
    catch ME
        rec.frt = 'ERROR'; rec.crit = empty_crit(ME.message);
        fprintf('mi%d sid%4d %-9s scr%-4g target=%.2f | ERROR: %s\n', mi, sid, ft, scr, target, ME.message);
    end
    R(end+1) = rec; %#ok<AGROW>
end

metrics_version = 'frt-v2'; %#ok<NASGU>
note = ['selected expanded switching spotcheck; not full-320 certification; ' ...
        'LVRT grid EMF calibrated per SCR/no-fault baseline; ' ...
        'non-SCR3/10 cases use nearest switching calibration curve unless exact files exist'];
base = fullfile('..', 'results', sprintf('selected_expanded_switching_%s_mi%d', tag, mi));
save([base '.mat'], 'R', 'metrics_version', 'note');
write_json_csv(base, R, mi, tag, note);
fprintf('wrote %s.{mat,json,csv} (%d scenarios)\n', base, numel(R));
end

function tr = trace_case(o, p)
cmd = o.get('HLC_cmd');
ct = cmd.Time(:);
cd = squeeze(cmd.Data);
if size(cd, 1) == 3 && size(cd, 2) ~= 3
    cd = cd.';
end
obs = o.get('HLC_obs');
ot = obs.Time(:);
od = squeeze(obs.Data);
if size(od, 1) == 20 && size(od, 2) ~= 20
    od = od.';
end
tr = struct();
tr.t_cmd = ct;
tr.actor_action = [cd(:,1) / p.I_action_peak, -cd(:,2), -cd(:,3)];
tr.t_obs = ot;
tr.obs = od;
end

function [param, source, calib_scr] = calibrated_param(cat, ft, target, scr)
exact = fullfile('..', 'results', sprintf('calib_%s_scr%g.mat', cat, scr));
if isfile(exact)
    calib_scr = scr;
    calfile = exact;
else
    candidates = dir(fullfile('..', 'results', sprintf('calib_%s_scr*.mat', cat)));
    if isempty(candidates), error('no calibration files for %s', cat); end
    scrs = nan(size(candidates));
    for i = 1:numel(candidates)
        tok = regexp(candidates(i).name, sprintf('calib_%s_scr([0-9.]+)\\.mat', cat), 'tokens', 'once');
        if ~isempty(tok), scrs(i) = str2double(tok{1}); end
    end
    [~, ix] = min(abs(scrs - scr));
    calib_scr = scrs(ix);
    calfile = fullfile(candidates(ix).folder, candidates(ix).name);
end
S = load(calfile);
curves = S.curves;
k = find(strcmp({curves.ft}, ft), 1);
if isempty(k), error('no calibration curve for %s %s scr%d', cat, ft, calib_scr); end
vp = curves(k).Vplus(:); pp = curves(k).param(:);
[vp, ord] = sort(vp); pp = pp(ord);
[vp, keep] = unique(vp, 'stable'); pp = pp(keep);
param = interp1(vp, pp, target, 'linear', 'extrap');
if abs(scr - calib_scr) < 1e-9
    source = sprintf('calib_scr%g', calib_scr);
else
    source = sprintf('nearest_calib_scr%g', calib_scr);
end
end

function emfV = calibrated_emf(M, Vnom, scr, Rg, Lg, cache)
key = sprintf('scr%g_R%.12g_L%.12g', scr, Rg, Lg);
if isKey(cache, key)
    emfV = cache(key);
    return;
end
set_param([M '/mode'], 'Value', '4');
set_param([M '/iq_ref'], 'Value', '0');
set_param([M '/mse_d'], 'Value', '0');
set_param([M '/mse_q'], 'Value', '0');
set_param([M '/GridFault'], 'FaultA', 'off', 'FaultB', 'off', 'FaultC', 'off', ...
    'GroundFault', 'off', 'SwitchTimes', '[99 100]');
set_param(M, 'StopTime', '0.35');
V0 = 10e3 * 1.125;
set_param([M '/Grid'], 'Voltage', num2str(V0));
o = sim(M);
t = o.get('tout');
Vlv = o.get('Vlv_abc');
if isempty(t)
    t = linspace(0, 0.35, size(Vlv, 1))';
end
idx = t > 0.25;
measured = max(max(abs(Vlv(idx, :)))) / Vnom;
emfV = V0 / max(0.5, measured);
cache(key) = emfV;
fprintf('  LVRT EMF calib scr%g R=%.4g L=%.4g: Vsrc %.3f -> %.3f V (LV=%.4f pu)\n', ...
    scr, Rg, Lg, V0, emfV, measured);
end

function write_json_csv(base, R, mi, tag, note)
J = struct('metrics_version', 'frt-v2', 'layer', 'Simulink switching', 'mode', mi, ...
    'tag', tag, 'note', note, 'n_scenarios', numel(R), 'scenarios', R);
fid = fopen([base '.json'], 'w'); fwrite(fid, jsonencode(J)); fclose(fid);
hdr = {'sid','category','fault_type','scr','target_V_pu','fault_param','fault_param_source', ...
       'frt','connect','reactive','limit','recover','survive', ...
       'Vdc_min','Vdc_max','V1_final_mean','V1_final_worst_signed', ...
       'actor_iq_fault_mean','actor_iq_fault_min','actor_iq_fault_max', ...
       'actor_md_fault_mean','actor_md_fault_min','actor_md_fault_max', ...
       'actor_mq_fault_mean','actor_mq_fault_min','actor_mq_fault_max'};
fid = fopen([base '.csv'], 'w'); fprintf(fid, '%s\n', strjoin(hdr, ','));
for i = 1:numel(R)
    r = R(i); c = r.crit; p = r.prov;
    sm = get_summary(c);
    fprintf(fid, '%d,%s,%s,%g,%.4f,%.8g,%s,%s,%s,%s,%s,%s,%s,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g\n', ...
        r.sid, p.category, p.fault_type, p.scr, p.target_V_pu, p.fault_param, ...
        p.fault_param_source, r.frt, c.connect.status, c.reactive.status, c.limit.status, ...
        c.recover.status, c.survive.status, sm.Vdc_min, sm.Vdc_max, ...
        sm.V1_final_mean, sm.V1_final_worst_signed, ...
        sm.actor_iq_fault_mean, sm.actor_iq_fault_min, sm.actor_iq_fault_max, ...
        sm.actor_md_fault_mean, sm.actor_md_fault_min, sm.actor_md_fault_max, ...
        sm.actor_mq_fault_mean, sm.actor_mq_fault_min, sm.actor_mq_fault_max);
end
fclose(fid);
end

function sm = get_summary(c)
if isfield(c, 'switching_summary')
    sm = c.switching_summary;
else
    sm = struct('Vdc_min', nan, 'Vdc_max', nan, 'V1_final_mean', nan, ...
        'V1_final_worst_signed', nan, ...
        'actor_iq_fault_mean', nan, 'actor_iq_fault_min', nan, 'actor_iq_fault_max', nan, ...
        'actor_md_fault_mean', nan, 'actor_md_fault_min', nan, 'actor_md_fault_max', nan, ...
        'actor_mq_fault_mean', nan, 'actor_mq_fault_min', nan, 'actor_mq_fault_max', nan);
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
fin = tout >= tout(end) - 0.12;
dev = V1(fin) - 1.0;
[~, ki] = max(abs(dev));
res.switching_summary = struct( ...
    'Vdc_min', min(Vdc(:))/800, 'Vdc_max', max(Vdc(:))/800, ...
    'V1_fault_min', min(V1(wf)), 'V1_fault_max', max(V1(wf)), ...
    'V1_final_mean', mean(V1(fin)), 'V1_final_min', min(V1(fin)), ...
    'V1_final_max', max(V1(fin)), 'V1_final_worst_signed', dev(ki), ...
    'iq_fault_median', median(iq(tout>=t_f+0.06 & tout<=t_f+dur)), ...
    'residual', residual);
cmd = o.get('HLC_cmd');
ct = cmd.Time(:);
cd = squeeze(cmd.Data);
if size(cd, 1) == 3 && size(cd, 2) ~= 3
    cd = cd.';
end
cf = ct >= t_f & ct <= t_f + dur;
actor_iq = cd(:,1) / p.I_action_peak;
actor_md = -cd(:,2);
actor_mq = -cd(:,3);
res.switching_summary.actor_iq_fault_mean = mean(actor_iq(cf));
res.switching_summary.actor_iq_fault_min = min(actor_iq(cf));
res.switching_summary.actor_iq_fault_max = max(actor_iq(cf));
res.switching_summary.actor_md_fault_mean = mean(actor_md(cf));
res.switching_summary.actor_md_fault_min = min(actor_md(cf));
res.switching_summary.actor_md_fault_max = max(actor_md(cf));
res.switching_summary.actor_mq_fault_mean = mean(actor_mq(cf));
res.switching_summary.actor_mq_fault_min = min(actor_mq(cf));
res.switching_summary.actor_mq_fault_max = max(actor_mq(cf));
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
