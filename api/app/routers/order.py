"""Order confirmation — POST /api/order/{conversation_id}/confirm.

Phase 3: validates the draft has been reviewed, snapshots the full order into an
`orders` row (status 'pending_handoff') with the complete handoff_payload, and
marks the draft 'confirmed'. No checkout call is made here yet - the swappable
checkout adapter is wired in Phase 4.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import checkout_adapter
from app.core.db import get_session
from app.models import Conversation, Order
from app.services import cart as cart_service

logger = logging.getLogger("app.order")

router = APIRouter(prefix="/api/order", tags=["order"])


async def _conversation_or_404(session: AsyncSession, conversation_id: str) -> Conversation:
    result = await session.execute(
        select(Conversation).where(Conversation.session_token == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Unknown conversation.")
    return conversation


@router.post("/{conversation_id}/confirm")
async def confirm_order(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = await _conversation_or_404(session, conversation_id)
    draft = await cart_service.get_active_draft(session, conversation.id, for_update=True)

    if draft is None or draft.status != "reviewed":
        raise HTTPException(
            status_code=409,
            detail="The cart must be reviewed before it can be confirmed.",
        )

    payload = await cart_service.build_handoff_payload(session, conversation, draft)

    # 1. Persist the order FIRST so it's durably captured no matter what the
    #    checkout handoff does (section 7: nothing is ever lost).
    order = Order(
        cart_draft_id=draft.id,
        conversation_id=conversation.id,
        status="pending_handoff",
        total_price=payload["total_price"],
        handoff_payload=payload,
    )
    session.add(order)
    draft.status = "confirmed"
    await session.commit()
    await session.refresh(order)

    logger.info(
        "order_confirmed",
        extra={
            "conversation_id": conversation_id,
            "order_id": order.id,
            "status": order.status,
            "total_price": float(order.total_price),
        },
    )

    # 2. Hand off to checkout via the swappable adapter. On any failure the order
    #    stays 'pending_handoff' (already safely saved) and we surface a soft
    #    error - the frontend still shows "order saved", never a dead end.
    redirect_url: str | None = None
    handoff_error: str | None = None
    try:
        result = checkout_adapter.send_to_checkout(order)
    except Exception:  # noqa: BLE001 - adapter must never break a saved order
        logger.exception("checkout_handoff_exception", extra={"order_id": order.id})
        result = checkout_adapter.HandoffResult(
            success=False, error_message="Checkout handoff failed unexpectedly."
        )

    if result.success and result.dispatched:
        order.status = "sent_to_checkout"
        await session.commit()
        await session.refresh(order)
    elif not result.success:
        handoff_error = result.error_message or "Checkout handoff was not completed."

    redirect_url = result.redirect_url

    logger.info(
        "order_handoff_result",
        extra={
            "order_id": order.id,
            "status": order.status,
            "success": result.success,
            "dispatched": result.dispatched,
            "has_redirect": redirect_url is not None,
        },
    )

    return {
        "conversation_id": conversation_id,
        "order_id": order.id,
        "status": order.status,
        "total_price": float(order.total_price),
        "redirect_url": redirect_url,
        "handoff_error": handoff_error,
    }
