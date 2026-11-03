---
name: fix-ci
description: Diagnose and repair a failing GitHub Actions run, then push the fix. Use for /fix-ci, "CI is red", or "fix the build". Also invoked by the ci-autofix workflow.
---

# /fix-ci [run-id]

1. Find the failure. If no run id was given, run `gh run list --branch "$(git branch --show-current)" --limit 5`, then `gh run view <id> --log-failed`. Read only the failing steps.
2. Reproduce it locally with the same command: `python scripts/check.py --backend` or `--frontend`.
3. Classify the cause:
   - **Code bug or test failure:** fix the root cause, using the `debugger` agent's method.
   - **Environment difference** (versions, OS, missing service or env var): fix the workflow or config, not the code.
   - **Flaky** (passes on rerun with no change): run `gh run rerun <id> --failed` once. If it is flaky again, fix the flakiness and do not rerun.
4. Run `python scripts/check.py` until it passes.
5. Commit with `fix(ci): <subject>` or the matching scope, then push.
6. Run `/lesson` with the root cause so the same failure does not happen again.
7. Report: the cause, the fix, and the commit sha.

Never disable a job, mark a step `continue-on-error`, or skip tests to turn CI green.
