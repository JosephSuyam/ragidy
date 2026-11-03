# Ragidy

Chat with your files and links using Retrieval-Augmented Generation. LlamaIndex handles ingestion and retrieval, LangChain/LangGraph handles orchestration, and the UI is React with shadcn/ui.

## Requirements
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12+ (or 20.19+)
- Docker, for Postgres + pgvector

## Setup
```bash
cp .env.example backend/.env           # then fill in the API keys
docker compose up -d db
cd backend && uv sync && uv run fastapi dev app/main.py
cd frontend && npm install && npm run dev
```

## Quality gate
```bash
python scripts/check.py            # everything
python scripts/check.py --backend  # or --frontend, --fast
```

## Development workflow
This repo is set up for Claude Code. See `CLAUDE.md` for the agents, skills (`/ship`, `/check`, `/commit`, `/pr`, `/fix-ci`, `/lesson`, `/handoff`), and the self-annealing hooks. Architecture: `docs/architecture.md`.
