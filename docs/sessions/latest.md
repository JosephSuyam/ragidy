# Session summary (2026-11-03)

## Goal
Set up Ragidy's Claude Code dev workflow (no app features yet): CLAUDE.md, agents, hooks, skills, CI, self-annealing, session summaries.

## Done
- Workflow scaffold: CLAUDE.md, 5 agents, 7 skills, 4 hooks, scripts/check.py, CI + autofix workflows (b2198fb)
- Post-edit hook lints frontend through `npm run lint` (oxlint --deny-warnings) (77db366)
- Frontend scaffold: Vite 8, React 19, TS 7, Tailwind v4, shadcn (radix, nova preset), Vitest smoke test (87aab6e)
- Hooks verified by hand with piped JSON: post-edit exits 2 on lint errors; stop gate blocks 3 times then gives up; session start and end round-trip

## Next steps
1. Merge `chore/frontend-scaffold` into `main` (no remote yet, so no PR).
2. When the user is ready: `gh repo create ragidy --private --source . --push`, then add the `ANTHROPIC_API_KEY` secret for ci-autofix.
3. Start the MVP with `/ship`: provider factory, then ingestion, then retrieval, then the LangGraph agent, then the upload and chat UI.

## Decisions
- LLM and embeddings are pluggable through env vars; the store is Postgres + pgvector; Python FastAPI with uv; single user, no auth; CI only, no deploy yet.
- Review uses the plugins (/ponytail-review, /security-review). There is no custom reviewer agent.
- The frontend lints with oxlint (the Vite template default), not ESLint.
- Runtime self-healing rules are documented in docs/architecture.md and get implemented in the MVP.

## Open questions
- GitHub repo visibility, and when to create it (the user said "not yet").

Branch: chore/frontend-scaffold | Uncommitted: 0 | PR: none | CI: not run (no remote)
