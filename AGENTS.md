# Ragidy: agent guide

Shared rules for every coding agent (Claude Code, Codex, Cursor, and others). Claude-specific workflow is in `CLAUDE.md`.

Ragidy is a RAG web app. The user uploads a file or gives a URL, then chats with it.
Pipeline: **chunk → embed → index → retrieve → generate**.

## Stack
- **API:** Python 3.12, FastAPI, uv (`apps/api`)
- **Data and retrieval:** LlamaIndex (`app/rag`). It parses, chunks, and embeds documents and queries; vector search is SQL in `app/repositories/vector` (ADR 0006, ADR 0007).
- **Orchestration:** LangChain + LangGraph (`app/agents`). It handles workflows, conversational memory, tools, and state.
- **Store:** Postgres + pgvector, for vectors, documents, chat history (`messages` rows, ADR 0008), and the ingestion job queue (the `documents` row is the job, ADR 0002). SeaweedFS (any S3-compatible store in production) holds raw uploads and fetched URL content. Migrations use Alembic.
- **LLM and embeddings:** pluggable through env vars (`LLM_PROVIDER`, `LLM_MODEL`, `EMBED_PROVIDER`, `EMBED_MODEL`), resolved only in `app/core/providers.py`.
- **Web:** React + TypeScript (Vite), Tailwind CSS v4, shadcn/ui, oxlint, Vitest (`apps/web`)
- **CI/CD:** GitHub Actions, Docker images on GHCR
- **Users (MVP):** guests get a private, expiring cookie session with no account; registered users sign in with email + password or Google/GitHub OAuth. Upload limits, file types, and document caps are configurable per tier (ADR 0003, `docs/architecture/requirements.md`). `features/workspaces` stays a reserved placeholder.

**Hard rule:** LlamaIndex code lives only in `app/rag/`, and LangChain/LangGraph code lives only in `app/agents/`. Only plain data (`RetrievedChunk`: text, score, metadata) crosses between them. One exception: `app/core/providers.py` may import LangChain and LlamaIndex model classes only to construct them (ADR 0004). See `docs/architecture/overview.md`.

## Layout
```
apps/api/app/
  main.py            app factory, mounts routers
  api/routes/        thin HTTP handlers          api/middleware/  request middleware
  core/              config, providers, logging
  schemas/           Pydantic request and response models
  services/          use cases: routes → services → rag | agents | repositories | core
  repositories/      all DB queries              models/          SQLAlchemy models
  rag/               ingestion, parsers, chunking, embeddings, indexing, retrieval, reranking
  agents/            workflows (LangGraph), memory, tools, state
  workers/           background jobs (ingestion)
apps/api/{tests,alembic}/
apps/web/src/
  components/        ui/ (shadcn), chat/, documents/, layout/
  features/          chat/, upload/, sources/, workspaces/, authentication/
  routes/ services/ (API client) hooks/ types/ lib/
apps/web/tests/
packages/shared-types/   TypeScript types that mirror the API schemas
infrastructure/          docker/ (Dockerfiles, compose), database/ (init SQL), scripts/ (check.py)
tests/                   integration/, e2e/, fixtures/ (cross-app)
docs/                    architecture/, api/, development/, decisions/ (ADRs), sessions/
```
Empty folders hold a placeholder (`__init__.py` or `.gitkeep`) until their first code arrives.

## Commands
```bash
make install        # uv sync + npm install
make db             # Postgres + pgvector on :5432
make s3             # SeaweedFS S3 on :8333; needs S3_* in apps/api/.env
make migrate        # apply Alembic migrations; needs make db
make api            # API on :8000 (reload)
make worker         # ingestion worker; needs make db, make s3, make migrate
make web            # web on :5173
make check          # full quality gate; `make fast` skips integration tests
make up             # full stack from production images; needs S3_* in apps/api/.env
```
Without `make`, run the commands in `Makefile` directly. The gate is `python infrastructure/scripts/check.py [--api|--web] [--fast]`.
Code navigation: when `graphify-out/graph.json` exists, run `graphify query "<question>"` (or `path`, `explain`) before grepping or reading source, and `graphify update .` after code changes.
Add dependencies with `uv add` (in `apps/api`) or `npm install` (in `apps/web`).

## Conventions
- KISS, DRY, YAGNI: build the smallest change that fully solves the task.
- Layering: `api/routes` → `services`; `services` and `workers` (own process) → (`rag` | `agents` | `repositories` | `core`) → `models`. Routes never call `workers`. Nothing calls upward.
- Commits: `<type>(<scope>): <subject>`. Type is feature|fix|docs|style|refactor|test|chore|perf. The subject is imperative, 50 characters or fewer, with no period.
- Branches: `<type>/<short-name>` from `develop`, merged by PR into `develop`, then promoted by PR `develop` → `staging` → `main`. Never commit directly to `develop`, `staging`, or `main`.
- Never read or commit `.env` files or secrets.
- Tests: mock LLMs and embeddings at `app/core/providers.py`. Mark tests that need Postgres or network with `@pytest.mark.integration`.
- Every change passes `python infrastructure/scripts/check.py` before commit.
