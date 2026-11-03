"""POST /api/chat — Phase 1 Q&A endpoint, streaming-first (SSE).

Flow per request:
  1. Resolve or create the conversation (by opaque session_token).
  2. Persist the incoming user message.
  3. Stream the assistant reply as Server-Sent Events while OpenAI generates it,
     executing the search_products tool server-side when the model calls it.
  4. Persist the final assistant message (with any tool calls) to `messages`.

The endpoint opens its OWN DB session inside the streaming generator rather than
using a request-scoped dependency, because the generator runs while the response
body streams - past the point a request-scoped session would be torn down.

Structured logs (request_id via middleware, plus conversation_id, tool calls,
errors) are emitted throughout.
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.limiter import chat_rate_limit, limiter
from app.deps import get_embedding_client, get_openai_client
from app.models import Conversation, Message
from app.services import cart as cart_service
from app.services import catalog as catalog_service
from app.services.chat import generate_chat_events

logger = logging.getLogger("app.chat")

router = APIRouter(prefix="/api", tags=["chat"])

FALLBACK_MESSAGE = (
    "My apologies — I'm unable to respond just now. Please try again in a moment."
)

# Phase 6: fixed opening suggestions shown before any conversation exists (see
# design note - there's no context yet to derive these from, so a curated
# static list is the right call; every subsequent turn's suggestions are
# generated per-conversation in generate_chat_events/generate_suggestions).
GREETING_SUGGESTIONS = [
    "What are your bestsellers?",
    "Do you ship internationally?",
    "Build me a custom box",
]


# Public, unauthenticated endpoint: bound what a single request can cost.
MAX_MESSAGE_CHARS = 1000
# Only the most recent messages are sent to the model each turn.
MAX_HISTORY_MESSAGES = 20


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(default="", max_length=MAX_MESSAGE_CHARS)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _get_or_create_conversation(
    session: AsyncSession, session_token: str | None
) -> Conversation:
    if session_token:
        result = await session.execute(
            select(Conversation).where(Conversation.session_token == session_token)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

    conversation = Conversation(session_token=str(uuid.uuid4()))
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def _load_history(session: AsyncSession, conversation_id: int) -> list[dict]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.role.in_(("user", "assistant")))
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    messages = reversed(result.scalars().all())
    return [{"role": m.role, "content": m.content} for m in messages if m.content]


async def _plate_sizes_context(session: AsyncSession) -> str:
    """A compact note listing available plate sizes (with ids) injected into the
    system prompt so the model can call start_plate with a valid plate_size_id."""
    sizes = await catalog_service.list_plate_sizes(session)
    if not sizes:
        return ""
    lines = [
        f"  - id={s.id}: {s.name} (holds {s.capacity} slots, base price {float(s.base_price)})"
        for s in sizes
    ]
    return "Available custom box/tray plate sizes:\n" + "\n".join(lines)


async def _categories_context(session: AsyncSession) -> str:
    """A compact note listing the real category names, injected into the system
    prompt so the model can pass search_products' exact-match `category` param
    (e.g. category="Gift Boxes & Trays") for category-shaped questions ("show
    me gift boxes") instead of only a free-text `query`, which only substring-
    matches product name/description and never a category name."""
    categories = await catalog_service.list_categories(session)
    if not categories:
        return ""
    lines = [f"  - {c.name}" for c in categories]
    return "Product categories (use verbatim as search_products' category param):\n" + "\n".join(
        lines
    )


async def _event_stream(
    client: AsyncOpenAI, model: str, body: ChatRequest, embedding_client: AsyncOpenAI
) -> AsyncGenerator[str, None]:
    async with get_sessionmaker()() as session:
        conversation = await _get_or_create_conversation(session, body.conversation_id)

        # Announce the conversation id first so a brand-new client can store it.
        yield _sse({"type": "conversation", "conversation_id": conversation.session_token})

        draft = await cart_service.get_or_create_draft(session, conversation.id)
        history = await _load_history(session, conversation.id)
        context_note = "\n\n".join(
            note
            for note in (
                await _plate_sizes_context(session),
                await _categories_context(session),
            )
            if note
        )

        session.add(
            Message(conversation_id=conversation.id, role="user", content=body.message)
        )
        await session.commit()

        logger.info(
            "chat_request",
            extra={
                "conversation_id": conversation.session_token,
                "cart_draft_id": draft.id,
                "history_len": len(history),
            },
        )

        reply_text = ""
        made_tool_calls = None
        ui_blocks: list[dict] = []
        suggestions: list[str] = []
        try:
            async for event in generate_chat_events(
                session, client, model, conversation, draft, history, body.message, context_note,
                embedding_client,
            ):
                if event["type"] == "token":
                    yield _sse(event)
                elif event["type"] == "tool_call":
                    logger.info(
                        "chat_tool_call",
                        extra={
                            "conversation_id": conversation.session_token,
                            "tool": event["name"],
                            "arguments": event["arguments"],
                        },
                    )
                    yield _sse(event)
                elif event["type"] == "ui_block":
                    yield _sse(event)
                elif event["type"] == "done":
                    reply_text = event.get("reply_text", "") or ""
                    made_tool_calls = event.get("tool_calls")
                    ui_blocks = event.get("ui_blocks", []) or []
                elif event["type"] == "suggestions_block":
                    # Generated (and yielded by generate_chat_events) AFTER the
                    # visible reply is already complete - see the comment above
                    # generate_suggestions. Captured here, forwarded below,
                    # after the visible "done" frame the client renders first.
                    suggestions = event.get("suggestions") or []
        except Exception:  # noqa: BLE001 - relay a friendly fallback, keep DB clean
            logger.exception(
                "chat_openai_error",
                extra={"conversation_id": conversation.session_token},
            )
            yield _sse({"type": "token", "text": FALLBACK_MESSAGE})
            yield _sse({"type": "done", "reply_text": FALLBACK_MESSAGE, "error": True})
            yield _sse({"type": "suggestions_block", "suggestions": []})
            return

        # Persist the assistant turn (content + any tool calls made).
        session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=reply_text,
                tool_calls=made_tool_calls,
            )
        )
        await session.commit()

        logger.info(
            "chat_response",
            extra={
                "conversation_id": conversation.session_token,
                "reply_chars": len(reply_text),
                "tool_calls": made_tool_calls,
                "ui_blocks": len(ui_blocks),
                "suggestions": len(suggestions),
            },
        )

        yield _sse({"type": "done", "reply_text": reply_text, "ui_blocks": ui_blocks})
        yield _sse({"type": "suggestions_block", "suggestions": suggestions})


@router.get("/chat/suggestions/greeting")
async def greeting_suggestions() -> dict:
    return {"suggestions": GREETING_SUGGESTIONS}


@router.post("/chat")
@limiter.limit(chat_rate_limit)
async def chat(
    request: Request,
    body: ChatRequest,
    client: AsyncOpenAI = Depends(get_openai_client),
    embedding_client: AsyncOpenAI = Depends(get_embedding_client),
) -> StreamingResponse:
    settings = get_settings()
    return StreamingResponse(
        _event_stream(client, settings.llm_model, body, embedding_client),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )