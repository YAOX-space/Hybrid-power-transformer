function frt_v2_1441_control_sweep(tag, cmdgrid)
% frt_v2_1441_control_sweep
% Open-loop feasibility sweep for expanded scenario 1441 using the switching model.
% Mode 10 commands fixed [iq_pu, mse_d, mse_q] through the same HLC ports used by
% the SAC/residual deployment path, then evaluates full frt-v2 criteria.
%
% cmdgrid rows use ODE/SAC convention [iq_pu, mse_d_total, mse_q_total].
% For mode 10 the HLC outputs mse_d=-sac_msed, so the block value is set to
% the positive total convention and the controller sign matches residual mode.
here = fileparts(mfilename('fullpath')); cd(here); p = pu_params(); M = 'hpt_frt_full';
if nargin < 1 || isempty(tag), tag = datestr(now, 'yyyymmdd_HHMMSS'); end
if nargin < 2 || isempty(cmdgrid)
    [IQ, MD, MQ] = ndgrid([-0.27 0.0 0.15 0.27], [-0.30 -0.15 0.0 0.15 0.30], [-0.30 0.0 0.30]);
    cmdgrid = [IQ(:), MD(:), MQ(:)];
end

A = readtable('../frt_scenarios_expanded.csv', 'TextType', 'string');
sid = 1441; ix = find(A.scenario_id == sid, 1);
if isempty(ix), error('scenario id 1441 not found'); end
ft = char(A.fault_type(ix)); cat = char(A.category(ix)); scr = double(A.scr(ix));
Rg = double(A.Rg_ohm(ix)); Lg = double(A.Lg_H(ix));
tf = 0.08; dur = min(double(A.fault_dur(ix)), 0.5); target = double(A.target_V_pu(ix));
[fault_param, param_source, calib_scr] = calibrated_param(cat, ft, target, scr);

build_hpt_frt_full(4, 'swell');
set_param(M, 'SimulationMode', 'normal');
set_param([M '/Zg'], 'Resistance', num2str(Rg), 'Inductance', num2str(Lg));
set_param([M '/mode'], 'Value', '10');
set_param([M '/fclass'], 'Value', '5');
set_param([M '/fdur'], 'Value', num2str(dur));
set_param([M '/t_fault'], 'Value', num2str(tf));
set_param(M, 'StopTime', num2str(tf + dur + 0.35));
set_param([M '/Grid'], 'VariationEntity', 'Amplitude', ...
    'VariationType', 'Table of time-amplitude pairs', ...
    'Amplitudes', sprintf('[1 1 %.4f %.4f 1]', fault_param, fault_param), ...
    'TimeValues', sprintf('[0 %.4f %.4f %.4f %.4f]', tf-1e-3, tf, tf+dur, tf+dur+1e-3), ...
    'VariationPhaseA', 'off');

R = struct('sid',{},'frt',{},'iq',{},'mse_d',{},'mse_q',{},'crit',{},'prov',{});
for i = 1:size(cmdgrid,1)
    iq = cmdgrid(i,1); md = cmdgrid(i,2); mq = cmdgrid(i,3);
    set_param([M '/iq_ref'], 'Value', num2str(iq * p.I_action_peak));
    set_param([M '/mse_d'], 'Value', num2str(md));
    set_param([M '/mse_q'], 'Value', num2str(mq));
    rec = struct('sid', sid, 'frt', 'ERROR', 'iq', iq, 'mse_d', md, 'mse_q', mq, ...
        'crit', empty_crit('not run'), ...
        'prov', struct('mode', 10, 'scenario_id', sid, 'category', cat, 'fault_type', ft, ...
        'scr', scr, 'Rg_ohm', Rg, 'Lg_H', Lg, 'target_V_pu', target, ...
        'fault_param', fault_param, 'fault_param_source', param_source, ...
        'calibration_scr', calib_scr, 'metrics_version', 'frt-v2'));
    try
        o = sim(M);
        res = eval_case(o, tf, dur, cat, p);
        rec.frt = res.frt_pass_str; rec.crit = res;
        fprintf('cmd%03d iq=%+.3f md=%+.3f mq=%+.3f | con=%s rea=%s lim=%s rec=%s(%6.4f) sur=%s | Vdc=%.4f final=%+.4f frt=%s\n', ...
            i, iq, md, mq, res.connect.status(1:min(4,end)), res.reactive.status(1:min(4,end)), ...
            res.limit.status(1:min(4,end)), res.recover.status(1:min(4,end)), res.recover.worst, ...
            res.survive.status(1:min(4,end)), res.switching_summary.Vdc_min, ...
            res.switching_summary.V1_final_worst_signed, res.frt_pass_str);
    catch ME
        rec.frt = 'ERROR'; rec.crit = empty_crit(ME.message);
        fprintf('cmd%03d iq=%+.3f md=%+.3f mq=%+.3f | ERROR: %s\n', i, iq, md, mq, ME.message);
    end
    R(end+1) = rec; %#ok<AGROW>
end

metrics_version = 'frt-v2'; %#ok<NASGU>
note = 'scenario 1441 mode-10 fixed-control feasibility sweep; switching frt-v2 evaluator';
base = fullfile('..', 'results', sprintf('control_sweep_1441_%s', tag));
save([base '.mat'], 'R', 'metrics_version', 'note', 'cmdgrid');
write_json_csv(base, R, tag, note);
fprintf('wrote %s.{mat,json,csv} (%d commands)\n', base, numel(R));
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
if abs(scr - calib_scr) < 1e-9
    source = sprintf('calib_scr%g', calib_scr);
else
    source = sprintf('nearest_calib_scr%g', calib_scr);
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
res.switching_summary = struct( ...
    'Vdc_min', min(Vdc(:))/800, 'Vdc_max', max(Vdc(:))/800, ...
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

function write_json_csv(base, R, tag, note)
J = struct('metrics_version', 'frt-v2', 'layer', 'Simulink switching', ...
    'mode', 10, 'tag', tag, 'note', note, 'n_commands', numel(R), 'commands', R);
fid = fopen([base '.json'], 'w'); fwrite(fid, jsonencode(J)); fclose(fid);
hdr = {'cmd','sid','iq','mse_d','mse_q','frt','connect','reactive','limit','recover','survive', ...
       'recover_worst','Vdc_min','Vdc_max','V1_final_mean','V1_final_worst_signed'};
fid = fopen([base '.csv'], 'w'); fprintf(fid, '%s\n', strjoin(hdr, ','));
for i = 1:numel(R)
    r = R(i); c = r.crit; sm = get_summary(c);
    fprintf(fid, '%d,%d,%.6g,%.6g,%.6g,%s,%s,%s,%s,%s,%s,%.8g,%.8g,%.8g,%.8g,%.8g\n', ...
        i, r.sid, r.iq, r.mse_d, r.mse_q, r.frt, c.connect.status, c.reactive.status, ...
        c.limit.status, c.recover.status, c.survive.status, c.recover.worst, ...
        sm.Vdc_min, sm.Vdc_max, sm.V1_final_mean, sm.V1_final_worst_signed);
end
fclose(fid);
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
