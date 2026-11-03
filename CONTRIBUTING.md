# Contributing

## Setup
Follow `README.md`: copy `.env.example` to `apps/api/.env`, then run `make install` and `make db`.

Optional, for coding agents: install graphify (`uv tool install graphifyy`), then run `graphify update .` to build the code graph in `graphify-out/` (gitignored) and `graphify hook install` to rebuild it on each commit.

## Workflow
1. Open or pick an issue. Bugs and features use the templates in `.github/ISSUE_TEMPLATE`.
2. Branch from `main`: `git switch -c <type>/<short-name>`.
3. Make the change. Add a test for each behavior.
4. Run `make check`. It must pass.
5. Commit as `<type>(<scope>): <subject>`:
   - type: feature, fix, docs, style, refactor, test, chore, or perf
   - subject: imperative mood, 50 characters or fewer, no period
   - Keep each commit atomic.
6. Open a PR against `main` using the template. CI (`ci.yml`), Tests (`tests.yml`), and Security (`security.yml`) must be green.

## Rules
- LlamaIndex code stays in `apps/api/app/rag/`, and LangChain/LangGraph code stays in `apps/api/app/agents/`.
- Schema changes ship as reversible Alembic migrations.
- New env vars go in `.env.example`. New endpoints go in `docs/api/`. Design decisions with trade-offs go in an ADR in `docs/decisions/`.
- Never commit secrets. The Security workflow scans for them.

## Releases
Merging to `main` deploys to staging. Pushing a `vX.Y.Z` tag promotes the same images to production. See `.claude/skills/release-management/SKILL.md`.

## Working with Claude Code
See `CLAUDE.md` and `docs/development/workflow.md`. Start with `/start`, plan with `/plan`, build with `/implement`, and end with `/summarize`.
