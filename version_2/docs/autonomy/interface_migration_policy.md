# Interface Migration Policy

Protected interfaces:

- Python module paths under `version_2.sac`.
- MATLAB scripts under `version_2/simulink`.
- Simulink workspace variables prefixed `hpt_`.
- SAC 24-D observation / 4-D action contract.
- Dataset fields separating command and measured response semantics.

Before replacing an old interface:

1. Record old and new names in `migration_notes.md`.
2. Add wrappers or compatibility routes when possible.
3. Update tests before removing old assumptions.
4. Re-run MATLAB/Python smoke gates.
5. Re-run proxy and switch-level validation if observations, actions, reward,
   envelope metrics, logged signals, or actor export formats changed.
