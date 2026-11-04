"""Box fillings (individual dates, priced per piece) are never shop products."""

import pytest
import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, PlateSize, Product, ProductVariant
from app.services import cart as cart_service
from app.services import catalog as catalog_service
from app.services.tools import dispatch_tool


@pytest_asyncio.fixture
async def shop(prepare_db):
    async with get_sessionmaker()() as s:
        dates = Category(name="Individual Dates", sort_order=0)
        packs = Category(name="Gourmet Packs", sort_order=1)
        s.add_all([dates, packs])
        await s.flush()
        pack = Product(category_id=packs.id, name="Golden Sukkari Dates (500g)", price=65,
                       is_active=True, is_bestseller=True, store_product_id="p1")
        # Synced filling: has the store date id and a piece weight.
        synced = Product(category_id=dates.id, name="Golden Sukkari Date", price=6, is_active=True,
                         is_bestseller=True, store_date_id="d1", weight_grams=12)
        # Legacy filling: never synced, only its category gives it away.
        legacy = Product(category_id=dates.id, name="Ajwa Date", price=7, is_active=True,
                         is_bestseller=True)
        # Filling that lost its category but keeps the store date id.
        orphan = Product(category_id=None, name="Orphan Date", price=5, is_active=True,
                         store_date_id="d2", weight_grams=10)
        nocat = Product(category_id=None, name="Loose Gift Tin", price=90, is_active=True)
        plate = PlateSize(name="Royal Assortment 150", capacity=50, base_price=150)
        conv = Conversation(session_token="t-fill")
        s.add_all([pack, synced, legacy, orphan, nocat, plate, conv])
        await s.flush()
        s.add(ProductVariant(product_id=pack.id, store_variant_id="v1", sku="A", label="500g",
                             price=65, stock=5, is_default=True))
        await s.commit()
        draft = await cart_service.get_or_create_draft(s, conv.id)
        return dict(conv=conv.id, draft=draft.id, pack=pack.id, synced=synced.id,
                    legacy=legacy.id, orphan=orphan.id, plate=plate.id)


async def _tool(s, shop, name, args):
    conv = await s.get(Conversation, shop["conv"])
    draft = await cart_service.get_active_draft(s, shop["conv"])
    return await dispatch_tool(s, None, conv, draft, name, args)


async def test_bestsellers_exclude_fillings(shop):
    async with get_sessionmaker()() as s:
        rows = await catalog_service.list_bestsellers(s)
        assert [r["name"] for r in rows] == ["Golden Sukkari Dates (500g)"]


async def test_search_excludes_fillings_and_sibling_expansion(shop):
    async with get_sessionmaker()() as s:
        rows = await catalog_service.search_products(s, "Golden Sukkari")
        assert [r["name"] for r in rows] == ["Golden Sukkari Dates (500g)"]
        assert await catalog_service.search_products(s, "Ajwa") == []
        assert await catalog_service.search_products(s, "Orphan") == []
        # products without a category are ordinary shop products
        assert [r["name"] for r in await catalog_service.search_products(s, "Gift Tin")] == ["Loose Gift Tin"]


async def test_search_for_box_returns_fillings_with_weight_and_no_price(shop):
    async with get_sessionmaker()() as s:
        rows = await catalog_service.search_products(s, "Date", for_box=True)
        assert {r["name"] for r in rows} == {"Golden Sukkari Date", "Ajwa Date", "Orphan Date"}
        assert all("price" not in r and r["kind"] == "box_filling" for r in rows)
        assert next(r for r in rows if r["name"] == "Orphan Date")["weight_grams"] == 10


async def test_tools_never_build_cards_for_fillings(shop):
    async with get_sessionmaker()() as s:
        for name, args in (
            ("search_products", {"query": "Date"}),
            ("search_products", {"query": "best sellers"}),
            ("recommend_items", {"preference_notes": "bestsellers"}),
            ("recommend_items", {"preference_notes": "Sukkari"}),
        ):
            r = await _tool(s, shop, name, args)
            names = [b["data"]["name"] for b in r.ui_blocks]
            assert not {"Golden Sukkari Date", "Ajwa Date", "Orphan Date"} & set(names), (name, args)
        r = await _tool(s, shop, "search_products", {"query": "Date", "for_box": True})
        assert r.ui_blocks == [] and len(r.data["results"]) == 3


def test_search_tool_documents_for_box():
    from app.services.tools import SEARCH_PRODUCTS_TOOL
    assert "for_box" in SEARCH_PRODUCTS_TOOL["function"]["parameters"]["properties"]


@pytest.mark.parametrize("key", ["synced", "legacy", "orphan"])
async def test_add_single_product_rejects_fillings(shop, key):
    async with get_sessionmaker()() as s:
        d = await cart_service.get_active_draft(s, shop["conv"])
        with pytest.raises(cart_service.CartError) as e:
            await cart_service.add_single_product(s, d, shop[key], 1)
        assert "only inside a custom box" in str(e.value)
        assert (await cart_service.get_cart_state_by_draft(s, d))["items"] == []


async def test_fillings_still_go_into_a_store_box(shop):
    """add_single_product is blocked, but the box flow keeps using fillings."""
    from app.models import PlateSize
    async with get_sessionmaker()() as s:
        plate = await s.get(PlateSize, shop["plate"])
        plate.store_canvas_id, plate.max_pieces, plate.capacity_grams = "c1", 50, 1000
        await s.commit()
        d = await cart_service.get_active_draft(s, shop["conv"])
        started = await cart_service.start_plate(s, d, shop["plate"])
        cid = started.data["cart_item_id"]
        r = await cart_service.add_item_to_plate(s, d, cid, shop["synced"], 2)
        assert "error" not in r.data
