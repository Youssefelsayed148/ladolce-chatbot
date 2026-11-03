"""Store custom-box rules: pieces AND grams limits, ribbon, gift message, quote."""

import importlib
import json

import httpx
import pytest
import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, Finish, PlateSize, Product
from app.services import cart as cart_service
from app.services import store_quote
from app.services.tools import dispatch_tool


@pytest_asyncio.fixture
async def box(prepare_db):
    async with get_sessionmaker()() as s:
        cat = Category(name="Individual Dates", sort_order=0)
        s.add(cat)
        await s.flush()
        light = Product(category_id=cat.id, name="Ajwa", price=6, is_active=True,
                        store_date_id="d-light", weight_grams=10)
        heavy = Product(category_id=cat.id, name="Majdool", price=8, is_active=True,
                        store_date_id="d-heavy", weight_grams=20)
        plain = Product(category_id=cat.id, name="Pack", price=50, is_active=True)
        # 10 pieces / 120g: grams bind before pieces for heavy dates.
        plate = PlateSize(name="Test Box", capacity=10, base_price=60, store_canvas_id="c1",
                          kind="BOX", capacity_grams=120, max_pieces=10)
        fin = Finish(store_finish_id="f1", name_en="Royal Gold", sort_order=0)
        conv = Conversation(session_token="t-box")
        s.add_all([light, heavy, plain, plate, fin, conv])
        await s.commit()
        draft = await cart_service.get_or_create_draft(s, conv.id)
        started = await cart_service.start_plate(s, draft, plate.id)
        return dict(conv=conv.id, draft=draft.id, item=started.data["cart_item_id"],
                    light=light.id, heavy=heavy.id, plain=plain.id, fin=fin.id)


async def _draft(s, ids):
    return await cart_service.get_active_draft(s, ids["conv"])


async def test_pieces_limit(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 10)
        assert r.data["remaining_pieces"] == 0 and r.data["grams_used"] == 100
        with pytest.raises(cart_service.CapacityExceeded) as e:
            await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 1)
        assert e.value.extra["remaining_pieces"] == 0


async def test_grams_limit_binds_before_pieces(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        with pytest.raises(cart_service.CapacityExceeded) as e:
            await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 7)  # 140g > 120g
        assert e.value.extra["remaining_grams"] == 120
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 6)  # 120g
        assert r.data["remaining_grams"] == 0 and r.data["remaining_pieces"] == 4


async def test_only_dates_allowed_and_price_stays_base(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        with pytest.raises(cart_service.CartError):
            await cart_service.add_item_to_plate(s, d, box["item"], box["plain"], 1)
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 2)
        assert r.data["plate_price"] == 60.0


async def test_gift_message_trimmed_and_limited(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        r = await cart_service.set_gift_message(s, d, box["item"], "  Happy Eid  ")
        assert r.data["gift_message"] == "Happy Eid"
        with pytest.raises(cart_service.CartError):
            await cart_service.set_gift_message(s, d, box["item"], "x" * 181)
        r = await cart_service.set_gift_message(s, d, box["item"], "x" * 180)
        assert len(r.data["gift_message"]) == 180


async def test_review_requires_contents_and_finish(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        with pytest.raises(cart_service.CartError, match="empty"):
            await cart_service.request_review(s, d)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 2)
        with pytest.raises(cart_service.CartError, match="ribbon"):
            await cart_service.request_review(s, d)
        await cart_service.set_finish(s, d, box["item"], box["fin"])
        r = await cart_service.request_review(s, d)
        assert r.data["status"] == "reviewed"


async def test_review_uses_store_quote(box, monkeypatch):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 2)
        await cart_service.set_finish(s, d, box["item"], box["fin"])
        seen = {}

        async def fake(canvas_id, items, finish_id=None):
            seen.update(canvas_id=canvas_id, items=items, finish_id=finish_id)
            return 75.0

        monkeypatch.setattr(store_quote, "quote_box", fake)
        await cart_service.request_review(s, d)
        state = await cart_service.get_cart_state_by_draft(s, d)
        assert state["total_price"] == 75.0
        assert seen == {"canvas_id": "c1", "items": [{"dateId": "d-light", "quantity": 2}],
                        "finish_id": "f1"}
        assert state["items"][0]["finish"] == "Royal Gold"


async def test_review_falls_back_to_base_price_when_quote_fails(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 2)
        await cart_service.set_finish(s, d, box["item"], box["fin"])
        await cart_service.request_review(s, d)  # conftest stub -> None
        assert (await cart_service.get_cart_state_by_draft(s, d))["total_price"] == 60.0


async def test_tools_set_finish_and_gift_message(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        conv = await s.get(Conversation, box["conv"])
        r = await dispatch_tool(s, None, conv, d, "set_finish",
                                {"cart_item_id": box["item"], "finish_id": box["fin"]})
        assert r.data["finish"] == "Royal Gold"
        r = await dispatch_tool(s, None, conv, d, "set_gift_message",
                                {"cart_item_id": box["item"], "message": "Hi"})
        assert r.data["gift_message"] == "Hi"


def test_split_items_caps_quantity_at_99():
    assert store_quote.split_items([("a", 250), ("b", 5)]) == [
        {"dateId": "a", "quantity": 99}, {"dateId": "a", "quantity": 99},
        {"dateId": "a", "quantity": 52}, {"dateId": "b", "quantity": 5}]


async def test_quote_client_success_and_failure(monkeypatch):
    # Fresh module so the conftest stub on quote_box doesn't apply.
    real = importlib.reload(store_quote).quote_box
    sent = {}

    def handler(request: httpx.Request):
        sent["body"] = json.loads(request.content)
        sent["url"] = str(request.url)
        return httpx.Response(201, json={"total": 160, "currency": "AED"})

    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    total = await real("c1", [{"dateId": "d", "quantity": 2}], "f1")
    assert total == 160.0
    assert sent["url"].endswith("/api/bespoke/quote")
    assert sent["body"] == {"canvasId": "c1", "items": [{"dateId": "d", "quantity": 2}],
                            "finishId": "f1"}

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "no"})), **kw))
    assert await real("c1", []) is None
