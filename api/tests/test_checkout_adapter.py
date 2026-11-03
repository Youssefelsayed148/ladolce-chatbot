"""Phase 4a tests: the swappable checkout adapter and its wiring into confirm.

Covers the stub behaviour plus both success (dispatched) and failure paths
through the adapter interface, mocking send_to_checkout - never hitting a live
site.
"""

import pytest_asyncio

import checkout_adapter
from app.core.db import get_sessionmaker
from app.models import (
    Category,
    Conversation,
    Order,
    PlateSize,
    Product,
)
from app.services import cart as cart_service


@pytest_asyncio.fixture
async def reviewed_cart(prepare_db):
    """Seed a catalog, build a cart, and mark it reviewed (ready to confirm)."""
    async with get_sessionmaker()() as session:
        cat = Category(name="Individual Dates", sort_order=0)
        session.add(cat)
        await session.flush()
        pack = Product(category_id=cat.id, name="Khudri Pack (1kg)", price=160, is_active=True)
        session.add(pack)
        session.add(PlateSize(name="Small Box", capacity=10, base_price=60))
        conversation = Conversation(session_token="checkout-token")
        session.add(conversation)
        await session.commit()

        draft = await cart_service.get_or_create_draft(session, conversation.id)
        await cart_service.add_single_product(session, draft, pack.id, 1)
        await cart_service.request_review(session, draft)

        return {"session_token": conversation.session_token}


class _FakeOrder:
    id = 42
    total_price = 160
    handoff_payload = {"total_price": 160.0, "items": []}


# --------------------------------------------------------------------------- #
# The stub in isolation
# --------------------------------------------------------------------------- #
def test_stub_reports_saved_but_not_dispatched():
    result = checkout_adapter.send_to_checkout(_FakeOrder())
    assert result.success is True
    assert result.dispatched is False
    # The widget fills the store cart; the server just points at the checkout page.
    assert result.redirect_url == "https://ladolcesaveur.com/checkout"
    assert result.error_message is None


# --------------------------------------------------------------------------- #
# Wiring into confirm
# --------------------------------------------------------------------------- #
async def test_confirm_with_stub_stays_pending_handoff(client, reviewed_cart):
    resp = await client.post(f"/api/order/{reviewed_cart['session_token']}/confirm")
    assert resp.status_code == 200
    body = resp.json()
    # Not dispatched until the widget reports back -> stays pending_handoff.
    assert body["status"] == "pending_handoff"
    assert body["redirect_url"] == "https://ladolcesaveur.com/checkout"
    assert body["store_lines"] == []  # legacy product without a store variant
    assert body["handoff_error"] is None


async def test_confirm_marks_sent_to_checkout_when_dispatched(
    client, reviewed_cart, monkeypatch
):
    def fake_send(order):
        return checkout_adapter.HandoffResult(
            success=True, redirect_url="https://shop.example/checkout/abc", dispatched=True
        )

    monkeypatch.setattr(checkout_adapter, "send_to_checkout", fake_send)

    resp = await client.post(f"/api/order/{reviewed_cart['session_token']}/confirm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "sent_to_checkout"
    assert body["redirect_url"] == "https://shop.example/checkout/abc"

    async with get_sessionmaker()() as session:
        order = await session.get(Order, body["order_id"])
        assert order.status == "sent_to_checkout"


async def test_confirm_adapter_failure_keeps_order_saved(client, reviewed_cart, monkeypatch):
    def fake_send(order):
        return checkout_adapter.HandoffResult(
            success=False, error_message="Checkout API unreachable."
        )

    monkeypatch.setattr(checkout_adapter, "send_to_checkout", fake_send)

    resp = await client.post(f"/api/order/{reviewed_cart['session_token']}/confirm")
    # No dead end: the order is saved, a soft error is surfaced.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_handoff"
    assert body["handoff_error"] == "Checkout API unreachable."

    async with get_sessionmaker()() as session:
        order = await session.get(Order, body["order_id"])
        assert order is not None  # order still durably captured
        assert order.status == "pending_handoff"


async def test_confirm_adapter_exception_is_handled(client, reviewed_cart, monkeypatch):
    def boom(order):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(checkout_adapter, "send_to_checkout", boom)

    resp = await client.post(f"/api/order/{reviewed_cart['session_token']}/confirm")
    # The saved order must not be lost to an adapter crash.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_handoff"
    assert body["handoff_error"] is not None

    async with get_sessionmaker()() as session:
        order = await session.get(Order, body["order_id"])
        assert order.status == "pending_handoff"
