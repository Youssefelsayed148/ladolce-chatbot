import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "verify_live", Path(__file__).resolve().parents[1] / "scripts" / "verify_live.py")
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)

LIVE = json.loads((Path(__file__).parent / "fixtures" / "live_products.json").read_text(encoding="utf-8"))["data"]


def _ours_from_live(price_shift=0.0):
    out = []
    for i, lp in enumerate(LIVE):
        out.append({
            "name": lp["titleEn"], "category": (lp.get("category") or {}).get("nameEn") or "x",
            "is_bestseller": i < 5, "is_active": True, "store_product_id": lp["id"], "store_date_id": None,
            "variants": [{"store_variant_id": v["id"], "label": v["label"],
                          "price": v["price"] + price_shift, "stock": v.get("stock")}
                         for v in lp.get("variants") or []],
        })
    return out


def test_matching_catalog_has_no_problems():
    lines, problems = vl.analyse(_ours_from_live(), LIVE, 10)
    assert problems == []
    assert any(l.startswith("## Price comparison") for l in lines)


def test_price_differences_and_fillings_are_reported():
    ours = _ours_from_live(price_shift=5)
    ours.append({"name": "Golden Sukkari Date", "category": "Individual Dates", "is_bestseller": True,
                 "is_active": True, "store_product_id": None, "store_date_id": "d1", "variants": []})
    _, problems = vl.analyse(ours, LIVE, 10)
    assert any("vs live" in p for p in problems)
    assert "bestseller is a box filling: Golden Sukkari Date" in problems


def test_missing_product_is_reported():
    ours = [p for p in _ours_from_live() if p["name"] != LIVE[0]["titleEn"]]
    _, problems = vl.analyse(ours, LIVE, 60)
    assert f"missing product: {LIVE[0]['titleEn']}" in problems
