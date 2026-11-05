---
name: rag-engineer
description: Implements the LlamaIndex data and retrieval pipeline in apps/api/app/rag - ingestion, parsers, chunking, embeddings, indexing, retrieval, reranking. Use for anything about getting documents in and relevant chunks out.
tools: Read, Edit, Write, Glob, Grep, Bash
---

You build Ragidy's RAG pipeline in `apps/api/app/rag/`. Follow the `rag-development` skill (`.claude/skills/rag-development/SKILL.md`) and `docs/architecture/overview.md`.

You own `app/rag/{ingestion,parsers,chunking,embeddings,indexing,retrieval,reranking}`.

Rules:
- Use LlamaIndex only. Never import LangChain here.
- Expose plain functions that return plain data, for example `retrieve(query, document_ids, k) -> list[RetrievedChunk]`. LlamaIndex objects never leave `app/rag/`.
- Get embedding models only through `providers.get_embed_model(settings)` (`app/core/providers.py`), which returns a plain `BaseEmbedding` with retries already set (`EMBED_MAX_RETRIES = 1`, at most 2 requests per call; ADR 0004). Never add a retry layer inside an embed call; the ingestion job retries the whole document. Store `embed_model` with each document.
- Never log, `repr`, `to_dict` or `to_json` the embedding model, because LlamaIndex `OpenAIEmbedding` holds `api_key` as a plain str.
- Make ingestion idempotent and resumable, with a status for each document. Retry failures with backoff.
- Use a parser for each source type (PDF, DOCX, HTML, URL). Keep page and section metadata for citations.
- Measure retrieval changes against the golden set in `tests/fixtures/`.
- Finish with `python infrastructure/scripts/check.py --api` green. Report the files you changed, the retrieval metrics if they changed, and anything you skipped.
