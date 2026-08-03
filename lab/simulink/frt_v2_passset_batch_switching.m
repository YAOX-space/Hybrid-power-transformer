function frt_v2_passset_batch_switching(scenario_set, mi, i0, i1, tag)
% frt_v2_passset_batch_switching
% Resumable switching-level frt-v2 pass-set runner for controller comparison.
%
% scenario_set:
%   'full320'      -> lab/frt_scenarios.csv + p3_scenario_faultparams.json
%   'expanded2040' -> lab/frt_scenarios_expanded.csv + calib_*_scr*.mat
%
% Example:
%   frt_v2_passset_batch_switching('full320', 12, 1, 320, 'current_20260712')
%   frt_v2_passset_batch_switching('expanded2040', 7, 1, 2040, 'current_20260712')

here = fileparts(mfilename('fullpath')); cd(here); p = pu_params(); M = 'hpt_frt_full';
if nargin < 1 || isempty(scenario_set), scenario_set = 'full320'; end
if nargin < 2 || isempty(mi), mi = 12; end
if nargin < 3 || isempty(i0), i0 = 1; end
if nargin < 4 || isempty(i1)
    if strcmp(scenario_set, 'expanded2040'), i1 = 2040; else, i1 = 320; end
end
if nargin < 5 || isempty(tag), tag = datestr(now, 'yyyymmdd_HHMMSS'); end

wfile = weight_file_for_mode(mi);
W = load(fullfile('..', wfile)); run_id = char(W.run_id);
base = fullfile('..', 'results', sprintf('passset_%s_switching_%s_mi%d', scenario_set, tag, mi));
resfile = [base '.mat'];
if isfile(resfile)
    S = load(resfile); R = S.R;
else
    R = struct('sid', {}, 'frt', {}, 'crit', {}, 'prov', {});
end
done = arrayfun(@(x) x.sid, R);

if strcmp(scenario_set, 'expanded2040')
    A = readtable('../frt_scenarios_expanded.csv', 'TextType', 'string');
    sid_list = i0:i1;
else
    A = readtable('../frt_scenarios.csv', 'TextType', 'string');
    fp = jsondecode(fileread('../results/p3_scenario_faultparams.json'));
    sid_list = i0:i1;
end

cfg = containers.Map({'sym3ph','1ph_g','2ph','2ph_g'}, ...
                     {[1 1 1 1],[1 0 0 1],[1 1 0 0],[1 1 0 1]});
curbuild = '';
emf_cache = containers.Map('KeyType', 'char', 'ValueType', 'double');
metrics_version = 'frt-v2'; %#ok<NASGU>
note = sprintf('resumable switching pass-set; scenario_set=%s; mi=%d; frt-v2', scenario_set, mi);

for n = 1:numel(sid_list)
    sid = sid_list(n);
    if any(done == sid), continue; end
    ix = find(A.scenario_id == sid, 1);
    if isempty(ix), warning('scenario id %d not found', sid); continue; end

    if strcmp(scenario_set, 'expanded2040')
        ft = char(A.fault_type(ix)); cat = char(A.category(ix)); scr = double(A.scr(ix));
        Rg = double(A.Rg_ohm(ix)); Lg = double(A.Lg_H(ix));
        target = double(A.target_V_pu(ix));
        [fault_param, param_source, calib_scr] = calibrated_param(cat, ft, target, scr);
        vg_p = target;
    else
        m = getfield(fp, sprintf('x%d', sid)); %#ok<GFLD>
        ft = char(m.fault_type); cat = char(m.category); scr = double(m.scr);
        Rg = double(A.Rg_ohm(ix)); Lg = double(A.Lg_H(ix));
        target = double(m.target_V_pu);
        fault_param = double(m.fault_param);
        param_source = 'p3_scenario_faultparams';
        calib_scr = scr;
        vg_p = double(m.Vg_p);
    end

    isH = strcmp(cat, 'HVRT');
    tf = 0.08; dur = min(double(A.fault_dur(ix)), 0.5);
    post_window = max(0.35, double(A.T_sim(ix)) - (double(A.t_fault(ix)) + dur));

    if ~isfinite(fault_param) || fault_param <= 0
        rec = struct();
        rec.sid = sid; rec.frt = 'ERROR'; rec.crit = empty_crit(sprintf('invalid fault_param %.12g', fault_param));
        rec.prov = struct('mi', mi, 'scenario_set', scenario_set, 'fault_type', ft, ...
            'category', cat, 'scr', scr, 'Rg_ohm', Rg, 'Lg_H', Lg, ...
            'Vg_p', vg_p, 'target_V_pu', target, 'fault_param', fault_param, ...
            'fault_param_source', param_source, 'calibration_scr', calib_scr, ...
            'grid_emf_V', nan, 'grid_emf_source', 'not_run_invalid_fault_param', ...
            'run_id', run_id, 'metrics_version', 'frt-v2');
        fprintf('%s mi%d sid%4d %-9s scr%-4g target=%.2f | ERROR: invalid fault_param %.12g\n', ...
            scenario_set, mi, sid, ft, scr, target, fault_param);
        R(end+1) = rec; %#ok<AGROW>
        done(end+1) = sid; %#ok<AGROW>
        save(resfile, 'R', 'metrics_version', 'note');
        write_json_csv(base, R, scenario_set, mi, tag, note);
        continue;
    end

    bkey = sprintf('%s_%d_%.12g_%.12g', scenario_set, isH, Rg, Lg);
    if ~strcmp(bkey, curbuild)
        if isH, build_hpt_frt_full(4, 'swell'); else, build_hpt_frt_full(4); end
        set_param(M, 'SimulationMode', 'normal');
        curbuild = bkey;
    end

    grid_emf_V = nan; grid_emf_source = 'n/a';
    if isH
        set_param([M '/Zg'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
    else
        set_param([M '/Grid'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
        if strcmp(scenario_set, 'expanded2040')
            grid_emf_V = calibrated_emf(M, p.VLN_peak, scr, Rg, Lg, emf_cache);
            set_param([M '/Grid'], 'Voltage', num2str(grid_emf_V));
            grid_emf_source = 'per_scr_no_fault_calibration';
        else
            grid_emf_source = 'build_default_full320_legacy';
        end
    end

    rec = struct();
    rec.sid = sid; rec.frt = 'ERROR'; rec.crit = empty_crit('not run');
    rec.prov = struct('mi', mi, 'scenario_set', scenario_set, 'fault_type', ft, ...
        'category', cat, 'scr', scr, 'Rg_ohm', Rg, 'Lg_H', Lg, ...
        'Vg_p', vg_p, 'target_V_pu', target, 'fault_param', fault_param, ...
        'fault_param_source', param_source, 'calibration_scr', calib_scr, ...
        'grid_emf_V', grid_emf_V, 'grid_emf_source', grid_emf_source, ...
        'run_id', run_id, 'metrics_version', 'frt-v2');
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
        rec.frt = res.frt_pass_str; rec.crit = res;
        fprintf('%s mi%d sid%4d %-9s scr%-4g target=%.2f | con=%s rea=%s lim=%s rec=%s sur=%s | frt=%s\n', ...
            scenario_set, mi, sid, ft, scr, target, ...
            res.connect.status(1:min(4,end)), res.reactive.status(1:min(4,end)), ...
            res.limit.status(1:min(4,end)), res.recover.status(1:min(4,end)), ...
            res.survive.status(1:min(4,end)), res.frt_pass_str);
    catch ME
        rec.frt = 'ERROR'; rec.crit = empty_crit(ME.message);
        fprintf('%s mi%d sid%4d %-9s scr%-4g target=%.2f | ERROR: %s\n', ...
            scenario_set, mi, sid, ft, scr, target, ME.message);
    end

    R(end+1) = rec; %#ok<AGROW>
    done(end+1) = sid; %#ok<AGROW>
    save(resfile, 'R', 'metrics_version', 'note');
    write_json_csv(base, R, scenario_set, mi, tag, note);
end
write_json_csv(base, R, scenario_set, mi, tag, note);
fprintf('wrote %s.{mat,json,csv} (%d records)\n', base, numel(R));
end

function wfile = weight_file_for_mode(mi)
wfile = 'sac_actor_weights.mat';
if mi == 12 || mi == 15
    wfile = 'sac_sym_weights.mat';
elseif mi == 14 || mi == 16 || mi == 18 || mi == 19 || ...
        (mi >= 20 && mi <= 208) || (mi >= 209 && mi <= 321) || (mi >= 322 && mi <= 372)
    wfile = 'sac_residual_weights.mat';
elseif mi == 17
    wfile = 'sac_resexpert_weights.mat';
end
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
if isempty(k), error('no calibration curve for %s %s scr%g', cat, ft, calib_scr); end
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

function write_json_csv(base, R, scenario_set, mi, tag, note)
J = struct('metrics_version', 'frt-v2', 'layer', 'Simulink switching', ...
    'scenario_set', scenario_set, 'mode', mi, 'tag', tag, 'note', note, ...
    'n_scenarios', numel(R), 'scenarios', summary_rows(R));
fid = fopen([base '.json'], 'w'); fwrite(fid, jsonencode(J)); fclose(fid);
hdr = {'sid','category','fault_type','scr','target_V_pu','Vg_p','fault_param','fault_param_source', ...
       'frt','connect','reactive','limit','recover','survive', ...
       'Vdc_min','Vdc_max','V1_final_mean','V1_final_worst_signed'};
fid = fopen([base '.csv'], 'w'); fprintf(fid, '%s\n', strjoin(hdr, ','));
for i = 1:numel(R)
    r = R(i); c = r.crit; pr = r.prov; sm = get_summary(c);
    fprintf(fid, '%d,%s,%s,%g,%.6g,%.6g,%.8g,%s,%s,%s,%s,%s,%s,%s,%.8g,%.8g,%.8g,%.8g\n', ...
        r.sid, pr.category, pr.fault_type, pr.scr, pr.target_V_pu, pr.Vg_p, ...
        pr.fault_param, pr.fault_param_source, r.frt, c.connect.status, ...
        c.reactive.status, c.limit.status, c.recover.status, c.survive.status, ...
        sm.Vdc_min, sm.Vdc_max, sm.V1_final_mean, sm.V1_final_worst_signed);
end
fclose(fid);
end

function rows = summary_rows(R)
rows = struct([]);
for i = 1:numel(R)
    r = R(i); c = r.crit; pr = r.prov; sm = get_summary(c);
    rows(i).sid = r.sid; %#ok<AGROW>
    rows(i).category = pr.category;
    rows(i).fault_type = pr.fault_type;
    rows(i).scr = pr.scr;
    rows(i).target_V_pu = pr.target_V_pu;
    rows(i).Vg_p = pr.Vg_p;
    rows(i).frt = r.frt;
    rows(i).connect = c.connect.status;
    rows(i).reactive = c.reactive.status;
    rows(i).limit = c.limit.status;
    rows(i).recover = c.recover.status;
    rows(i).survive = c.survive.status;
    rows(i).Vdc_min = sm.Vdc_min;
    rows(i).Vdc_max = sm.Vdc_max;
    rows(i).V1_final_mean = sm.V1_final_mean;
    rows(i).V1_final_worst_signed = sm.V1_final_worst_signed;
end
end

function sm = get_summary(c)
if isfield(c, 'switching_summary')
    sm = c.switching_summary;
else
    sm = struct('Vdc_min', nan, 'Vdc_max', nan, 'V1_final_mean', nan, ...
        'V1_final_worst_signed', nan);
end
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
