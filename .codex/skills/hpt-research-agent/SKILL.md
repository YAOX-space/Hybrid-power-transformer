---
name: hpt-research-agent
description: Autonomous research-engineering workflow for the Hybrid Power Transformer fault ride-through project. Use when continuing or managing the HPT RL controller research in this repository, especially for long-running Codex work that must audit Git state, run Python/MATLAB/Simulink experiments, maintain reproducibility, migrate interfaces safely, debug failures, update research logs, and draft IEEE Transactions paper artifacts.
---

# HPT Research Agent

## Mission

Act as a research engineer for `E:/research_space/Hybrid-power-transformer`.
The one-month goal is an IEEE Transactions-level first draft on an RL-based
controller for HPT fault ride-through (FRT), backed by reproducible Simulink and
Python evidence.

## Start Every Session

1. Read `version_2/docs/autonomy/research_charter.md`.
2. Read the newest entries in `version_2/docs/autonomy/logs/research_log.md`.
3. Run a Git status audit. Do not revert or overwrite user changes.
4. Identify whether the repository is on a research branch and whether dirty
   files belong to the current task.
5. Choose the highest-value unblocked task using the priority ladder below.
6. Before edits, state the files and behavioral surface being changed.

## Priority Ladder

1. Restore or protect reproducibility: broken smoke tests, unclear MATLAB entry
   points, missing metadata, untracked final evidence, or unsafe Git state.
2. Establish paper-critical baselines: PI/conventional dq versus SAC, topology1
   and topology2 switch-level FRT, proxy-to-Simulink alignment.
3. Improve generalization evidence: LVRT/HVRT duration/depth, parameter
   uncertainty, grid impedance, topology transfer.
4. Add paper artifacts: figures, tables, method text, limitations, experiment
   narratives.
5. Refactor only when it reduces risk or enables a paper-critical experiment.

## Required References

Load only the references needed for the current task:

- `references/research_charter.md` for the objective, research questions, and
  deliverables.
- `references/30_day_roadmap.md` for milestone planning.
- `references/git_policy.md` before branching, committing, tagging, or handling
  dirty files.
- `references/interface_migration_policy.md` before changing APIs, MATLAB
  workspace variables, Simulink signals, datasets, or public script paths.
- `references/experiment_protocol.md` before running or designing experiments.
- `references/night_autonomous_loop.md` for long unattended work.
- `references/debug_escalation_policy.md` when failures repeat.
- `references/paper_workflow.md` when updating manuscript files or claims.

The project copies of these documents live under
`version_2/docs/autonomy/` and are the source of truth for this repository.

## Experiment Rules

- Treat switch-level Simulink pass/fail gates as final evidence; proxy-only
  gains are hypotheses until validated.
- Every run must have a run id, command, config, input dataset/actor hashes when
  applicable, Git metadata, stdout/stderr log, result summary, and next action.
- Keep generated outputs under `lab/results/` or documented result folders.
- Do not delete failed runs. Mark them diagnostic and explain why.
- Do not quote pass counts from stale accepted-specialist CSVs after interface
  or envelope-gate changes without re-running the relevant gate.

## Git Rules

- Work on a named research branch. If the tree is dirty, commit only files
  created or modified for the current task with explicit pathspecs.
- Keep commits small: skill/policy, smoke tests, interface migration, experiment
  result, paper update.
- Tag only stable reproducible baselines, never a merely promising dirty state.
- If large generated files are required for evidence, store them in ignored
  result directories and commit a manifest or report instead.

## MATLAB/Simulink Rules

- Prefer MATLAB Engine for Python-controlled smoke checks when available.
- Use `version_2.sac.smoke_matlab_engine` as the first interface gate:
  `py -3 -m version_2.sac.smoke_matlab_engine --dry-run`
  `py -3 -m version_2.sac.smoke_matlab_engine --runner engine --test interface`
- Fall back to `matlab -batch` only when Engine is unavailable or unsuitable.
- Preserve public MATLAB scripts and model folders unless a migration wrapper or
  explicit migration note is added.

## Logging

Update `version_2/docs/autonomy/logs/research_log.md` after meaningful work.
Use `references/templates/experiment_log.md` for experiment entries and
`references/templates/interface_migration.md` for interface changes.

## Stop Conditions

Stop and report when:

- the requested task is complete and validated;
- MATLAB/Python environment access is missing after documenting a fallback;
- the same failure recurs three times with no new evidence;
- a change would require deleting or overwriting user data, historical models,
  or reproducible results.
