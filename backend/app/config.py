from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    embed_provider: str = "openai"
    embed_model: str = "text-embedding-3-small"
    database_url: str = "postgresql+psycopg://ragidy:ragidy@localhost:5432/ragidy"


@lru_cache
def get_settings() -> Settings:
    return Settings()
