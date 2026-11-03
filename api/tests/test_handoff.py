"""Store handoff: store_lines in the confirm response + handoff-result report."""

import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import (
    Category, Conversation, Finish, Order, PlateSize, Product, ProductVariant,
)
from app.services import cart as cart_service


@pytest_asyncio.fixture
async def ready(prepare_db):
    async with get_sessionmaker()() as s:
        cat = Category(name="Individual Dates", sort_order=0)
        s.add(cat)
        await s.flush()
        pack = Product(category_id=cat.id, name="Khudri Almond", price=110, is_active=True)
        date = Product(category_id=cat.id, name="Ajwa", price=6, is_active=True,
                       store_date_id="date-1", weight_grams=10)
        plate = PlateSize(name="Box", capacity=200, base_price=60, store_canvas_id="canvas-1",
                          kind="BOX", capacity_grams=5000, max_pieces=200)
        fin = Finish(store_finish_id="fin-1", name_en="Royal Gold")
        conv = Conversation(session_token="hand-token")
        other = Conversation(session_token="other-token")
        s.add_all([pack, date, plate, fin, conv, other])
        await s.flush()
        var = ProductVariant(product_id=pack.id, store_variant_id="var-1", label="500g / S",
                             price=110, stock=50, is_default=True)
        s.add(var)
        await s.commit()
        d = await cart_service.get_or_create_draft(s, conv.id)
        await cart_service.add_single_product(s, d, pack.id, 2)
        started = await cart_service.start_plate(s, d, plate.id)
        item = started.data["cart_item_id"]
        await cart_service.add_item_to_plate(s, d, item, date.id, 150)  # splits 99 + 51
        await cart_service.set_finish(s, d, item, fin.id)
        await cart_service.set_gift_message(s, d, item, "Happy Eid")
        await cart_service.request_review(s, d)
        return {"token": "hand-token"}


async def test_confirm_returns_store_lines(client, ready):
    body = (await client.post(f"/api/order/{ready['token']}/confirm")).json()
    lines = body["store_lines"]
    assert lines[0] == {"kind": "single", "variantId": "var-1", "quantity": 2, "name": "Khudri Almond"}
    assert lines[1]["kind"] == "bespoke" and lines[1]["canvasId"] == "canvas-1"
    assert lines[1]["finishId"] == "fin-1" and lines[1]["giftMessage"] == "Happy Eid"
    assert sum(i["quantity"] for i in lines[1]["items"]) == 150
    assert all(i["quantity"] <= 99 for i in lines[1]["items"])


async def test_handoff_result_success_marks_sent(client, ready):
    order_id = (await client.post(f"/api/order/{ready['token']}/confirm")).json()["order_id"]
    r = await client.post(f"/api/order/{ready['token']}/{order_id}/handoff-result",
                          json={"success": True})
    assert r.status_code == 200 and r.json()["status"] == "sent_to_checkout"
    async with get_sessionmaker()() as s:
        order = await s.get(Order, order_id)
        assert order.status == "sent_to_checkout"
        assert order.handoff_payload["handoff_result"]["success"] is True


async def test_handoff_result_failure_keeps_order_pending(client, ready):
    order_id = (await client.post(f"/api/order/{ready['token']}/confirm")).json()["order_id"]
    r = await client.post(f"/api/order/{ready['token']}/{order_id}/handoff-result",
                          json={"success": False, "failed_items": ["Khudri Almond"], "error": "stock"})
    assert r.json()["status"] == "pending_handoff"
    async with get_sessionmaker()() as s:
        order = await s.get(Order, order_id)
        assert order.handoff_payload["handoff_result"]["failed_items"] == ["Khudri Almond"]
        assert order.handoff_payload["items"]  # original payload kept


async def test_handoff_result_rejects_other_conversation(client, ready):
    order_id = (await client.post(f"/api/order/{ready['token']}/confirm")).json()["order_id"]
    r = await client.post(f"/api/order/other-token/{order_id}/handoff-result", json={"success": True})
    assert r.status_code == 404
