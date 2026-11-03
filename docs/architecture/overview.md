# Architecture

## Pipeline

```
upload / URL ─▶ ingestion (LlamaIndex) ─▶ pgvector
                 load → parse → chunk → embed → index

question ─▶ agent (LangGraph) ─▶ retrieve (LlamaIndex) ─▶ grade ─▶ generate ─▶ streamed answer + citations
              │  memory (Postgres checkpointer)          │
              └────────── rewrite query, retry ◀─────────┘
```

| Stage | Owner | Module |
|---|---|---|
| Load and parse (PDF, DOCX, HTML, URL) | LlamaIndex readers | `app/ingestion` |
| Chunk | LlamaIndex node parsers | `app/ingestion` |
| Embed and index | LlamaIndex + `PGVectorStore` | `app/ingestion` |
| Retrieve and rerank | LlamaIndex retrievers | `app/retrieval` |
| Memory, loop, and generation | LangGraph + LangChain chat models | `app/agent` |
| Model selection | Provider factory reading `Settings` | `app/providers` |

**Boundary:** `app/retrieval` returns `list[RetrievedChunk]`, where each item holds `text`, `score` and `metadata` (source, page, document_id). `app/agent` wraps retrieval as a tool or graph node. LlamaIndex objects never leave `ingestion/` or `retrieval/`.

## Providers
`app/providers` builds the LLM and the embedding model from `LLM_PROVIDER`/`LLM_MODEL` and `EMBED_PROVIDER`/`EMBED_MODEL`. It is the only place that imports vendor SDKs.

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
