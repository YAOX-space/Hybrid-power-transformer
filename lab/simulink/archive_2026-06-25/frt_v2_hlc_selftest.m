function frt_v2_hlc_selftest()
% frt_v2_hlc_selftest — exercise the codegen-compatible frt-v2 HLC primitives with SYNTHETIC weights
% (no retraining, no Simulink). Proves the de-privileged + 3-D + current-base contract:
%   (item 4) identical MEASURED history with different true onset -> identical observation;
%   (item 5) 20-D observation, 3-output actor matrix -> 3-element action;
%   (item 6) action iq=0.3 -> 0.3*I_action_peak = I_pe_peak amps; converter clip caps |I| at I_pe_peak.
OBS_DIM = 20; N_ACT = 3; H = 256; ok = true;
p = pu_params();

% ---- synthetic actor weights (deterministic, small) ----
rng_state = 0;                                   % no Math.random: fixed fill
W = struct();
W.latent_pi_0_weight = fill_mat(H, OBS_DIM, 1);  W.latent_pi_0_bias = fill_mat(H,1,2);
W.latent_pi_2_weight = fill_mat(H, H, 3);        W.latent_pi_2_bias = fill_mat(H,1,4);
W.latent_pi_4_weight = fill_mat(H, H, 5);        W.latent_pi_4_bias = fill_mat(H,1,6);
W.mu_weight = fill_mat(N_ACT, H, 7);             W.mu_bias = fill_mat(N_ACT,1,8);
W.act_low  = [-0.30; -0.20; -0.20];              W.act_high = [0.30; 0.20; 0.20];

% ---- item 5: obs shape 20, actor 3 ----
det0 = struct('detected', false, 'onset_t', 0.0, 'last_t', 0.0);
[det, inF, ~] = frt_v2_hlc('ofd', det0, 0.30, 0.5, 0.1);
obs = frt_v2_hlc('obs', 0.9, 0.5, 0.1, 0.2, 0.0, det, [0;0;0]);
ok = ok && isequal(size(obs), [OBS_DIM 1]);
act = frt_v2_hlc('actor', W, obs);
ok = ok && isequal(size(act), [N_ACT 1]) && inF;
fprintf('  obs=%dx1 act=%dx1  %s\n', numel(obs), numel(act), tern(ok,'OK','FAIL'));

% ---- item 4: same measured history, different absolute onset -> identical obs ----
patV2p = [1.0 1.0 1.0 1.0 1.0 0.5 0.5 0.5 0.5 0.5];
obsA = run_history(patV2p, 0.05);   % onset at t0=0.05
obsB = run_history(patV2p, 0.37);   % onset at t0=0.37 (different true time)
dmax = max(abs(obsA - obsB));
ok = ok && dmax < 1e-12;
fprintf('  de-privileged: max|obsA-obsB|=%.3g (expect 0) %s\n', dmax, tern(dmax<1e-12,'OK','FAIL'));

% ---- item 6: current-base round trip + clip ----
iq_amp = frt_v2_hlc('iq_cmd', p, 0.30);
ok = ok && abs(iq_amp - p.I_pe_peak) < 1e-6 && abs(iq_amp - p.I_converter_peak) < 1e-6;
fprintf('  iq=0.3 -> %.3f A peak (expect %.3f = I_pe_peak) %s\n', iq_amp, p.I_pe_peak, ...
        tern(abs(iq_amp-p.I_pe_peak)<1e-6,'OK','FAIL'));
[idc, iqc] = frt_v2_hlc('clip', p, 300.0, 300.0);
ok = ok && abs(hypot(idc,iqc) - p.I_converter_peak) < 1e-6;
fprintf('  clip(300,300) -> |I|=%.3f (expect %.3f) %s\n', hypot(idc,iqc), p.I_converter_peak, ...
        tern(abs(hypot(idc,iqc)-p.I_converter_peak)<1e-6,'OK','FAIL'));
% no second 0.3 multiply
ok = ok && abs(iq_amp - 0.30*p.I_pe_peak) > 1.0;

if ok, fprintf('frt_v2_hlc_selftest: ALL OK (de-privileged obs + 3-D actor + current-base)\n');
else,  error('frt_v2_hlc_selftest FAILED'); end

  function obsv = run_history(pv, t0)
    d = struct('detected', false, 'onset_t', 0.0, 'last_t', 0.0); dt = 0.02; obsv = zeros(OBS_DIM,1);
    for k = 1:numel(pv)
      [d, ~, ~] = frt_v2_hlc('ofd', d, t0 + (k-1)*dt, pv(k), 0.0);
      obsv = frt_v2_hlc('obs', 0.9, pv(k), 0.0, 0.2, 0.0, d, [0;0;0]);
    end
  end
end

function M = fill_mat(r, c, seed)
% deterministic small weights in [-0.05,0.05] (no rng/random for reproducibility/codegen)
[I, J] = ndgrid(1:r, 1:c);
M = 0.05 * sin(0.7*I + 1.3*J + seed);
end
function s = tern(c,a,b), if c, s=a; else, s=b; end, end
