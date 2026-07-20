# HPT Research Log

## 2026-07-21 - Autonomy skill bootstrap

- Branch: `research/hpt-autonomy-skill`
- Scope: repository audit, project skill creation, autonomy policies, MATLAB
  Engine smoke runner, and dry-run baseline.
- Findings:
  - Git root is `E:/research_space/Hybrid-power-transformer`.
  - `version_2` is a subworkspace inside a dirty research branch.
  - Active Python entry points are concentrated under `version_2.sac`.
  - MATLAB/Simulink smoke scripts already exist under `version_2/simulink/tests`.
  - The existing SAC contract is 24-D observation / 4-D action.
- Decision: create only additive files and commit with explicit pathspecs.
- Validation:
  - Skill structure validation passed.
  - `py -3 -m version_2.sac.smoke_matlab_engine --dry-run` passed.
  - `py -3 -m pytest tests/test_hpt_v2_smoke_runner.py -q` passed.
  - MATLAB Engine mode failed because the active Python environments do not
    have the `matlab` module installed.
  - `py -3 -m version_2.sac.smoke_matlab_engine --runner batch --test interface`
    passed in about 93 s, confirming the topology1/topology2 24-D observation
    and 4-D action Simulink interface regression.
- Follow-up:
  - Install/configure MATLAB Engine for the project Python environment.
  - Investigate non-blocking MATLAB model-name shadowing warnings for
    `hpt_v2_1to1_switchlevel` and `hpt_v2_topology2_paper`.
