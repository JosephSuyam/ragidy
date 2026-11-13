# 0004: Provider factory and logging

- Status: accepted
- Date: 2026-11-05
- Amends: [0001](0001-stack-and-scope.md) (Library split: one documented exception)
- Amended: 2026-11-09 (chat providers: `google` and `groq`)

## Context
ADR 0001 resolves the LLM and the embedding model in one factory, `app/core/providers.py`. The hard rule keeps LlamaIndex in `app/rag/` and LangChain/LangGraph in `app/agents/`. The chat model is a LangChain object and the embedding model is a LlamaIndex object, so a factory in `app/core` that builds both must import both frameworks. Tests also need one place to mock models, and the API needs basic logs.

## Decision
- **Single exception to the hard rule.** `app/core/providers.py` is the only module that imports vendor model integrations. It may import `langchain_core`, `langchain_anthropic`, `langchain_openai`, `langchain_ollama`, `langchain_google_genai`, `langchain_groq`, `llama_index.core`, `llama_index.embeddings.openai` and `llama_index.embeddings.ollama`, only to construct model objects. No other code in `app/core` imports those frameworks. Layering is unchanged: `app/rag` and `app/agents` call down into `app/core`.
- **Contract:**
  ```python
  # app/core/providers.py
  def get_chat_model(settings: Settings) -> BaseChatModel   # anthropic -> ChatAnthropic, openai -> ChatOpenAI, ollama -> ChatOllama, google -> ChatGoogleGenerativeAI, groq -> ChatGroq
  def get_embed_model(settings: Settings) -> BaseEmbedding  # openai -> OpenAIEmbedding, ollama -> OllamaEmbedding
  # app/core/logging.py
  def configure_logging() -> None  # logging.basicConfig, INFO, "%(asctime)s %(levelname)s %(name)s %(message)s"
  ```
  - Returns are plain `BaseChatModel` and `BaseEmbedding`, not wrapped, so agents can call `.with_structured_output` or `.bind_tools` first.
  - Callers use `from app.core import providers` and then `providers.get_chat_model(settings)`, so tests monkeypatch the module attribute. Tests mock LLMs and embeddings here.
  - `main.py` calls `configure_logging()` before `FastAPI(...)`.
- **Settings:** `llm_provider: Literal["anthropic", "openai", "ollama", "google", "groq"]`, `embed_provider: Literal["openai", "ollama"]`, `anthropic_api_key`, `openai_api_key`, `google_api_key` and `groq_api_key: SecretStr` (default empty), `ollama_base_url: str = "http://localhost:11434"`. Keys live in `Settings` because pydantic reads `.env` without exporting it to `os.environ`, which the SDK classes read. A key is unwrapped with `.get_secret_value()` only at the constructor call.
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

## Amendment (2026-11-09)
- `LLM_PROVIDER` gains `google` (Google AI Studio, `GOOGLE_API_KEY`) and `groq` (`GROQ_API_KEY`), built with `langchain-google-genai` `ChatGoogleGenerativeAI` and `langchain-groq` `ChatGroq`. Both get the 60 s timeout and the missing-key `ValueError`. Embeddings stay `openai | ollama`. Vertex AI is out of scope.
- **Google retries:** `google-genai` retries connection errors, timeouts, 408, 429, 500, 502, 503 and 504, never 409, other 5xx (such as 501) or other 4xx. LangChain maps its `max_retries` to total attempts, so the factory passes `MAX_RETRIES + 1` to keep 3 attempts in total. Single retry layer.
- **Google Vertex guard:** `google-genai` reads `GOOGLE_GENAI_USE_VERTEXAI` and `GOOGLE_GENAI_USE_ENTERPRISE` from the environment even when LangChain passes `vertexai=False`, and would then send the AI Studio key to Vertex. The factory raises `ValueError` when either is set to `true` or `1` (case-insensitive, the values `google-genai` treats as on) with `LLM_PROVIDER=google`, so operators must leave both unset or false. With `EMBED_PROVIDER=google`, `GOOGLE_GENAI_USE_VERTEXAI` must be unset (see the 2026-11-14 amendment).
- **Groq:** the `groq` SDK matches the rules above: `max_retries=2` (3 attempts) on connection errors, timeouts, 408, 409, 429 and 5xx, a timeout in seconds, and no second layer. Its structured output defaults to `function_calling` with a forced tool. Groq validates the tool arguments on the server and returns a non-retried 400 `tool_use_failed` when a small model emits bad arguments, so the grader fails and the chat ends with the `answer_failed` event. `Grade` is simple, so the risk is low; test the configured Groq model once by hand.
- Rejected: `ChatOpenAI` with a `base_url` pointing at each OpenAI-compatible endpoint. It adds no dependency, but the corrective-RAG grader needs `.with_structured_output(Grade)`, and those endpoints support structured output only partly (Groq `json_schema` on some models only; the Gemini compatibility layer is beta).

## Amendment (2026-11-14)
- `EMBED_PROVIDER` gains `google`, built with `llama-index-embeddings-google-genai` `GoogleGenAIEmbedding` (example model `gemini-embedding-001`). It reuses `GOOGLE_API_KEY` (AI Studio, not Vertex AI) and the same missing-key `ValueError` as the google chat model. `embed_provider` is now `Literal["openai", "ollama", "google"]`, and `llama_index.embeddings.google_genai` and `google.genai.types.HttpOptions` join the allowed imports (the wrapper types `http_options` as `HttpOptions`).
- **Embed Vertex guard is stricter.** `GoogleGenAIEmbedding.__init__` does `os.getenv("GOOGLE_GENAI_USE_VERTEXAI", False)` with no bool parse, so even `false` or `0` turns Vertex on. For `EMBED_PROVIDER=google` the factory raises `ValueError` on any non-empty `GOOGLE_GENAI_USE_VERTEXAI`, so it must be unset, not "false". `GOOGLE_GENAI_USE_ENTERPRISE` is still rejected only for `true` or `1`. This replaces "unset or false" above for the embed provider.
- **Google embed retries and timeout.** The wrapper's tenacity retry (`retries=2`, total attempts) covers only `APIError` 429, 502, 503 and 504 and `requests` `ConnectionError`. A timeout, 500 or 408 gets no retry, and the async aiohttp path has only the SDK's implicit connector-error retry. So the "connection errors, 408, 409, 429 and 5xx" rule above does not hold for google embeddings. The ingestion job's 3 attempts (ADR 0002) still apply. The 60 s timeout is passed as `HttpOptions(timeout=60000)` in milliseconds, because the wrapper's own `timeout` field is unused. Switching embed provider or model needs re-ingestion (ADR 0006).
- The package requires `google-genai<3`, so the lock holds `google-genai` 2.34.0 instead of 3.0.0. Retry-attempt and Vertex env-var behavior are unchanged in 2.34.
