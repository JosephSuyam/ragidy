---
name: commit
description: Create atomic git commits in Ragidy's format `<type>(<scope>): <subject>`. Use for /commit, "commit this", or "commit the changes".
---

# /commit

1. Run `git status` and `git diff`. Group the changes into atomic commits, one concern each. Split unrelated changes.
2. For each group, stage only its files (`git add <paths>`), then commit.
3. Message format: `<type>(<scope>): <subject>`
   - type: `feature` | `fix` | `docs` | `style` | `refactor` | `test` | `chore` | `perf`
   - scope: the area, for example `backend`, `frontend`, `ingestion`, `retrieval`, `agent`, `chat`, `upload`, `ci`, `workflow`
   - subject: imperative mood, 50 characters or fewer, no period
   - For a small change, write one line. For a complex change, add a body wrapped at 72 characters that explains what and why, and reference issues (`Refs #12`).
4. Never commit `.env` files, secrets, or `.claude/sessions/`. Never use `--no-verify`.
5. Do not commit on `main`. Create a branch first if you are on `main`.
6. Report each commit as `<sha> <subject>`.
