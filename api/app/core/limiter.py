"""Rate limiting for the public API (slowapi).

Keyed per-session when a conversation_id / session token is present, falling
back to client IP. The chat endpoint is the one that costs real OpenAI spend on
an unauthenticated public surface, so it's the primary thing being protected -
its limit is read from settings (CHAT_RATE_LIMIT) via a callable so it stays
configurable without an import-time freeze.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def _rate_key(request: Request) -> str:
    conversation_id = request.query_params.get("conversation_id")
    if conversation_id:
        return f"conv:{conversation_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key)


def chat_rate_limit() -> str:
    return get_settings().chat_rate_limit
