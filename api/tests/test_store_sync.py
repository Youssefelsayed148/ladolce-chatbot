"""Tests for scripts/sync_store_catalog.py apply_sync (live fixtures, no network)."""

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models import Finish, PlateSize, Product, ProductVariant

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR / "scripts"))
import seed_catalog  # noqa: E402
import sync_store_catalog as sync  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
DATA = API_DIR.parent / "data"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _live():
    return {k: _load(FIX / f"live_{k}.json") for k in ("products", "dates", "canvases", "finishes")} | {
        "products": _load(FIX / "live_products.json")["data"]
    }


def _session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine)
    seed_catalog.seed(s, _load(DATA / "unique_products.json"), _load(DATA / "scraped_plate_sizes.json"))
    return s


def test_apply_links_products_variants_canvases_finishes():
    s = _session()
    stats = sync.apply_sync(s, _live())
    assert stats["canvases"] == 6 and stats["finishes"] == 3
    linked = s.scalars(select(Product).where(Product.store_product_id.is_not(None))).all()
    assert len(linked) == 41
    assert len(s.scalars(select(ProductVariant)).all()) == 82
    plates = s.scalars(select(PlateSize)).all()
    assert len(plates) == 6 and all(p.store_canvas_id and p.max_pieces for p in plates)
    royal = next(p for p in plates if p.max_pieces == 50)
    assert royal.capacity_grams == 1000 and float(royal.base_price) == 150
    assert len(s.scalars(select(Finish)).all()) == 3
    # every live bespoke date is linked, including the 2 we lacked
    dates = s.scalars(select(Product).where(Product.store_date_id.is_not(None))).all()
    assert len(dates) == 27 and stats["dates_created"] == 2


def test_aliases_map_majdool_to_khudri_and_keep_bestseller():
    s = _session()
    sync.apply_sync(s, _live())
    p = s.scalar(select(Product).where(Product.name == "Khudri Dates with Pecans"))
    assert p.store_product_id and p.variants
    paste = s.scalar(select(Product).where(Product.name == "Pistachio Date with pastachio cream"))
    assert paste.is_bestseller is True


def test_sync_clears_bestseller_flag_on_fillings():
    s = _session()
    for r in s.scalars(select(Product)).all():
        if r.name in ("Jordanian Majdool Date", "Golden Sukkari Date", "Khudri Date with Pistachio"):
            r.is_bestseller = True  # as on the live DB before the fix
    s.commit()
    sync.apply_sync(s, _live())
    flagged = [r for r in s.scalars(select(Product).where(Product.is_bestseller.is_(True))).all()]
    assert flagged and all(r.store_date_id is None for r in flagged)
    assert not any(r.name in ("Jordanian Majdool Date", "Golden Sukkari Date") for r in flagged)


def test_sync_flags_curated_shop_bestsellers():
    s = _session()
    sync.apply_sync(s, _live())
    best = s.scalars(select(Product).where(Product.is_bestseller.is_(True), Product.is_active.is_(True))).all()
    assert 4 <= len(best) <= 6
    assert all(p.store_product_id and p.variants and p.store_date_id is None for p in best)


def test_unmatched_old_rows_deactivated_not_deleted():
    s = _session()
    before = len(s.scalars(select(Product)).all())
    sync.apply_sync(s, _live())
    rows = s.scalars(select(Product)).all()
    assert len(rows) >= before
    stale = s.scalar(select(Product).where(Product.name.like("Sukkari Date Oreo Biscuit%")))
    assert stale is not None and stale.is_active is False


def test_apply_is_idempotent():
    s = _session()
    sync.apply_sync(s, _live())
    counts = [len(s.scalars(select(m)).all()) for m in (Product, ProductVariant, PlateSize, Finish)]
    sync.apply_sync(s, _live())
    assert counts == [len(s.scalars(select(m)).all()) for m in (Product, ProductVariant, PlateSize, Finish)]
