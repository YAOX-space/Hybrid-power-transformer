%% drl_trainer.m  — Method B
% PPO-based Deep Reinforcement Learning controller for HPT.
% Uses MATLAB Reinforcement Learning Toolbox (R2022a+) with rlSimulinkEnv.
%
% Architecture:
%   Environment: hpt_main_model.slx (Simulink)
%   State  (13): [V1_err, V2_err, Vdc_err, Ish_d, Ish_q, Ise_d, Ise_q,
%                 P1_err, Q1_err, mode_1, mode_2, mode_3, t_norm]
%   Action  (3): [ΔVse_d, ΔVse_q, ΔIsh_d]  incremental, ±0.05 pu/step
%   Reward:      -α|V2_err|² - β|P_err|² - γ*I_overcurrent + δ*efficiency
%
% Training curriculum (3 stages):
%   Stage 1 (0–20k):  Normal load variation
%   Stage 2 (20–50k): Mode switching + step changes
%   Stage 3 (50–150k): Fault scenarios
%
% Reference: "Deep Reinforcement Learning for Power Converter Control" (ResearchGate 2024)

clear; clc;
addpath('../simulink');
run('parameters.m');

%% ── SIMULATION MODEL ──────────────────────────────────────────────────────────
mdl = 'hpt_main_model';
load_system(mdl);

% RL Agent block must be added to the Simulink model at:
%   mdl/HPT_Controller/RL_Agent
% The agent block reads the state bus and outputs action bus.

%% ── OBSERVATION SPECIFICATION ─────────────────────────────────────────────────
% 13-dimensional state vector
obs_info = rlNumericSpec([13 1], ...
    'LowerLimit', -ones(13,1)*5, ...
    'UpperLimit',  ones(13,1)*5);
obs_info.Name = 'HPT States';
obs_info.Description = [...
    'V1_err V2_err Vdc_err Ish_d Ish_q Ise_d Ise_q ' ...
    'P1_err Q1_err mode_1 mode_2 mode_3 t_norm'];

%% ── ACTION SPECIFICATION ──────────────────────────────────────────────────────
% 3 incremental control outputs (bounded ±0.05 pu per step)
act_info = rlNumericSpec([3 1], ...
    'LowerLimit', [-0.05; -0.05; -0.05], ...
    'UpperLimit', [ 0.05;  0.05;  0.05]);
act_info.Name = 'HPT Control';
act_info.Description = 'delta_Vse_d  delta_Vse_q  delta_Ish_d (pu/step)';

%% ── SIMULINK ENVIRONMENT ──────────────────────────────────────────────────────
% The Simulink model must have:
%   - An "RL Agent" block at mdl/HPT_Controller/RL_Agent
%   - Observation port (13-channel bus)
%   - Action port  (3-channel bus)
%   - Reward port  (scalar signal)
%   - IsDone port  (boolean — episode termination on fault or timeout)

env = rlSimulinkEnv(mdl, [mdl '/HPT_Controller/RL_Agent'], ...
    obs_info, act_info);

% Reset function: randomizes load, initial conditions per episode
env.ResetFcn = @(in) hpt_reset_fcn(in);

%% ── REWARD FUNCTION (embedded in Simulink via MATLAB Function block) ──────────
% Weights (tune via Weights struct)
W.alpha  = 10.0;   % Voltage error penalty
W.beta   = 5.0;    % Power error penalty
W.gamma  = 50.0;   % Overcurrent penalty
W.delta  = 0.1;    % Efficiency bonus
W.fault  = -20.0;  % Additional penalty during fault

% The reward block in Simulink calls: compute_reward(obs, W)
% This function is defined below and must be added as a MATLAB Function block

%% ── PPO AGENT ─────────────────────────────────────────────────────────────────
% Actor network: maps observation → action distribution mean
actor_net = [
    featureInputLayer(13, Name='obs')
    fullyConnectedLayer(256, Name='fc1')
    reluLayer(Name='relu1')
    fullyConnectedLayer(256, Name='fc2')
    reluLayer(Name='relu2')
    fullyConnectedLayer(128, Name='fc3')
    reluLayer(Name='relu3')
    fullyConnectedLayer(3, Name='output')
    tanhLayer(Name='tanh')          % squash to (-1, 1), scaled by action bounds
];

% Critic network: maps observation → value estimate V(s)
critic_net = [
    featureInputLayer(13, Name='obs')
    fullyConnectedLayer(256, Name='fc1')
    reluLayer(Name='relu1')
    fullyConnectedLayer(256, Name='fc2')
    reluLayer(Name='relu2')
    fullyConnectedLayer(128, Name='fc3')
    reluLayer(Name='relu3')
    fullyConnectedLayer(1, Name='value')
];

actor_net  = dlnetwork(layerGraph(actor_net));
critic_net = dlnetwork(layerGraph(critic_net));

% Create actor and critic objects
actor  = rlContinuousGaussianActor(actor_net,  obs_info, act_info, ...
    ActionMeanOutputNames='tanh', ...
    ObservationInputNames='obs');
critic = rlValueFunction(critic_net, obs_info, ...
    ObservationInputNames='obs');

% PPO options
agent_opts = rlPPOAgentOptions(...
    'SampleTime',               T_sim_step, ...
    'DiscountFactor',           0.99, ...
    'GAEFactor',                0.95, ...       % Generalized Advantage Estimation
    'ClipFactor',               0.2, ...        % PPO clip ratio
    'EntropyLossWeight',        0.01, ...       % Entropy bonus for exploration
    'NumEpoch',                 4, ...          % Mini-batch SGD epochs per update
    'MiniBatchSize',            256, ...
    'ExperienceHorizon',        2048, ...       % Steps before update
    'NormalizeObservations',    true, ...
    'NormalizeRewards',         false);

agent_opts.ActorOptimizerOptions  = rlOptimizerOptions('LearnRate', 3e-4);
agent_opts.CriticOptimizerOptions = rlOptimizerOptions('LearnRate', 1e-3);

agent = rlPPOAgent(actor, critic, agent_opts);

%% ── TRAINING OPTIONS ──────────────────────────────────────────────────────────
% Stage 1: normal operation (20k steps)
STAGE1_EPISODES = 200;
STAGE2_EPISODES = 500;
STAGE3_EPISODES = 1000;

train_opts = rlTrainingOptions(...
    'MaxEpisodes',              STAGE1_EPISODES, ...
    'MaxStepsPerEpisode',       2000, ...       % 2000 steps × 50µs = 0.1s
    'StopTrainingCriteria',     'AverageReward', ...
    'StopTrainingValue',        -5, ...          % Stop when avg reward > -5
    'ScoreAveragingWindowLength', 50, ...
    'SaveAgentCriteria',        'EpisodeReward', ...
    'SaveAgentValue',           -10, ...
    'SaveAgentDirectory',       '../data/models/drl', ...
    'Verbose',                  true, ...
    'Plots',                    'training-progress', ...
    'UseParallel',              false);

%% ── CURRICULUM TRAINING ───────────────────────────────────────────────────────
fprintf('\n=== STAGE 1: Normal load variation (0–%d episodes) ===\n', STAGE1_EPISODES);
env.ResetFcn = @(in) hpt_reset_fcn(in, 'stage', 1);
result_s1 = train(agent, env, train_opts);

fprintf('\n=== STAGE 2: Mode switching + step changes ===\n');
env.ResetFcn = @(in) hpt_reset_fcn(in, 'stage', 2);
train_opts.MaxEpisodes = STAGE1_EPISODES + STAGE2_EPISODES;
result_s2 = train(agent, env, train_opts);

fprintf('\n=== STAGE 3: Fault scenarios (full curriculum) ===\n');
env.ResetFcn = @(in) hpt_reset_fcn(in, 'stage', 3);
train_opts.MaxEpisodes = STAGE1_EPISODES + STAGE2_EPISODES + STAGE3_EPISODES;
train_opts.StopTrainingValue = -2;  % Higher performance target in final stage
result_s3 = train(agent, env, train_opts);

%% ── SAVE TRAINED AGENT ────────────────────────────────────────────────────────
agent_save_path = '../data/models/drl/hpt_ppo_agent_final.mat';
save(agent_save_path, 'agent', 'obs_info', 'act_info', 'W');
fprintf('\nFinal agent saved to: %s\n', agent_save_path);

%% ── EXPORT POLICY AS MATLAB FUNCTION ─────────────────────────────────────────
% This generates deployable MATLAB code for the Simulink controller block
policy_save_path = '../simulink/ppo_policy_deployed.m';
generatePolicyFunction(agent, 'PolicyFunctionName', 'ppo_policy_deployed', ...
    'MATLABFile', policy_save_path);
fprintf('Deployable policy exported to: %s\n', policy_save_path);

%% ── EVALUATION ───────────────────────────────────────────────────────────────
fprintf('\n=== Evaluating trained agent (50 episodes) ===\n');
sim_opts = rlSimulationOptions('MaxSteps', 4000, 'NumSimulations', 50);
experience = sim(env, agent, sim_opts);

rewards = cellfun(@(e) sum(e.Reward), experience);
fprintf('  Mean reward: %.2f ± %.2f\n', mean(rewards), std(rewards));
fprintf('  Min reward:  %.2f\n', min(rewards));
fprintf('  Max reward:  %.2f\n', max(rewards));

close_system(mdl, 0);


%% ═══════════════════════════════════════════════════════════════════════════
%% HELPER FUNCTIONS
%% ═══════════════════════════════════════════════════════════════════════════

function in = hpt_reset_fcn(in, varargin)
%% hpt_reset_fcn  Randomizes episode initial conditions per training stage.
% Inputs:  in    — SimulationInput object
%          stage — training stage (1, 2, or 3)

stage = 1;
for k = 1:2:length(varargin)
    if strcmp(varargin{k}, 'stage')
        stage = varargin{k+1};
    end
end

run('../simulink/parameters.m');

% Randomize load (all stages)
P_pct = 0.3 + 0.7*rand();
Q_pct = 0.0 + 0.5*rand();
in = setVariable(in, 'P_load', S_rated * P_pct);
in = setVariable(in, 'Q_load', S_rated * Q_pct);

% Randomize initial DC voltage
in = setVariable(in, 'V_dc_init', V_dc_ref * (0.95 + 0.1*rand()));

if stage >= 2
    % Randomize operating mode
    mode_choice = randi(3);
    in = setVariable(in, 'mode_init', mode_choice);

    % Step change time
    in = setVariable(in, 't_step', 0.5 + 0.3*rand());
    in = setVariable(in, 'P_step_factor', 0.5 + 1.0*rand());
end

if stage >= 3
    % Enable fault injection
    fault_type = randi(5);  % 1:igbt_sh, 2:igbt_se, 3:cap, 4:sc_1ph, 5:no_fault
    in = setVariable(in, 'fault_type_rl', fault_type);
    in = setVariable(in, 't_fault_rl', 0.8 + 0.4*rand());
end
end


function r = compute_reward(obs, W, I_pu, I_max_pu, eta)
%% compute_reward  Called from MATLAB Function block in Simulink.
% obs:     [V1_err V2_err Vdc_err Ish_d Ish_q Ise_d Ise_q P1_err Q1_err ...]
% I_pu:    converter current magnitude (pu)
% I_max_pu: max allowed current (1.0 pu)
% eta:     instantaneous efficiency estimate

V2_err  = obs(2);
Vdc_err = obs(3);
P1_err  = obs(8);
Q1_err  = obs(9);

% Penalty terms
r_voltage    = -W.alpha * (V2_err^2 + 0.5*Vdc_err^2);
r_power      = -W.beta  * (P1_err^2 + 0.5*Q1_err^2);
r_overcurrent = -W.gamma * max(0, I_pu - I_max_pu)^2;

% Efficiency bonus (only if operating well)
r_efficiency = W.delta * eta * (abs(V2_err) < 0.05);

r = r_voltage + r_power + r_overcurrent + r_efficiency;

% Terminal condition: severe fault → large negative reward
if abs(Vdc_err) > 0.5 || abs(V2_err) > 0.4
    r = r + W.fault;
end
end
