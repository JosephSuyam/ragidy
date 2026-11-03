---
name: debugging
description: Find and fix the root cause of a bug, a failing test, or a red GitHub Actions run, then record the lesson. Use for /debug, "this is broken", "test fails", "CI is red", or "fix the build". The CI workflow's autofix job also invokes it.
---

# Debugging

The `debugger` agent follows this method. For non-trivial bugs, delegate to that agent.

## Local bug or failing test
1. **Reproduce.** Get a failing command or test. If you cannot reproduce the bug, stop and report what you tried.
2. **Hypothesize.** List up to 3 likely causes, ranked by evidence. Check the top one with logs, prints, or a minimal script.
3. **Fix the root cause** with the smallest change, in shared code. Grep every caller of the function you change.
4. **Regression test.** Add a test that fails without the fix. See the `test-generation` skill.
5. **Verify.** Run `python infrastructure/scripts/check.py` until it passes.
6. **Learn.** If the cause was non-obvious, record a lesson with the `documentation` skill.

## CI failure (`/debug ci [run-id]`)
1. Find the failure. If no run id was given, run `gh run list --branch "$(git branch --show-current)" --limit 5`, then `gh run view <id> --log-failed`. Read only the failing steps.
2. Reproduce it locally with the same command: `python infrastructure/scripts/check.py --api` or `--web`.
3. Classify the cause:
   - **Code bug or test failure:** fix it with the local method above.
   - **Environment difference** (versions, OS, missing service or env var): fix the workflow or config, not the code.
   - **Flaky** (passes on rerun with no change): run `gh run rerun <id> --failed` once. If it is flaky again, fix the flakiness and do not rerun.
4. Run `python infrastructure/scripts/check.py` until it passes.
5. Commit with `fix(ci): <subject>` or the matching scope, then push.
6. Record the root cause as a lesson with the `documentation` skill.
7. Report: the cause, the fix, and the commit sha.

## Never
- Weaken, skip, or delete a test to make it pass.
- Swallow an exception to hide a symptom.
- Disable a CI job or mark a step `continue-on-error`.
