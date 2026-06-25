function res = frt_v2_evaluate(t, V1, category, residual, t_fault, dur, opts)
% frt_v2_evaluate — THE single authoritative MATLAB frt-v2 criteria evaluator (audit round-5 E).
% Mirrors src/hpt_frt/common/frt_v2.py EXACTLY (golden-vector tested). validate_mode_full.m and
% run_spotcheck.m MUST call this — they may NOT duplicate the criteria.
%
% Inputs:
%   t        : REAL recorded time vector (e.g. simulation tout) — NO linspace reconstruction.
%   V1       : positive-seq terminal voltage (pu), same length as t.
%   category : 'LVRT' or 'HVRT'.
%   residual : imposed residual (pu) for the LVRT hold floor.
%   t_fault, dur : fault onset and duration (s) — PLANT timing (allowed for the evaluator/harness).
%   opts     : struct, any field may be [] (missing -> NOT_EVALUATED):
%              .V2 .Vdc .iq .i_peak .idq_mag .i2  (all pu, same length as t), .solver_tol.
%
% Output res: struct with per-criterion res.<c>.{status,worst,t_worst,reason} for
%   c in {connect,reactive,limit,recover,survive}; res.frt_pass (1/0/NaN = True/False/None),
%   res.frt_pass_str, res.evaluation_complete (logical), res.metrics_version='frt-v2', res.response.
if nargin < 7, opts = struct(); end
PASS='PASS'; FAIL='FAIL'; NE='NOT_EVALUATED';
% ── constants (MUST match frt_v2.py) ──
LVRT_HOLD=0.625; LVRT_REACH=2.0; RECOVER_BAND=0.07; RECOVER_MIN_COVER=0.10;
REACTIVE_TOL=0.12; REACTIVE_DELAY=0.06; REACTIVE_DWELL=0.80; REACTIVE_SIGN_EPS=1e-3;
I2_MAX_PU=3.0; VDC_LO=0.75; VDC_HI=1.25; I_CONV_MAX_PU=0.35;
stol = getf(opts,'solver_tol',1e-3);

t=t(:); V1=V1(:);
% ── structural validation (raise on bad input, like the Python ValueError) ──
if numel(t)~=numel(V1) || numel(t)<2, error('frt_v2_evaluate:input','t/V1 length mismatch or <2'); end
if any(~isfinite(t)) || any(~isfinite(V1)), error('frt_v2_evaluate:input','non-finite t/V1'); end
if any(diff(t)<=0), error('frt_v2_evaluate:input','t not strictly increasing'); end
if dur<=0, error('frt_v2_evaluate:input','dur<=0'); end
in_fault = (t>=t_fault) & (t<=t_fault+dur);
if ~any(in_fault), error('frt_v2_evaluate:input','empty fault window'); end
post = t > t_fault + dur;

[V2,Vdc,iq,i_peak,idq_mag,i2] = deal(getf(opts,'V2',[]),getf(opts,'Vdc',[]),getf(opts,'iq',[]), ...
    getf(opts,'i_peak',[]),getf(opts,'idq_mag',[]),getf(opts,'i2',[]));

res = struct(); res.metrics_version='frt-v2';

% ── connect: V+ vs time-varying GB/T envelope over fault+recovery ──
env = zeros(size(t));
if strcmp(category,'LVRT')
    for k=1:numel(t), env(k)=lvrt_lower_env(t(k)-t_fault, residual, LVRT_HOLD, LVRT_REACH); end
    margin = V1 - env;
else
    for k=1:numel(t), env(k)=hvrt_upper_env(t(k)-t_fault); end
    margin = env - V1;
end
win = in_fault | post;
mw = margin; mw(~win)=inf; [mn,ki]=min(mw);
ok = mn >= -stol;
res.connect = crit(tern(ok,PASS,FAIL), mn, t(ki), tern(ok,'ok','V+ left GB/T envelope'));

% ── reactive: minimum-support (signed) with response delay + dwell + wrong-sign FAIL ──
if isempty(iq)
    res.reactive = crit(NE, nan, t_fault, 'iq not provided');
else
    res.reactive = reactive_criterion(t,V1,iq,category,in_fault,t_fault, ...
        REACTIVE_TOL,REACTIVE_DELAY,REACTIVE_DWELL,REACTIVE_SIGN_EPS, PASS,FAIL,NE);
end

% ── limit: max(peak phase current, sqrt(id^2+iq^2)) <= 0.35 (pu, peak base) ──
cur=[];
if ~isempty(i_peak), cur=i_peak(:); end
if ~isempty(idq_mag), if isempty(cur), cur=idq_mag(:); else, cur=max(cur,idq_mag(:)); end; end
if isempty(cur)
    res.limit = crit(NE, nan, t_fault, 'current (i_peak/idq_mag) not provided');
else
    [mx,ki]=max(cur); good = mx <= I_CONV_MAX_PU + stol;
    res.limit = crit(tern(good,PASS,FAIL), mx, t(ki), tern(good,'ok',sprintf('I>%.2f pu',I_CONV_MAX_PU)));
end

% ── recover: post-clear ramp envelope + final steady |V+-1|<=band; window>=cover else NE ──
if any(post), cover = t(end) - (t_fault+dur); else, cover = 0; end
if ~any(post) || cover < RECOVER_MIN_COVER
    res.recover = crit(NE, nan, t(end), sprintf('insufficient recovery window (%.3fs<%.2fs)',cover,RECOVER_MIN_COVER));
else
    tp=t(post); Vp=V1(post); envp=zeros(size(tp));
    if strcmp(category,'LVRT')
        for k=1:numel(tp), envp(k)=lvrt_lower_env(tp(k)-t_fault,residual,LVRT_HOLD,LVRT_REACH); end
        env_ok = all(Vp >= envp - stol);
    else
        for k=1:numel(tp), envp(k)=hvrt_upper_env(tp(k)-t_fault); end
        env_ok = all(Vp <= envp + stol);
    end
    fin = tp >= tp(end)-0.12; fdev = max(abs(Vp(fin)-1.0));
    good = env_ok && fdev <= RECOVER_BAND;
    if good, rn='ok'; elseif fdev>RECOVER_BAND, rn='|V+-1|>band'; else, rn='left recovery env'; end
    res.recover = crit(tern(good,PASS,FAIL), fdev, tp(end), rn);
end

% ── survive: Vdc in [0.75,1.25] FULL domain AND I2<=3pu (both mandatory) ──
if isempty(Vdc) || isempty(i2)
    res.survive = crit(NE, nan, t_fault, 'Vdc and/or i2 not provided');
else
    Vdc=Vdc(:); i2=i2(:);
    vmin=min(Vdc); vmax=max(Vdc); vdc_ok = (vmin>=VDC_LO) && (vmax<=VDC_HI);   % no solver_tol (mirror py)
    i2max=max(i2); i2_ok = i2max <= I2_MAX_PU;
    if ~vdc_ok
        lowv = VDC_LO - vmin; highv = vmax - VDC_HI;                          % report the boundary MARGIN
        if lowv >= highv, [~,ki]=min(Vdc); w=lowv; tw=t(ki); rn='Vdc<0.75';
        else, [~,ki]=max(Vdc); w=highv; tw=t(ki); rn='Vdc>1.25'; end
    elseif ~i2_ok
        [~,ki]=max(i2); w=i2max-I2_MAX_PU; tw=t(ki); rn='I2>3pu';
    else
        [~,ki]=min(Vdc); w=0.0; tw=t(ki); rn='ok';
    end
    res.survive = crit(tern(vdc_ok&&i2_ok,PASS,FAIL), w, tw, rn);
end

% ── frt_pass precedence: any FAIL -> False(0); else any NOT_EVALUATED -> None(NaN); else True(1) ──
mand = {res.connect,res.reactive,res.limit,res.recover,res.survive};
sts = cellfun(@(c) c.status, mand, 'uni', 0);
if any(strcmp(sts,FAIL)), res.frt_pass=0; res.frt_pass_str='False';
elseif any(strcmp(sts,NE)), res.frt_pass=nan; res.frt_pass_str='None';
else, res.frt_pass=1; res.frt_pass_str='True'; end
res.evaluation_complete = ~any(strcmp(sts,NE));

% ── 5 ms response — SEPARATE, never in frt_pass ──
if isempty(iq)
    res.response = struct('response_status',NE,'rise_time_ms',nan,'settling_time_ms',nan,'meets_5ms',nan,'reason','iq missing');
else
    target = iq_ref_droop(residual);
    if abs(target) < 0.02
        res.response = struct('response_status',NE,'rise_time_ms',nan,'settling_time_ms',nan,'meets_5ms',nan,'reason','no reactive event');
    else
        res.response = response_metrics(t, iq(:), t_fault, target);
    end
end
end

% ============================ helpers (mirror frt_v2.py) ============================
function v = lvrt_lower_env(tr, residual, HOLD, REACH)
if tr<0, v=0.9; elseif tr<=HOLD, v=residual;
elseif tr<=REACH, v=residual+(0.9-residual)*(tr-HOLD)/(REACH-HOLD); else, v=0.9; end
end
function v = hvrt_upper_env(tr)
if tr<0, v=1.1; elseif tr<=0.5, v=1.30; elseif tr<=1.0, v=1.20; else, v=1.10; end
end
function r = iq_ref_droop(V1)
if V1<0.9, r=min(0.30,1.5*(0.9-V1)); elseif V1>1.1, r=max(-0.30,-1.5*(V1-1.1)); else, r=0; end
end
function c = crit(status,worst,tw,reason), c=struct('status',status,'worst',worst,'t_worst',tw,'reason',reason); end
function s = tern(c,a,b), if c, s=a; else, s=b; end, end
function v = getf(s,f,d), if isfield(s,f) && ~isempty(s.(f)), v=s.(f); else, v=d; end, end

function c = reactive_criterion(t,V1,iq,category,in_fault,t_fault,tol,delay,dwell,signeps,PASS,FAIL,NE)
iq=iq(:); ref=arrayfun(@iq_ref_droop,V1);
f=in_fault;
assess = f & (t >= t_fault+delay);   % response-settling window (also used for min-support / dwell)
% SUSTAINED wrong sign within the ASSESSMENT window -> FAIL. Assess AFTER the response delay (not the
% raw onset): as iq slews from its pre-event ~0 state through zero it can sit on the wrong side of 0 for
% a single sample while V+ is just crossing 1.1 — that transient must not trip it (it failed every swell).
wrong = any(V1(assess)<0.9 & iq(assess)<-signeps) || any(V1(assess)>1.1 & iq(assess)>signeps);
if wrong, c=crit(FAIL,nan,t_fault,'wrong sign (sourcing under-volt / absorbing over-volt)'); return; end
demanded = assess & (abs(ref)>tol);
if ~any(demanded), c=crit(NE,nan,t_fault,'no sustained reactive demand after response delay'); return; end
iqd=iq(demanded); refd=ref(demanded); td=t(demanded);
if strcmp(category,'LVRT'), short=max(0,(refd-tol)-iqd); else, short=max(0,iqd-(refd+tol)); end
met = short<=1e-9; metfrac=mean(met);
[worst,j]=max(short); good = metfrac>=dwell;
if good, rn='ok'; else, rn=sprintf('min-support held %.0f%% (<%.0f%%); under %.3f',100*metfrac,100*dwell,worst); end
c=crit(tern(good,PASS,FAIL), worst, td(j), rn);
end

function r = response_metrics(t, s, t_event, target)
BAND=0.02; DWELL=0.002; RLO=0.10; RHI=0.90; MINS=3;
t=t(:); s=s(:); nan_=nan;
post = t>=t_event;
if sum(post) < MINS
    r=struct('response_status','NOT_EVALUATED','rise_time_ms',nan_,'settling_time_ms',nan_,'meets_5ms',nan,'reason','insufficient resolution'); return;
end
i0 = find(t>=t_event,1,'first'); if isempty(i0), i0=numel(t); end
pre = (t>=t_event-0.02) & (t<t_event);
if any(pre), baseline=mean(s(pre)); else, baseline=s(max(1,i0-1)); end
settled = target; step = settled-baseline; sgn = sign(step); if sgn==0, sgn=1; end
% rise time 10->90%
rise=nan_;
if abs(step) > max(1e-6,BAND)
    lo=baseline+RLO*step; hi=baseline+RHI*step; tlo=[]; thi=[];
    for k=i0:numel(s)
        if isempty(tlo) && sgn*(s(k)-lo)>=0, tlo=t(k); end
        if isempty(thi) && sgn*(s(k)-hi)>=0, thi=t(k); break; end
    end
    if ~isempty(tlo) && ~isempty(thi), rise=(thi-tlo)*1e3; end
end
% settling: last exit from band, require dwell to end
inband = abs(s-settled)<=BAND; settle=nan_; settled_ok=false;
af=find(post);
out=af(~inband(af));
if isempty(out), settle=(t(af(1))-t_event)*1e3; settled_ok=true;
else
    lo=max(out);
    if lo<numel(s)
        ts=t(lo+1);
        if (t(end)-ts)>=DWELL && all(inband(lo+1:end)), settle=(ts-t_event)*1e3; settled_ok=true; end
    end
end
st = tern(settled_ok,'settled','not_settled');
r=struct('response_status',st,'rise_time_ms',rise,'settling_time_ms',settle, ...
         'meets_5ms', settled_ok && settle<=5.0, 'reason','');
end
