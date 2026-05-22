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

    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: str = Field(default="", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: str = Field(default="", alias="AWS_SESSION_TOKEN")
    bedrock_model_review: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0",
        alias="BEDROCK_MODEL_REVIEW",
    )
    bedrock_review_enabled: bool = Field(default=True, alias="BEDROCK_REVIEW_ENABLED")
    bedrock_review_max_tokens: int = Field(default=300, alias="BEDROCK_REVIEW_MAX_TOKENS")
    bedrock_review_fallback_groq: bool = Field(
        default=False,
        alias="BEDROCK_REVIEW_FALLBACK_GROQ",
    )
    bedrock_review_use_crewai: bool = Field(
        default=False,
        alias="BEDROCK_REVIEW_USE_CREWAI",
    )
    bedrock_review_rag_refresh: bool = Field(
        default=False,
        alias="BEDROCK_REVIEW_RAG_REFRESH",
    )
    bedrock_review_rag_top_k: int = Field(default=6, alias="BEDROCK_REVIEW_RAG_TOP_K")
    bedrock_review_rag_snippet_chars: int = Field(
        default=800,
        alias="BEDROCK_REVIEW_RAG_SNIPPET_CHARS",
    )

    gmail_notify_enabled: bool = Field(default=False, alias="GMAIL_NOTIFY_ENABLED")
    gmail_service_account_file: Path = Field(
        default=Path("gcp/key_gmail.json"),
        alias="GMAIL_SERVICE_ACCOUNT_FILE",
    )
    gmail_oauth_token_file: Path = Field(
        default=Path("gcp/gmail_token.json"),
        alias="GMAIL_OAUTH_TOKEN_FILE",
    )
    gmail_impersonate_user: str = Field(default="", alias="GMAIL_IMPERSONATE_USER")
    gmail_to: str = Field(default="", alias="GMAIL_TO")
    gmail_fail_on_error: bool = Field(default=False, alias="GMAIL_FAIL_ON_ERROR")

    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    api_access_token: str = Field(default="", alias="API_ACCESS_TOKEN")
    jwt_auth_enabled: bool = Field(default=True, alias="JWT_AUTH_ENABLED")

    agentops_api_key: str = Field(default="", alias="AGENTOPS_API_KEY")
    agentops_enabled: bool = Field(default=True, alias="AGENTOPS_ENABLED")
    agentops_project_tags: str = Field(default="denialflow,poc", alias="AGENTOPS_PROJECT_TAGS")

    @property
    def agentops_tags_list(self) -> list[str]:
        return [t.strip() for t in self.agentops_project_tags.split(",") if t.strip()]

    @property
    def agentops_should_init(self) -> bool:
        return self.agentops_enabled and bool(self.agentops_api_key.strip())

    def validate_auth_config(self) -> None:
        """Fail fast when auth is enabled but no token is configured."""
        if not self.jwt_auth_enabled:
            return
        token = self.api_access_token.strip()
        secret = self.jwt_secret.strip()
        if not token and not secret:
            raise ValueError(
                "JWT_AUTH_ENABLED=true requires API_ACCESS_TOKEN and/or JWT_SECRET in .env"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
