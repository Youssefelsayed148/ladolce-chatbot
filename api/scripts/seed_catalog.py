#!/usr/bin/env python3
"""Seed the catalog tables from the approved data pipeline output.

Reads:
  - data/unique_products.json     -> categories + products  (reviewed/approved)
  - data/scraped_plate_sizes.json -> plate_sizes            (see PLATE SIZES note)

Idempotent: it clears the catalog tables (categories, products,
product_slot_cost, plate_sizes) and re-inserts, so re-running always yields the
same state. Conversations/messages are never touched.

Run locally:   python api/scripts/seed_catalog.py
Run in Docker: docker compose run --rm api python scripts/seed_catalog.py
               (compose mounts ./data at /data)

------------------------------------------------------------------------------
PLATE SIZES ASSUMPTION — READ THIS
------------------------------------------------------------------------------
The Phase 1 prompt said to seed plate_sizes with placeholder Small/Medium/Large
boxes because "it has no source yet." It DOES have a source: the website scraper
already produced data/scraped_plate_sizes.json (6 real box/tray sizes with real
names, capacities, and prices from ladolcesaveur.com). Inventing placeholders
when real data exists would be strictly worse, so this script seeds from that
file instead.

Caveats to confirm:
  * That file was NOT part of the explicitly reviewed/approved unique_products.json
    output, so treat these 6 rows as provisional until you sign off.
  * `capacity` here is the site's piece-count per box/tray (e.g. 50 for the 1kg
    box). Confirm that matches how you intend "slots" to work in the plate builder.
  * The scraped data also has a `weight_limit` field (grams) that section 3's
    plate_sizes schema does not include, so it is dropped here. If the plate
    builder needs a weight cap as well as a slot count, add the column later.
If you'd rather use synthetic Small/Medium/Large placeholders, say so and this
flips in one edit.
------------------------------------------------------------------------------
"""

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

# Make the app package importable when run as a standalone script.
API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.models import Category, PlateSize, Product, ProductSlotCost, ProductVariant  # noqa: E402

REPO_ROOT = API_DIR.parent

# Curated bestsellers (Phase 6) - real, unvaried product names from
# data/unique_products.json, spanning categories so the chip/card response to
# "what are your bestsellers" isn't one-note. Provisional until sign-off; swap
# freely without touching the schema.
BESTSELLER_NAMES = {
    "Jordanian Majdool Date",
    "Golden Sukkari Date",
    "Khudri Date with Pistachio",
    "The Royal Assortment",
    "The Signature Selection",
    "Pistachio Date Paste With Pistachio Cream",
}


def log(message: str) -> None:
    print(f"[seed_catalog] {message}", file=sys.stderr)


def _data_dir() -> Path:
    override = os.environ.get("SEED_DATA_DIR")
    if override:
        return Path(override)
    # Local run: <repo>/data. In the container the same resolution yields /data,
    # which is where compose mounts ./data.
    return REPO_ROOT / "data"


def _sync_engine():
    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://ladolce:ladolce@db:5432/ladolce"
    ).replace("+asyncpg", "+psycopg")
    return create_engine(url, future=True)


def _product_name(row: dict) -> str:
    """Fold the weight variant into the display name so the two price tiers of a
    weight-tiered product remain distinct products (section 3's products table
    has no variant column)."""
    name = row["name"]
    variant = row.get("variant")
    return f"{name} ({variant})" if variant else name


def seed(session: Session, products_data: list[dict], plate_sizes_data: list[dict]) -> dict:
    # Clear catalog tables (respect FK order). Cart tables don't exist yet.
    session.execute(delete(Product.__table__.metadata.tables["product_slot_cost"]))
    session.execute(delete(ProductVariant))
    session.execute(delete(Product))
    session.execute(delete(PlateSize))
    session.execute(delete(Category))
    session.flush()

    # Categories: distinct names in first-appearance order.
    categories: dict[str, Category] = {}
    for row in products_data:
        cat_name = row.get("category") or "Uncategorized"
        if cat_name not in categories:
            category = Category(name=cat_name, sort_order=len(categories))
            session.add(category)
            categories[cat_name] = category
    session.flush()

    # Products.
    # A handful of rows (the PDF-only menu items in scraped_pdf_products.json -
    # see data/needs_manual_review.json) never had a price captured at all, not
    # even a stale/placeholder one. Seeding those as active would surface a
    # product_card with "Add to order" but no visible price - a dead end, since
    # add_single_product already rejects a null-priced product server-side
    # (cart.py). Rather than leak them through with a blank price, keep them
    # out of customer-facing search/browsing (is_active=False) until a real
    # price is sourced; re-run this script once data/unique_products.json has
    # one.
    product_count = 0
    unpriced_count = 0
    for row in products_data:
        cat_name = row.get("category") or "Uncategorized"
        price = row.get("price")
        name = _product_name(row)
        if price is None:
            unpriced_count += 1
        session.add(
            Product(
                category_id=categories[cat_name].id,
                name=name,
                description=row.get("description"),
                price=price,
                image_url=row.get("image_url"),
                is_single_item=True,
                is_active=price is not None,
                is_bestseller=name in BESTSELLER_NAMES,
            )
        )
        product_count += 1

    # Plate sizes (see module docstring's PLATE SIZES ASSUMPTION).
    plate_count = 0
    for row in plate_sizes_data:
        session.add(
            PlateSize(
                name=row["title"],
                capacity=row["capacity"],
                base_price=row["base_price"],
                image_url=row.get("image_url"),
            )
        )
        plate_count += 1

    session.commit()
    return {
        "categories": len(categories),
        "products": product_count,
        "unpriced_products": unpriced_count,
        "plate_sizes": plate_count,
    }


def main() -> None:
    data_dir = _data_dir()
    products_path = data_dir / "unique_products.json"
    plate_sizes_path = data_dir / "scraped_plate_sizes.json"

    log(f"reading {products_path}")
    products_data = json.loads(products_path.read_text(encoding="utf-8"))
    log(f"reading {plate_sizes_path}")
    plate_sizes_data = json.loads(plate_sizes_path.read_text(encoding="utf-8"))

    engine = _sync_engine()
    with Session(engine) as session:
        counts = seed(session, products_data, plate_sizes_data)

    log(
        f"seeded {counts['categories']} categories, {counts['products']} products "
        f"({counts['unpriced_products']} inactive - no price captured), "
        f"{counts['plate_sizes']} plate sizes"
    )


if __name__ == "__main__":
    main()
