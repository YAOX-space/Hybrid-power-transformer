function varargout = frt_v2_hlc(cmd, varargin) %#codegen
% frt_v2_hlc — codegen-compatible frt-v2 HLC primitives for the deployed Simulink controller.
% Replaces the legacy HLC's PRIVILEGED observation (true tf / future fdur / true fault class) and its
% 4-D action + conflated Imax current base. Dispatch by string `cmd`:
%
%   [det,inF,elapsed] = frt_v2_hlc('ofd', det, t, V2p, V2n)      % online fault detector (no true tf)
%   obs               = frt_v2_hlc('obs', Vdc_pu, V2p, V2n, iq, iq_ref, det, last_a3)   % 20-D obs
%   act3              = frt_v2_hlc('actor', W, obs)               % 3-output actor forward pass
%   iq_amp            = frt_v2_hlc('iq_cmd', p, iq_pu)            % action -> PEAK amp (I_action_peak)
%   [idc,iqc]         = frt_v2_hlc('clip', p, id_a, iq_a)        % clip |I| to I_converter_peak
%
% Contract constants (must match src/hpt_frt/device/frt_env_v2.py): OBS_DIM=20, N_ACT=3, hidden=256.
% The detector/obs use ONLY the controller clock `t` and MEASURED (V2p,V2n) — never the scenario
% fault type, true onset, future duration, target residual or clearing time.
OBS_DIM = 20; N_ACT = 3; H = 256;
GATE_LV = 0.90; GATE_HV = 1.060; GATE_V2N = 0.05; ELAPSED_NORM = 0.5;

switch cmd
  case 'ofd'
    det = varargin{1}; t = varargin{2}; V2p = varargin{3}; V2n = varargin{4};
    faulted = (V2p < GATE_LV) || (V2p > GATE_HV) || (V2n > GATE_V2N);
    if faulted
      if ~det.detected
        det.detected = true; det.onset_t = t;
      end
    else
      det.detected = false; det.onset_t = 0.0;
    end
    det.last_t = t;                                   % current clock (for elapsed in 'obs')
    if det.detected, elapsed = max(0.0, t - det.onset_t); else, elapsed = 0.0; end
    varargout{1} = det; varargout{2} = det.detected; varargout{3} = elapsed;

  case 'obs'
    Vdc_pu = varargin{1}; V2p = varargin{2}; V2n = varargin{3}; iq = varargin{4};
    iq_ref = varargin{5}; det = varargin{6}; last_a3 = varargin{7};
    vdev = 0.9 - V2p; iq_err = iq_ref - iq;
    if det.detected, elapsed = max(0.0, det.last_t - det.onset_t); else, elapsed = 0.0; end
    in_fault = double(det.detected);
    % online fault-class one-hot from MEASURED seq only (normal0 sym1 1phg2 2ph3 2phg4 swell5)
    probs = zeros(6,1); fc = 0;
    if V2p > GATE_HV, fc = 5;
    elseif V2p < GATE_LV, if V2n > GATE_V2N, fc = 2; else, fc = 1; end
    end
    if in_fault > 0.5 && fc ~= 0, probs(fc+1) = 0.92; probs(1) = probs(1) + 0.08; else, probs(1) = 1.0; end
    tfrac = min(1.0, max(0.0, elapsed / ELAPSED_NORM));
    o = [Vdc_pu; V2p; V2n; abs(iq); 0.0; 0.0; vdev; iq_err; iq; probs; tfrac; in_fault; ...
         last_a3(1); last_a3(2); last_a3(3)];
    varargout{1} = min(5.0, max(-5.0, reshape(o, OBS_DIM, 1)));

  case 'actor'
    W = varargin{1}; obs = reshape(varargin{2}, OBS_DIM, 1);
    W0 = reshape(W.latent_pi_0_weight, H, OBS_DIM); b0 = reshape(W.latent_pi_0_bias, H, 1);
    W2 = reshape(W.latent_pi_2_weight, H, H);       b2 = reshape(W.latent_pi_2_bias, H, 1);
    W4 = reshape(W.latent_pi_4_weight, H, H);       b4 = reshape(W.latent_pi_4_bias, H, 1);
    Wm = reshape(W.mu_weight, N_ACT, H);            bm = reshape(W.mu_bias, N_ACT, 1);
    alo = reshape(W.act_low, N_ACT, 1);             ahi = reshape(W.act_high, N_ACT, 1);
    h = max(0, W0*obs + b0); h = max(0, W2*h + b2); h = max(0, W4*h + b4);
    mu = Wm*h + bm; at = tanh(mu);
    varargout{1} = alo + 0.5*(at + 1).*(ahi - alo);    % [iq, mse_d, mse_q]

  case 'iq_cmd'
    p = varargin{1}; iq_pu = varargin{2};
    varargout{1} = iq_pu * p.I_action_peak;            % ACTION scale = I_action_peak (NOT I_pe_rms)

  case 'clip'
    p = varargin{1}; id_a = varargin{2}; iq_a = varargin{3};
    mag = hypot(id_a, iq_a);
    if mag > p.I_converter_peak && mag > 0
      s = p.I_converter_peak / mag; id_a = id_a*s; iq_a = iq_a*s;   % clip COMBINED vector, no 2nd 0.3
    end
    varargout{1} = id_a; varargout{2} = iq_a;

  otherwise
    error('frt_v2_hlc:badcmd', 'unknown cmd %s', cmd);
end
end
