%% HPT System Parameters
% Multi-Port Hybrid Power Transformer (400kVA, 10kV/400V)
% Reference: 多端口柔性混合配变研制 project

%% Grid Parameters
V_grid_ll   = 10e3;          % Grid line-to-line voltage (V)
V_grid_ph   = V_grid_ll / sqrt(3); % Phase voltage (V)
f_grid      = 50;            % Grid frequency (Hz)
w_grid      = 2*pi*f_grid;  % Angular frequency (rad/s)
Z_grid      = 0.1 + 1j*0.3; % Grid Thevenin impedance (Ohm, per phase)

%% Main Transformer Parameters
S_rated     = 400e3;         % Rated apparent power (VA)
S_pe        = 120e3;         % Power electronic converter capacity (VA), >=120kVA
V_primary   = 10e3;          % Primary voltage (V, line-to-line)
V_secondary = 400;           % Secondary voltage (V, line-to-line)
Tr_ratio    = V_primary / V_secondary;  % 25
Tr_leakage  = 0.05;          % Leakage reactance (pu)
Tr_resist   = 0.01;          % Winding resistance (pu)

%% DC Link
V_dc_ref    = 800;           % DC bus reference voltage (V)
C_dc        = 2200e-6;       % DC link capacitance (F)
V_dc_init   = 800;           % Initial DC voltage (V)

%% VSC_sh (Shunt Converter — 3-phase bridge, secondary side)
% Maintains V_dc, reactive power compensation, harmonic suppression
V_sh_rated  = V_secondary;   % Nominal AC voltage at shunt port (400V)
I_sh_max    = S_pe / (sqrt(3) * V_sh_rated);  % Max current (A)
L_sh        = 3e-3;          % Shunt filter inductance (H)
R_sh        = 0.05;          % Shunt filter resistance (Ohm)
% Coupling transformer T_sh (1:1 ratio, small leakage)
Tsh_ratio   = 1.0;
Tsh_leakage = 0.02;          % pu

%% VSC_se (Series Converter — 3x single-phase H-bridge, primary side)
% Injects series voltage for regulation and power flow control
V_se_max    = 0.20 * V_grid_ph;  % Max series voltage = ±20% of primary phase voltage
I_se_max    = S_rated / (sqrt(3) * V_grid_ph);  % Rated line current (A)
L_se        = 1e-3;          % Series filter inductance (H)
R_se        = 0.02;          % Series filter resistance (Ohm)
% Coupling transformer T_se (step-down, 1:k ratio for isolation)
Tse_ratio   = V_grid_ph / (V_dc_ref / 2);  % Approximate turns ratio
Tse_leakage = 0.02;          % pu

%% PWM and Sampling
f_sw_sh     = 5e3;           % VSC_sh switching frequency (Hz)
f_sw_se     = 5e3;           % VSC_se switching frequency (Hz)
f_sample    = 20e3;          % Data logging sample rate (Hz), 50us sample time
T_sample    = 1/f_sample;    % Sample time (s)
T_sim_step  = 50e-6;         % Simulink solver step size (s)

%% PI Controller Tuning — VSC_sh Inner Current Loop (dq-axis)
% Bandwidth target: 1/10 of switching frequency = 500 Hz
wb_sh       = 2*pi*500;      % Inner loop bandwidth (rad/s)
Kp_ish      = L_sh * wb_sh;  % Proportional gain
Ki_ish      = R_sh * wb_sh;  % Integral gain

%% PI Controller Tuning — VSC_se Inner Voltage/Current Loop
wb_se       = 2*pi*500;
Kp_ise      = L_se * wb_se;
Ki_ise      = R_se * wb_se;

%% PI Controller Tuning — DC Voltage Outer Loop (VSC_sh)
wb_dc       = 2*pi*50;       % DC voltage loop bandwidth (rad/s, ~1/10 of inner)
Kp_vdc      = C_dc * wb_dc;
Ki_vdc      = Kp_vdc * wb_dc / 10;

%% PI Controller Tuning — AC Voltage Outer Loop (VSC_se)
wb_vac      = 2*pi*50;
Kp_vac      = 1.0;
Ki_vac      = 50.0;

%% PI Controller Tuning — Reactive Power (VSC_sh)
Kp_q        = 0.01;
Ki_q        = 5.0;

%% PI Controller Tuning — Power Flow (VSC_se)
Kp_pf       = 0.5;
Ki_pf       = 20.0;

%% Load Parameters (configurable per scenario)
% Default: rated resistive load at secondary
R_load      = V_secondary^2 / S_rated;   % ~0.4 Ohm
L_load      = 0;             % No inductive load (set per scenario)
pf_load     = 1.0;           % Power factor

%% PV Source Parameters (for PV scenario)
P_pv_rated  = 50e3;          % PV rated power (W)
V_pv        = 400;           % PV string voltage (V)

%% Efficiency Target
eta_target  = 0.96;          % Minimum efficiency >=96%

%% Operating Voltage Range
Vbus_min    = V_secondary * (1 - 0.20);  % -20%
Vbus_max    = V_secondary * (1 + 0.20);  % +20%

%% Dynamic Response Target
T_response  = 5e-3;          % Maximum settling time (s), <5ms

%% Display Parameters
fprintf('=== HPT System Parameters ===\n');
fprintf('Grid: %.0f kV, %.0f Hz\n', V_grid_ll/1e3, f_grid);
fprintf('Main Transformer: %.0f kVA, %.0f kV / %.0f V\n', S_rated/1e3, V_primary/1e3, V_secondary);
fprintf('PE Capacity: %.0f kVA\n', S_pe/1e3);
fprintf('DC Bus: %.0f V, C=%.0f uF\n', V_dc_ref, C_dc*1e6);
fprintf('Max Series Voltage: %.0f V (%.0f%%)\n', V_se_max, 20);
fprintf('Switching Freq: %.0f kHz\n', f_sw_sh/1e3);
fprintf('Sample Rate: %.0f kHz\n', f_sample/1e3);
