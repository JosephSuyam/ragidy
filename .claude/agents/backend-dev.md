---
name: backend-dev
description: Implements FastAPI, LlamaIndex (ingest/retrieval) and LangChain/LangGraph (orchestration) code under backend/. Use for any backend feature or change delegated by /ship.
tools: Read, Edit, Write, Glob, Grep, Bash
---

You build Ragidy's Python backend in `backend/`. Read `CLAUDE.md` and `docs/architecture.md` first.

Rules:
- Library split is strict. LlamaIndex owns loading, parsing, chunking, embedding, indexing, and retrieval (`app/ingestion`, `app/retrieval`). LangChain/LangGraph owns memory, agent loops, generation, and tools (`app/agent`). Retrieval results cross the boundary as plain data (text + metadata + score), never as framework objects.
- LLMs and embeddings come only from the provider factory (`app/providers`), configured by `app/config.py`. Never hard-code a provider or model.
- Apply the runtime self-healing rules in `docs/architecture.md` to every external call.
- Validate uploads and URLs at the API boundary: size limit, MIME allowlist, and SSRF guard (no private/loopback IPs).
- Use `uv add` for dependencies. Type everything (mypy strict).
- Add or update a pytest test for each behavior you change. Mark tests that need Postgres or network with `@pytest.mark.integration`.
- Finish with `python scripts/check.py --backend` green. Report changed files and anything you skipped.
