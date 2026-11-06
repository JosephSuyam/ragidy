# Ragidy

Chat with your files and links using Retrieval-Augmented Generation. LlamaIndex handles ingestion and retrieval, LangChain/LangGraph handles orchestration, and the UI is React with shadcn/ui.

## Requirements
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12+ (or 20.19+)
- Docker, for Postgres + pgvector and SeaweedFS
- `make` (optional; every target is a plain command in `Makefile`)
- [graphify](https://github.com/safishamsi/graphify) (optional): code knowledge graph for agents. See `docs/development/workflow.md`

## Setup
```bash
cp .env.example apps/api/.env   # then fill in the API keys; set S3_* to any random values (openssl rand -hex 20)
make install
make db
make migrate                    # apply DB migrations; needs make db
make s3                         # SeaweedFS S3 on :8333; needs S3_* in apps/api/.env
make api                        # http://localhost:8000/health
make web                        # http://localhost:5173; proxies /api/* to :8000
```

`make up` runs the full stack from production images instead (needs `S3_*` in `apps/api/.env`). Open http://localhost:8080: the web container serves the app and proxies `/api/*` to the API. Compose sets `PUBLIC_BASE_URL=http://localhost:8080` and `TRUSTED_PROXIES=10.80.80.10` for that stack, on a fixed `proxy` network `10.80.80.0/24`. If that subnet clashes with a local network or VPN (Docker reports `Pool overlaps with other one on this address space`), change the subnet, the web `ipv4_address` and `TRUSTED_PROXIES` together in `infrastructure/docker/docker-compose.yml`.

On Windows, `make api` (`fastapi dev`) works as is. Without reload (`fastapi run` or plain `uvicorn`), run `uvicorn app.main:app --loop asyncio:SelectorEventLoop --no-proxy-headers`. psycopg async refuses the default Proactor loop (ADR 0005), and `--no-proxy-headers` stops plain uvicorn from trusting `X-Forwarded-For` from 127.0.0.1 before `TRUSTED_PROXIES` applies.

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
- MVP roadmap: `docs/development/roadmap.md`
