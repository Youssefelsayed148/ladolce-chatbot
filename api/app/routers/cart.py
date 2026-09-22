"""Cart endpoints.

GET /api/cart/{conversation_id} returns the live cart state (the frontend's
source of truth). The review endpoint is implemented in Phase 3.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Conversation
from app.services import cart as cart_service

router = APIRouter(prefix="/api/cart", tags=["cart"])


async def _conversation_or_404(session: AsyncSession, conversation_id: str) -> Conversation:
    result = await session.execute(
        select(Conversation).where(Conversation.session_token == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Unknown conversation.")
    return conversation


@router.get("/{conversation_id}")
async def get_cart(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = await _conversation_or_404(session, conversation_id)
    state = await cart_service.get_cart_state(session, conversation.id)
    return {"conversation_id": conversation_id, **state}


@router.post("/{conversation_id}/review")
async def review_cart(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Lock the draft and return the full itemized order summary (server-side)."""
    conversation = await _conversation_or_404(session, conversation_id)
    draft = await cart_service.get_active_draft(session, conversation.id)
    if draft is None:
        raise HTTPException(status_code=400, detail="No active cart to review.")
    try:
        await cart_service.request_review(session, draft)
    except cart_service.CartError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    summary = await cart_service.build_order_summary(session, draft)
    return {"conversation_id": conversation_id, **summary}
