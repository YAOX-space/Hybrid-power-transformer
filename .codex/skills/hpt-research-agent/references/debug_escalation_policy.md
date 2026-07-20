# Debug Escalation Policy

Level 1: local fault.

- Syntax error, missing import, wrong path, stale cache, obvious MATLAB path
  issue. Fix and retry once.

Level 2: contract fault.

- Observation/action dimensions, dataset fields, Simulink logged signal names,
  or metadata schema mismatch. Add/repair tests and migration notes.

Level 3: model or scientific fault.

- Proxy and switch-level disagree, DC-link collapses, current limit fails, or
  baseline wins. Preserve artifacts, write failure analysis, and design a
  narrower experiment.

Level 4: blocked.

- Missing MATLAB/Engine/license/toolbox, repeated solver failure, or ambiguous
  research decision. Record exact command, logs, environment, attempted fixes,
  and the smallest user decision needed.
