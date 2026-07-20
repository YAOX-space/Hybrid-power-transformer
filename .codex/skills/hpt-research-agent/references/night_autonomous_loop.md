# Night Autonomous Loop

Loop:

1. Audit Git and read the research log.
2. Pick one task from the priority ladder.
3. Make the smallest useful change or launch the smallest useful experiment.
4. Run a smoke test or dry-run before long execution.
5. If a failure occurs, diagnose once from logs, fix once, retry once.
6. If the second retry fails, write an escalation note and choose a lower-risk
   task.
7. Update the research log and commit task-owned source/docs changes.
8. Continue while new evidence is being produced.

Never let an overnight loop:

- overwrite active actor MAT files without backup/restore;
- delete failed result folders;
- change public interfaces without migration notes;
- keep retrying the same failing command without a new hypothesis.
