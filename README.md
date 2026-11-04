# Ragidy

Chat with your files and links using Retrieval-Augmented Generation. LlamaIndex handles ingestion and retrieval, LangChain/LangGraph handles orchestration, and the UI is React with shadcn/ui.

## Requirements
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12+ (or 20.19+)
- Docker, for Postgres + pgvector
- `make` (optional; every target is a plain command in `Makefile`)
- [graphify](https://github.com/safishamsi/graphify) (optional): code knowledge graph for agents. See `docs/development/workflow.md`

## Setup
```bash
cp .env.example apps/api/.env   # then fill in the API keys
make install
make db
make api                        # http://localhost:8000/health
make web                        # http://localhost:5173
```

## Quality gate
```bash
make check   # lint, format, typecheck, all tests (needs `make db`)
make fast    # same, without integration tests
```

## Repository layout
- `apps/api`: FastAPI service (RAG in `app/rag`, agents in `app/agents`)
- `apps/web`: React app
- `packages/shared-types`: TypeScript types shared with the API
- `infrastructure`: Dockerfiles, compose, DB init, the gate script
- `tests`: cross-app integration, e2e, and fixtures
- `docs`: architecture, API, development guide, ADRs, session summaries

## More
- Contributing: `CONTRIBUTING.md`
- Agent and Claude Code workflow: `AGENTS.md`, `CLAUDE.md`, `docs/development/workflow.md`
- Architecture: `docs/architecture/overview.md`, diagrams in `docs/architecture/diagrams.md`
