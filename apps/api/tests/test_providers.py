import socket
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from pydantic import SecretStr

from app.core import providers
from app.core.config import Settings

SECRET = "sk-test-secret"
OLLAMA_URL = "http://ollama.test:11434"
# Not the default, and a name OpenAIEmbedding accepts: it rejects names outside its enum.
EMBED_MODEL = "text-embedding-3-large"


def _refuse_connect(*_: object) -> None:
    raise AssertionError("model constructor opened a network connection")


@pytest.fixture(autouse=True)
def no_network(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _refuse_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse_connect)


def load(**overrides: Any) -> Settings:
    keys = {"anthropic_api_key": SecretStr(SECRET), "openai_api_key": SecretStr(SECRET)}
    return Settings(_env_file=None, **{**keys, **overrides})


@pytest.mark.parametrize(
    ("provider", "cls"),
    [("anthropic", ChatAnthropic), ("openai", ChatOpenAI), ("ollama", ChatOllama)],
)
def test_chat_model_per_provider(provider: str, cls: type) -> None:
    model = providers.get_chat_model(load(llm_provider=provider, llm_model="m-1"))
    assert isinstance(model, cls)
    if isinstance(model, ChatAnthropic):
        assert (model.model, model.max_retries, model.default_request_timeout) == ("m-1", 2, 60.0)
    elif isinstance(model, ChatOpenAI):
        assert (model.model_name, model.max_retries, model.request_timeout) == ("m-1", 2, 60.0)
    else:
        assert model.model == "m-1"


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
    ("build", "overrides", "message"),
    [
        (
            providers.get_chat_model,
            {"llm_provider": "anthropic", "anthropic_api_key": SecretStr("")},
            "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic",
        ),
        (
            providers.get_chat_model,
            {"llm_provider": "openai", "openai_api_key": SecretStr("")},
            "OPENAI_API_KEY is required when LLM_PROVIDER=openai",
        ),
        (
            providers.get_embed_model,
            {"embed_provider": "openai", "openai_api_key": SecretStr("")},
            "OPENAI_API_KEY is required when EMBED_PROVIDER=openai",
        ),
    ],
)
def test_missing_api_key_names_setting(build: Any, overrides: dict[str, Any], message: str) -> None:
    settings = load(**overrides)
    with pytest.raises(ValueError, match=f"^{message}$") as exc:
        build(settings)
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(settings)


def test_ollama_base_url_passed() -> None:
    settings = load(llm_provider="ollama", embed_provider="ollama", ollama_base_url=OLLAMA_URL)
    chat = providers.get_chat_model(settings)
    embed = providers.get_embed_model(settings)
    assert isinstance(chat, ChatOllama)
    assert isinstance(embed, OllamaEmbedding)
    assert chat.base_url == embed.base_url == OLLAMA_URL
