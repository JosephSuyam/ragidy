from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    embed_provider: str = "openai"
    embed_model: str = "text-embedding-3-small"
    database_url: str = "postgresql+psycopg://ragidy:ragidy@localhost:5432/ragidy"
    s3_endpoint_url: str = "http://localhost:8333"
    s3_bucket: str = "ragidy"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
