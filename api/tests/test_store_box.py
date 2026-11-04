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


async def test_card_total_follows_store_quote_with_breakdown(box, monkeypatch):
    """Store charges for the dates: card shows the store total and per-date lines."""
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)

        async def fake(canvas_id, items, finish_id=None):
            return 76.0  # 60 base + 2 x 8

        monkeypatch.setattr(store_quote, "quote_box", fake)
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 2)
        data = r.ui_blocks[0]["data"]
        assert data["price"] == 76.0 and data["price_estimated"] is False
        assert r.data["plate_price"] == 76.0
        line = data["items"][0]
        assert (line["unit_price"], line["line_total"]) == (8.0, 16.0)
        # the cart line total now matches what the store will charge
        state = await cart_service.get_cart_state_by_draft(s, d)
        assert state["total_price"] == 76.0


async def test_card_hides_line_prices_when_store_total_is_base_only(box, monkeypatch):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)

        async def fake(canvas_id, items, finish_id=None):
            return 60.0  # dates free

        monkeypatch.setattr(store_quote, "quote_box", fake)
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 2)
        data = r.ui_blocks[0]["data"]
        assert data["price"] == 60.0
        assert data["items"][0]["unit_price"] == 0.0  # card shows "included"


async def test_card_flags_estimate_when_store_quote_unavailable(box):
    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        r = await cart_service.add_item_to_plate(s, d, box["item"], box["heavy"], 2)  # stub -> None
        data = r.ui_blocks[0]["data"]
        assert data["price"] == 60.0 and data["price_estimated"] is True


async def test_review_and_ribbon_are_done_server_side_even_if_model_does_not_call_tools(box):
    """A model that answers in prose must not be able to block checkout."""
    from app.services.chat import generate_chat_events
    from tests.conftest import FakeOpenAIClient

    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 2)
        conv = await s.get(Conversation, box["conv"])
        events = [
            e async for e in generate_chat_events(
                s, FakeOpenAIClient("plain"), "m", conv, d, [],
                "use the Royal Gold ribbon and review my order",
            )
        ]
        calls = [e["name"] for e in events if e["type"] == "tool_call"]
        assert calls == ["set_finish", "request_review"]
        assert any(e["type"] == "ui_block" and e["block"]["type"] == "review_order_button" for e in events)
        d2 = await _draft(s, box)
        assert d2.status == "reviewed"


async def test_review_without_ribbon_gets_no_button_but_a_real_error_for_the_model(box):
    from app.services.chat import generate_chat_events
    from tests.conftest import FakeOpenAIClient

    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 2)
        conv = await s.get(Conversation, box["conv"])
        fake = FakeOpenAIClient("plain")
        events = [
            e async for e in generate_chat_events(s, fake, "m", conv, d, [], "review my order")
        ]
        assert not any(e["type"] == "ui_block" for e in events)
        # the model's first call saw the tool error (ribbon missing), not a success
        sent = fake.chat.completions.calls[0]["messages"]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert "ribbon" in tool_msgs[0]["content"].lower()


async def test_cart_and_box_dates_context_carry_ids_between_turns(box):
    from app.routers.chat import _box_dates_context, _cart_context

    async with get_sessionmaker()() as s:
        d = await _draft(s, box)
        await cart_service.add_item_to_plate(s, d, box["item"], box["light"], 3)
        cart = await _cart_context(s, d)
        assert f"cart_item_id={box['item']}" in cart
        assert "Ajwa x3" in cart and "7 pieces" in cart and "ribbon: not chosen" in cart
        assert "Totals: subtotal" in cart and "VAT 5%" in cart and "before shipping and promo" in cart
        dates = await _box_dates_context(s)
        assert f"product_id={box['light']}: Ajwa (10g)" in dates
        assert f"product_id={box['heavy']}: Majdool (20g)" in dates
        assert "Pack" not in dates  # not a boxable date


async def test_naming_a_size_starts_that_box_server_side(prepare_db):
    from app.models import PlateSize
    from app.services.chat import generate_chat_events
    from tests.conftest import FakeOpenAIClient

    async with get_sessionmaker()() as s:
        s.add(PlateSize(name="Small Round Tray (2kg)", capacity=120, base_price=200,
                        store_canvas_id="c9", kind="TRAY", capacity_grams=2000, max_pieces=120))
        s.add(PlateSize(name="The Classic Petite (350g)", capacity=18, base_price=60,
                        store_canvas_id="c1", kind="BOX", capacity_grams=350, max_pieces=18))
        conv = Conversation(session_token="t-start")
        s.add(conv)
        await s.commit()
        d = await cart_service.get_or_create_draft(s, conv.id)
        events = [
            e async for e in generate_chat_events(
                s, FakeOpenAIClient("plain"), "m", conv, d, [],
                "I'd like to build a custom box in Small Round Tray (2kg).",
            )
        ]
        calls = [(e["name"], e["arguments"]) for e in events if e["type"] == "tool_call"]
        assert [c[0] for c in calls] == ["start_plate"]
        blocks = [e["block"]["type"] for e in events if e["type"] == "ui_block"]
        assert blocks == ["plate_builder"]  # box card, not a second set of size cards
