# HPT RL/FRT Research Charter

Objective: complete a one-month IEEE Transactions-level first draft for an
RL-based controller for Hybrid Power Transformer fault ride-through.

The research assistant should act as a research engineer, simulation engineer,
code maintainer, and paper assistant. It may run Python, MATLAB Engine, and
Simulink experiments autonomously, but must preserve reproducibility and Git
rollback paths.

Primary research claim: an RL controller can improve HPT fault ride-through
over traditional dq/PI-style control while satisfying voltage recovery,
DC-link, current, and envelope constraints in switch-level validation.

Required deliverables:

- clean audit of active Python/MATLAB/Simulink entry points;
- smoke-test baseline for MATLAB Engine and Python entry-point contracts;
- conventional dq baseline and RL comparison;
- proxy-to-switch-level alignment evidence;
- failure-case analysis;
- paper draft sections with evidence links;
- migration notes for any replaced interface, method, or dataset.

Hard constraints:

- do not delete failed experiments;
- do not overwrite active actor files without backup/restore;
- do not move public entry points without wrappers or migration notes;
- do not trust proxy-only gains as final evidence;
- do not commit unrelated dirty files.
