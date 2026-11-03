---
name: rag-development
description: Build or change Ragidy's RAG pipeline - parsing, chunking, embedding, indexing, retrieval, reranking (LlamaIndex) and the agent workflow, memory, and tools (LangChain/LangGraph). Use for any work under apps/api/app/rag or apps/api/app/agents.
---

# RAG development

Read `docs/architecture/overview.md` first. It holds the pipeline, the boundary, and the self-healing rules.

## Ownership

| Stage | Library | Module | Agent |
|---|---|---|---|
| Ingest a file or URL, track status | LlamaIndex readers | `app/rag/ingestion` | `rag-engineer` |
| Parse PDF, DOCX, HTML | LlamaIndex readers | `app/rag/parsers` | `rag-engineer` |
| Chunk | LlamaIndex node parsers | `app/rag/chunking` | `rag-engineer` |
| Embed | Provider factory, then LlamaIndex embedding | `app/rag/embeddings` | `rag-engineer` |
| Index into pgvector | LlamaIndex `PGVectorStore` | `app/rag/indexing` | `rag-engineer` |
| Retrieve, rerank | LlamaIndex retrievers and postprocessors | `app/rag/retrieval`, `app/rag/reranking` | `rag-engineer` |
| Graph: retrieve, grade, rewrite, generate | LangGraph | `app/agents/workflows` | `agent-engineer` |
| Chat memory | LangGraph Postgres checkpointer | `app/agents/memory` | `agent-engineer` |
| Tools (retrieval tool, external APIs) | LangChain tools | `app/agents/tools` | `agent-engineer` |
| Graph state types | TypedDict or Pydantic | `app/agents/state` | `agent-engineer` |

## Rules
- **Boundary:** `app/rag/retrieval` returns `list[RetrievedChunk]` (text, score, metadata), which is plain data. LlamaIndex objects never leave `app/rag/`, and LangChain objects never enter it.
- **Providers:** LLMs and embeddings come only from `app/core/providers.py`. Never import a vendor SDK anywhere else.
- **Embedding model:** store `embed_model` with each document. Changing the model or its dimensions requires a re-index; never mix models in one query.
- **Chunking defaults:** use sentence-aware splitting at about 512 tokens with about 64 overlap. Keep page and section metadata for citations. Change these defaults only with a golden-set result showing the change is better.
- **Self-healing:** retry with backoff, fall back across providers, run the corrective-RAG loop (at most 2 query rewrites), and track ingestion status per document.
- **Grounding:** answers cite their chunks. Empty or low-relevance retrieval returns "not found in the document".
- **Long work:** ingesting a big file runs in `app/workers/`, never in the request handler.

## Evaluate a change
1. Run the golden-set retrieval test in `tests/fixtures/`. Hit@k must not drop.
2. Ask a few questions by hand through the API, and check the citations.
3. Report the chunk size, top-k, and hit@k before and after the change.
