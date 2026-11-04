"""Single products sold in store variants (size/weight)."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, Product, ProductVariant
from app.services import catalog as catalog_service
from app.services import cart as cart_service
from app.services.tools import dispatch_tool


@pytest_asyncio.fixture
async def shop(prepare_db):
    async with get_sessionmaker()() as s:
        cat = Category(name="Stuffed Dates", sort_order=0)
        s.add(cat)
        await s.flush()
        p = Product(category_id=cat.id, name="Khudri Almond", price=110, is_active=True,
                    store_product_id="p1")
        legacy = Product(category_id=cat.id, name="Legacy Pack", price=30, is_active=True)
        conv = Conversation(session_token="t-var")
        s.add_all([p, legacy, conv])
        await s.flush()
        v1 = ProductVariant(product_id=p.id, store_variant_id="v-500s", sku="A", label="500g / S",
                            price=110, stock=5, is_default=True)
        v2 = ProductVariant(product_id=p.id, store_variant_id="v-1kgl", sku="B", label="1kg / L",
                            price=245, stock=0)
        v3 = ProductVariant(product_id=p.id, store_variant_id="v-1kgs", sku="C", label="1kg / S",
                            price=200, stock=9)
        s.add_all([v1, v2, v3])
        await s.commit()
        draft = await cart_service.get_or_create_draft(s, conv.id)
        return dict(conv=conv.id, draft=draft.id, p=p.id, legacy=legacy.id,
                    v1=v1.id, v2=v2.id, v3=v3.id)


async def _d(s, ids):
    return await cart_service.get_active_draft(s, ids["conv"])


async def test_variant_required_when_several(shop):
    async with get_sessionmaker()() as s:
        d = await _d(s, shop)
        with pytest.raises(cart_service.CartError) as e:
            await cart_service.add_single_product(s, d, shop["p"], 1)
        assert {o["label"] for o in e.value.extra["options"]} == {"500g / S", "1kg / S", "1kg / L"}


async def test_variant_price_label_and_payload_ids(shop):
    async with get_sessionmaker()() as s:
        d = await _d(s, shop)
        r = await cart_service.add_single_product(s, d, shop["p"], 2, shop["v3"])
        line = r.data["cart"]["items"][0]
        assert line["unit_price"] == 200 and line["line_total"] == 400
        assert line["variant_label"] == "1kg / S" and line["store_variant_id"] == "v-1kgs"
        # same variant merges; a different one is its own line
        await cart_service.add_single_product(s, d, shop["p"], 1, shop["v3"])
        r = await cart_service.add_single_product(s, d, shop["p"], 1, shop["v1"])
        items = r.data["cart"]["items"]
        assert [(i["variant_label"], i["quantity"]) for i in items] == [("1kg / S", 3), ("500g / S", 1)]


async def test_out_of_stock_and_quantity_over_stock(shop):
    async with get_sessionmaker()() as s:
        d = await _d(s, shop)
        with pytest.raises(cart_service.CartError, match="out of stock"):
            await cart_service.add_single_product(s, d, shop["p"], 1, shop["v2"])
        with pytest.raises(cart_service.CartError, match="Only 5"):
            await cart_service.add_single_product(s, d, shop["p"], 6, shop["v1"])


async def test_unknown_variant_and_legacy_product(shop):
    async with get_sessionmaker()() as s:
        d = await _d(s, shop)
        with pytest.raises(cart_service.NotFound):
            await cart_service.add_single_product(s, d, shop["p"], 1, 99999)
        r = await cart_service.add_single_product(s, d, shop["legacy"], 1)
        assert "variant_label" not in r.data["cart"]["items"][0]


async def test_search_rows_list_in_stock_variants_and_tool_passes_variant_id(shop):
    async with get_sessionmaker()() as s:
        rows = await catalog_service.search_products(s, "Khudri")
        assert {v["label"] for v in rows[0]["variants"]} == {"500g / S", "1kg / S"}
        d = await _d(s, shop)
        conv = await s.get(Conversation, shop["conv"])
        r = await dispatch_tool(s, None, conv, d, "add_single_product",
                                {"product_id": shop["p"], "quantity": 1, "variant_id": shop["v1"]})
        assert r.data["added"]["variant"] == "500g / S"


async def test_price_zero_single_product_is_blocked(shop):
    """Bespoke-only dates (price 0) are fillings for boxes, never single products."""
    async with get_sessionmaker()() as s:
        zero = Product(category_id=(await s.get(Product, shop["p"])).category_id,
                       name="Bespoke Only Date", price=0, is_active=True)
        s.add(zero)
        await s.commit()
        d = await _d(s, shop)
        with pytest.raises(cart_service.CartError) as e:
            await cart_service.add_single_product(s, d, zero.id, 1)
        assert "not available for purchase" in str(e.value)
        state = await cart_service.get_cart_state_by_draft(s, d)
        assert state["items"] == []


async def test_price_zero_variant_is_blocked(shop):
    async with get_sessionmaker()() as s:
        s.add(ProductVariant(product_id=shop["p"], store_variant_id="v-free", sku="Z",
                             label="Free", price=0, stock=3))
        await s.commit()
        free = (await s.execute(select(ProductVariant).where(ProductVariant.sku == "Z"))).scalar_one()
        d = await _d(s, shop)
        with pytest.raises(cart_service.CartError):
            await cart_service.add_single_product(s, d, shop["p"], 1, free.id)
