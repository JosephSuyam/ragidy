---
name: pr
description: Push the current branch and open a GitHub pull request filled from the PR template. Use for /pr, "open a PR", or "create pull request".
---

# /pr

1. Confirm the branch is not `main` and the working tree is clean. If it is not clean, run `/commit` first.
2. Confirm `python scripts/check.py` passes.
3. Run `git push -u origin HEAD`.
4. Run `gh pr create --base main --title "<type>(<scope>): <subject>" --body-file <file>`. Write the body from `.github/pull_request_template.md`, filled with:
   - Summary: what changed and why, in 1-3 bullets.
   - How tested: the commands you ran and the tests you added.
   - Risks: what could break, any migrations, any new env vars.
   - Linked issues.
5. Return the PR URL. Then run `gh pr checks --watch` and run `/fix-ci` if any check fails.
