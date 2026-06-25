function assert_metrics_version(expected)
% assert_metrics_version(expected) — guard the single-source metrics_version before any result write.
% Errors if pu_params.m has drifted from the expected version. Store the returned version in every
% MAT/CSV result so a file can never be mistaken for a different criteria generation.
%
% Usage:  assert_metrics_version('frt-v1-INVALIDATED');   % legacy diagnostic runs
%         assert_metrics_version('frt-v2');                % once the MATLAB frt-v2 rewrite (P1) lands
p = pu_params();
if nargin >= 1 && ~isempty(expected) && ~strcmp(p.metrics_version, expected)
  error('HPT:MetricsVersionMismatch', ...
        'metrics_version mismatch: pu_params=%s expected=%s', p.metrics_version, expected);
end
end
