"""FastAPI dependencies.

`get_openai_client` is a dependency so tests can override it with a fake client
(no network, no API key) via app.dependency_overrides. The function name is
kept for backward compatibility; the client it returns is now provider-aware.
"""

from openai import AsyncOpenAI

from app.core.config import get_settings


# --- OPENAI (disabled, see docs/llm-layer-audit.md) ---
# def get_openai_client() -> AsyncOpenAI:
#     settings = get_settings()
#     # A placeholder key keeps the constructor from raising when no real key is
#     # configured (local dev / scaffold). Any actual API call then fails and is
#     # caught by the endpoint, which relays a friendly fallback.
#     return AsyncOpenAI(api_key=settings.openai_api_key or "sk-not-configured")
# --- END OPENAI ---


def get_openai_client() -> AsyncOpenAI:
    settings = get_settings()
    # A placeholder key keeps the constructor from raising when no real key is
    # configured (local dev / scaffold). Any actual API call then fails and is
    # caught by the endpoint, which relays a friendly fallback.
    return AsyncOpenAI(
        base_url=settings.llm_api_base,
        api_key=settings.llm_api_key or "sk-not-configured",
    )
