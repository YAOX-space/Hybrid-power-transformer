function [T, X, Y] = hpt_ode_model(scenario, t_end, t_fault, rng_seed)
% HPT_ODE_MODEL  Physics-grounded HPT average model for training data generation.
%
% Model assumptions (suitable for control-oriented simulation):
%   1. Inner current loops are ideal (fast PI tracking)  → I = I_ref
%   2. V_dc closed-loop: first-order response to reference (τ_dc ≈ 20 ms)
%   3. Fault signatures applied as phase-specific ABC distortions
%
% States: x(1)=V_dc

if nargin < 4, rng_seed = 42; end
rng(rng_seed);

%% ── Parameters ───────────────────────────────────────────────────────────────
f    = 50;  wb = 2*pi*f;
V1n  = 10e3/sqrt(3);          % Primary phase voltage RMS (V)
V2n  = 400/sqrt(3);           % Secondary phase voltage RMS (V)
S    = 400e3;                  % Rated VA
Vdc_ref = 800;                 % DC reference (V)
tau_dc  = 0.020;               % DC bus closed-loop time constant (s, ≈20ms)

% Nominal dq reference currents (peak, based on rated conditions)
P_load = S * (0.30 + 0.70*rand());
Q_load = S * (0.00 + 0.40*rand());

I1d_nom = (2/3) * P_load / (V1n * sqrt(2));   % Primary d-current peak (A)
I1q_nom = (2/3) * Q_load / (V1n * sqrt(2));   % Primary q-current peak (A)
Ishd_nom= (2/3) * P_load / (V2n * sqrt(2));   % Shunt d-current peak (A)
Ishq_nom= (2/3) * Q_load / (V2n * sqrt(2));   % Shunt q-current peak (A)

% Series voltage injection reference (small — regulation correction)
Vse_d_nom = 0.02 * V1n * sqrt(2);  % ≈2% of rated for baseline regulation

%% ── Fault setup ─────────────────────────────────────────────────────────────
if nargin < 3 || isempty(t_fault)
    t_fault = 0.8 + 0.4*rand();
end
fault_phase = randi(3);   % faulted phase index (1=A, 2=B, 3=C)
t_clear = t_fault + 0.08 + 0.07*rand();  % SC clearance (80-150 ms)

%% ── Simulation ───────────────────────────────────────────────────────────────
fs   = 20000;
dt   = 1/fs;
t_grid = (0:dt:(t_end-dt))';
N    = length(t_grid);

V1_abc       = zeros(N,3);
I1_abc       = zeros(N,3);
V2_abc       = zeros(N,3);
I2_abc       = zeros(N,3);
Vdc_log      = zeros(N,1);
Ish_dq       = zeros(N,2);
Ise_dq       = zeros(N,2);
P1_log       = zeros(N,1);  Q1_log = zeros(N,1);
P2_log       = zeros(N,1);  Q2_log = zeros(N,1);
mode_log     = ones(N,1);
fault_labels = zeros(N,1);

x = Vdc_ref;   % initial V_dc

for k = 1:N
    t     = t_grid(k);
    theta = wb * t;

    in_fault        = (t >= t_fault);
    in_fault_window = (t >= t_fault) && (t < t_clear);
    t_since = max(0, t - t_fault);

    %% Current and voltage references (fault-adjusted)
    I1d  = I1d_nom;   I1q  = I1q_nom;
    Ishd = Ishd_nom;  Ishq = Ishq_nom;
    Vsed = Vse_d_nom; Vseq = 0;
    fault_label = 0;

    % Phase amplitude scales for ABC reconstruction
    sv1 = [1, 1, 1];   si1 = [1, 1, 1];
    sv2 = [1, 1, 1];   si2 = [1, 1, 1];
    Vdc_perturbation = 0;

    switch scenario
        case 3   % IGBT OC in VSC_sh — faulted phase current collapses
            if in_fault
                fault_label = 1;
                si2(fault_phase) = 0.05 + 0.01*randn();
                Ishd = Ishd_nom * 0.15;
                Vdc_perturbation = 25 * (1 - exp(-t_since/0.08));
            end
        case 4   % IGBT OC in VSC_se — series voltage distorted on one phase
            if in_fault
                fault_label = 2;
                si1(fault_phase) = 0.12 + 0.03*randn();
                sv1(fault_phase) = 0.80 + 0.05*randn();
                Vsed = Vse_d_nom * 0.10;
            end
        case 5   % DC capacitor fault — V_dc drops and oscillates
            if in_fault
                fault_label = 3;
                decay = exp(-t_since / 0.08);
                Vdc_perturbation = -80 * decay + 55 * sin(2*pi*300*t) * decay;
            end
        case 6   % Single-phase AC short circuit
            if in_fault_window
                fault_label = 4;
                sv2(fault_phase) = 0.04 + 0.01*randn();
                si1(fault_phase) = 4.2  + 0.5*rand();
                si2(fault_phase) = 3.8  + 0.5*rand();
                I1d = I1d_nom * 4;
            end
        case 7   % Three-phase AC short circuit
            if in_fault_window
                fault_label = 5;
                sv2 = [0.04 0.04 0.04] + 0.01*rand(1,3);
                si1 = [4.2  4.2  4.2]  + 0.5*rand(1,3);
                si2 = [3.8  3.8  3.8]  + 0.5*rand(1,3);
                I1d = I1d_nom * 4;
            end
        case 8   % Cascade: IGBT fault → monotonic DC overvoltage
            if in_fault
                fault_label = 6;
                si2(fault_phase) = 0.05 + 0.01*randn();
                Ishd = Ishd_nom * 0.08;
                Vdc_perturbation = min(t_since * 65, 135);
            end
    end

    %% V_dc first-order closed-loop dynamics + fault perturbation
    dVdc = (Vdc_ref - x) / tau_dc;
    x = x + dVdc * dt;
    Vdc_out = x + Vdc_perturbation + randn() * 2.0;
    Vdc_out = max(Vdc_out, 20);

    %% dq → abc (balanced three-phase sinusoids)
    T_dq2abc = sqrt(2/3) * [
        cos(theta),          -sin(theta);
        cos(theta-2*pi/3),   -sin(theta-2*pi/3);
        cos(theta+2*pi/3),   -sin(theta+2*pi/3)];

    nV1 = V1n * sqrt(2);  nV2 = V2n * sqrt(2);
    noise_frac = 0.008;

    V1_base = (T_dq2abc * [nV1; 0])';
    I1_base = (T_dq2abc * [I1d; I1q])';
    V2_base = (T_dq2abc * [nV2; 0])';
    I2_base = (T_dq2abc * [Ishd; Ishq])';

    V1_abc(k,:) = V1_base .* sv1  +  noise_frac*nV1  * randn(1,3);
    I1_abc(k,:) = I1_base .* si1  +  noise_frac*I1d  * randn(1,3);
    V2_abc(k,:) = V2_base .* sv2  +  noise_frac*nV2  * randn(1,3);
    I2_abc(k,:) = I2_base .* si2  +  noise_frac*Ishd * randn(1,3);

    %% Logged quantities
    Vdc_log(k)      = Vdc_out;
    Ish_dq(k,:)     = [Ishd, Ishq];
    Ise_dq(k,:)     = [Vsed, Vseq];
    P1_log(k)       = 1.5 * nV1 * I1d;
    Q1_log(k)       = 1.5 * nV1 * I1q;
    P2_log(k)       = 1.5 * nV2 * Ishd;
    Q2_log(k)       = 1.5 * nV2 * Ishq;
    mode_log(k)     = 1;
    fault_labels(k) = fault_label;
end

T = t_grid;
X = x;
Y = struct('t_uniform', t_grid, 'V1_abc', V1_abc, 'I1_abc', I1_abc, ...
           'V2_abc', V2_abc, 'I2_abc', I2_abc, 'V_dc', Vdc_log, ...
           'Ish_dq', Ish_dq, 'Ise_dq', Ise_dq, 'P1', P1_log, 'Q1', Q1_log, ...
           'P2', P2_log, 'Q2', Q2_log, 'mode', mode_log, 'fault_labels', fault_labels);
end
