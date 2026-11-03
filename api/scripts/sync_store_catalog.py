#!/usr/bin/env python3
"""Compare / sync our catalog with the live store API.

Only public GET requests are made against the store. Without --apply the script
only prints a markdown report (and writes it to --out if given). With --apply it
upserts store ids/variants/canvases/finishes into our DB (idempotent; unmatched
old rows are deactivated, never deleted). Run it AFTER seed_catalog.py - the seed
clears the catalog tables.

Run: python api/scripts/sync_store_catalog.py [--dry-run | --apply] [--out report.md]
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.config import get_settings  # noqa: E402
from app.models import Category, Finish, PlateSize, Product, ProductVariant  # noqa: E402

DATA = API_DIR.parent / "data" / "unique_products.json"

# Our name (normalized, variant suffix stripped) -> live product title, for rows
# the exact match misses. Only confident pairs; the rest are deactivated.
ALIASES = {
    "majdool dates with almonds": "Khudri Dates with Almond",
    "majdool dates with pecans": "Khudri Dates with Pecans",
    "majdool dates with pistachio": "Khudri Dates with Pistachio",
    "majdool dates with hazelnuts": "Khudri Dates with Hazelnuts",
    "date paste peanut cream": "Peanut Cream Date",
    "sesame date paste with tahina": "Sesasm Date With Tahina",
    "pistachio date paste with pistachio cream": "Pistachio Date with pastachio cream",
    "ajwa dates": "Royal Ajwa Dates",
}
SITE = "https://ladolcesaveur.com"
INDIVIDUAL = "Individual Dates"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _base_key(name: str) -> str:
    return norm(re.sub(r"\s*\([^)]*\)\s*$", "", name or ""))


def fetch(base: str) -> dict:
    out = {}
    with httpx.Client(base_url=base, timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for key, path in {
            "products": "/api/products?limit=100",
            "dates": "/api/bespoke/dates",
            "canvases": "/api/bespoke/canvases",
            "finishes": "/api/bespoke/finishes",
        }.items():
            for attempt in range(3):
                try:
                    r = c.get(path)
                    r.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
            j = r.json()
            out[key] = j["data"] if isinstance(j, dict) and "data" in j else j
    return out


def build_report(live: dict, ours: list[dict]) -> str:
    L: list[str] = ["# Store catalog diff (read-only)", ""]
    products = live["products"]
    live_by_title = {norm(p["titleEn"]): p for p in products}
    live_dates = {norm(d["nameEn"]): d for d in live["dates"]}

    individual = [r for r in ours if r["category"] == "Individual Dates"]
    others = [r for r in ours if r["category"] != "Individual Dates"]

    L += ["## Live store", f"- products: {len(products)}, variants: "
          f"{sum(len(p.get('variants') or []) for p in products)}",
          f"- bespoke canvases: {len(live['canvases'])}, dates: {len(live['dates'])}, "
          f"finishes: {len(live['finishes'])}", ""]

    m, mis = [], []
    for r in individual:
        (m if norm(r["name"]) in live_dates else mis).append(r)
    L += [f"## Individual dates: {len(m)}/{len(individual)} match live bespoke dates"]
    for r in mis:
        near = difflib.get_close_matches(norm(r["name"]), live_dates, n=1, cutoff=0.6)
        L.append(f"- name mismatch: '{r['name']}' -> suggestion: "
                 f"{live_dates[near[0]]['nameEn'] if near else 'none'}")
    ours_names = {norm(r["name"]) for r in individual}
    for k, d in live_dates.items():
        if k not in ours_names and not difflib.get_close_matches(k, ours_names, n=1, cutoff=0.6):
            L.append(f"- only in live: '{d['nameEn']}' ({d['weightGrams']}g)")
    L.append("")

    mp, mism, price_diff = [], [], []
    for r in others:
        p = live_by_title.get(norm(r["name"]))
        if not p:
            mism.append(r)
            continue
        mp.append(r)
        prices = {v["price"] for v in p.get("variants") or []} or {p.get("price")}
        if r["price"] not in prices:
            price_diff.append((r, p))
    L += [f"## Other products: {len(mp)}/{len(others)} match live titles"]
    for r in mism:
        near = difflib.get_close_matches(norm(r["name"]), live_by_title, n=1, cutoff=0.6)
        L.append(f"- only in ours: '{r['name']}' ({r['category']}, {r['price']}) -> suggestion: "
                 f"{live_by_title[near[0]]['titleEn'] if near else 'none'}")
    matched_live = {norm(r["name"]) for r in mp}
    for k, p in live_by_title.items():
        if k not in matched_live and not difflib.get_close_matches(k, [norm(r["name"]) for r in others], n=1, cutoff=0.6):
            L.append(f"- only in live: '{p['titleEn']}' ({p['category']['nameEn']}, from {p['price']})")
    L += ["", f"## Price differences ({len(price_diff)})"]
    for r, p in price_diff:
        vs = ", ".join(f"{v['label']}={v['price']}" for v in p.get("variants") or [])
        L.append(f"- {r['name']}: ours {r['price']} vs live [{vs}]")
    stock = [p for p in products if (p.get("totalStock") or 0) <= 0 or not p.get("isActive", True)]
    L += ["", f"## Out of stock / inactive on live ({len(stock)})"]
    L += [f"- {p['titleEn']}" for p in stock]

    L += ["", "## Bespoke canvases (live)"]
    for c in live["canvases"]:
        L.append(f"- {c.get('kind')} {c.get('capacityGrams')}g / {c.get('maxPieces')} pcs: {c.get('basePrice')}")
    L += ["", "## Finishes (live)"] + [f"- {f.get('nameEn') or f.get('name')}" for f in live["finishes"]]
    return "\n".join(L) + "\n"


def _get_category(session: Session, name: str) -> Category:
    cat = session.scalar(select(Category).where(Category.name == name))
    if cat is None:
        n = len(session.scalars(select(Category)).all())
        cat = Category(name=name, sort_order=n)
        session.add(cat)
        session.flush()
    return cat


def _title_grams(name: str) -> int | None:
    """'Medium Rectangular Tray (3kg)' -> 3000, 'X (700g)' -> 700."""
    m = re.search(r"\((\d+(?:\.\d+)?)\s*(kg|g)\)", name or "")
    if not m:
        return None
    return round(float(m.group(1)) * (1000 if m.group(2) == "kg" else 1))


def _abs_url(u: str | None) -> str | None:
    return u if not u or u.startswith("http") else SITE + u


def apply_sync(session: Session, live: dict) -> dict:
    """Upsert the live store catalog into our DB. Idempotent."""
    stats = {"products_updated": 0, "products_created": 0, "products_deactivated": 0,
             "variants": 0, "dates_matched": 0, "dates_created": 0,
             "canvases": 0, "finishes": 0}
    all_rows = session.scalars(select(Product)).all()
    cat_name = {c.id: c.name for c in session.scalars(select(Category)).all()}
    regular = [r for r in all_rows if cat_name.get(r.category_id) != INDIVIDUAL]
    index: dict[str, list[Product]] = {}
    for r in regular:
        index.setdefault(_base_key(r.name), []).append(r)
    claimed: set[int] = set()

    for lp in live["products"]:
        variants = [v for v in lp.get("variants") or [] if v.get("price") is not None]
        key = norm(lp["titleEn"])
        cands = [r for r in index.get(key, []) if r.id not in claimed]
        alias_rows = [
            r for ours_key, live_title in ALIASES.items() if norm(live_title) == key
            for r in index.get(ours_key, []) if r.id not in claimed and r not in cands
        ]
        if not cands:
            cands, alias_rows = alias_rows, []
        # A row already linked to this store product (re-run) wins.
        linked = [r for r in regular if r.store_product_id == lp["id"]]
        if linked:
            cands = linked + [c for c in cands if c not in linked]
        default = next((v for v in variants if v.get("isDefault")), None)
        price = (default or min(variants, key=lambda v: v["price"]))["price"] if variants else lp.get("price")
        fields = dict(
            name=lp["titleEn"],
            description=lp.get("descriptionEn") or None,
            price=price,
            store_product_id=lp["id"],
            is_active=bool(lp.get("isActive", True)),
        )
        if cands:
            prod = cands[0]
            for extra in cands[1:] + alias_rows:  # duplicate weight-rows / alias twins
                extra.is_active = False
                claimed.add(extra.id)
                prod.is_bestseller = prod.is_bestseller or extra.is_bestseller
            for k, v in fields.items():
                if k == "description" and v is None:
                    continue
                setattr(prod, k, v)
            if not prod.image_url:
                prod.image_url = _abs_url(lp.get("imageUrl"))
            stats["products_updated"] += 1
        else:
            cat = _get_category(session, (lp.get("category") or {}).get("nameEn") or "Uncategorized")
            prod = Product(category_id=cat.id, image_url=_abs_url(lp.get("imageUrl")),
                           is_single_item=True, is_bestseller=False, **fields)
            session.add(prod)
            stats["products_created"] += 1
        session.flush()
        claimed.add(prod.id)

        seen = set()
        for v in variants:
            row = session.scalar(select(ProductVariant).where(ProductVariant.store_variant_id == v["id"]))
            if row is None:
                row = ProductVariant(store_variant_id=v["id"], product_id=prod.id, label="", price=0)
                session.add(row)
            row.product_id = prod.id
            row.sku = v.get("sku")
            row.label = v.get("label") or ""
            row.weight_grams = v.get("weightGrams")
            row.size = v.get("size")
            row.price = v["price"]
            row.stock = v.get("stock")
            row.is_default = bool(v.get("isDefault"))
            row.is_active = True
            seen.add(v["id"])
            stats["variants"] += 1
        session.flush()
        for old in session.scalars(select(ProductVariant).where(ProductVariant.product_id == prod.id)):
            if old.store_variant_id not in seen:
                old.is_active = False

    for r in regular:
        if r.id not in claimed and r.store_product_id is None and r.is_active:
            r.is_active = False
            stats["products_deactivated"] += 1

    # Individual dates <-> bespoke dates
    ind = [r for r in all_rows if cat_name.get(r.category_id) == INDIVIDUAL]
    ind_key = {norm(r.name): r for r in ind}
    used: set[int] = set()
    ind_cat = None
    for d in live["dates"]:
        k = norm(d["nameEn"])
        row = next((r for r in ind if r.store_date_id == d["id"]), None) or ind_key.get(k)
        if row is None:
            free = [x for x in ind_key if ind_key[x].id not in used and ind_key[x].store_date_id is None]
            near = difflib.get_close_matches(k, free, n=1, cutoff=0.6)
            row = ind_key[near[0]] if near else None
        if row is not None and row.id in used:
            row = None
        if row is None:
            ind_cat = ind_cat or _get_category(session, INDIVIDUAL)
            row = Product(category_id=ind_cat.id, name=d["nameEn"], price=0,
                          image_url=_abs_url(d.get("imageUrl")), is_single_item=True,
                          is_active=True, is_bestseller=False)
            session.add(row)
            session.flush()
            stats["dates_created"] += 1
        else:
            stats["dates_matched"] += 1
        row.name = d["nameEn"]
        row.store_date_id = d["id"]
        row.weight_grams = d.get("weightGrams")
        used.add(row.id)
    for r in ind:
        if r.id not in used and r.store_date_id is None and r.is_active:
            r.is_active = False
            stats["products_deactivated"] += 1

    # Canvases <-> plate sizes (matched on max pieces)
    plates = list(session.scalars(select(PlateSize)).all())
    for c in live["canvases"]:
        ps = next((p for p in plates if p.store_canvas_id == c["id"]), None) or next(
            (p for p in plates if p.store_canvas_id is None and _title_grams(p.name) == c["capacityGrams"]),
            None)
        if ps is None:
            ps = PlateSize(name=f"{c['nameEn']} ({c['capacityGrams']}g)",
                           capacity=c["maxPieces"], base_price=c["basePrice"])
            session.add(ps)
            plates.append(ps)
        ps.store_canvas_id = c["id"]
        ps.kind = c.get("kind")
        ps.capacity_grams = c["capacityGrams"]
        ps.max_pieces = c["maxPieces"]
        ps.capacity = c["maxPieces"]
        ps.base_price = c["basePrice"]
        stats["canvases"] += 1

    for i, f in enumerate(live["finishes"]):
        row = session.scalar(select(Finish).where(Finish.store_finish_id == f["id"]))
        if row is None:
            row = Finish(store_finish_id=f["id"], name_en="")
            session.add(row)
        row.name_en = f["nameEn"]
        row.name_ar = f.get("nameAr")
        row.sort_order = i
        stats["finishes"] += 1
    session.commit()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    ap.add_argument("--apply", action="store_true", help="write the live catalog into our DB")
    ap.add_argument("--out")
    args = ap.parse_args()
    base = get_settings().store_api_base
    live = fetch(base)
    if args.apply:
        from seed_catalog import _sync_engine

        with Session(_sync_engine()) as session:
            print("applied:", apply_sync(session, live), file=sys.stderr)
        return
    ours = json.loads(DATA.read_text(encoding="utf-8"))
    report = build_report(live, ours)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8"))


if __name__ == "__main__":
    main()
