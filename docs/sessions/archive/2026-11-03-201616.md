# Session summary (2026-11-03 17:00)

## Goal
Restructure the repo into the user's monorepo layout (apps/, packages/, infrastructure/, docs/ tree), moving existing files rather than recreating them, and fill in the new agents, skills, commands, and workflows.

## Done
- Moved backend → apps/api, frontend → apps/web, check.py → infrastructure/scripts, compose → infrastructure/docker, hook logic → .claude/hooks/scripts behind .sh wrappers (a01f700)
- Renamed and merged the skills and agents. Added 8 agents, 5 skills, and 8 commands (543de01)
- Added Dockerfiles, DB init SQL, and the Makefile (6cfbfc3)
- Split CI into ci (with an autofix job), tests, security, deploy-staging, and deploy-production. Added issue templates (ca7c88a)
- Wrote AGENTS.md (shared rules), CLAUDE.md (Claude-specific), CONTRIBUTING, docs/{api,development,decisions}, ADR 0001
- `python infrastructure/scripts/check.py` is green, and pip-audit is clean

## Next steps
1. Merge `refactor/monorepo-layout`, which contains `chore/frontend-scaffold`, into `main`.
2. When the user is ready: `gh repo create`, push, add the `ANTHROPIC_API_KEY` secret, and create the `staging` and `production` environments (add an approval rule on production).
3. Pick a hosting target, then replace the placeholder deploy steps in the deploy-*.yml files.
4. Start the MVP with `/plan`: the provider factory, then ingestion, then retrieval, then the LangGraph workflow, then the upload and chat UI.

## Decisions
- AGENTS.md holds the tool-agnostic rules, and CLAUDE.md imports it. This avoids duplicating them.
- Skills hold the procedures. Commands and agents only point to them.
- ci-autofix.yml was merged into ci.yml as the `autofix` job, so the workflow list matches the requested layout.
- Production promotes the staging `sha-<sha>` image and never rebuilds.
- Auth and workspaces are placeholders only; the app is still single user (ADR 0001).

## Open questions
- Hosting target for staging and production.
- The project skill `code-review` shares its name with the built-in `/code-review`. Confirm which one runs, or rename it.

## Not verified
- Docker image builds: the Docker daemon was not running.
- All GitHub workflows: there is no remote yet.

Branch: refactor/monorepo-layout | PR: none | CI: not run (no remote)
