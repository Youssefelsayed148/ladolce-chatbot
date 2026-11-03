"""Server-side price quote from the client store's bespoke-box API.

POST {STORE_API_BASE}/api/bespoke/quote is a read-only quote (no cart/order
write). Returns the store's own `total`, or None if the call fails - callers
fall back to the local canvas base price and log the fallback.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("app.store_quote")

MAX_ITEM_QUANTITY = 99  # the store rejects any single line above this


def split_items(items: list[tuple[str, int]]) -> list[dict]:
    """[(dateId, qty)] -> payload lines, splitting any qty > 99 into several."""
    out: list[dict] = []
    for date_id, qty in items:
        while qty > 0:
            take = min(qty, MAX_ITEM_QUANTITY)
            out.append({"dateId": date_id, "quantity": take})
            qty -= take
    return out


async def quote_box(
    canvas_id: str, items: list[dict], finish_id: str | None = None
) -> float | None:
    body: dict = {"canvasId": canvas_id, "items": items}
    if finish_id:
        body["finishId"] = finish_id
    try:
        async with httpx.AsyncClient(
            base_url=get_settings().store_api_base, timeout=10.0
        ) as client:
            resp = await client.post("/api/bespoke/quote", json=body)
            resp.raise_for_status()
            return float(resp.json()["total"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        logger.warning("store_quote_failed", extra={"error": str(exc), "canvas_id": canvas_id})
        return None
