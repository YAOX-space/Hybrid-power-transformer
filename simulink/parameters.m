%% HPT System Parameters
% Multi-Port Hybrid Power Transformer (400kVA, 10kV/400V)
% Reference: 多端口柔性混合配变研制 project
%
% REVISION LOG (2026-05-29):
%   D2-FIX: DC-link PI gains corrected per Liu et al. IEEE TPEL 2021
%           (K_IuD/K_PuD = 55–400 rad/s vs previous 3.14 rad/s)
%   D3-FIX: Notch filter design parameters added per Liu et al. IEEE TPEL 2021
%   D5-FIX: dq decoupling feedforward terms documented per standard practice
%   Tse_ratio: Corrected formula — must be V_se_max/V_dc_ref, not V_grid_ph/(V_dc_ref/2)
%
% Literature basis:
%   [1] Liu et al., "Power Flow Analysis and DC-link Voltage Control of HDT",
%       IEEE Trans. Power Electron., vol. 36, no. 11, Nov. 2021.
%   [2] Lai et al., "Enhancing Transient Performance of HDT Using ET-PIRC",
%       IEEE Trans. Power Electron., vol. 41, no. 2, Feb. 2026.
%   [3] Shang et al., "HPT Voltage Control Strategy for Grid-connected PV",
%       2024 CEEPE, IEEE, 2024.

%% Grid Parameters
V_grid_ll   = 10e3;          % Grid line-to-line voltage (V)
V_grid_ph   = V_grid_ll / sqrt(3); % Phase voltage (V) = 5774 V
f_grid      = 50;            % Grid frequency (Hz)
w_grid      = 2*pi*f_grid;  % Angular frequency (rad/s) = 314.16 rad/s
Z_grid      = 0.1 + 1j*0.3; % Grid Thevenin impedance (Ohm, per phase)

%% Main Transformer Parameters
S_rated     = 400e3;         % Rated apparent power (VA)
S_pe        = 120e3;         % Power electronic converter capacity (VA), >=120kVA
V_primary   = 10e3;          % Primary voltage (V, line-to-line)
V_secondary = 400;           % Secondary voltage (V, line-to-line)
Tr_ratio    = V_primary / V_secondary;  % 25  (line-to-line; per-phase = same for Δ-Y)
Tr_leakage  = 0.05;          % Leakage reactance (pu)
Tr_resist   = 0.01;          % Winding resistance (pu)

%% Phase offset (Dyyn11 or Δ-Y connection)
% The Delta-Y transformer introduces a 30° (π/6 rad) phase shift between
% primary and secondary voltages per IEEE/IEC transformer vector group standard.
% Ref: Lai et al. 2026, eq. (7): v_LVxref = V_LV·sin(θ + π/6 + 2pπ/3)
phi_dy      = pi/6;          % Phase offset: +30° (LV lags MV by 30°, Dyyn11/Δ-Yg)

%% DC Link
V_dc_ref    = 800;           % DC bus reference voltage (V)
C_dc        = 2200e-6;       % DC link capacitance (F)
V_dc_init   = 800;           % Initial DC voltage (V)
E_dc_stored = 0.5*C_dc*V_dc_ref^2;  % Stored energy = 704 J

%% Energy-extraction converter (3-phase bridge at secondary LV bus)
% Maintains V_dc, reactive power compensation, harmonic suppression
V_sh_rated  = V_secondary;   % Nominal AC voltage at shunt port (400V)
I_sh_max    = S_pe / (sqrt(3) * V_sh_rated);  % Max current (A) = 173.2 A
L_sh        = 3e-3;          % Shunt filter inductance (H)
R_sh        = 0.05;          % Shunt filter resistance (Ohm)
% Coupling transformer T_sh (1:1 ratio, small leakage)
Tsh_ratio   = 1.0;
Tsh_leakage = 0.02;          % pu

%% Regulation converter (3x single-phase H-bridges for series injection)
% Injects series voltage for regulation and power flow control
% [3] Shang 2024 eq. (1): V1 = Vse + k·Vm1 + jX_T·I1
V_se_max    = 0.20 * V_grid_ph;  % Max series voltage injection = ±20% × 5774 = ±1155 V
I_se_max    = S_rated / (sqrt(3) * V_grid_ph);  % Rated line current (A) = 23.1 A
L_se        = 1e-3;          % Series filter inductance (H)
R_se        = 0.02;          % Series filter resistance (Ohm)

% Coupling transformer T_se turns ratio (H-bridge side : MV primary side)
% CORRECTED (D-fix): For ±20% injection on primary side from 800V H-bridge:
%   Required turns ratio = V_dc_ref / V_se_max = 800 / 1155 ≈ 0.693
%   (H-bridge produces ±Vdc, needs step-UP to inject ±V_se_max on MV side)
%   N_hbridge : N_mv = 1 : (V_se_max / V_dc_ref) = 1 : 1.44
%   Old (wrong) formula: V_grid_ph / (V_dc_ref/2) = 5774/400 = 14.4
Tse_ratio   = V_dc_ref / V_se_max;  % ≈ 0.693 (H-bridge:MV = 1 : 1.44 step-up)
Tse_leakage = 0.02;          % pu

%% PWM and Sampling
f_sw_sh     = 5e3;           % energy-extraction VSC switching frequency (Hz)
f_sw_se     = 5e3;           % regulation VSC switching frequency (Hz)
f_sample    = 20e3;          % Data logging sample rate (Hz), 50us sample time
T_sample    = 1/f_sample;    % Sample time (s)
T_sim_step  = 50e-6;         % Simulink solver step size (s)

%% PI Controller Tuning — energy-extraction VSC inner current loop (dq-axis)
% Standard bandwidth: 1/10 of switching frequency = 500 Hz
% Cross-coupling decoupling (D5-FIX): must add ±w_grid·L_sh·i_{q,d} feedforward
%   in the VSC SPWM block: u_d = PI(e_d) - w_grid*L_sh*i_q
%                          u_q = PI(e_q) + w_grid*L_sh*i_d
wb_sh       = 2*pi*500;      % Inner loop bandwidth (rad/s) = 3142 rad/s
Kp_ish      = L_sh * wb_sh;  % Proportional gain = 3e-3 * 3142 = 9.42
Ki_ish      = R_sh * wb_sh;  % Integral gain = 0.05 * 3142 = 157.1

%% PI Controller Tuning — regulation VSC inner voltage/current loop
wb_se       = 2*pi*500;
Kp_ise      = L_se * wb_se;  % = 1e-3 * 3142 = 3.14
Ki_ise      = R_se * wb_se;  % = 0.02 * 3142 = 62.8

%% PI Controller Tuning — DC Voltage Outer Loop (energy-extraction VSC)
% D2-FIX: Corrected per Liu et al. 2021 [1]
% Transfer function: G_uD(s) = 3√2·U1N / (C_D·U_D·s)  [Liu 2021 eq. 40]
%   = 3√2 × (400/√3) / (2200e-6 × 800 × s) = 612.4 / (1.76e-3 × s)
% Literature recommends ω_PI = K_IuD/K_PuD ≈ 55 rad/s (PI-filters, Liu 2021 Table II)
%   or 400 rad/s for pure PI.
% Previous (INCORRECT): Kp_vdc = C_dc*wb_dc = 0.691, Ki_vdc = 2.17
%   → ω_PI = Ki/Kp = 3.14 rad/s  (17.5× too low)
% Corrected: Use Liu 2021 recommended values (Table II, eq. 42)
Kp_vdc      = 0.30;          % Proportional gain [Liu 2021 validated: 0.014-0.30]
Ki_vdc      = Kp_vdc * 55;   % Integral gain = 0.30 × 55 = 16.5 rad/s  [Liu 2021 ω_PI=55 for PI+filters]
% Note: if no notch filters, use Ki_vdc = Kp_vdc * 400 = 120 (pure PI bandwidth)
% With notch filters (recommended), use ω_PI = 55 rad/s as above.

%% PI Controller Tuning — AC Voltage Outer Loop (regulation VSC)
% [3] Shang 2024 eq. (17): V_sed = V1d/k − V2d + PI(V2_rms_ref² − V2_rms²)/(V1d/k+V2d)
wb_vac      = 2*pi*50;       % Outer loop bandwidth (~50 Hz)
Kp_vac      = 1.0;
Ki_vac      = 50.0;

%% PI Controller Tuning — Reactive Power (energy-extraction VSC)
Kp_q        = 0.01;
Ki_q        = 5.0;

%% PI Controller Tuning — Power Flow (regulation VSC)
Kp_pf       = 0.5;
Ki_pf       = 20.0;

%% D3-FIX: Notch Filter Design for DC-Link Voltage Control
% Liu et al. 2021 recommends 3 notch filters to eliminate AC harmonics in the
% DC-link control path that cause grid current distortion under asymmetric loads.
% Without these, pure PI causes THD ≈ 12–21% in grid currents [Liu 2021 Table I].
%
% Notch filter transfer function: G_BEF(s) = (s² + ωn²) / (s² + ωn/Q·s + ωn²)
% Center frequencies: ω0, 2ω0, 3ω0  (50, 100, 150 Hz)
% Quality factor Q = 3 (recommended by Liu 2021)

% Notch filter 1: ω0 = 314.16 rad/s (50 Hz)
notch1_wn   = w_grid;        % Center frequency (rad/s)
notch1_Q    = 3.0;           % Quality factor

% Notch filter 2: 2ω0 = 628.32 rad/s (100 Hz)
notch2_wn   = 2 * w_grid;
notch2_Q    = 3.0;

% Notch filter 3: 3ω0 = 942.48 rad/s (150 Hz)
notch3_wn   = 3 * w_grid;
notch3_Q    = 3.0;

% Low-pass filter for DC-link control (τ_LPF = 1 ms, Liu 2021 eq. 52)
tau_lpf_vdc = 1e-3;          % LPF time constant (s)

%% D5-FIX: dq Cross-Coupling Decoupling Feedforward Terms
% The shunt VSC current controller in dq frame must include decoupling:
%   u_d_ref = Kp_ish*(i_d_ref - i_d) + Ki_ish*∫(i_d_ref-i_d) - w_grid*L_sh*i_q
%   u_q_ref = Kp_ish*(i_q_ref - i_q) + Ki_ish*∫(i_q_ref-i_q) + w_grid*L_sh*i_d
% Cross-coupling term magnitude at rated current:
i_rated_sh  = I_sh_max;      % ≈ 173.2 A
decoupling_v = w_grid * L_sh * i_rated_sh;  % ≈ 314.16 × 3e-3 × 173.2 ≈ 163 V
% This is ≈ 40% of V_sh_rated/√2 = 163V, significant and must not be neglected.

%% Series Converter Control Reference (D1-FIX: π/6 phase offset)
% For Δ-Y (Dyyn11) connection, the LV reference voltage must include
% the 30° (π/6) phase offset between MV primary and LV secondary.
% Ref: Lai et al. 2026 eq. (7): v_LVxref = V_LV·sin(θ + π/6 + 2pπ/3)
%
% In the build_hpt_switching_model.m Regulation_VSC_SPWM block:
%   BEFORE (incorrect): theta = 2*pi*f1*t
%   AFTER  (correct):   theta = 2*pi*f1*t + pi/6
%
% Additionally, per-phase series voltage reference [Lai 2026 eq. (8)]:
%   v_SCaref = N_SC*(v_LVaref/N_LV - v_MVab/N_MV)
%   v_SCbref = N_SC*(v_LVbref/N_LV - v_MVbc/N_MV)
%   v_SCcref = N_SC*(v_LVcref/N_LV - v_MVca/N_MV)
% where N_SC/N_LV ≈ 1 (same side), N_MV/N_LV = Tr_ratio = 25
theta_phase_offset = phi_dy;  % = pi/6, to be added in build script SPWM block

%% ET-PIRC Parameters (for future implementation)
% Event-triggered PI-RC control per Lai et al. 2026, eqs. (15)–(29)
% Allocation coefficient K_ET ∈ [0, 0.5]:
%   G_ET-PIRC = (1-K_ET)·G_PI + K_ET·G_RC
% Trigger condition: |e(tk)| > A × max_steady_error
% Dynamic update: K_ET(t) = B / (1 + |e(t)|)
etpirc_KET_nominal = 0.5;    % Steady-state: equal PI/RC contribution
etpirc_A    = 3.0;           % Trigger threshold factor (2–4, Liu recommends 3)
etpirc_B    = 0.5;           % KET scale factor (keeps KET in (0, 0.5))
etpirc_Q    = 0.97;          % RC low-pass filter coefficient (Liu: 0.95–0.99, Q=0.97 recommended)
etpirc_N    = 400;           % Samples per fundamental cycle (20kHz / 50Hz = 400)
etpirc_Kr   = 0.5;           % RC gain coefficient

%% FAHC Strategy Parameters
% Fault-Aware Hierarchical Controller reference adjustments
% Physics rationale: ΔE(800→720V) = 0.5×2200e-6×(800²−720²) = 134 J
% Improves VdcMin by ~0.095 pu in borderline scenarios (VdcMin 0.65–0.75)
fahc_S0_vdc = 800;  fahc_S0_v2 = 400;  fahc_S0_ilim = 3.0;   % sc_id 0,1,2
fahc_S1_vdc = 760;  fahc_S1_v2 = 400;  fahc_S1_ilim = 2.8;   % sc_id 3 (cap_fault)
fahc_S2_vdc = 740;  fahc_S2_v2 = 380;  fahc_S2_ilim = 2.8;   % sc_id 4 (sc_1ph)
fahc_S3_vdc = 720;  fahc_S3_v2 = 360;  fahc_S3_ilim = 2.5;   % sc_id 5,6 (sc_3ph, cascade)

%% Load Parameters (configurable per scenario)
% Default: rated resistive load at secondary
R_load      = V_secondary^2 / S_rated;   % ~0.4 Ohm
L_load      = 0;             % No inductive load (set per scenario)
pf_load     = 1.0;           % Power factor

%% PV Source Parameters (for PV scenario)
P_pv_rated  = 50e3;          % PV rated power (W)
V_pv        = 400;           % PV string voltage (V)

%% Performance Targets (per project specification)
eta_target  = 0.96;          % Minimum efficiency >=96%
Vbus_min    = V_secondary * (1 - 0.20);  % -20% = 320 V
Vbus_max    = V_secondary * (1 + 0.20);  % +20% = 480 V
T_response  = 5e-3;          % Maximum settling time (s), <5ms
V_reg_range = 0.20;          % ±20% voltage regulation range

%% LVRT Pass Criteria
lvrt_vdc_min = 0.75;         % Vdc_min >= 0.75 pu (= 600V)
lvrt_vdc_max = 1.25;         % Vdc_max <= 1.25 pu (= 1000V)
lvrt_i2_max  = 3.0;          % I2_max <= 3.0 pu
lvrt_v2_recovery_ms = 100;   % V2 recovery <= 100 ms

%% Display Parameters
fprintf('=== HPT System Parameters (Revised 2026-05-29) ===\n');
fprintf('Grid: %.0f kV, %.0f Hz\n', V_grid_ll/1e3, f_grid);
fprintf('Main Transformer: %.0f kVA, %.0f kV / %.0f V (Δ-Yg, phase offset π/6)\n', ...
        S_rated/1e3, V_primary/1e3, V_secondary);
fprintf('PE Capacity: %.0f kVA (%.0f%% of rated)\n', S_pe/1e3, 100*S_pe/S_rated);
fprintf('DC Bus: %.0f V, C=%.0f uF, E=%.0f J\n', V_dc_ref, C_dc*1e6, E_dc_stored);
fprintf('Max Series Injection: ±%.0f V (±%.0f%% of Vph)\n', V_se_max, 20);
fprintf('Tse turns ratio (H-bridge:MV): 1:%.2f (step-up)\n', 1/Tse_ratio);
fprintf('DC-link PI: Kp=%.3f, Ki=%.1f (ω_PI=%.0f rad/s)\n', Kp_vdc, Ki_vdc, Ki_vdc/Kp_vdc);
fprintf('Notch filters: %.0f/%.0f/%.0f Hz, Q=%.1f\n', ...
        notch1_wn/(2*pi), notch2_wn/(2*pi), notch3_wn/(2*pi), notch1_Q);
fprintf('Series phase offset (Dyyn11): π/6 = %.4f rad\n', phi_dy);
fprintf('Switching Freq: %.0f kHz\n', f_sw_sh/1e3);
fprintf('Sample Rate: %.0f kHz\n', f_sample/1e3);
