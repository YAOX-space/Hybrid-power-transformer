function p = pu_params()
% pu_params — SINGLE SOURCE OF TRUTH (MATLAB mirror of src/hpt_frt/common/pu.py).
% MUST stay numerically identical to pu.py (tests/test_pu.py checks the headline identities).
%
% Conventions (audit 2026-06-22): SYSTEM base S_base=400kVA, VLL=400Vrms. iq command is SYSTEM-pu;
% iq=0.3 == PE full == 120 kVAr == 173.2 A rms == 244.9 A PEAK line current.
% dq = AMPLITUDE-INVARIANT (2/3 Clarke) -> id,iq are PEAK amplitudes, P=1.5(vd id+vq iq).
% Therefore MEASURED peak dq currents must be normalised by a PEAK base (I_sys_peak / I_pe_peak),
% NOT I_pe_rms. The legacy criteria used /173.2 (=I_pe_rms) on peak dq -> ~sqrt(2) peak/RMS mix.

p.S_base_VA  = 400e3;
p.VLL_base   = 400.0;
p.VLN_rms    = p.VLL_base/sqrt(3);
p.VLN_peak   = sqrt(2)*p.VLN_rms;
p.f_nom      = 50.0;

p.I_sys_rms  = p.S_base_VA/(sqrt(3)*p.VLL_base);   % 577.35 A
p.I_sys_peak = sqrt(2)*p.I_sys_rms;                % 816.50 A

p.S_pe_VA    = 120e3;
p.S_pe_pu    = p.S_pe_VA/p.S_base_VA;              % 0.30
p.I_pe_rms   = p.S_pe_VA/(sqrt(3)*p.VLL_base);     % 173.21 A
p.I_pe_peak  = sqrt(2)*p.I_pe_rms;                 % 244.95 A

p.iq_pe_limit_pu = p.S_pe_pu;                      % 0.30 droop saturation
p.I_conv_max_pu  = 0.35;                           % limit-criterion converter current line

% ★ frt-v2 current base for normalising MEASURED PEAK dq currents (fixes audit C3):
p.I_dq_base_peak = p.I_sys_peak;                   % use this, NOT 173.2, for dq/peak -> pu

% ── current-base redesign (audit item 6): THREE DISTINCT roles, NEVER conflated ──
% Legacy HLC used Imax=I_pe_rms(173.2) as BOTH action scale AND converter clip (wrong: rms vs peak;
% PE-rating vs action scale). Separate:
p.I_action_peak    = p.I_sys_peak;                 % (1) ACTION current SCALE: iq_pu -> peak amps (816.50)
p.I_converter_peak = p.I_pe_peak;                  % (2) PHYSICAL PE converter PEAK clip limit (244.95)
%                    (3) system-pu PE limit = p.S_pe_pu (0.30).
% Identity: iq=0.3 -> 0.3*I_action_peak = 244.95 A peak = I_converter_peak = I_pe_peak -> 120 kVAr.
% The current controller clips the COMBINED dq vector to I_converter_peak; NO second 0.3 multiply.

p.metrics_version = 'frt-v2';
end
