# Interface Migration Policy

Protected interfaces:

- Python module entry points under `version_2.sac.*`.
- MATLAB scripts under `version_2/simulink/{tests,evaluators,collectors,sweeps}`.
- Simulink workspace variables prefixed `hpt_`.
- SAC observation/action contract: 24-D observation and 4-D action unless a
  migration plan updates all producers, consumers, tests, exports, and docs.
- Dataset fields that distinguish command (`cmd_m_*`, `raw_m_*`) from measured
  response (`meas_*`).

Migration steps:

1. Write the reason and affected files.
2. Add a wrapper or compatibility path only when backward compatibility is
   required by the user or by active scripts.
3. Update smoke tests before removing old assumptions.
4. Record old name, new name, reason, validation, and rollback in
   `version_2/docs/autonomy/migration_notes.md`.
5. Re-run proxy alignment and switch-level gate when observations, actions,
   reward, envelope metrics, or Simulink outputs change.
