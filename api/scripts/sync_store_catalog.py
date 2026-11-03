#!/usr/bin/env python3
"""Compare our catalog (data/unique_products.json) with the live store API.

Phase 1: READ-ONLY. Only public GET requests; nothing is written to the DB.
Prints a markdown report (and writes it to --out if given).

Run: python api/scripts/sync_store_catalog.py --dry-run [--out report.md]
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import httpx

API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.config import get_settings  # noqa: E402

DATA = API_DIR.parent / "data" / "unique_products.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def fetch(base: str) -> dict:
    out = {}
    with httpx.Client(base_url=base, timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for key, path in {
            "products": "/api/products?limit=100",
            "dates": "/api/bespoke/dates",
            "canvases": "/api/bespoke/canvases",
            "finishes": "/api/bespoke/finishes",
        }.items():
            r = c.get(path)
            r.raise_for_status()
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

    # Individual dates vs bespoke dates
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

    # Other products vs live products
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only (the only mode in Phase 1)")
    ap.add_argument("--out")
    ap.parse_args_ = ap.parse_args()
    args = ap.parse_args_
    base = get_settings().store_api_base
    ours = json.loads(DATA.read_text(encoding="utf-8"))
    report = build_report(fetch(base), ours)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8"))


if __name__ == "__main__":
    main()
