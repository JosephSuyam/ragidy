# MVP roadmap

Build order for the MVP in `docs/architecture/requirements.md` (R1-R14). Status as of 2026-11-07.

1. Finalize system architecture: done (ADRs 0001-0003, `docs/architecture/overview.md`)
2. Define MVP requirements: done (`docs/architecture/requirements.md`, PR #6)
3. GitHub repo, CI and FastAPI + React scaffold: done (Pipeline, `/health`, Vite app)
4. First DB migration: done (PR #7: Alembic 0001 + 0002)
5. Providers and logging: done (PR #8, ADR 0004: `app/core/providers.py`, `app/core/logging.py`)
6. Guest session, owner lookup, `GET /me`: done (PR #9, ADR 0005: R1 AC4-6; AC1-3 close with steps 8 and 11-12)
7. Accounts: register, login, logout, Google/GitHub OAuth, guest-to-user migration (R2-R6): done (7a PR #10: password accounts; 7b PR #12: OAuth sign-in, R4)
8. Upload and URL ingestion with tier limits and caps (R7-R9): done (`POST /documents`, `POST /documents/url`: object storage + pending `documents` row)
9. Ingestion worker: parse, chunk, embed, index into pgvector; status and retry (R11): next
10. Retrieval and generation (corrective RAG); test RAG on its own
11. LangGraph chat: SSE answers with citations, history, per-hour limit (R12-R13)
12. Deletion and guest purge (R10, R14)
13. React frontend: auth, upload, document status/retry, chat, sources, `packages/shared-types`
14. Testing and deployment: SeaweedFS hardening, e2e, Linux `extra_hosts` for Ollama, promote `develop` → `staging` → `main`

Notes: ChromaDB replaced by pgvector (ADR 0001); LangChain lives in `app/agents` from the start (step 11).
