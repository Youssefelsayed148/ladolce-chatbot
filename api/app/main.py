"""FastAPI application entrypoint.

Wires together: structured JSON logging, a per-request request_id, CORS for the
widget, slowapi rate limiting, and the (currently stubbed) API routers. No
business logic yet - every endpoint returns a well-formed 200 so the container
stack can be verified end to end.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import configure_logging, request_id_var
from app import models  # noqa: F401  (register ORM tables on Base.metadata)
from app.routers import cart, catalog, chat, order

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_startup", extra={"environment": settings.environment})
    yield


app = FastAPI(title="La Dolce Saveur Ordering API", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["x-request-id"] = request_id
    return response


# /health is for container-level healthchecks hitting the api directly;
# /api/health is the same payload reachable through the public Nginx proxy
# (which only forwards /api/*), so the frontend can probe it same-origin.
@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


app.include_router(chat.router)
app.include_router(cart.router)
app.include_router(order.router)
app.include_router(catalog.router)
