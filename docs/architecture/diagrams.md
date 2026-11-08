# Architecture diagrams

Source of truth: [overview.md](overview.md), [ADR 0001](../decisions/0001-stack-and-scope.md), [ADR 0002](../decisions/0002-object-storage-and-job-queue.md) and [ADR 0003](../decisions/0003-guest-and-user-accounts.md). These diagrams only restate them.

## Containers

```mermaid
flowchart LR
  browser["Browser"] --> web["Web: React + Vite (apps/web)"]
  web -->|"proxies /api/*, strips /api"| api["API: FastAPI (apps/api)"]
  api --> db[("Postgres + pgvector<br/>vectors, documents and job queue, chat history, LangGraph checkpoints,<br/>owners, users, oauth_accounts, sessions, guests")]
  browser -->|"sign-in redirect"| oauth["OAuth providers<br/>Google, GitHub"]
  api -->|"OAuth client config (app/core)<br/>code exchange, identity"| oauth
  api -->|"raw file"| objstore[("Object storage: SeaweedFS<br/>raw uploads and fetched URL content")]
  worker["Worker (app/workers)<br/>separate process, API image"] -->|"claim pending row, SKIP LOCKED"| db
  worker -->|"read raw file"| objstore
  api -->|"Providers (app/core)"| llm["LLM provider<br/>LLM_PROVIDER, LLM_MODEL"]
  api -->|"Providers (app/core)"| emb["Embedding provider<br/>EMBED_PROVIDER, EMBED_MODEL"]
  worker -->|"Providers (app/core)"| emb
```

Postgres holds structured state, vectors and the job queue; SeaweedFS holds the raw files. The API never runs ingestion: it stores the file, inserts a `pending` row, and the worker process claims it. Providers are resolved only in `app/core/providers.py`, the only place that imports vendor SDKs. OAuth providers are external: the browser is redirected to them to sign in, and the API exchanges the code and reads the identity server-side.

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
    ingestion["Ingestion, embedding (app/rag/ingestion)<br/>Parsers (app/rag/parsers)<br/>Chunking (app/rag/chunking)"]
    retrieval["Retrieval: query embedding (app/rag/retrieval)<br/>Reranking (app/rag/reranking)"]
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
  objstore[("Object storage: SeaweedFS")]
  API --> SERVICE
  SERVICE --> RAG
  SERVICE --> AGENTS
  SERVICE --> INFRA
  SERVICE --> objstore
  RAG --> INFRA
  AGENTS --> INFRA
  repos -.->|"RetrievedChunk (text, score, metadata), through a retrieve callable bound in services"| agentmods
```

Arrows connect layers, not modules, and each one means "calls"; every arrow points down, and nothing calls upward. Routes only handle requests: they never run retrieval or touch the vector store, and go through services instead. Rag and agents never call each other: services embed the query through rag, search through repositories, and pass agents a `retrieve` callable. The dotted edge is the only data that reaches agents from retrieval, and it is plain data ([ADR 0007](../decisions/0007-retrieval-and-corrective-rag.md)). `app/rag` never touches object storage; workers pass it the bytes and the MIME type as plain data. Workers run as their own process and are never called by routes; the API only inserts a `pending` row.

## Ingestion

```mermaid
sequenceDiagram
  actor User
  participant UI as Web UI
  participant R as Routes (app/api/routes)
  participant S as Services (app/services)
  participant W as Workers (app/workers)
  participant RAG as RAG: LlamaIndex (app/rag)
  participant OS as Object storage: SeaweedFS
  participant DB as Postgres + pgvector
  User->>UI: upload a file or give a URL
  UI->>R: file or URL
  R->>S: create document for the owner (guest or user)
  S->>S: check the tier's document cap, then validate the file<br/>(tier size limit, server-detected type in the tier allowlist)<br/>or URL (http(s) only, no private, loopback or link-local IPs,<br/>checked on the connected IP and every redirect hop, timeout, tier size cap), then fetch it
  alt invalid input
    S-->>R: validation error
    R-->>UI: clear 4xx error
  else valid input
    S->>OS: put raw file or fetched URL content at documents/<id>, a server-generated id (app/core)
    S->>DB: insert documents row with that id, owner_id, status pending, embed_model (app/repositories)
    S-->>R: document id
    R-->>UI: document id, status pending
    W->>DB: claim pending row, SKIP LOCKED, status processing (app/repositories)
    W->>OS: read raw file at documents/<id> (app/core)
    W->>RAG: Parse (app/rag/parsers), Chunk (app/rag/chunking),<br/>Embed (app/rag/ingestion)
    RAG-->>W: EmbeddedChunk list (text, embedding, metadata)
    alt success
      W->>DB: replace the document's chunks (app/repositories/vector),<br/>status ready, embed_model used (app/repositories)
    else error
      Note over W: 3 attempts in total, with backoff;<br/>an IngestionError (unusable input) fails at once
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
  agent --> retrieve["Retrieve: embed query (app/rag/retrieval)<br/>vector search (app/repositories/vector)"]
  retrieve --> grade{"grade_chunks (app/agents/workflows)"}
  retrieve -->|"no chunks, or same chunks after a rewrite"| notfound
  grade -->|"relevant"| generate["Generate (app/agents/workflows)"]
  grade -->|"no relevant chunk"| rewrite["rewrite_query, max 2 (app/agents/workflows)"]
  rewrite --> retrieve
  grade -->|"none after 2 rewrites"| notfound["Answer: not found in the document (app/agents/workflows)"]
  generate --> out["streamed answer + citations"]
```

## Database schema

```mermaid
erDiagram
  %% Attributes are written name-first so the column name renders in the first column.
  owners ||--o| users : "is (CASCADE)"
  owners ||--o| guests : "is (CASCADE)"
  users ||--o{ sessions : "has (CASCADE)"
  users ||--o{ oauth_accounts : "has (CASCADE)"
  owners ||--o{ documents : "owns (RESTRICT)"
  owners ||--o{ chats : "owns (RESTRICT)"
  chats ||--o{ messages : "has (CASCADE)"
  documents ||--o{ chunks : "has (CASCADE)"
  owners {
    id uuid PK
    kind text "user or guest"
    created_at timestamptz
  }
  users {
    id uuid PK
    owner_id uuid FK, UK
    email text UK "nullable, normalized"
    name text "nullable"
    password text "nullable, hash only"
    created_at timestamptz
  }
  guests {
    id uuid PK
    owner_id uuid FK, UK
    token bytea UK "hash only"
    expires_at timestamptz "indexed"
    created_at timestamptz
  }
  sessions {
    id uuid PK
    user_id uuid FK "indexed"
    token bytea UK "hash only"
    expires_at timestamptz "indexed"
    created_at timestamptz
  }
  oauth_accounts {
    id uuid PK
    user_id uuid FK "indexed"
    provider text "unique with provider_user_id"
    provider_user_id text
    created_at timestamptz
  }
  documents {
    id uuid PK "object key documents/id"
    owner_id uuid FK "indexed"
    source text "filename or URL"
    status text "default pending"
    error text "nullable"
    embed_model text
    attempts int "default 0"
    run_after timestamptz "default now"
    created_at timestamptz
  }
  chunks {
    id uuid PK
    document_id uuid FK "unique with position"
    position int
    text text
    metadata jsonb "default empty object"
    embedding vector "no dimension"
  }
  chats {
    id uuid PK "LangGraph thread id"
    owner_id uuid FK
    title text "nullable"
    created_at timestamptz
  }
  messages {
    id uuid PK
    chat_id uuid FK
    role text "user or assistant"
    content text
    citations jsonb "default empty array"
    created_at timestamptz
  }
```

- CHECK constraints: `owners.kind` is `user` or `guest`; `users.email` equals `lower(btrim(email))`, so its unique constraint holds on the normalized form; `documents.status` is `pending`, `processing`, `ready` or `failed`, and `failed` requires a non-empty `error`; `messages.role` is `user` or `assistant`.
- The partial index `ix_documents_pending_run_after` (on `run_after`, `WHERE status = 'pending'`) serves the worker's job-queue claim ([ADR 0002](../decisions/0002-object-storage-and-job-queue.md)). `chats` and `messages` have `(owner_id, created_at)` and `(chat_id, created_at)` indexes for listing.
- `RESTRICT` on `documents` and `chats` blocks deleting an owner that still owns either, so a cascade never drops rows whose vectors, objects or checkpoints still exist. The guest purge deletes those first, then the rows, then the owner ([ADR 0003](../decisions/0003-guest-and-user-accounts.md)).
- The object key is not a column: it is `documents/<id>`, derived from the document's `id`.
- `chunks.embedding` has no dimension, so changing `EMBED_MODEL` needs no migration; retrieval filters on `documents.embed_model`. There is no HNSW index for the MVP ([ADR 0006](../decisions/0006-vector-store.md)).
- The LangGraph checkpoint tables live in the same database, but outside Alembic and this diagram.

[Runtime self-healing rules](overview.md#runtime-self-healing-rules)
