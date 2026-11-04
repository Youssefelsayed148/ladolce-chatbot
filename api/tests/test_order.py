"""Phase 3 tests: request_review idempotency, review totals, confirm validation,
and handoff_payload completeness."""

import pytest_asyncio
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import CartDraft, Category, Conversation, Order, PlateSize, Product
from app.services import cart as cart_service


@pytest_asyncio.fixture
async def cart_ready(prepare_db):
    """Seed a catalog and build a cart (one single product + one custom plate)."""
    async with get_sessionmaker()() as session:
        cat = Category(name="Individual Dates", sort_order=0)
        session.add(cat)
        await session.flush()

        ajwa = Product(category_id=cat.id, name="Ajwa Date", price=6, is_active=True)
        packs = Category(name="Date Packs", sort_order=1)
        session.add(packs)
        await session.flush()
        pack = Product(category_id=packs.id, name="Khudri Pack (1kg)", price=160, is_active=True)
        session.add_all([ajwa, pack])
        await session.flush()

        plate = PlateSize(name="Small Box", capacity=10, base_price=60)
        session.add(plate)

        conversation = Conversation(session_token="order-token")
        session.add(conversation)
        await session.commit()

        draft = await cart_service.get_or_create_draft(session, conversation.id)
        await cart_service.add_single_product(session, draft, pack.id, 2)  # 2 x 160 = 320
        started = await cart_service.start_plate(session, draft, plate.id)  # base 60
        await cart_service.add_item_to_plate(
            session, draft, started.data["cart_item_id"], ajwa.id, 3
        )

        return {
            "session_token": conversation.session_token,
            "conversation_id": conversation.id,
            "ajwa": ajwa.id,
            "pack": pack.id,
            "expected_total": 398.0,  # 320 (pack) + 78 (plate: base 60 + 3 x Ajwa 6)
        }


async def test_request_review_is_idempotent(cart_ready):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_active_draft(session, cart_ready["conversation_id"])
        r1 = await cart_service.request_review(session, draft)
        r2 = await cart_service.request_review(session, draft)

        assert r1.data["status"] == "reviewed"
        assert r2.data["status"] == "reviewed"
        assert r1.ui_blocks == r2.ui_blocks  # same review_order_button, not duplicated

        drafts = (
            await session.execute(
                select(CartDraft).where(
                    CartDraft.conversation_id == cart_ready["conversation_id"]
                )
            )
        ).scalars().all()
        assert len(drafts) == 1
        assert drafts[0].status == "reviewed"


async def test_review_endpoint_returns_accurate_totals(client, cart_ready):
    resp = await client.post(f"/api/cart/{cart_ready['session_token']}/review")
    assert resp.status_code == 200
    summary = resp.json()

    assert summary["status"] == "reviewed"
    assert summary["total_price"] == cart_ready["expected_total"]

    # Line totals sum to the grand total.
    assert round(sum(i["line_total"] for i in summary["items"]), 2) == summary["total_price"]
    # Both a single product and a custom plate are present.
    types = {i["type"] for i in summary["items"]}
    assert types == {"single_product", "custom_plate"}


async def test_confirm_requires_review_first(client, cart_ready):
    # Not reviewed yet -> confirm rejected with a clear error.
    resp = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    assert resp.status_code == 409
    assert "reviewed" in resp.json()["detail"].lower()


async def test_confirm_creates_pending_handoff_order(client, cart_ready):
    await client.post(f"/api/cart/{cart_ready['session_token']}/review")
    resp = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_handoff"
    assert body["total_price"] == cart_ready["expected_total"]
    order_id = body["order_id"]

    async with get_sessionmaker()() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == "pending_handoff"

        # Draft is now terminal (confirmed).
        draft = await session.get(CartDraft, order.cart_draft_id)
        assert draft.status == "confirmed"


async def test_confirm_is_not_repeatable(client, cart_ready):
    await client.post(f"/api/cart/{cart_ready['session_token']}/review")
    first = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    assert first.status_code == 200
    # Second confirm: draft is confirmed (terminal), so there's no reviewed cart.
    second = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    assert second.status_code == 409

    async with get_sessionmaker()() as session:
        orders = (await session.execute(select(Order))).scalars().all()
        assert len(orders) == 1  # no duplicate order


async def test_handoff_payload_is_complete_and_accurate(client, cart_ready):
    await client.post(f"/api/cart/{cart_ready['session_token']}/review")
    resp = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    order_id = resp.json()["order_id"]

    async with get_sessionmaker()() as session:
        order = await session.get(Order, order_id)
        payload = order.handoff_payload

        assert payload["conversation_id"] == cart_ready["session_token"]
        assert payload["cart_draft_id"] == order.cart_draft_id
        assert payload["total_price"] == cart_ready["expected_total"]
        assert float(order.total_price) == payload["total_price"]

        # Items carry full detail for both line types.
        single = next(i for i in payload["items"] if i["type"] == "single_product")
        assert single["quantity"] == 2
        assert single["unit_price"] == 160.0
        assert single["line_total"] == 320.0

        plate = next(i for i in payload["items"] if i["type"] == "custom_plate")
        assert plate["base_price"] == 60.0
        assert plate["line_total"] == 78.0  # base 60 + 3 x Ajwa 6
        assert plate["capacity_used"] == 3
        assert len(plate["contents"]) == 1
        assert plate["contents"][0]["unit_price"] == 6.0
        assert plate["contents"][0]["line_total"] == 18.0


async def test_modifying_reviewed_cart_reverts_and_blocks_confirm(client, cart_ready):
    await client.post(f"/api/cart/{cart_ready['session_token']}/review")

    # Modify the cart after review -> review is invalidated (status back to building).
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_active_draft(session, cart_ready["conversation_id"])
        await cart_service.add_single_product(session, draft, cart_ready["pack"], 1)
        assert draft.status == "building"

    # Confirm now blocked until re-review.
    resp = await client.post(f"/api/order/{cart_ready['session_token']}/confirm")
    assert resp.status_code == 409
