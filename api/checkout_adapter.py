"""Checkout handoff adapter — the ONE swappable seam to the site's checkout.

This is the only module in the codebase that knows which integration mode is in
use (redirect-with-params vs. a real cart/order API). Nothing else references it
except the confirm endpoint, which calls send_to_checkout() and reacts to the
returned HandoffResult. Phase 4b replaces only the INSIDE of send_to_checkout();
the function signature and HandoffResult shape are the stable contract.

Current implementation (store integration): the cart is replayed into the
store's own cart by the widget, running in the guest's browser with the guest's
own cart token (see web/src/storeCart.ts). The server therefore only logs the
payload and returns the store checkout URL; the order is NOT marked dispatched
here - the widget reports the outcome to POST /api/order/.../handoff-result,
which flips the status to 'sent_to_checkout'. Orders are durably saved first.
"""

import logging
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger("app.checkout")


@dataclass
class HandoffResult:
    """Outcome of a checkout handoff attempt.

    success:       the handoff step completed without error.
    redirect_url:  where to send the browser to finish checkout, if the mode
                   uses a redirect (None otherwise).
    error_message: human-readable failure reason when success is False.
    dispatched:    whether the order was actually transmitted to a live checkout
                   system. Distinguishes "captured but awaiting real integration"
                   (stub: success=True, dispatched=False -> order stays
                   'pending_handoff') from "really sent" (dispatched=True ->
                   'sent_to_checkout'). This lets Phase 4b (redirect OR real API)
                   drive the order status correctly without touching the confirm
                   endpoint.
    """

    success: bool
    redirect_url: str | None = None
    error_message: str | None = None
    dispatched: bool = False


def send_to_checkout(order) -> HandoffResult:
    """Hand a confirmed order off to checkout.

    `order` is the persisted Order (with its handoff_payload). Phase 4b will
    replace the body below with the confirmed integration; do not change the
    signature or the HandoffResult shape.
    """
    logger.info(
        "checkout_handoff",
        extra={
            "order_id": getattr(order, "id", None),
            "total_price": (
                float(order.total_price) if getattr(order, "total_price", None) is not None else None
            ),
            "handoff_payload": getattr(order, "handoff_payload", None),
        },
    )
    return HandoffResult(
        success=True,
        redirect_url=get_settings().store_checkout_url,
        error_message=None,
        dispatched=False,  # flipped by the widget's handoff-result report
    )
