# Migration inventory + commit plan (2026-06-22 round-4, NOT committed)

Working-tree only; HEAD/index untouched (except 4 PRE-EXISTING staged renames, see below).

## Reconciliation with `git status`
```
git status --porcelain summary:
      254 D
        7 ??
        4 RD
        2 M

After rename detection (git add -A on a TEMP index):
      231 A
      158 D
        2 M
      100 R
```
- 2 modified tracked: .gitignore, README.md
- 7 untracked top-level trees: src/ lab/ docs/ tests/ references/ pyproject.toml requirements.txt
- 254 deletions = old frt_standard/ + emt/ paths (the 2026-06-21 restructure), 100 of which
  resolve to RENAMES (moves into docs/ + lab/) once `git add -A` runs.
- 4 PRE-EXISTING staged renames (frt_standard/simulink/*.m -> .../legacy/) were staged BEFORE
  this work and are left untouched. Unstage with: git restore --staged frt_standard/simulink

## Ignored build artifacts (verified not tracked)
  slprj/ codegen/ *.egg-info/ __pycache__/ .pytest_cache/ *.asv *.autosave *.slxc .venv/ data/ .codex/
  (lab/simulink/slprj + all __pycache__ removed from the tree this round; egg-info kept for editable install)

## Suggested grouped commits (run manually; NOT executed here)
```
# 1. repo restructure (the big move) — keep history via rename detection
git add -A docs/ lab/ references/ pyproject.toml requirements.txt
git add -u   # stage the frt_standard/ + emt/ deletions so renames are detected
git commit -m "repo: restructure to src/ lab/ docs/ tests/ (moves, rename-detected)"

# 2. frt-v2 criteria core (versioned envelope + min-support reactive + response)
git add src/hpt_frt/common/frt_v2.py src/hpt_frt/common/pu.py src/hpt_frt/common/sequence.py docs/FRT_SPEC.md
git commit -m "frt-v2: versioned envelope iface, min-support reactive, 5ms response, status model"

# 3. device pipeline + V2 envs + training entrypoints (default V2, --legacy, metadata)
git add src/hpt_frt/device/
git commit -m "device: frt_metrics completeness semantics; V2 env unified trip; train entrypoints default V2"

# 4. network governance (phasor screening quarantine + spotcheck fail-fast)
git add src/hpt_frt/network/ src/hpt_frt/network/results/simulink_cases/legacy_pre_audit/
git commit -m "network: quarantine phasor metrics; fill_spotcheck fail-fast on non-frt-v2 MATs"

# 5. MATLAB frt-v2 (guards, online detector, pu single-source, selfchecks)
git add lab/simulink/
git commit -m "matlab: frt_v2_guard/assert_metrics_version, frt_v2_hlc online detector, pu_selfcheck"

# 6. tests (regression for A-H)
git add tests/
git commit -m "tests: A-H regression (spotcheck/env/training/metrics/reactive/response/governance)"

# 7. docs governance + change report + this inventory
git add README.md docs/ .gitignore
git commit -m "docs: frt-v1 INVALIDATED governance, PENDING headline, migration inventory"
```
