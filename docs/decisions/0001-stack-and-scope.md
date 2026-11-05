# 0001: Stack and initial scope

- Status: accepted
- Date: 2026-11-03
- Amended: 2026-11-04 (delivery: branch flow and tree-hash promotion)
- Amended: 2026-11-04 (store: raw files in object storage, see 0002)
- Amended: 2026-11-04 (users: guest and registered tiers, see 0003)
- Amended: 2026-11-05 (library split: providers exception, see [0004](0004-provider-factory.md))
- Amended: 2026-11-05 (store: async request DB access, see [0005](0005-request-db-access.md))

## Context
Ragidy lets a user upload a file or link and chat with it through RAG. We need to pick the stack and keep the first scope small.

## Decision
- **API:** Python 3.12 + FastAPI + uv. The Python LlamaIndex and LangChain are more mature than their JS ports (PDF parsing, retrievers, LangGraph).
- **Library split:** LlamaIndex for data and retrieval (`app/rag`), and LangChain/LangGraph for orchestration and memory (`app/agents`). Only plain data crosses the boundary.
- **Store:** Postgres + pgvector, one database for vectors, documents, chat history, and LangGraph checkpoints.
- **Providers:** LLM and embedding providers are chosen through env vars and resolved in one factory (`app/core/providers.py`).
- **Web:** React + TypeScript + Vite, Tailwind v4, shadcn/ui (radix, nova preset), oxlint, and Vitest.
- **Users:** single user, no auth. `features/authentication` and `features/workspaces` exist as empty placeholders for later.
- **Delivery:** GitHub Actions (`pipeline.yml`) and GHCR. Branches flow `develop` → `staging` → `main` through PRs. A push to `staging` builds images tagged `tree-<git tree hash>` and deploys staging. A push to `main` promotes the same images to production without a rebuild, because the merge keeps the tree. Version tags only mark releases and do not deploy. The hosting target is not chosen yet.

## Alternatives
- Node/TypeScript end to end: one language, but fewer loaders and retrievers.
- Chroma or Qdrant: simpler or more specialized, but they need a second store for chat history.
- Auth from day one: not needed for a single-user MVP.

## Consequences
- Changing the embedding model requires a re-index, so `embed_model` is stored with each document.
- The deploy workflows build and promote images but do not deploy them anywhere until a host is chosen.
