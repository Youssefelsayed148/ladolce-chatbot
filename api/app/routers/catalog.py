"""Catalog browsing endpoints — GET /api/products, GET /api/plate-sizes.

Read straight from Postgres (seeded from data/unique_products.json and
data/scraped_plate_sizes.json). /api/products takes an optional ?category filter.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services import catalog

router = APIRouter(prefix="/api", tags=["catalog"])


class ProductOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    price: float | None = None
    image_url: str | None = None
    category: str | None = None
    is_single_item: bool = True

    model_config = {"from_attributes": True}


class PlateSizeOut(BaseModel):
    id: int
    name: str
    capacity: int
    base_price: float
    image_url: str | None = None

    model_config = {"from_attributes": True}


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[ProductOut]:
    products = await catalog.list_products(session, category=category)
    return [
        ProductOut(
            id=p.id,
            name=p.name,
            description=p.description,
            price=float(p.price) if p.price is not None else None,
            image_url=p.image_url,
            category=p.category.name if p.category else None,
            is_single_item=p.is_single_item,
        )
        for p in products
    ]


@router.get("/plate-sizes", response_model=list[PlateSizeOut])
async def list_plate_sizes(
    session: AsyncSession = Depends(get_session),
) -> list[PlateSizeOut]:
    sizes = await catalog.list_plate_sizes(session)
    return [
        PlateSizeOut(
            id=s.id,
            name=s.name,
            capacity=s.capacity,
            base_price=float(s.base_price),
            image_url=s.image_url,
        )
        for s in sizes
    ]
