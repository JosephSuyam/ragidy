import os

from google.genai.types import HttpOptions
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from pydantic import SecretStr

from app.core.config import Settings

# Hosted APIs only; Ollama keeps library defaults because a CPU model can exceed 60 s.
MAX_RETRIES = 2
# LlamaIndex applies this twice (client retry and its own wrapper), so 1 means at most 2 requests.
EMBED_MAX_RETRIES = 1
TIMEOUT_SECONDS = 60.0
# GoogleGenAIEmbedding counts total attempts (not retries), so 2 means at most 2 requests.
GOOGLE_EMBED_ATTEMPTS = 2
# Without it, LlamaIndex sends every embed batch at once (about 25 OpenAI or 250 Ollama
# requests for a 5 MB file).
EMBED_WORKERS = 4


def _require(key: SecretStr, key_name: str, provider_setting: str, provider: str) -> SecretStr:
    if not key.get_secret_value():
        raise ValueError(f"{key_name} is required when {provider_setting}={provider}")
    return key


def _reject_vertex_env(provider_setting: str, *, any_vertexai: bool = False) -> None:
    # google-genai reads these itself and would send the AI Studio key to Vertex.
    for name in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"):
        value = os.environ.get(name, "")
        # llama-index skips the bool parse, so any non-empty VERTEXAI value (even "false") is true.
        if value.lower() in ("true", "1") or (
            any_vertexai and name == "GOOGLE_GENAI_USE_VERTEXAI" and value
        ):
            raise ValueError(f"{name} must be unset when {provider_setting}=google")


def get_chat_model(settings: Settings) -> BaseChatModel:
    match settings.llm_provider:
        case "anthropic":
            return ChatAnthropic(
                model_name=settings.llm_model,
                api_key=_require(
                    settings.anthropic_api_key, "ANTHROPIC_API_KEY", "LLM_PROVIDER", "anthropic"
                ),
                max_retries=MAX_RETRIES,
                timeout=TIMEOUT_SECONDS,
                stop=None,  # mypy reads the aliased stop_sequences field as required
            )
        case "openai":
            return ChatOpenAI(
                model=settings.llm_model,
                api_key=_require(
                    settings.openai_api_key, "OPENAI_API_KEY", "LLM_PROVIDER", "openai"
                ),
                max_retries=MAX_RETRIES,
                timeout=TIMEOUT_SECONDS,
            )
        case "google":
            _reject_vertex_env("LLM_PROVIDER")
            return ChatGoogleGenerativeAI(
                model=settings.llm_model,
                google_api_key=_require(
                    settings.google_api_key, "GOOGLE_API_KEY", "LLM_PROVIDER", "google"
                ),
                max_retries=MAX_RETRIES + 1,  # google-genai counts total attempts, not retries
                timeout=TIMEOUT_SECONDS,
            )
        case "groq":
            return ChatGroq(
                model=settings.llm_model,
                api_key=_require(settings.groq_api_key, "GROQ_API_KEY", "LLM_PROVIDER", "groq"),
                max_retries=MAX_RETRIES,
                timeout=TIMEOUT_SECONDS,
            )
        case "ollama":
            return ChatOllama(model=settings.llm_model, base_url=settings.ollama_base_url)


def get_embed_model(settings: Settings) -> BaseEmbedding:
    match settings.embed_provider:
        case "openai":
            key = _require(settings.openai_api_key, "OPENAI_API_KEY", "EMBED_PROVIDER", "openai")
            return OpenAIEmbedding(
                model=settings.embed_model,
                api_key=key.get_secret_value(),
                max_retries=EMBED_MAX_RETRIES,
                timeout=TIMEOUT_SECONDS,
                num_workers=EMBED_WORKERS,
            )
        case "google":
            key = _require(settings.google_api_key, "GOOGLE_API_KEY", "EMBED_PROVIDER", "google")
            _reject_vertex_env("EMBED_PROVIDER", any_vertexai=True)
            return GoogleGenAIEmbedding(
                model_name=settings.embed_model,
                api_key=key.get_secret_value(),
                retries=GOOGLE_EMBED_ATTEMPTS,
                # Its own timeout field is never sent; the client takes milliseconds.
                http_options=HttpOptions(timeout=int(TIMEOUT_SECONDS * 1000)),
                num_workers=EMBED_WORKERS,
            )
        case "ollama":
            return OllamaEmbedding(
                model_name=settings.embed_model,
                base_url=settings.ollama_base_url,
                num_workers=EMBED_WORKERS,
            )
