# 0004: Provider factory and logging

- Status: accepted
- Date: 2026-11-05
- Amends: [0001](0001-stack-and-scope.md) (Library split: one documented exception)

## Context
ADR 0001 resolves the LLM and the embedding model in one factory, `app/core/providers.py`. The hard rule keeps LlamaIndex in `app/rag/` and LangChain/LangGraph in `app/agents/`. The chat model is a LangChain object and the embedding model is a LlamaIndex object, so a factory in `app/core` that builds both must import both frameworks. Tests also need one place to mock models, and the API needs basic logs.

## Decision
- **Single exception to the hard rule.** `app/core/providers.py` is the only module that imports vendor model integrations. It may import `langchain_core`, `langchain_anthropic`, `langchain_openai`, `langchain_ollama`, `llama_index.core`, `llama_index.embeddings.openai` and `llama_index.embeddings.ollama`, only to construct model objects. No other code in `app/core` imports those frameworks. Layering is unchanged: `app/rag` and `app/agents` call down into `app/core`.
- **Contract:**
  ```python
  # app/core/providers.py
  def get_chat_model(settings: Settings) -> BaseChatModel   # anthropic -> ChatAnthropic, openai -> ChatOpenAI, ollama -> ChatOllama
  def get_embed_model(settings: Settings) -> BaseEmbedding  # openai -> OpenAIEmbedding, ollama -> OllamaEmbedding
  # app/core/logging.py
  def configure_logging() -> None  # logging.basicConfig, INFO, "%(asctime)s %(levelname)s %(name)s %(message)s"
  ```
  - Returns are plain `BaseChatModel` and `BaseEmbedding`, not wrapped, so agents can call `.with_structured_output` or `.bind_tools` first.
  - Callers use `from app.core import providers` and then `providers.get_chat_model(settings)`, so tests monkeypatch the module attribute. Tests mock LLMs and embeddings here.
  - `main.py` calls `configure_logging()` before `FastAPI(...)`.
- **Settings:** `llm_provider: Literal["anthropic", "openai", "ollama"]`, `embed_provider: Literal["openai", "ollama"]`, `anthropic_api_key: SecretStr` and `openai_api_key: SecretStr` (default empty), `ollama_base_url: str = "http://localhost:11434"`. Keys live in `Settings` because pydantic reads `apps/api/.env` without exporting it to `os.environ`, which the SDK classes read. A key is unwrapped with `.get_secret_value()` only at the constructor call.
- **Missing key:** the factory raises `ValueError` naming the setting, never its value, for example "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic". The check runs when the model is built, not in a `Settings` validator, because CI and tests run without keys.
- **Retries:** chat models get the SDKs' built-in `max_retries=2` (3 attempts in total) and a 60 s timeout. SDK retries cover connection errors, 408, 409, 429 and 5xx, never other 4xx. The OpenAI embedding gets `EMBED_MAX_RETRIES = 1`, because LlamaIndex `OpenAIEmbedding` applies `max_retries` twice (the OpenAI client retry, then its own tenacity wrapper), so one embed call makes at most 2 requests, on transient errors only. The ingestion job's 3 attempts (ADR 0002) sit on top. No `.with_retry` on top. Ollama runs locally and has no retry.
- **Ollama ships now.** In Docker, the api container reaches the host's Ollama at `http://host.docker.internal:11434` through `OLLAMA_BASE_URL`.

## Alternatives
- **Option B: the factory returns a plain config dataclass, and `app/agents` and `app/rag` build their own models.** It keeps the hard rule with no exception, but gives tests two mock points instead of one, and needs about five doc changes.
- **`.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)`:** its default `retry_if_exception_type=(Exception,)` also retries 4xx, and it stacks on the SDK retries, so one call can become 9 requests.
- **Request-id middleware, JSON logs, `LOG_LEVEL`, a log-redaction filter:** deferred, because no requirement asks for them. The requirement is that logs never contain passwords, tokens, cookie values or OAuth codes, which code meets by never logging them.
- **Provider fallbacks (`with_fallbacks`):** deferred until a second provider is configured, in the agent step.
- **Model caching:** deferred until profiling shows construction cost matters.

## Consequences
- The hard rule has one named exception; code review rejects framework imports anywhere else in `app/core`.
- One mock point for LLMs and embeddings in tests.
- Keys stay out of logs and errors: `SecretStr` hides them in `Settings` reprs, and the missing-key error names only the setting. LlamaIndex `OpenAIEmbedding` stores `api_key` as a plain str, so its `repr`, `str`, `to_dict()` and `to_json()` show the raw key; never log or serialize the embedding model.
- `.env.example`, `AGENTS.md` and agent guides need the new settings and the exception; the documentation agent updates them.
- On Linux Docker, `host.docker.internal` needs `extra_hosts: ["host.docker.internal:host-gateway"]` on the api service.
