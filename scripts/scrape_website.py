#!/usr/bin/env python3
"""Extract La Dolce Saveur's product catalog from its built frontend bundle.

The site is a Vite/React SPA with no backend API and no server-rendered HTML -
the entire catalog is baked into the JS bundle at build time as plain object
literals (see docs/2026-07-23-ordering-chatbot-design.md discussion). So this
script does not parse HTML or drive a browser: it fetches the bundle text and
extracts the relevant arrays by content signature (not by minified variable
name, since minifier-assigned names like `ap`/`op` change on every rebuild),
then evaluates each array literal via Node's vm module (safe here because
these are pure data literals - no function calls - confirmed by inspection).
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://ladolcesaveur.com"
USER_AGENT = (
    "LaDolceSaveurCatalogBot/1.0 "
    "(+one-off catalog extraction for ordering chatbot data pipeline; "
    "contact: youssefelsayed1480@gmail.com)"
)
REQUEST_DELAY_SECONDS = 1.0

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / "data" / "cache"
OUTPUT_DIR = ROOT_DIR / "data"

CATEGORY_PRE_CURATED = "Stuffed & Flavored Dates"
CATEGORY_GOURMET_PACK = "Date Packs"
CATEGORY_GIFT = "Gift Boxes & Trays"
CATEGORY_INDIVIDUAL_DATES = "Individual Dates"


def log(message):
    print(f"[scrape_website] {message}", file=sys.stderr)


def fetch(url, cache_name, force_refresh):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / cache_name
    if cache_path.exists() and not force_refresh:
        log(f"using cached {cache_name}")
        return cache_path.read_text(encoding="utf-8")

    log(f"fetching {url}")
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    cache_path.write_text(response.text, encoding="utf-8")
    time.sleep(REQUEST_DELAY_SECONDS)
    return response.text


def get_bundle_js(force_refresh):
    html = fetch(f"{BASE_URL}/", "index.html", force_refresh)
    match = re.search(r'<script[^>]+type="module"[^>]+src="(/assets/[^"]+\.js)"', html)
    if not match:
        raise RuntimeError(
            "Could not find the main JS bundle <script> tag in index.html - "
            "the site's build setup may have changed; re-inspect before editing this script."
        )
    bundle_path = match.group(1)
    bundle_url = f"{BASE_URL}{bundle_path}"
    cache_name = "bundle_" + Path(bundle_path).name
    return fetch(bundle_url, cache_name, force_refresh), bundle_url


def extract_balanced_array(text, array_start):
    depth = 0
    for i in range(array_start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[array_start:i + 1]
    raise ValueError("Unbalanced array literal - could not find matching ']'")


def find_array_by_signature(bundle_text, signature):
    """Find the JS array literal containing `signature`, keying off content
    rather than the minified variable name it's assigned to (that name is not
    stable across rebuilds)."""
    sig_idx = bundle_text.find(signature)
    if sig_idx == -1:
        raise ValueError(f"Signature not found in bundle - site content may have changed: {signature!r}")
    assign_idx = bundle_text.rfind("=[", max(0, sig_idx - 8000), sig_idx)
    if assign_idx == -1:
        raise ValueError(f"Could not find enclosing array start for signature: {signature!r}")
    array_start = assign_idx + 1  # position of '['
    return extract_balanced_array(bundle_text, array_start)


def eval_js_array(js_array_text):
    """Evaluate a JS array literal (backtick strings, !0/!1 booleans etc.) in a
    sandboxed Node vm context and return it as a Python object."""
    script = (
        "const vm = require('vm');"
        "const src = process.argv[1];"
        "const result = vm.runInNewContext('(' + src + ')', {}, {timeout: 2000});"
        "process.stdout.write(JSON.stringify(result));"
    )
    try:
        proc = subprocess.run(
            ["node", "-e", script, js_array_text],
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
    except FileNotFoundError:
        raise RuntimeError("Node.js is required to parse the bundle's embedded catalog data but was not found on PATH.")
    if proc.returncode != 0:
        raise RuntimeError(f"Node failed to evaluate array literal: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def absolute_image_url(img_path):
    if not img_path:
        return None
    if img_path.startswith("http"):
        return img_path
    # Some source paths (the box/tray size images) contain literal spaces
    # instead of %20, while others are already percent-encoded - encode with
    # safe="/%" so we fix the former without double-encoding the latter.
    return f"{BASE_URL}{quote(img_path, safe='/%')}"


def build_simple_products(items, category):
    """Items with a single price and no weight tiers (e.g. individual date
    fillings, preset gift boxes/trays)."""
    rows = []
    for item in items:
        name = item.get("title") or item.get("id")
        price = item.get("price")
        if not name or price is None:
            log(f"skipping item with missing name/price: {item}")
            continue
        rows.append({
            "name": name,
            "name_ar": item.get("titleAr"),
            "description": item.get("description"),
            "description_ar": None,
            "price": price,
            "image_url": absolute_image_url(item.get("img")),
            "category": category,
            "variant": None,
            "source": "website",
        })
    return rows


def build_weight_tiered_products(items, category):
    """Items with weights: [{label, price}, ...] - emit one row per tier."""
    rows = []
    for item in items:
        name = item.get("title") or item.get("id")
        weights = item.get("weights") or []
        if not name or not weights:
            log(f"skipping weight-tiered item with missing name/weights: {item}")
            continue
        for tier in weights:
            price = tier.get("price")
            if price is None:
                log(f"skipping variant with missing price for {name!r} ({tier.get('label')})")
                continue
            rows.append({
                "name": name,
                "name_ar": item.get("titleAr"),
                "description": item.get("description"),
                "description_ar": None,
                "price": price,
                "image_url": absolute_image_url(item.get("img")),
                "category": category,
                "variant": tier.get("label"),
                "source": "website",
            })
    return rows


def build_plate_sizes(items):
    rows = []
    for item in items:
        rows.append({
            "title": item.get("title"),
            "base_price": item.get("price"),
            "capacity": item.get("cap"),
            "weight_limit": item.get("weightLimit"),
            "image_url": absolute_image_url(item.get("img")),
        })
    return rows


def main():
    force_refresh = "--refresh" in sys.argv

    bundle_text, bundle_url = get_bundle_js(force_refresh)
    log(f"bundle: {bundle_url}")

    # Signatures are literal first-element `id:` values, not just field/type
    # names - e.g. "type:`pre_curated`" also appears dozens of times in cart/
    # animation logic elsewhere in the bundle (e.g. `e.type===`pre_curated``),
    # so matching on that alone grabs the wrong array. A literal id like
    # "pc-t4" only ever appears once: inside the actual data literal.
    plate_size_items = eval_js_array(find_array_by_signature(bundle_text, "id:`box_1kg`"))
    individual_date_items = eval_js_array(find_array_by_signature(bundle_text, "id:`Ajwa Date`"))
    pre_curated_items = eval_js_array(find_array_by_signature(bundle_text, "id:`pc-t4`"))
    gourmet_pack_items = eval_js_array(find_array_by_signature(bundle_text, "id:`gp-t1`"))
    gift_items = eval_js_array(find_array_by_signature(bundle_text, "id:`gc-b1`"))

    log(
        f"found: {len(plate_size_items)} plate sizes, {len(individual_date_items)} individual dates, "
        f"{len(pre_curated_items)} pre_curated, {len(gourmet_pack_items)} gourmet_pack, {len(gift_items)} gift"
    )

    products = []
    products += build_simple_products(individual_date_items, CATEGORY_INDIVIDUAL_DATES)
    products += build_weight_tiered_products(pre_curated_items, CATEGORY_PRE_CURATED)
    products += build_weight_tiered_products(gourmet_pack_items, CATEGORY_GOURMET_PACK)
    products += build_simple_products(gift_items, CATEGORY_GIFT)

    plate_sizes = build_plate_sizes(plate_size_items)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    products_path = OUTPUT_DIR / "scraped_website_products.json"
    plate_sizes_path = OUTPUT_DIR / "scraped_plate_sizes.json"

    products_path.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    plate_sizes_path.write_text(json.dumps(plate_sizes, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"wrote {len(products)} product rows -> {products_path}")
    log(f"wrote {len(plate_sizes)} plate size rows -> {plate_sizes_path}")


if __name__ == "__main__":
    main()
