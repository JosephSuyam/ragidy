# Architecture

## Pipeline

```mermaid
flowchart LR
  src["upload / URL"] --> ingest["Ingestion: LlamaIndex<br/>Load (app/rag/ingestion)<br/>Parse (app/rag/parsers)<br/>Chunk (app/rag/chunking)<br/>Embed (app/rag/embeddings)<br/>Index (app/rag/indexing)<br/>Status (app/workers)"] --> pg[("pgvector")]
  q["question"] --> agent["Agent: LangGraph (app/agents/workflows)<br/>Memory (app/agents/memory)"] --> retrieve["Retrieve: LlamaIndex (app/rag/retrieval, app/rag/reranking)"] --> grade{"grade_chunks (app/agents/workflows)"} --> generate["Generate (app/agents/workflows)"] --> out["streamed answer + citations"]
  grade -->|"rewrite_query (app/agents/workflows)"| retrieve
```

More diagrams: [diagrams.md](diagrams.md).

| Stage | Owner | Module |
|---|---|---|
| Ingest a file or URL, track status | LlamaIndex readers + `app/workers` | `app/rag/ingestion` |
| Parse (PDF, DOCX, HTML) | LlamaIndex readers | `app/rag/parsers` |
| Chunk | LlamaIndex node parsers | `app/rag/chunking` |
| Embed | Provider factory, then LlamaIndex embedding | `app/rag/embeddings` |
| Index | LlamaIndex `PGVectorStore` | `app/rag/indexing` |
| Retrieve, rerank | LlamaIndex retrievers and postprocessors | `app/rag/retrieval`, `app/rag/reranking` |
| Workflow: grade, rewrite, generate | LangGraph + LangChain chat models | `app/agents/workflows` |
| Memory | LangGraph Postgres checkpointer | `app/agents/memory` |
| Tools, state | LangChain tools, typed state | `app/agents/tools`, `app/agents/state` |
| Model selection | Provider factory reading `Settings` | `app/core/providers.py` |

**Boundary:** `app/rag/retrieval` returns `list[RetrievedChunk]`, where each item holds `text`, `score` and `metadata` (source, page, document_id). `app/agents` wraps retrieval as a tool or graph node. LlamaIndex objects never leave `app/rag/`.

**Layering:** `api/routes` → `services` → (`rag` | `agents` | `repositories`) → `models`. Nothing calls upward.

## Providers
`app/core/providers.py` builds the LLM and the embedding model from `LLM_PROVIDER`/`LLM_MODEL` and `EMBED_PROVIDER`/`EMBED_MODEL`. It is the only place that imports vendor SDKs.

**Constraint:** changing the embedding model or its dimensions requires a re-index. Store `embed_model` with each document and refuse to query across mismatched models.

## Runtime self-healing rules
Every piece of app code must follow these rules.

1. **Retry transient failures.** Wrap LLM and embedding calls with `.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)`. Retry only on timeouts, 429 and 5xx responses, never on 4xx validation errors.
2. **Fall back across providers.** When a second provider is configured, build the chat model as `primary.with_fallbacks([secondary])`.
3. **Corrective RAG.** The LangGraph flow is `retrieve → grade_chunks → (generate | rewrite_query → retrieve)`.
   - The grader scores relevance.
   - On low relevance, it rewrites the query, at most 2 times.
   - After that, it answers "not found in the document" instead of guessing.
4. **Grounded answers only.** Every answer cites the chunks it used. When retrieval returns nothing, say so; never answer from model memory.
5. **Ingestion status.** Each document moves through `pending → processing → ready | failed` and stores an `error` field.
   - Failed ingestion retries up to 3 times with backoff.
   - The UI shows the status and offers a retry.
6. **Fail safe at the boundary.**
   - Validate uploads with a size limit and a MIME allowlist.
   - Validate URLs: http(s) only, no private, loopback or link-local IPs (SSRF), with a timeout and a size cap.
   - Return clear 4xx errors.

## Data (Postgres)
- `documents`: id, source (filename or URL), status, error, embed_model, created_at
- Vector table: managed by LlamaIndex `PGVectorStore`, with `document_id` in its metadata
- LangGraph checkpointer tables: one thread per chat
