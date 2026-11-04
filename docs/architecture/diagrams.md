# Architecture diagrams

Source of truth: [overview.md](overview.md), [ADR 0001](../decisions/0001-stack-and-scope.md) and [ADR 0002](../decisions/0002-object-storage-and-job-queue.md). These diagrams only restate them.

## Containers

```mermaid
flowchart LR
  browser["Browser"] --> web["Web: React + Vite (apps/web)"]
  web --> api["API: FastAPI (apps/api)"]
  api --> db[("Postgres + pgvector<br/>vectors, documents and job queue, chat history, LangGraph checkpoints")]
  api -->|"raw file"| minio[("Object storage: MinIO<br/>raw uploads and fetched URL content")]
  worker["Worker (app/workers)<br/>separate process, API image"] -->|"claim pending row, SKIP LOCKED"| db
  worker -->|"read raw file"| minio
  api -->|"Providers (app/core)"| llm["LLM provider<br/>LLM_PROVIDER, LLM_MODEL"]
  api -->|"Providers (app/core)"| emb["Embedding provider<br/>EMBED_PROVIDER, EMBED_MODEL"]
  worker -->|"Providers (app/core)"| emb
```

Postgres holds structured state, vectors and the job queue; MinIO holds the raw files. The API never runs ingestion: it stores the file, inserts a `pending` row, and the worker process claims it. Providers are resolved only in `app/core/providers.py`, the only place that imports vendor SDKs.

## Module layering

```mermaid
flowchart TD
  subgraph API["API Layer: routes and request handling"]
    routes["Routes (app/api/routes)"]
  end
  subgraph SERVICE["Service Layer: business logic and orchestration"]
    services["Services (app/services)"]
    workers["Workers (app/workers)"]
  end
  subgraph RAG["RAG Layer: LlamaIndex (app/rag)"]
    ingestion["Ingestion (app/rag/ingestion)<br/>Parsers (app/rag/parsers)<br/>Chunking (app/rag/chunking)<br/>Embeddings (app/rag/embeddings)<br/>Indexing (app/rag/indexing)"]
    retrieval["Retrieval (app/rag/retrieval)<br/>Reranking (app/rag/reranking)"]
  end
  subgraph AGENTS["Agent Layer: LangChain / LangGraph (app/agents)"]
    agentmods["Workflows (app/agents/workflows)<br/>Memory (app/agents/memory)<br/>Tools (app/agents/tools)<br/>State (app/agents/state)"]
  end
  subgraph INFRA["Infrastructure Layer"]
    repos["Repositories (app/repositories)"]
    models["Models (app/models)"]
    providers["Providers, object storage client (app/core)"]
    storage[("Storage: Postgres + pgvector<br/>Job queue: Postgres")]
  end
  objstore[("Object storage: MinIO")]
  API --> SERVICE
  SERVICE --> RAG
  SERVICE --> AGENTS
  SERVICE --> INFRA
  SERVICE --> objstore
  RAG --> INFRA
  AGENTS --> INFRA
  retrieval -.->|"RetrievedChunk (text, score, metadata)"| agentmods
```

Arrows connect layers, not modules, and each one means "calls"; every arrow points down, and nothing calls upward. Routes only handle requests: they never run retrieval or touch the vector store, and go through services instead. The dotted edge is the only thing that crosses between rag and agents, and it carries plain data. `app/rag` never touches object storage; workers pass it the bytes and the MIME type as plain data. Workers run as their own process and are never called by routes; the API only inserts a `pending` row.

## Ingestion

```mermaid
sequenceDiagram
  actor User
  participant UI as Web UI
  participant R as Routes (app/api/routes)
  participant S as Services (app/services)
  participant W as Workers (app/workers)
  participant RAG as RAG: LlamaIndex (app/rag)
  participant OS as Object storage: MinIO
  participant DB as Postgres + pgvector
  User->>UI: upload a file or give a URL
  UI->>R: file or URL
  R->>S: create document
  S->>S: validate file (size limit, server-detected MIME in allowlist)<br/>or URL (http(s) only, no private, loopback or link-local IPs,<br/>checked on the connected IP and every redirect hop, timeout, size cap), then fetch it
  alt invalid input
    S-->>R: validation error
    R-->>UI: clear 4xx error
  else valid input
    S->>OS: put raw file or fetched URL content at a server-generated key (app/core)
    S->>DB: insert documents row, status pending, object key, embed_model (app/repositories)
    S-->>R: document id
    R-->>UI: document id, status pending
    W->>DB: claim pending row, SKIP LOCKED, status processing (app/repositories)
    W->>OS: read raw file by object key (app/core)
    W->>RAG: Load (app/rag/ingestion), Parse (app/rag/parsers),<br/>Chunk (app/rag/chunking), Embed (app/rag/embeddings),<br/>Index (app/rag/indexing)
    RAG->>DB: PGVectorStore writes vectors (app/rag/indexing)
    alt success
      W->>DB: status ready (app/repositories)
    else error
      Note over W: 3 attempts in total, with backoff
      W->>DB: status pending with backoff while attempts are under 3, else failed, store error (app/repositories)
    end
    Note over UI: shows the status and offers a retry
  end
```

Status moves `pending → processing → ready | failed`. Services validate the input before any file or row is written; URL validation and fetch live together in `app/services`. Routes only pass the request to services.

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
