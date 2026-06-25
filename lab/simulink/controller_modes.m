function out = controller_modes(query)
% controller_modes — single source of truth for HPT-FRT controller modes (MATLAB side).
% Mirrors CONTROL_MODES.md (repo root) and controller_registry.py. Canonical modes are 0-6.
%
% The Simulink HLC INTERNAL integer dispatch (mi==4/5/6/7/8/10/11/12/13/14) and result
% filenames frt320_m{N}_* are LEFT UNCHANGED on purpose: renumbering would force a full model
% rebuild + re-validation of every result. This function exposes the canonical 0-6 system and a
% legacy alias. Main method = Mode 5 (online-gated multi-expert SAC). Mode 6 (MPC-assisted
% residual SAC) is an EXTENSION, not the main method, and is NOT "pure SAC".
%
% Usage:
%   controller_modes()            % print the canonical table
%   controller_modes('main')      % canonical id of the main method (=5)
%   controller_modes(7)           % legacy internal int -> canonical id (+ deprecation warning)
%
% NO RESULT MAY BE COPIED FROM ONE MODE TO ANOTHER. validity='pending' == 待验证.

% canonical table: {id, name, zh, internal_HLC, results, status, validity, main}
T = {
 0,'Calibration / no-HLC',        '标定/无高层控制',      NaN, '(calib/sim_compare)','active-infra','n/a',          false
 1,'Tuned fixed-law controller',  '最强固定律控制',        7,  'frt320_m7_*',        'active',      'pending-frt-v2 (legacy frt-v1 64.1% INVALIDATED)',  false
 2,'One-step explicit MPC',       '一步显式 MPC',          8,  'frt320_m8_*',        'active',      'pending-frt-v2 (legacy frt-v1 79.7% INVALIDATED)',  false
 3,'Unified SAC',                 '单一 SAC',              11, 'frt320_m11_*',       'active',      'pending-frt-v2 (legacy frt-v1 44.4% INVALIDATED)',false
 4,'Oracle-gated expert SAC',     'Oracle 门控多专家 SAC', 15, 'frt320_m15_*',       'active',      'pending-frt-v2 (legacy frt-v1 81.2% INVALIDATED, ablation)',false
 5,'Online-gated expert SAC',     '在线门控多专家 SAC',    12, 'frt320_m12_*',       'active',      'pending-frt-v2 (legacy frt-v1 82.2% INVALIDATED; retrain PENDING)', true
 6,'MPC-assisted residual SAC',   'MPC 辅助残差 SAC',      14, 'frt320_m14_*',       'active',      'pending-frt-v2 (legacy frt-v1 96.3% INVALIDATED; extension, NOT main/pure-SAC)', false
};

% legacy internal HLC int -> canonical id (NaN = deprecated, no canonical id)
LEG = [7 1; 8 2; 11 3; 12 5; 14 6; 15 4; 4 NaN; 5 NaN; 6 NaN; 10 NaN; 13 NaN];
LEGNOTE = containers.Map({4,5,6,10,13}, { ...
  'dq-legacy (deprecated failure-demo; historical 27.5%)', ...
  'Song-style fixed law (deprecated historical)', ...
  'Jia-style fixed law (deprecated historical)', ...
  'fixed-setpoint probe (deprecated; calibration config, Mode 0 family)', ...
  'SAC/MPC domain-partition hybrid (deprecated; historical 88.4%)'});

if nargin==0
    fprintf('Canonical HPT-FRT controller modes (see CONTROL_MODES.md):\n');
    for i=1:size(T,1)
        star = ''; if T{i,8}; star=' *MAIN'; end
        fprintf('  Mode %d: %s / %s  [internal mi=%g, %s]%s\n', ...
            T{i,1}, T{i,2}, T{i,3}, T{i,4}, T{i,7}, star);
    end
    fprintf('\nMain method = Mode 5 (online-gated multi-expert SAC).\n');
    out = T; return
end

if ischar(query) || isstring(query)
    if strcmp(query,'main'), out = 5; return; end
    error('controller_modes: unknown query "%s"', query);
end

% numeric query = legacy internal int -> canonical
row = LEG(LEG(:,1)==query, 2);
if isempty(row), error('controller_modes: unknown internal mode %g', query); end
if isnan(row)
    note = ''; if isKey(LEGNOTE, query), note = LEGNOTE(query); end
    warning('controller_modes:deprecated', ...
        'internal mode %g is DEPRECATED: %s. No canonical 0-6 id; must not appear in papers/lectures.', query, note);
    out = NaN; return
end
warning('controller_modes:legacy', ...
    'legacy internal mode %g -> canonical Mode %d (%s). Use the canonical id.', query, row, T{row+1,2});
out = row;
end
