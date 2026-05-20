from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model_primary: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_PRIMARY")
    openai_model_fallback: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_FALLBACK")
    openai_model_appeal: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_APPEAL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model_primary: str = Field(
        default="llama-3.3-70b-versatile",
        alias="GROQ_MODEL_PRIMARY",
    )
    groq_model_fallback: str = Field(
        default="llama-3.1-8b-instant",
        alias="GROQ_MODEL_FALLBACK",
    )
    groq_model_appeal: str = Field(
        default="llama-3.3-70b-versatile",
        alias="GROQ_MODEL_APPEAL",
    )

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    database_path: Path = Field(default=Path("data/denialflow.db"), alias="DATABASE_PATH")
    chroma_persist_dir: Path = Field(default=Path("data/chroma"), alias="CHROMA_PERSIST_DIR")
    seed_documents_dir: Path = Field(
        default=Path("data/seed_documents"),
        alias="SEED_DOCUMENTS_DIR",
    )

    workflow_token_budget: int = Field(default=120_000, alias="WORKFLOW_TOKEN_BUDGET")
    classification_cache_ttl_seconds: int = Field(
        default=3600,
        alias="CLASSIFICATION_CACHE_TTL_SECONDS",
    )

    log_json: bool = Field(default=False, alias="LOG_JSON")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
