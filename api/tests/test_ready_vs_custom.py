"""Ready-made boxes (store products) vs custom boxes (canvases priced by size)."""

import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, PlateSize, Product
from app.services import cart as cart_service
from app.services import catalog as catalog_service
from app.services.tools import dispatch_tool


@pytest_asyncio.fixture
async def shop(prepare_db):
    async with get_sessionmaker()() as s:
        boxes = Category(name="Gift Boxes & Trays", sort_order=0)
        packs = Category(name="Date Packs", sort_order=1)
        s.add_all([boxes, packs])
        await s.flush()
        s.add_all([
            Product(category_id=boxes.id, name="The Royal Assortment", price=450, is_active=True,
                    is_bestseller=True),
            Product(category_id=packs.id, name="Khudri Dates (1kg)", price=160, is_active=True),
            PlateSize(name="Royal Assortment (1000g)", capacity=50, base_price=150,
                      store_canvas_id="c1", kind="BOX", capacity_grams=1000, max_pieces=50),
            PlateSize(name="Small Round Tray (2000g)", capacity=120, base_price=200,
                      store_canvas_id="c2", kind="TRAY", capacity_grams=2000, max_pieces=120),
        ])
        conv = Conversation(session_token="t-rc")
        s.add(conv)
        await s.commit()
        await cart_service.get_or_create_draft(s, conv.id)
        return conv.id


async def test_rows_say_ready_made_or_shop_product(shop):
    async with get_sessionmaker()() as s:
        royal = (await catalog_service.search_products(s, "Royal"))[0]
        assert royal["kind"] == "ready_made_box" and royal["price"] == 450
        pack = (await catalog_service.search_products(s, "Khudri"))[0]
        assert pack["kind"] == "shop_product" and "custom_box_same_name" not in pack


async def test_ready_made_box_points_at_its_custom_twin(shop):
    async with get_sessionmaker()() as s:
        royal = (await catalog_service.search_products(s, "royal assortment"))[0]
        twin = royal["custom_box_same_name"]
        assert twin["price"] == 150 and twin["plate_size_id"]
        assert "build your own" in twin["note"].lower() and "size" in twin["note"].lower()
        # bestsellers too
        best = (await catalog_service.list_bestsellers(s))[0]
        assert best["custom_box_same_name"]["price"] == 150


async def test_plate_sizes_are_labeled_custom_and_priced_by_size(shop):
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, shop)
        d = await cart_service.get_active_draft(s, shop)
        r = await dispatch_tool(s, None, conv, d, "list_plate_sizes", {})
        assert all(p["box_type"] == "custom" for p in r.data["plate_sizes"])
        assert "size" in r.data["note"].lower() and "not the dates" in r.data["note"].lower()
        assert r.ui_blocks[0]["data"]["sizes"][0]["box_type"] == "custom"


def test_prompt_explains_ready_made_vs_custom():
    from app.services.chat import SYSTEM_PROMPT
    low = SYSTEM_PROMPT.lower()
    assert "ready-made" in low and "custom box" in low and "never present a custom box price" in low


async def test_product_card_carries_kind_and_twin(shop):
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, shop)
        d = await cart_service.get_active_draft(s, shop)
        r = await dispatch_tool(s, None, conv, d, "search_products", {"query": "Royal"})
        data = r.ui_blocks[0]["data"]
        assert data["kind"] == "ready_made_box"
        assert data["custom_box_same_name"]["price"] == 150
