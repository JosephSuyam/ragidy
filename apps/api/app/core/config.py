from functools import lru_cache
from ipaddress import ip_network
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SUPPORTED_UPLOAD_TYPES = frozenset({"pdf", "docx", "txt", "md", "html"})
_DEFAULT_UPLOAD_TYPES = sorted(SUPPORTED_UPLOAD_TYPES)
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MIB = 1024 * 1024
_MIN_AUTH_SECRET_LENGTH = 32

UploadTypes = Annotated[list[str], NoDecode]
Networks = Annotated[list[str], NoDecode]


def _split_csv(value: Any) -> list[str]:
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list):
        raise ValueError("must be a comma-separated string or a list")
    return [str(item).strip() for item in items if str(item).strip()]


class Settings(BaseSettings):
    # Errors hide input so str(exc) never leaks secrets; exc.errors() still has it: never log that.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    llm_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    embed_provider: Literal["openai", "ollama"] = "openai"
    embed_model: str = "text-embedding-3-small"
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://localhost:11434"
    database_url: str = "postgresql+psycopg://ragidy:ragidy@localhost:5432/ragidy"
    s3_endpoint_url: str = "http://localhost:8333"
    s3_bucket: str = "ragidy"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: SecretStr = SecretStr("")

    upload_max_mb_guest: PositiveInt = 3
    upload_max_mb_user: PositiveInt = 5
    upload_types_guest: UploadTypes = _DEFAULT_UPLOAD_TYPES
    upload_types_user: UploadTypes = _DEFAULT_UPLOAD_TYPES
    max_docs_guest: PositiveInt = 3
    max_docs_user: PositiveInt = 20
    guest_ttl_days: PositiveInt = 7
    session_ttl_days: PositiveInt = 30

    auth_secret: SecretStr = SecretStr("")
    public_base_url: str = "http://localhost:5173"
    oauth_google_client_id: str = ""
    oauth_google_client_secret: SecretStr = SecretStr("")
    oauth_github_client_id: str = ""
    oauth_github_client_secret: SecretStr = SecretStr("")

    rate_limit_auth_per_minute: PositiveInt = 10
    login_max_failures: PositiveInt = 5
    login_failure_window_minutes: PositiveInt = 15
    trusted_proxies: Networks = []
    guest_create_per_ip_per_hour: PositiveInt = 10
    chat_messages_per_hour_guest: PositiveInt = 20
    chat_messages_per_hour_user: PositiveInt = 100

    @property
    def upload_max_bytes_guest(self) -> int:
        return self.upload_max_mb_guest * _MIB

    @property
    def upload_max_bytes_user(self) -> int:
        return self.upload_max_mb_user * _MIB

    @field_validator("upload_types_guest", "upload_types_user", mode="before")
    @classmethod
    def _parse_upload_types(cls, value: Any) -> list[str]:
        types = [item.lower() for item in _split_csv(value)]
        if not types:
            raise ValueError("must list at least one file type")
        unknown = sorted(set(types) - SUPPORTED_UPLOAD_TYPES)
        if unknown:
            supported = ", ".join(sorted(SUPPORTED_UPLOAD_TYPES))
            raise ValueError(f"unsupported file types {unknown}; supported: {supported}")
        return types

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _parse_trusted_proxies(cls, value: Any) -> list[str]:
        # Strings, not network objects: uvicorn ProxyHeadersMiddleware(trusted_hosts=...) needs str.
        return [str(ip_network(item, strict=False)) for item in _split_csv(value)]

    @field_validator("auth_secret")
    @classmethod
    def _check_auth_secret_length(cls, value: SecretStr) -> SecretStr:
        if 0 < len(value.get_secret_value()) < _MIN_AUTH_SECRET_LENGTH:
            raise ValueError(f"must be at least {_MIN_AUTH_SECRET_LENGTH} characters")
        return value

    @field_validator("public_base_url")
    @classmethod
    def _check_public_base_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("must be an http(s) origin such as https://app.example.com")
        # Normalized like a browser Origin header, so Origin checks can compare strings exactly.
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        port = parts.port
        if port is None or port == _DEFAULT_PORTS[parts.scheme]:
            return f"{parts.scheme}://{host}"
        return f"{parts.scheme}://{host}:{port}"

    @model_validator(mode="after")
    def _check_oauth_secrets(self) -> Self:
        providers = [
            ("google", self.oauth_google_client_id, self.oauth_google_client_secret),
            ("github", self.oauth_github_client_id, self.oauth_github_client_secret),
        ]
        for name, client_id, client_secret in providers:
            if not client_id:
                continue
            if not self.auth_secret.get_secret_value():
                raise ValueError(f"AUTH_SECRET is required when {name} OAuth is set")
            if not client_secret.get_secret_value():
                raise ValueError(f"OAUTH_{name.upper()}_CLIENT_SECRET is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
