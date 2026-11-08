import socket
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from pydantic import SecretStr

from app.agents.workflows import Grade
from app.core import providers
from app.core.config import Settings

SECRET = "sk-test-secret"
# Distinctive, so a leak is easy to spot in any rendered output.
RENDER_KEY = "key-never-rendered-8d1f"
OLLAMA_URL = "http://ollama.test:11434"
# Not the default, and a name OpenAIEmbedding accepts: it rejects names outside its enum.
EMBED_MODEL = "text-embedding-3-large"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/"
VERTEX_ENV_NAMES = ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE")


def _refuse_connect(*_: object) -> None:
    raise AssertionError("model constructor opened a network connection")


@pytest.fixture(autouse=True)
def no_network(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _refuse_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse_connect)


def load(**overrides: Any) -> Settings:
    keys = {
        "anthropic_api_key": SecretStr(SECRET),
        "openai_api_key": SecretStr(SECRET),
        "google_api_key": SecretStr(SECRET),
        "groq_api_key": SecretStr(SECRET),
    }
    return Settings(_env_file=None, **{**keys, **overrides})


@pytest.mark.parametrize(
    ("provider", "cls"),
    [
        ("anthropic", ChatAnthropic),
        ("openai", ChatOpenAI),
        ("ollama", ChatOllama),
        ("google", ChatGoogleGenerativeAI),
        ("groq", ChatGroq),
    ],
)
def test_chat_model_per_provider(provider: str, cls: type) -> None:
    model = providers.get_chat_model(load(llm_provider=provider, llm_model="m-1"))
    assert isinstance(model, cls)
    if isinstance(model, ChatAnthropic):
        assert (model.model, model.max_retries, model.default_request_timeout) == ("m-1", 2, 60.0)
    elif isinstance(model, ChatOpenAI):
        assert (model.model_name, model.max_retries, model.request_timeout) == ("m-1", 2, 60.0)
    elif isinstance(model, ChatGoogleGenerativeAI):
        assert (model.model, model.max_retries, model.timeout) == ("m-1", 3, 60.0)
        assert model.google_api_key is not None
        assert model.google_api_key.get_secret_value() == SECRET
    elif isinstance(model, ChatGroq):
        assert (model.model_name, model.max_retries, model.request_timeout) == ("m-1", 2, 60.0)
        assert model.groq_api_key is not None
        assert model.groq_api_key.get_secret_value() == SECRET
    else:
        assert model.model == "m-1"


def test_google_sdk_makes_three_attempts() -> None:
    model = providers.get_chat_model(load(llm_provider="google"))
    request = model._prepare_request([HumanMessage(content="hi")])
    assert request["config"].http_options.retry_options.attempts == 3


@pytest.mark.parametrize(
    ("provider", "cls"), [("openai", OpenAIEmbedding), ("ollama", OllamaEmbedding)]
)
def test_embed_model_per_provider(provider: str, cls: type) -> None:
    model = providers.get_embed_model(load(embed_provider=provider, embed_model=EMBED_MODEL))
    assert isinstance(model, cls)
    assert model.model_name == EMBED_MODEL
    assert model.num_workers == providers.EMBED_WORKERS
    if isinstance(model, OpenAIEmbedding):
        assert (model.max_retries, model.timeout) == (1, 60.0)


@pytest.mark.parametrize(
    ("build", "overrides", "key_name", "message"),
    [
        (
            providers.get_chat_model,
            {"llm_provider": "anthropic", "anthropic_api_key": SecretStr("")},
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic",
        ),
        (
            providers.get_chat_model,
            {"llm_provider": "openai", "openai_api_key": SecretStr("")},
            "OPENAI_API_KEY",
            "OPENAI_API_KEY is required when LLM_PROVIDER=openai",
        ),
        (
            providers.get_chat_model,
            {"llm_provider": "google", "google_api_key": SecretStr("")},
            "GOOGLE_API_KEY",
            "GOOGLE_API_KEY is required when LLM_PROVIDER=google",
        ),
        (
            providers.get_chat_model,
            {"llm_provider": "groq", "groq_api_key": SecretStr("")},
            "GROQ_API_KEY",
            "GROQ_API_KEY is required when LLM_PROVIDER=groq",
        ),
        (
            providers.get_embed_model,
            {"embed_provider": "openai", "openai_api_key": SecretStr("")},
            "OPENAI_API_KEY",
            "OPENAI_API_KEY is required when EMBED_PROVIDER=openai",
        ),
    ],
)
def test_missing_api_key_names_setting(
    build: Any,
    overrides: dict[str, Any],
    key_name: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The SDK could read this env var itself; the factory must still fail fast on the empty setting.
    monkeypatch.setenv(key_name, "env-only")
    settings = load(**overrides)
    with pytest.raises(ValueError, match=f"^{message}$") as exc:
        build(settings)
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(settings)


@pytest.mark.parametrize("name", VERTEX_ENV_NAMES)
@pytest.mark.parametrize("value", ["true", "1", "TRUE"])
def test_google_rejects_vertex_env(name: str, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=f"^{name} must be unset when LLM_PROVIDER=google$"):
        providers.get_chat_model(load(llm_provider="google"))


def test_google_client_uses_ai_studio_when_vertex_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in VERTEX_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    model = providers.get_chat_model(load(llm_provider="google"))
    sdk = model.client._api_client
    # The SDK leaves vertexai as None when no env var selects Vertex, which means the Gemini API.
    assert not sdk.vertexai
    assert sdk._http_options.base_url == GEMINI_API_URL


@pytest.mark.parametrize("provider", ["google", "groq"])
def test_api_key_never_rendered(provider: str) -> None:
    key = SecretStr(RENDER_KEY)
    model = providers.get_chat_model(
        load(llm_provider=provider, google_api_key=key, groq_api_key=key)
    )
    rendered = [repr(model), str(model), model.model_dump_json(), str(model.model_dump())]
    assert all(RENDER_KEY not in text for text in rendered)


@pytest.mark.parametrize("provider", ["google", "groq"])
def test_structured_output_builds_without_network(provider: str) -> None:
    chat = providers.get_chat_model(load(llm_provider=provider))
    assert isinstance(chat.with_structured_output(Grade), Runnable)


def test_ollama_base_url_passed() -> None:
    settings = load(llm_provider="ollama", embed_provider="ollama", ollama_base_url=OLLAMA_URL)
    chat = providers.get_chat_model(settings)
    embed = providers.get_embed_model(settings)
    assert isinstance(chat, ChatOllama)
    assert isinstance(embed, OllamaEmbedding)
    assert chat.base_url == embed.base_url == OLLAMA_URL
