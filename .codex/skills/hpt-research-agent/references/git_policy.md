# Git Policy

- Start from `git status --short --branch`.
- Never revert user changes unless explicitly requested.
- Create or reuse a named branch for long research work.
- Commit only task-owned files with explicit pathspecs.
- Use commit messages in this style:
  `Add HPT autonomy charter`
  `Add MATLAB Engine smoke runner`
  `Record topology1 baseline smoke`
- Do not commit generated caches, `slprj/`, `*.slxc`, `__pycache__/`, or large
  result payloads.
- Commit reports, manifests, configs, scripts, and small summary CSVs that make
  ignored result directories interpretable.
- Tag only after a smoke test or baseline is demonstrably reproducible.
