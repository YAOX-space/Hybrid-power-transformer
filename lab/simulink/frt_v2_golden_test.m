function frt_v2_golden_test()
% frt_v2_golden_test — run frt_v2_evaluate.m on the Python-generated golden vectors and assert the
% per-criterion status, frt_pass and worst values MATCH common/frt_v2.py (audit round-5 E.12).
here = fileparts(mfilename('fullpath'));
gm = fullfile(here, '..', '..', 'tests', 'golden', 'frt_v2_golden.mat');
if ~isfile(gm), error('golden vectors missing — run: python -m tests.golden.gen_golden_vectors'); end
S = load(gm); cases = S.cases;
n = numel(cases); ok = true; nfail = 0;
fprintf('frt_v2_golden_test: %d cases\n', n);
for i = 1:n
    c = cases{i};
    opts = struct();
    if ~isempty(c.Vdc),    opts.Vdc=double(c.Vdc(:)); end
    if ~isempty(c.iq),     opts.iq=double(c.iq(:)); end
    if ~isempty(c.i_peak), opts.i_peak=double(c.i_peak(:)); end
    if ~isempty(c.i2),     opts.i2=double(c.i2(:)); end
    r = frt_v2_evaluate(double(c.t(:)), double(c.V1(:)), char(c.category), double(c.residual), ...
                        double(c.t_fault), double(c.dur), opts);
    chk = strcmp(r.connect.status, char(c.exp_connect)) && ...
          strcmp(r.reactive.status, char(c.exp_reactive)) && ...
          strcmp(r.limit.status, char(c.exp_limit)) && ...
          strcmp(r.recover.status, char(c.exp_recover)) && ...
          strcmp(r.survive.status, char(c.exp_survive)) && ...
          strcmp(r.frt_pass_str, char(c.exp_frt_pass));
    % worst-value parity (where finite) within 1e-6
    wchk = near(r.connect.worst, c.exp_connect_worst) && ...
           near(r.limit.worst, c.exp_limit_worst) && ...
           near(r.survive.worst, c.exp_survive_worst);
    if ~(chk && wchk)
        ok = false; nfail = nfail + 1;
        fprintf('  MISMATCH [%s]: got con=%s rea=%s lim=%s rec=%s sur=%s frt=%s | exp %s/%s/%s/%s/%s/%s | wchk=%d\n', ...
            char(c.name), r.connect.status, r.reactive.status, r.limit.status, r.recover.status, ...
            r.survive.status, r.frt_pass_str, char(c.exp_connect), char(c.exp_reactive), ...
            char(c.exp_limit), char(c.exp_recover), char(c.exp_survive), char(c.exp_frt_pass), wchk);
    else
        fprintf('  ok [%-20s] con=%s rea=%s lim=%s rec=%s sur=%s frt=%s\n', char(c.name), ...
            r.connect.status, r.reactive.status, r.limit.status, r.recover.status, r.survive.status, r.frt_pass_str);
    end
end
if ok, fprintf('frt_v2_golden_test: ALL %d MATCH Python frt_v2.evaluate\n', n);
else, error('frt_v2_golden_test FAILED: %d/%d mismatches', nfail, n); end
end
function tf = near(a,b)
if (isnan(a)||a==0) && (isnan(b)) , tf=true; return; end   % both unevaluated/zero-vs-NaN tolerated
if isnan(a)&&isnan(b), tf=true; return; end
tf = abs(a-b) <= 1e-6 + 1e-6*abs(b);
end
