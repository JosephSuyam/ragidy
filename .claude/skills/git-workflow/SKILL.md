---
name: git-workflow
description: Branch, commit, push, and open a pull request for Ragidy. Commits use the format `<type>(<scope>): <subject>`. Use for "commit this", "open a PR", "push", or "create pull request", and as the commit and PR steps of feature-development.
---

# Git workflow

## Branch
- Branch from an up-to-date `develop`: `git switch develop && git pull && git switch -c <type>/<short-name>`.
- Never commit directly to `develop`, `staging`, or `main`.

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
3. Run `gh pr create --base develop --title "<type>(<scope>): <subject>" --body-file <file>`. Write the body from `.github/pull_request_template.md`, filled with:
   - Summary: what changed and why, in 1-3 bullets.
   - How tested: the commands you ran and the tests you added.
   - Risks: what could break, any migrations, any new env vars.
   - Linked issues.
4. Return the PR URL. PRs trigger no CI, so checks run after the merge.
5. When the user approves, merge with `gh pr merge <n> --merge --delete-branch`. Then watch the run: `gh run list --workflow pipeline.yml --branch develop --limit 1`, then `gh run watch <id>`. If it is red, follow the `debugging` skill's CI section.

## Promote
Promote `develop` → `staging` → `main`, one PR per step. Each merge runs `Pipeline` once. See `docs/development/workflow.md`.
1. Run `gh pr create --base staging --head develop --title "chore(release): promote develop to staging" --body "<changes>"`.
2. When the user approves, merge with `gh pr merge <n> --merge`. Use merge commits, and never pass `--delete-branch`, because `develop` and `staging` must stay.
3. Watch the run: `gh run list --workflow pipeline.yml --branch staging --limit 1`, then `gh run watch <id>`. It builds the images and deploys staging.
4. When staging is green, repeat with `--base main --head staging`. The merge to `main` deploys production.
