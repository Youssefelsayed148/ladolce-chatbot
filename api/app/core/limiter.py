"""Rate limiting for the public API (slowapi).

Keyed by client IP. The chat endpoint is the one that costs real OpenAI spend on
an unauthenticated public surface, so it's the primary thing being protected -
its limit is read from settings (CHAT_RATE_LIMIT) via a callable so it stays
configurable without an import-time freeze.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def _rate_key(request: Request) -> str:
    # Keyed by client IP only. A client-chosen value (e.g. a query param) must
    # never be the key - it would let anyone dodge the limit by changing it.
    # Behind nginx the real IP comes from X-Forwarded-For, which uvicorn applies
    # via --proxy-headers (see api/Dockerfile).
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_key)


def chat_rate_limit() -> str:
    return get_settings().chat_rate_limit
