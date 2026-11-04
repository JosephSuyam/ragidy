# Architecture diagrams

Source of truth: [overview.md](overview.md) and [ADR 0001](../decisions/0001-stack-and-scope.md). These diagrams only restate them.

## Containers

```mermaid
flowchart LR
  browser["Browser"] --> web["Web: React + Vite (apps/web)"]
  web --> api["API: FastAPI (apps/api)"]
  api --> db[("Postgres + pgvector<br/>vectors, documents, chat history, LangGraph checkpoints")]
  api -->|"Providers (app/core)"| llm["LLM provider<br/>LLM_PROVIDER, LLM_MODEL"]
  api -->|"Providers (app/core)"| emb["Embedding provider<br/>EMBED_PROVIDER, EMBED_MODEL"]
```

One Postgres database holds all state. Providers are resolved only in `app/core/providers.py`, the only place that imports vendor SDKs.

## Module layering

```mermaid
flowchart TD
  routes["Routes (app/api/routes)"] --> services["Services (app/services)"]
  services --> RAG
  services --> AGENTS
  services --> repos["Repositories (app/repositories)"]
  services --> workers["Workers (app/workers)"]
  workers --> ingestion
  workers --> repos
  subgraph RAG["RAG: LlamaIndex (app/rag)"]
    ingestion["Ingestion (app/rag/ingestion)<br/>Parsers (app/rag/parsers)<br/>Chunking (app/rag/chunking)<br/>Embeddings (app/rag/embeddings)<br/>Indexing (app/rag/indexing)"]
    retrieval["Retrieval (app/rag/retrieval)<br/>Reranking (app/rag/reranking)"]
  end
  subgraph AGENTS["Agents: LangChain / LangGraph (app/agents)"]
    agentmods["Workflows (app/agents/workflows)<br/>Memory (app/agents/memory)<br/>Tools (app/agents/tools)<br/>State (app/agents/state)"]
  end
  retrieval -.->|"RetrievedChunk (text, score, metadata)"| agentmods
  RAG --> providers["Providers (app/core)"]
  AGENTS --> providers
  RAG --> models["Models (app/models)"]
  AGENTS --> models
  repos --> models
```

Solid arrows mean "calls", and nothing calls upward. The dotted edge is the only thing that crosses between rag and agents, and it carries plain data.

## Ingestion

```mermaid
sequenceDiagram
  actor User
  participant UI as Web UI
  participant R as Routes (app/api/routes)
  participant S as Services (app/services)
  participant W as Workers (app/workers)
  participant RAG as RAG: LlamaIndex (app/rag)
  participant DB as Postgres + pgvector
  User->>UI: upload a file or give a URL
  UI->>R: file or URL
  R->>R: validate file (size limit, MIME allowlist)<br/>or URL (http(s) only, no private, loopback or link-local IPs, timeout, size cap)
  alt invalid input
    R-->>UI: clear 4xx error
  else valid input
    R->>S: create document
    S->>DB: insert documents row, status pending, embed_model (app/repositories)
    S->>W: start ingestion
    W->>DB: status processing (app/repositories)
    W->>RAG: Load (app/rag/ingestion), Parse (app/rag/parsers),<br/>Chunk (app/rag/chunking), Embed (app/rag/embeddings),<br/>Index (app/rag/indexing)
    RAG->>DB: PGVectorStore writes vectors (app/rag/indexing)
    alt success
      W->>DB: status ready (app/repositories)
    else error
      Note over W: Failed ingestion retries up to 3 times with backoff
      W->>DB: status failed, store error (app/repositories)
    end
    Note over UI: shows the status and offers a retry
  end
```

Status moves `pending → processing → ready | failed`. Validation happens at the boundary, before any row is written.

## Chat

```mermaid
flowchart LR
  q["question"] --> agent["Agent: LangGraph (app/agents/workflows)"]
  mem[("Memory (app/agents/memory)<br/>Postgres checkpointer, one thread per chat")] -->|"memory"| agent
  agent --> retrieve["Retrieve: LlamaIndex (app/rag/retrieval, app/rag/reranking)"]
  retrieve --> grade{"grade_chunks (app/agents/workflows)"}
  grade -->|"relevant"| generate["Generate (app/agents/workflows)"]
  grade -->|"low relevance"| rewrite["rewrite_query, max 2 (app/agents/workflows)"]
  rewrite --> retrieve
  grade -->|"still low after 2 rewrites"| notfound["Answer: not found in the document (app/agents/workflows)"]
  generate --> out["streamed answer + citations"]
```

[Runtime self-healing rules](overview.md#runtime-self-healing-rules)
