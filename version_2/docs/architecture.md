# Version 2 Architecture

## Purpose

The version-2 stack connects Python RL/proxy tooling with switch-level
MATLAB/Simulink HPT validation.

## Main Components

- Python package entry points live under `version_2.sac`.
- Proxy environment and controller contracts live in
  `version_2/sac/hpt_voltage_sac_env.py`.
- Experiment metadata helpers live in `version_2/sac/experiment_metadata.py`.
- Switch-level models and MATLAB scripts live under `version_2/simulink`.
- MATLAB smoke and regression scripts live under `version_2/simulink/tests`.
- Long-run results should be written under `lab/results`.

## Controller Contract

The current SAC interface is a 24-D observation and 4-D action contract. The
MATLAB regression `version_2/simulink/tests/test_hpt_v2_sac_interface.m`
checks this contract for topology1 and topology2.

Any change to this contract must update Python producers, MATLAB consumers,
actor export, Simulink tests, docs, and migration notes in one traceable unit.

## Reproducibility Contract

Long-running experiments must record:

- command and configuration;
- Git branch, commit, and dirty state;
- input dataset or trajectory path;
- actor/model hashes where applicable;
- summary metrics and failure reason;
- next action.
