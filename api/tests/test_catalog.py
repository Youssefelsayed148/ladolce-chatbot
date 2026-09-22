"""Tests for GET /api/products and GET /api/plate-sizes."""

import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import Category, PlateSize, Product


@pytest_asyncio.fixture
async def seeded(prepare_db):
    async with get_sessionmaker()() as session:
        dates = Category(name="Individual Dates", sort_order=0)
        packs = Category(name="Date Packs", sort_order=1)
        session.add_all([dates, packs])
        await session.flush()

        session.add_all(
            [
                Product(category_id=dates.id, name="Ajwa Date", price=6, is_active=True),
                Product(category_id=dates.id, name="Safawi Date", price=6, is_active=True),
                Product(category_id=packs.id, name="Khudri Dates (1kg)", price=160, is_active=True),
                Product(
                    category_id=packs.id,
                    name="Hidden Pack",
                    price=99,
                    is_active=False,  # inactive -> must not appear
                ),
                PlateSize(name="The Classic Petite (350g)", capacity=18, base_price=60),
            ]
        )
        await session.commit()


async def test_list_products_returns_active_only(client, seeded):
    resp = await client.get("/api/products")
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data}
    assert "Ajwa Date" in names
    assert "Khudri Dates (1kg)" in names
    assert "Hidden Pack" not in names  # inactive filtered out
    assert len(data) == 3


async def test_list_products_category_filter(client, seeded):
    resp = await client.get("/api/products", params={"category": "Individual Dates"})
    assert resp.status_code == 200
    data = resp.json()
    assert {p["name"] for p in data} == {"Ajwa Date", "Safawi Date"}
    assert all(p["category"] == "Individual Dates" for p in data)


async def test_list_plate_sizes(client, seeded):
    resp = await client.get("/api/plate-sizes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "The Classic Petite (350g)"
    assert data[0]["capacity"] == 18
    assert data[0]["base_price"] == 60.0


async def test_list_products_empty(client, prepare_db):
    resp = await client.get("/api/products")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_categories_returns_names_in_sort_order(seeded):
    from app.services import catalog as catalog_service

    async with get_sessionmaker()() as session:
        categories = await catalog_service.list_categories(session)
    assert [c.name for c in categories] == ["Individual Dates", "Date Packs"]
