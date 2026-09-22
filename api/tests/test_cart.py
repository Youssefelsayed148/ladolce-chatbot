"""Phase 2 tests: server-side capacity enforcement and price snapshotting.

These exercise the cart service directly (the authoritative logic) plus the tool
dispatcher's structured-error behaviour and the GET /api/cart endpoint.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import (
    CartItem,
    Category,
    Conversation,
    PlateSize,
    Product,
    ProductSlotCost,
)
from app.services import cart as cart_service
from app.services.tools import dispatch_tool


@pytest_asyncio.fixture
async def seeded(prepare_db):
    """Seed a small catalog and a conversation; return the relevant ids."""
    async with get_sessionmaker()() as session:
        cat = Category(name="Individual Dates", sort_order=0)
        session.add(cat)
        await session.flush()

        ajwa = Product(category_id=cat.id, name="Ajwa Date", price=6, is_active=True)
        grand = Product(category_id=cat.id, name="Grand Tart", price=20, is_active=True)
        pack = Product(category_id=cat.id, name="Khudri Pack (1kg)", price=160, is_active=True)
        session.add_all([ajwa, grand, pack])
        await session.flush()

        # Grand Tart occupies 2 slots per unit; others default to 1.
        session.add(ProductSlotCost(product_id=grand.id, slot_cost=2))

        plate = PlateSize(name="Small Box", capacity=3, base_price=60)
        session.add(plate)

        conversation = Conversation(session_token="test-token")
        session.add(conversation)
        await session.commit()

        return {
            "ajwa": ajwa.id,
            "grand": grand.id,
            "pack": pack.id,
            "plate": plate.id,
            "conversation_id": conversation.id,
            "session_token": conversation.session_token,
        }


# --------------------------------------------------------------------------- #
# Capacity enforcement
# --------------------------------------------------------------------------- #
async def test_capacity_exact_fit_allowed(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        # 3 x Ajwa (1 slot each) exactly fills the 3-slot box.
        result = await cart_service.add_item_to_plate(
            session, draft, item_id, seeded["ajwa"], 3
        )
        assert result.data["capacity_used"] == 3
        assert result.data["capacity_total"] == 3


async def test_capacity_exceeded_raises_structured_error(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        await cart_service.add_item_to_plate(session, draft, item_id, seeded["ajwa"], 2)

        # Only 1 slot left; adding a 4th Ajwa must fail, not overfill.
        with pytest.raises(cart_service.CapacityExceeded) as exc_info:
            await cart_service.add_item_to_plate(session, draft, item_id, seeded["ajwa"], 2)

        err = exc_info.value
        assert err.extra["capacity_total"] == 3
        assert err.extra["capacity_used"] == 2
        assert err.extra["available_slots"] == 1
        assert err.extra["requested_slots"] == 2

        # Nothing was added: still only 2 slots used.
        refreshed = await cart_service._get_plate_item(session, draft.id, item_id)
        assert cart_service._plate_slots_used(refreshed) == 2


async def test_slot_cost_multiplier_consumes_multiple_slots(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        # One Grand Tart uses 2 slots (slot_cost=2).
        result = await cart_service.add_item_to_plate(
            session, draft, item_id, seeded["grand"], 1
        )
        assert result.data["capacity_used"] == 2

        # A second Grand Tart would need 2 more slots -> 4 > 3 -> rejected.
        with pytest.raises(cart_service.CapacityExceeded):
            await cart_service.add_item_to_plate(session, draft, item_id, seeded["grand"], 1)


async def test_remove_frees_capacity(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        await cart_service.add_item_to_plate(session, draft, item_id, seeded["grand"], 1)
        removed = await cart_service.remove_item_from_plate(
            session, draft, item_id, seeded["grand"]
        )
        assert removed.data["capacity_used"] == 0


async def test_dispatch_tool_returns_structured_capacity_error(seeded):
    async with get_sessionmaker()() as session:
        conversation = await session.get(Conversation, seeded["conversation_id"])
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        # Overfill via the tool interface: should be a structured error, not a raise.
        # client is None: this tool never needs the OpenAI client.
        result = await dispatch_tool(
            session,
            None,
            conversation,
            draft,
            "add_item_to_plate",
            {"cart_item_id": item_id, "product_id": seeded["ajwa"], "quantity": 99},
        )
        assert "error" in result.data
        assert result.data["available_slots"] == 3


# --------------------------------------------------------------------------- #
# Price snapshotting
# --------------------------------------------------------------------------- #
async def test_single_product_price_snapshot_survives_catalog_change(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        await cart_service.add_single_product(session, draft, seeded["pack"], 2)

        state = await cart_service.get_cart_state_by_draft(session, draft)
        line = next(i for i in state["items"] if i["type"] == "single_product")
        assert line["unit_price"] == 160.0
        assert line["line_total"] == 320.0

        # Catalog price changes AFTER the item is in the cart.
        pack = await session.get(Product, seeded["pack"])
        pack.price = 999
        await session.commit()

        # The in-cart line is unaffected (snapshotted at add-time).
        state_after = await cart_service.get_cart_state_by_draft(session, draft)
        line_after = next(i for i in state_after["items"] if i["type"] == "single_product")
        assert line_after["unit_price"] == 160.0
        assert line_after["line_total"] == 320.0


async def test_custom_plate_price_is_base_plus_fillings(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        # Plate price = base_price + sum(filling unit_price * qty).
        # base 60 + 3 x Ajwa(6) = 78.
        await cart_service.add_item_to_plate(session, draft, item_id, seeded["ajwa"], 3)

        state = await cart_service.get_cart_state_by_draft(session, draft)
        plate_line = next(i for i in state["items"] if i["type"] == "custom_plate")
        assert plate_line["base_price"] == 60.0
        assert plate_line["line_total"] == 78.0
        assert state["total_price"] == 78.0
        # Filling is itemized with its snapshotted price.
        filling = plate_line["contents"][0]
        assert filling["unit_price"] == 6.0
        assert filling["line_total"] == 18.0


async def test_plate_price_tracks_fillings_added_and_removed(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]

        # Empty plate: price is just the base. (Small Box holds 3 slots.)
        empty = await cart_service.get_cart_state_by_draft(session, draft)
        assert next(i for i in empty["items"] if i["type"] == "custom_plate")["line_total"] == 60.0

        # Add 1 x Ajwa(6, 1 slot) -> 60 + 6 = 66; tool result echoes the live price.
        r1 = await cart_service.add_item_to_plate(session, draft, item_id, seeded["ajwa"], 1)
        assert r1.data["plate_price"] == 66.0

        # Add 1 x Grand Tart(20, 2 slots) -> 66 + 20 = 86 (fills all 3 slots).
        r2 = await cart_service.add_item_to_plate(session, draft, item_id, seeded["grand"], 1)
        assert r2.data["plate_price"] == 86.0

        # Remove the Grand Tart -> back down to 66.
        r3 = await cart_service.remove_item_from_plate(session, draft, item_id, seeded["grand"])
        assert r3.data["plate_price"] == 66.0

        # Final cart total reflects the plate at 66.
        state = await cart_service.get_cart_state_by_draft(session, draft)
        assert state["total_price"] == 66.0


async def test_plate_filling_price_is_snapshotted_against_catalog_change(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        started = await cart_service.start_plate(session, draft, seeded["plate"])
        item_id = started.data["cart_item_id"]
        await cart_service.add_item_to_plate(session, draft, item_id, seeded["ajwa"], 2)

        # Catalog price of Ajwa changes after it was added to the plate.
        ajwa = await session.get(Product, seeded["ajwa"])
        ajwa.price = 99
        await session.commit()

        # Plate keeps the add-time snapshot: base 60 + 2 x 6 = 72, not 60 + 2 x 99.
        state = await cart_service.get_cart_state_by_draft(session, draft)
        plate_line = next(i for i in state["items"] if i["type"] == "custom_plate")
        assert plate_line["line_total"] == 72.0


async def test_add_single_product_merges_quantity_keeps_first_snapshot(seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        await cart_service.add_single_product(session, draft, seeded["pack"], 1)

        # Price changes between two adds of the same product.
        pack = await session.get(Product, seeded["pack"])
        pack.price = 999
        await session.commit()

        await cart_service.add_single_product(session, draft, seeded["pack"], 1)

        items = (
            await session.execute(
                select(CartItem).where(CartItem.cart_draft_id == draft.id)
            )
        ).scalars().all()
        # Merged into a single line at the ORIGINAL snapshot price.
        assert len(items) == 1
        assert float(items[0].unit_price) == 160.0
        assert items[0].quantity == 2
        assert float(items[0].line_total) == 320.0


# --------------------------------------------------------------------------- #
# GET /api/cart endpoint
# --------------------------------------------------------------------------- #
async def test_get_cart_endpoint_returns_state(client, seeded):
    async with get_sessionmaker()() as session:
        draft = await cart_service.get_or_create_draft(session, seeded["conversation_id"])
        await cart_service.add_single_product(session, draft, seeded["pack"], 1)

    resp = await client.get(f"/api/cart/{seeded['session_token']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == seeded["session_token"]
    assert body["total_price"] == 160.0
    assert len(body["items"]) == 1


async def test_get_cart_unknown_conversation_404(client, prepare_db):
    resp = await client.get("/api/cart/does-not-exist")
    assert resp.status_code == 404
