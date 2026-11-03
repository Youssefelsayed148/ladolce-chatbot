"""Application settings, loaded from environment variables.

Every value here has a corresponding entry in the repo-root .env.example.
Nothing secret is hardcoded - defaults are safe local-dev placeholders only.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://ladolce:ladolce@db:5432/ladolce"
    )

    # Client store API (read-only catalog sync / quotes).
    store_api_base: str = Field(default="https://ladolce.theosirislabs.com")

    # Where the guest finishes the order (the store's own checkout page).
    store_checkout_url: str = Field(default="https://ladolcesaveur.com/checkout")

    # OpenAI - kept for the embeddings/RAG exception and as a one-line revert
    # path for chat. See docs/llm-layer-audit.md Section 8 for revert steps.
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    # Phase 5 (knowledge base / RAG) - OpenCode Go has no embeddings endpoint,
    # so KB ingestion/retrieval stays on OpenAI. The dimension must match
    # models.KB_EMBEDDING_DIM = 1536.
    openai_embedding_model: str = Field(default="text-embedding-3-small")

    # OpenCode Go provider (active for chat/tool-calling).
    # Endpoint verified: https://opencode.ai/zen/go/v1/chat/completions exists
    # (401 with a bad key); /v1/embeddings returns 404.
    llm_provider: str = Field(default="opencodego")
    llm_api_base: str = Field(default="https://opencode.ai/zen/go/v1")
    llm_api_key: str = Field(default="")
    # Default chat model: Kimi K2.7 Code is the strongest OpenAI-compatible
    # tool-caller in the Go lineup at a moderate price point.
    llm_model: str = Field(default="kimi-k2.7-code")

    # CORS - comma-separated list of allowed origins for the widget.
    cors_origins: str = Field(default="http://localhost:8080,http://localhost:5173")

    # Follow-up chips cost one extra LLM call per message. Turn off to save
    # free-tier quota; the widget simply shows no chips after the greeting.
    suggestions_enabled: bool = Field(default=True)

    # Rate limiting for the public, unauthenticated /api/chat endpoint.
    chat_rate_limit: str = Field(default="20/minute")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
