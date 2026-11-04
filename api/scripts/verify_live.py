#!/usr/bin/env python3
"""Read-only check of the chatbot's catalog against the live store (step G).

Prints: bestsellers and whether any is a box filling or lacks variants, filling
rows still flagged, our categories vs the live collections, and a price
comparison of up to N products (weight/size variants) between our DB and the
store API. Only public GETs against the store and SELECTs on our DB: nothing is
written. Exit code 1 when a problem is found.

Run (on the VPS):  docker compose exec -T api python scripts/verify_live.py [--sample 10]
"""

import argparse
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FILLING_CATEGORY = "Individual Dates"
READY_MADE = {"gift boxes & trays", "pre-curated", "gift collection"}


def is_filling(p: dict) -> bool:
    return p["store_date_id"] is not None or (
        p["store_product_id"] is None and p["category"] == FILLING_CATEGORY
    )


def analyse(ours: list[dict], live_products: list[dict], sample: int = 10) -> tuple[list[str], list[str]]:
    """(report lines, problems). `ours`: dicts with name, category, is_bestseller,
    is_active, store_product_id, store_date_id, variants=[{store_variant_id,label,price,stock}]."""
    lines: list[str] = []
    problems: list[str] = []

    best = [p for p in ours if p["is_active"] and p["is_bestseller"]]
    lines.append(f"## Bestsellers ({len(best)} flagged, active)")
    for p in best:
        tags = []
        if is_filling(p):
            tags.append("BOX FILLING")
            problems.append(f"bestseller is a box filling: {p['name']}")
        if not p["variants"] and p["category"].lower() not in READY_MADE:
            tags.append("no variants")
        lines.append(f"- {p['name']} [{p['category']}] {', '.join(tags)}".rstrip())
    shown = [p for p in best if not is_filling(p)]
    if len(shown) < 4:
        problems.append(f"only {len(shown)} usable bestsellers (want 4-6)")

    flagged_fill = [p["name"] for p in ours if is_filling(p) and p["is_bestseller"]]
    lines += ["", f"## Fillings still flagged is_bestseller: {len(flagged_fill)}"] + [f"- {n}" for n in flagged_fill]

    live_cats = sorted({(lp.get("category") or {}).get("nameEn") or "?" for lp in live_products})
    our_cats = sorted({p["category"] for p in ours if p["is_active"]})
    lines += ["", "## Categories", f"- live collections: {', '.join(live_cats)}",
              f"- ours (active): {', '.join(our_cats)}"]
    ready = [c for c in our_cats if c.lower() in READY_MADE]
    lines.append(f"- treated as ready-made boxes: {', '.join(ready) or 'NONE'}")
    if not ready:
        problems.append("no category is recognised as ready-made boxes")
    for c in live_cats:
        if c.lower() in ("pre-curated", "gift collection") and c.lower() not in {x.lower() for x in our_cats}:
            lines.append(f"- note: live '{c}' has no same-named category here (its products may sit in a legacy one)")

    by_store = {p["store_product_id"]: p for p in ours if p["store_product_id"]}
    live_with_variants = [lp for lp in live_products if lp.get("variants") and lp.get("isActive", True)]
    # Spread the sample across the catalog: every k-th product, with price differences first.
    step = max(1, len(live_with_variants) // max(1, sample))
    picked = live_with_variants[::step][:sample]
    lines += ["", f"## Price comparison ({len(picked)} products)"]
    for lp in picked:
        ours_p = by_store.get(lp["id"])
        title = lp["titleEn"]
        if ours_p is None:
            lines.append(f"- {title}: MISSING in our DB")
            problems.append(f"missing product: {title}")
            continue
        our_vars = {v["store_variant_id"]: v for v in ours_p["variants"]}
        bad = []
        for v in lp["variants"]:
            o = our_vars.get(v["id"])
            if o is None:
                bad.append(f"{v['label']}: not in ours (live {v['price']})")
            elif float(o["price"]) != float(v["price"]):
                bad.append(f"{v['label']}: ours {float(o['price']):g} vs live {float(v['price']):g}")
        lines.append(f"- {title}: " + ("; ".join(bad) if bad else f"OK ({len(lp['variants'])} variants)"))
        problems += [f"{title} {b}" for b in bad]
    return lines, problems


def load_ours() -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import Session, selectinload

    from app.models import Product
    from seed_catalog import _sync_engine

    with Session(_sync_engine()) as s:
        rows = s.scalars(
            select(Product).options(selectinload(Product.category), selectinload(Product.variants))
        ).all()
        return [
            {
                "name": p.name,
                "category": p.category.name if p.category else "(none)",
                "is_bestseller": p.is_bestseller,
                "is_active": p.is_active,
                "store_product_id": p.store_product_id,
                "store_date_id": p.store_date_id,
                "variants": [
                    {"store_variant_id": v.store_variant_id, "label": v.label,
                     "price": float(v.price), "stock": v.stock}
                    for v in p.variants if v.is_active
                ],
            }
            for p in rows
        ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10)
    args = ap.parse_args()
    from app.core.config import get_settings
    from sync_store_catalog import fetch

    live = fetch(get_settings().store_api_base)
    lines, problems = analyse(load_ours(), live["products"], args.sample)
    print("\n".join(lines))
    print("\n## Result")
    print("\n".join(f"- PROBLEM: {p}" for p in problems) if problems else "- all checks passed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
