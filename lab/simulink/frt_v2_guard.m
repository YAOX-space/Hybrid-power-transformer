function outroot = frt_v2_guard(scriptname)
% frt_v2_guard — FAIL-FAST for result-producing scripts that still run LEGACY frt-v1 criteria
% (linspace time reconstruction, connect = tV-0.07, iq-only limit, old recovery). The full MATLAB
% frt-v2 criteria rewrite is PENDING (P1, see docs/CHANGE_REPORT_2026-06-22.md). These scripts must
% NEVER silently emit files that look like active frt-v2 results.
%
% Default: throws HPT:PENDING_FRT_V2 (the script cannot run).
% To run for LEGACY diagnostics: set environment HPT_ALLOW_LEGACY_FRT=1. Output is then FORCED into
% ../results/legacy_pre_audit and every result must be tagged metrics_version='frt-v1-INVALIDATED'.
if isempty(getenv('HPT_ALLOW_LEGACY_FRT'))
  error('HPT:PENDING_FRT_V2', ...
    ['%s runs LEGACY frt-v1 criteria (PENDING_FRT_V2). The MATLAB frt-v2 criteria rewrite is P1. ' ...
     'Refusing to produce result files that could be mistaken for frt-v2. Set HPT_ALLOW_LEGACY_FRT=1 ' ...
     'to run for legacy diagnostics (output is forced into ../results/legacy_pre_audit).'], scriptname);
end
outroot = '../results/legacy_pre_audit';
if ~exist(outroot, 'dir'); mkdir(outroot); end
warning('HPT:LEGACY_FRT', ...
        '%s: LEGACY frt-v1 run (HPT_ALLOW_LEGACY_FRT set). Output -> %s. NOT frt-v2 certified.', ...
        scriptname, outroot);
end
