function pu_selfcheck()
% pu_selfcheck — verify lab/simulink/pu_params.m against src/hpt_frt/common/pu.py and the headline
% 120 kVAr identity. Run: pu_selfcheck. Pure (no Simulink); part of the frt-v2 single-source audit.
p = pu_params();

% expected values from the Python single source (src/hpt_frt/common/pu.py)
exp = struct('S_base_VA',400e3,'VLL_base',400,'I_sys_rms',577.3503,'I_sys_peak',816.4966, ...
             'S_pe_VA',120e3,'I_pe_rms',173.2051,'I_pe_peak',244.9490, ...
             'iq_pe_limit_pu',0.30,'I_conv_max_pu',0.35,'I_dq_base_peak',816.4966, ...
             'I_action_peak',816.4966,'I_converter_peak',244.9490);
fn = fieldnames(exp); ok = true;
for i=1:numel(fn)
  got = p.(fn{i}); want = exp.(fn{i});
  d = abs(got-want);
  tol = 1e-3*max(1,abs(want));
  pass = d <= tol;
  ok = ok && pass;
  fprintf('  %-16s MATLAB=%-12.4f Python=%-12.4f %s\n', fn{i}, got, want, tern(pass,'OK','MISMATCH'));
end

% headline identity: iq=0.3 system-pu == PE full == 120 kVAr
kvar = p.iq_pe_limit_pu * p.S_base_VA/1e3;
fprintf('  iq=0.3 -> %.3f kVAr (expect 120) %s\n', kvar, tern(abs(kvar-120)<1e-6,'OK','MISMATCH'));
ok = ok && abs(kvar-120)<1e-6;

% peak/RMS bases must never be conflated
ok = ok && abs(p.I_pe_peak/p.I_pe_rms - sqrt(2))<1e-9 && abs(p.I_sys_peak/p.I_sys_rms - sqrt(2))<1e-9;
ok = ok && abs(p.I_dq_base_peak - p.I_sys_peak)<1e-9;   % criteria base = system PEAK

% the inline function-call dot-access used across the criteria/plot code must work
test_inline = pu_params().I_dq_base_peak;
ok = ok && abs(test_inline - p.I_sys_peak)<1e-9;

% ── current-base redesign end-to-end round trip (item 6): action -> amp -> kVAr -> pu ──
iq_pu      = 0.30;
cmd_amp    = iq_pu * p.I_action_peak;              % action SCALE = I_action_peak (816.50)
rt_pu      = cmd_amp / p.I_sys_peak;               % peak amp -> system-pu
rt_kvar    = rt_pu * p.S_base_VA/1e3;              % -> kVAr
ok = ok && abs(cmd_amp - p.I_pe_peak) < 1e-6;     % 0.3*816.50 = 244.95 = I_pe_peak = I_converter_peak
ok = ok && abs(rt_kvar - 120.0)       < 1e-6;     % round trip -> 120 kVAr
fprintf('  action iq=0.3 -> %.3f A peak (expect %.3f) -> %.3f kVAr %s\n', ...
        cmd_amp, p.I_converter_peak, rt_kvar, tern(abs(rt_kvar-120)<1e-6,'OK','MISMATCH'));
% NO second 0.3 multiply: command must NOT be 0.3*I_pe_peak (=73.5 A)
ok = ok && abs(cmd_amp - 0.30*p.I_pe_peak) > 1.0;
% converter clip: a large combined dq vector is capped at I_converter_peak, direction preserved
mag = hypot(300.0, 300.0); s = min(1.0, p.I_converter_peak/mag);
idc = 300.0*s; iqc = 300.0*s;
ok = ok && abs(hypot(idc,iqc) - p.I_converter_peak) < 1e-6;

if ok, fprintf('pu_selfcheck: ALL OK (MATLAB pu_params matches Python pu.py + 120 kVAr + action/clip round trip)\n');
else,  error('pu_selfcheck FAILED — pu_params.m diverges from pu.py'); end
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
