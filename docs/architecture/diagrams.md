# Architecture diagrams

Source of truth: [overview.md](overview.md) and [ADR 0001](../decisions/0001-stack-and-scope.md). These diagrams only restate them.

## Containers

```mermaid
flowchart LR
  browser["Browser"] --> web["Web: React + Vite (apps/web)"]
  web --> api["API: FastAPI (apps/api)"]
  api --> db[("Postgres + pgvector<br/>vectors, documents, chat history, LangGraph checkpoints")]
  api -->|"app/core/providers.py"| llm["LLM provider<br/>LLM_PROVIDER, LLM_MODEL"]
  api -->|"app/core/providers.py"| emb["Embedding provider<br/>EMBED_PROVIDER, EMBED_MODEL"]
```

One Postgres database holds all state. Providers are resolved only in `app/core/providers.py`, the only place that imports vendor SDKs.

## Module layering

```mermaid
flowchart TD
  routes["api/routes"] --> services["services"]
  services --> RAG
  services --> AGENTS
  services --> repos["repositories"]
  services --> workers["workers"]
  workers --> ingestion
  workers --> repos
  subgraph RAG["app/rag (LlamaIndex)"]
    ingestion["ingestion, parsers, chunking, embeddings, indexing"]
    retrieval["retrieval, reranking"]
  end
  subgraph AGENTS["app/agents (LangChain / LangGraph)"]
    agentmods["workflows, memory, tools, state"]
  end
  retrieval -.->|"RetrievedChunk (text, score, metadata)"| agentmods
  RAG --> providers["core/providers.py"]
  AGENTS --> providers
  RAG --> models["models"]
  AGENTS --> models
  repos --> models
```

Solid arrows mean "calls", and nothing calls upward. The dotted edge is the only thing that crosses between rag and agents, and it carries plain data.

## Ingestion

```mermaid
sequenceDiagram
  actor User
  participant UI as Web UI
  participant R as api/routes
  participant S as services
  participant W as workers
  participant RAG as app/rag (LlamaIndex)
  participant DB as Postgres + pgvector
  User->>UI: upload a file or give a URL
  UI->>R: file or URL
  R->>R: validate file (size limit, MIME allowlist)<br/>or URL (http(s) only, no private, loopback or link-local IPs, timeout, size cap)
  alt invalid input
    R-->>UI: clear 4xx error
  else valid input
    R->>S: create document
    S->>DB: insert documents row (status pending, embed_model)
    S->>W: start ingestion
    W->>DB: status processing
    W->>RAG: load, parse, chunk, embed, index
    RAG->>DB: PGVectorStore writes vectors
    alt success
      W->>DB: status ready
    else error
      Note over W: Failed ingestion retries up to 3 times with backoff
      W->>DB: status failed, store error
    end
    Note over UI: shows the status and offers a retry
  end
```

Status moves `pending → processing → ready | failed`. Validation happens at the boundary, before any row is written.

## Chat

```mermaid
flowchart LR
  q["question"] --> agent["agent (LangGraph)"]
  mem[("Postgres checkpointer<br/>one thread per chat")] -->|"memory"| agent
  agent --> retrieve["retrieve (LlamaIndex)"]
  retrieve --> grade{"grade_chunks"}
  grade -->|"relevant"| generate["generate"]
  grade -->|"low relevance"| rewrite["rewrite_query (max 2)"]
  rewrite --> retrieve
  grade -->|"still low after 2 rewrites"| notfound["answer: not found in the document"]
  generate --> out["streamed answer + citations"]
```

[Runtime self-healing rules](overview.md#runtime-self-healing-rules)
