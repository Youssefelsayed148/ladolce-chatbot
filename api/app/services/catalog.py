"""Catalog queries — the source of truth for products and plate sizes.

Also hosts `search_products`, which backs the LLM tool of the same name. The
model calls the tool with a free-text query; the backend runs the actual DB
search and returns authoritative rows (name/price/category) — the model never
invents catalog data.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, PlateSize, Product

# Many date varieties in this catalog exist as two (or three) separate product
# rows: a per-piece entry in "Individual Dates" (e.g. "Golden Sukkari Date",
# used for box-building) and one row per weight tier in "Date Packs" /
# "Stuffed & Flavored Dates" (e.g. "Golden Sukkari Dates (500g)" and "...
# (1kg)"), since the products table has no `variant` column - the seed script
# folds the tier into the name instead (see seed_catalog.py's _product_name).
# A free-text query like "Golden Sukkari Date(s)" can therefore
# substring-match only one of these near-duplicates depending on the exact
# wording/pluralization the model happens to send, and a plain alphabetical
# ORDER BY then arbitrarily favours whichever sorts first (the shortest,
# unqualified name) - silently answering with the wrong product/price. This
# regex strips the parenthetical weight tag so all of a variety's rows
# normalize to the same key regardless of which one was actually matched.
_VARIANT_SUFFIX_RE = re.compile(r"\s*\(\d+(?:\.\d+)?\s*(?:g|kg)\)\s*$", re.IGNORECASE)


def _normalized_base_name(name: str) -> str:
    """Collapse a product name to a variety key: strip the weight-tier suffix,
    then a trailing plural 's', so "Golden Sukkari Date", "Golden Sukkari
    Dates (500g)", and "Golden Sukkari Dates (1kg)" all collapse to the same
    string. Used only to detect cross-category near-duplicates - never shown
    to the guest or the model."""
    base = _VARIANT_SUFFIX_RE.sub("", name).strip().lower()
    return base[:-1] if base.endswith("s") else base


async def list_products(
    session: AsyncSession, category: str | None = None
) -> list[Product]:
    stmt = select(Product).where(Product.is_active.is_(True))
    if category:
        stmt = stmt.join(Category).where(Category.name == category)
    # Eager-load category: it's read after the query (p.category.name), which
    # would trigger a forbidden lazy load under async otherwise.
    stmt = stmt.options(selectinload(Product.category)).order_by(Product.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_plate_sizes(session: AsyncSession) -> list[PlateSize]:
    stmt = select(PlateSize).order_by(PlateSize.base_price)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_categories(session: AsyncSession) -> list[Category]:
    stmt = select(Category).order_by(Category.sort_order)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _row_from_product(p: Product) -> dict:
    return {
        # product_id is included so the model can reference the item in
        # follow-up cart tools (add_single_product, add_item_to_plate).
        "product_id": p.id,
        "name": p.name,
        "description": p.description,
        "price": float(p.price) if p.price is not None else None,
        "category": p.category.name if p.category else None,
    }


async def _cross_category_siblings(
    session: AsyncSession, products: list[Product]
) -> list[Product]:
    """Given already-matched products, find other active products (in a
    different category) that normalize to the same variety key - the
    "Golden Sukkari Date" vs "Golden Sukkari Dates (500g)/(1kg)" case - and
    weren't already matched. See module note above _normalized_base_name."""
    base_names = {_normalized_base_name(p.name) for p in products}
    if not base_names:
        return []
    seen_ids = {p.id for p in products}
    stmt = select(Product).where(Product.is_active.is_(True)).options(
        selectinload(Product.category)
    )
    result = await session.execute(stmt)
    return [
        p
        for p in result.scalars().all()
        if p.id not in seen_ids and _normalized_base_name(p.name) in base_names
    ]


async def search_products(
    session: AsyncSession,
    query: str,
    category: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Fuzzy-ish product search for the LLM tool. Case-insensitive substring
    match over name + description; optional category filter. Returns plain dicts
    (what gets handed back to the model as the tool result).

    A free-text (non category-scoped) query can resolve to a product that has
    a same-variety sibling in another category - sold individually vs sold by
    weight (see the module note above _normalized_base_name). Rather than
    silently returning whichever one the raw match/alphabetical order
    happened to surface, every sibling is added to the result set so the
    concierge sees (and can present) all of them instead of guessing which
    the guest meant - "server is authoritative, don't guess" applies to
    disambiguation, not just pricing/capacity math."""
    stmt = select(Product).where(Product.is_active.is_(True))

    term = (query or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            Product.name.ilike(like) | Product.description.ilike(like)
        )
    if category:
        stmt = stmt.join(Category).where(Category.name == category)

    stmt = stmt.options(selectinload(Product.category)).order_by(Product.name).limit(limit)
    result = await session.execute(stmt)
    products = list(result.scalars().all())

    if term and not category and products:
        products = products + await _cross_category_siblings(session, products)

    # Rank an exact (case-insensitive) name match first - it's still the best
    # single signal available - but, unlike the old plain alphabetical order,
    # this no longer determines which products are RETURNED, only which one
    # is listed first among them.
    term_lower = term.lower()
    products.sort(key=lambda p: (p.name.lower() != term_lower, p.name))

    return [_row_from_product(p) for p in products]


async def list_bestsellers(session: AsyncSession, limit: int = 6) -> list[dict]:
    """Curated bestsellers (products.is_bestseller, seeded by
    scripts/seed_catalog.py) - a structural flag rather than a free-text
    search, so "what are your bestsellers" doesn't depend on that literal
    phrase substring-matching a product's name/description (it never would)."""
    stmt = (
        select(Product)
        .where(Product.is_active.is_(True), Product.is_bestseller.is_(True))
        .options(selectinload(Product.category))
        .order_by(Product.name)
        .limit(limit)
    )
    result = await session.execute(stmt)
    products = result.scalars().all()
    return [_row_from_product(p) for p in products]
