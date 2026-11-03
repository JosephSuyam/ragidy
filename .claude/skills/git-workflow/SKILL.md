---
name: git-workflow
description: Branch, commit, push, and open a pull request for Ragidy. Commits use the format `<type>(<scope>): <subject>`. Use for "commit this", "open a PR", "push", or "create pull request", and as the commit and PR steps of feature-development.
---

# Git workflow

## Branch
- Branch from an up-to-date `main`: `git switch main && git pull && git switch -c <type>/<short-name>`.
- Never commit directly to `main`.

## Commit
1. Run `git status` and `git diff`. Group the changes into atomic commits, one concern each. Split unrelated changes.
2. For each group, stage only its files (`git add <paths>`), then commit.
3. Message format: `<type>(<scope>): <subject>`
   - type: `feature` | `fix` | `docs` | `style` | `refactor` | `test` | `chore` | `perf`
   - scope: `api`, `web`, `rag`, `agents`, `db`, `chat`, `upload`, `ci`, `infra`, `workflow`, `docs`
   - subject: imperative mood, 50 characters or fewer, no period
   - For a small change, write one line. For a complex change, add a body wrapped at 72 characters that explains what and why, and reference issues (`Refs #12`).
4. Never commit `.env` files or secrets. Never use `--no-verify`.
5. Report each commit as `<sha> <subject>`.

## Pull request
1. Confirm the working tree is clean and `python infrastructure/scripts/check.py` passes.
2. Run `git push -u origin HEAD`.
3. Run `gh pr create --base main --title "<type>(<scope>): <subject>" --body-file <file>`. Write the body from `.github/pull_request_template.md`, filled with:
   - Summary: what changed and why, in 1-3 bullets.
   - How tested: the commands you ran and the tests you added.
   - Risks: what could break, any migrations, any new env vars.
   - Linked issues.
4. Return the PR URL. Then run `gh pr checks --watch`. If any check fails, follow the `debugging` skill's CI section.
