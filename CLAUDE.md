# Ragidy

A RAG web app. The user uploads a file or gives a URL, then chats with it.
Pipeline: **chunk → embed → index → retrieve → generate**. Single user, no auth.

## Stack
- **Backend:** Python 3.12, FastAPI, uv (`backend/`)
- **Data and retrieval:** LlamaIndex. It loads, parses (PDF and HTML), chunks, embeds, indexes, and retrieves.
- **Orchestration:** LangChain + LangGraph. It handles conversation memory, agent loops, generation, and external tools.
- **Store:** Postgres + pgvector, for vectors, documents, chat history, and LangGraph checkpoints.
- **LLM and embeddings:** pluggable through env vars (`LLM_PROVIDER`, `LLM_MODEL`, `EMBED_PROVIDER`, `EMBED_MODEL`). See `.env.example`.
- **Frontend:** React + TypeScript (Vite), Tailwind CSS v4, shadcn/ui, oxlint, Vitest (`frontend/`)
- **CI:** GitHub Actions (`.github/workflows/`). There is no deploy job yet; add one as a `deploy` job in `ci.yml` that runs on `main` after `backend` and `frontend` pass.

The library split is strict. LlamaIndex returns retrieval results as plain data (text, metadata, score), and LangChain consumes them. Never mix the two roles. Details: `docs/architecture.md`.

## Module map
```
backend/app/
  main.py        FastAPI app, routers mounted here
  config.py      Settings from env (pydantic-settings)
  api/           HTTP routers: documents, chat            (planned)
  providers/     LLM and embedding factory from config    (planned)
  ingestion/     LlamaIndex: load, parse, chunk, embed, index (planned)
  retrieval/     LlamaIndex: retrievers, rerankers        (planned)
  agent/         LangGraph: graph, memory, tools          (planned)
  db/            Postgres and pgvector access             (planned)
backend/tests/   pytest, mirroring app/
frontend/src/
  components/ui/ shadcn generated components
  features/      upload/, chat/, documents/               (planned)
  lib/           utils.ts; api.ts for all backend calls  (planned)
scripts/check.py the single quality gate (hooks, /check, and CI all use it)
```
Create a planned folder when its first code arrives, not before.

## Commands
```bash
docker compose up -d db                      # Postgres + pgvector on :5432
cd backend && uv sync && uv run fastapi dev app/main.py   # API on :8000
cd frontend && npm install && npm run dev    # UI on :5173
python scripts/check.py [--backend|--frontend] [--fast]  # lint, types, tests
```
Add Python dependencies with `uv add` (or `uv add --dev`), and Node dependencies with `npm install`.

## Conventions
- KISS, DRY, YAGNI. Build the smallest change that fully solves the task. The ponytail plugin is enabled for this project.
- Commits: `<type>(<scope>): <subject>`. Type is feature|fix|docs|style|refactor|test|chore|perf. The subject is imperative, 50 characters or fewer, with no period. Use `/commit`.
- Branch from `main` as `<type>/<short-name>`. Never commit directly to `main`.
- Never read or commit `.env` files or secrets.
- Mark tests that need Postgres or network with `@pytest.mark.integration`. Mock LLMs and embeddings at `app/providers` in unit tests.

## Workflow
Use `/ship <task>` for features. It runs: clarify → branch → delegate → `/check` → review → docs → `/commit` → `/pr` → CI → `/handoff`.

| Need | Use |
|---|---|
| Backend code | `backend-dev` agent |
| UI code | `frontend-dev` agent |
| Tests | `test-writer` agent |
| Bug or failing test | `debugger` agent |
| Docs update | `docs-writer` agent |
| Code review | `/ponytail-review`, plus `/security-review` for uploads, URLs, the DB, or secrets |
| Whole-repo audit | `/ponytail-audit` |
| Deferred shortcuts | `/ponytail-debt` |
| Quality gate | `/check` |
| Red CI | `/fix-ci` |

## Self-annealing
1. **Hooks fix as you go.** After each edit, `post_edit.py` formats and lints the file. Before you stop, `stop_gate.py` runs `check.py --fast`. If either reports errors, fix the root cause. Never weaken, skip, or delete a test, and never add a blanket ignore.
2. **Lessons.** After a non-obvious bug, a gate failure that took more than one try, or a user correction, run `/lesson`.
3. **CI.** When CI fails, run `/fix-ci`. In GitHub, `ci-autofix.yml` runs it automatically on non-main branches when the `ANTHROPIC_API_KEY` secret is set.
4. **Runtime.** App code must follow the self-healing rules in `docs/architecture.md`: retries, provider fallbacks, corrective RAG, and ingestion status.

## Sessions
- At startup, the SessionStart hook loads `.claude/sessions/LATEST.md`, the git state, and the lesson count. Read it and continue from "Next steps".
- When the user says they are done, or asks to wrap up or save, run `/handoff`. The SessionEnd hook writes a git-only fallback summary when `/handoff` was not run.

## Lessons learned
@.claude/LESSONS.md
