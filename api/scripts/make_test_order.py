"""Build a REVIEWED test cart in the local DB and print its conversation token.

Used for the live-store widget test (docs/deploy.md, "Live-store test"): set the
printed token as localStorage.ladolce_conversation_id on the store page, inject
widget.js, then press Confirm. Nothing is confirmed or sent here; the review
step does call the store's read-only quote endpoint.

Run from api/:  python scripts/make_test_order.py [--single]
The gift message is labelled TEST so the box is obvious in the store's cart.
"""

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import get_sessionmaker  # noqa: E402
from app.models import Conversation, PlateSize, Product  # noqa: E402
from app.services import cart as cart_service  # noqa: E402

BOX_NAME = "The Classic Petite (350g)"
FILLINGS = [("Ajwa Date", 12), ("Golden Sukkari Date", 6)]  # 18 pcs, 180 g
GIFT = "TEST ORDER - DO NOT PREPARE"


async def main(with_single: bool) -> None:
    async with get_sessionmaker()() as s:
        token = f"test-{secrets.token_hex(6)}"
        conv = Conversation(session_token=token)
        s.add(conv)
        await s.commit()
        draft = await cart_service.get_or_create_draft(s, conv.id)

        plate = (await s.execute(select(PlateSize).where(PlateSize.name == BOX_NAME))).scalar_one()
        started = await cart_service.start_plate(s, draft, plate.id)
        item_id = started.data["cart_item_id"]
        for name, qty in FILLINGS:
            prod = (await s.execute(select(Product).where(Product.name == name))).scalar_one()
            await cart_service.add_item_to_plate(s, draft, item_id, prod.id, qty)
        await cart_service.set_finish(s, draft, item_id, 3)  # Royal Gold
        await cart_service.set_gift_message(s, draft, item_id, GIFT)
        if with_single:
            await cart_service.add_single_product(s, draft, *(await _single(s)))
        await cart_service.request_review(s, draft)
        state = await cart_service.get_cart_state_by_draft(s, draft)
        print("status:", draft.status, "total:", state["total_price"], file=sys.stderr)
        print(token)


async def _single(s):
    from app.models import ProductVariant

    v = (
        await s.execute(
            select(ProductVariant).where(ProductVariant.stock > 0).order_by(ProductVariant.price)
        )
    ).scalars().first()
    return v.product_id, 1, v.id


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", action="store_true", help="also add the cheapest in-stock variant")
    asyncio.run(main(ap.parse_args().single))
