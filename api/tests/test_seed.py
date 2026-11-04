"""Tests for the catalog seed script (scripts/seed_catalog.py).

Runs against a synchronous SQLite database, mirroring how the seed script talks
to the DB (a sync Session).
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models import Category, PlateSize, Product

# Import the seed module (api/scripts is not a package).
API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR / "scripts"))
import seed_catalog  # noqa: E402


SAMPLE_PRODUCTS = [
    {
        "name": "Khudri Dates with Almond",
        "name_ar": "تمر خضري باللوز",
        "description": "Premium Khudri dates with almonds.",
        "description_ar": None,
        "price": 120,
        "image_url": "https://example.com/a.png",
        "category": "Stuffed & Flavored Dates",
        "variant": "500g",
    },
    {
        "name": "Khudri Dates with Almond",
        "name_ar": "تمر خضري باللوز",
        "description": "Premium Khudri dates with almonds.",
        "description_ar": None,
        "price": 230,
        "image_url": "https://example.com/a.png",
        "category": "Stuffed & Flavored Dates",
        "variant": "1kg",
    },
    {
        "name": "Ajwa Date",
        "name_ar": None,
        "description": None,
        "description_ar": None,
        "price": 6,
        "image_url": "https://example.com/ajwa.png",
        "category": "Individual Dates",
        "variant": None,
    },
]

SAMPLE_PLATE_SIZES = [
    {
        "title": "The Classic Petite (350g)",
        "base_price": 60,
        "capacity": 18,
        "weight_limit": 350,
        "image_url": "https://example.com/box.png",
    },
]


def _make_session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_populates_categories_products_plate_sizes():
    session = _make_session()
    counts = seed_catalog.seed(session, SAMPLE_PRODUCTS, SAMPLE_PLATE_SIZES)

    assert counts == {"categories": 2, "products": 3, "unpriced_products": 0, "plate_sizes": 1}

    categories = session.execute(select(Category).order_by(Category.sort_order)).scalars().all()
    assert [c.name for c in categories] == ["Stuffed & Flavored Dates", "Individual Dates"]
    # sort_order assigned by first appearance
    assert [c.sort_order for c in categories] == [0, 1]


def test_seed_folds_variant_into_product_name():
    session = _make_session()
    seed_catalog.seed(session, SAMPLE_PRODUCTS, SAMPLE_PLATE_SIZES)

    names = set(session.execute(select(Product.name)).scalars().all())
    # The two weight tiers become two distinct products, variant folded into name.
    assert "Khudri Dates with Almond (500g)" in names
    assert "Khudri Dates with Almond (1kg)" in names
    # Non-variant product keeps its plain name.
    assert "Ajwa Date" in names


def test_seed_plate_size_maps_title_to_name_and_drops_weight_limit():
    session = _make_session()
    seed_catalog.seed(session, SAMPLE_PRODUCTS, SAMPLE_PLATE_SIZES)

    plate = session.execute(select(PlateSize)).scalars().one()
    assert plate.name == "The Classic Petite (350g)"
    assert plate.capacity == 18
    assert float(plate.base_price) == 60.0
    # weight_limit is intentionally not a column (section 3 schema).
    assert not hasattr(plate, "weight_limit")


def test_seed_flags_curated_bestsellers():
    session = _make_session()
    products_data = SAMPLE_PRODUCTS + [
        {
            "name": "The Royal Assortment",
            "name_ar": None,
            "description": None,
            "description_ar": None,
            "price": 450,
            "image_url": "https://example.com/royal.png",
            "category": "Gift Boxes & Trays",
            "variant": None,
        }
    ]
    seed_catalog.seed(session, products_data, SAMPLE_PLATE_SIZES)

    products = {p.name: p for p in session.execute(select(Product)).scalars().all()}
    assert products["The Royal Assortment"].is_bestseller is True
    # Everything not in the curated list stays unflagged.
    assert products["Ajwa Date"].is_bestseller is False
    # Per-piece fillings are never flagged, even if a curated name matches.
    for row in products_data:
        if row["category"] == "Individual Dates":
            assert products[_product_name_of(row)].is_bestseller is False
    assert products["Khudri Dates with Almond (500g)"].is_bestseller is False


def test_seed_marks_priceless_products_inactive():
    # PDF-only menu rows (data/scraped_pdf_products.json, see
    # data/needs_manual_review.json) never had a price captured at all - not
    # even a stale one. Seeding them active would render a product_card with
    # "Add to order" but no visible price, a dead end since
    # cart.add_single_product already rejects a null-priced product. They
    # must be excluded from customer-facing search/browsing until a real
    # price is sourced.
    session = _make_session()
    products_data = SAMPLE_PRODUCTS + [
        {
            "name": "Ajwa Dates",
            "name_ar": None,
            "description": None,
            "description_ar": None,
            "price": None,
            "image_url": None,
            "category": "Plain Dates",
            "variant": None,
        }
    ]
    counts = seed_catalog.seed(session, products_data, SAMPLE_PLATE_SIZES)

    assert counts["unpriced_products"] == 1
    products = {p.name: p for p in session.execute(select(Product)).scalars().all()}
    assert products["Ajwa Dates"].is_active is False
    assert products["Ajwa Dates"].price is None
    # Priced products are unaffected.
    assert products["Ajwa Date"].is_active is True


def test_seed_is_idempotent():
    session = _make_session()
    seed_catalog.seed(session, SAMPLE_PRODUCTS, SAMPLE_PLATE_SIZES)
    seed_catalog.seed(session, SAMPLE_PRODUCTS, SAMPLE_PLATE_SIZES)

    # Re-running does not duplicate rows.
    assert session.execute(select(Product)).scalars().all().__len__() == 3
    assert session.execute(select(Category)).scalars().all().__len__() == 2
    assert session.execute(select(PlateSize)).scalars().all().__len__() == 1


def _product_name_of(row):
    return seed_catalog._product_name(row)


def test_seed_never_flags_individual_dates_even_if_curated_name_matches():
    session = _make_session()
    products_data = SAMPLE_PRODUCTS + [
        {"name": "Golden Sukkari Date", "name_ar": None, "description": None, "description_ar": None,
         "price": 6, "image_url": None, "category": "Individual Dates", "variant": None},
    ]
    seed_catalog.seed(session, products_data, SAMPLE_PLATE_SIZES)
    p = session.execute(select(Product).where(Product.name == "Golden Sukkari Date")).scalar_one()
    assert p.is_bestseller is False
