import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "model_check", Path(__file__).resolve().parents[1] / "scripts" / "model_check.py")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)


def _turn(tools=(), blocks=(), used=None, plates=(), reply="ok", chips=("a",)):
    return dict(tools=list(tools), blocks=list(blocks), max_used=used, plate_ids=list(plates),
                reply=reply, suggestions=list(chips), conversation_id="c")


GOOD = [
    _turn(["list_plate_sizes"], ["plate_size_options"]),
    _turn(["start_plate"], ["plate_builder"], 0, [1]),
    _turn(["add_item_to_plate"], ["plate_builder"], 6, [1]),
    _turn(["add_item_to_plate"], ["plate_builder"], 6, [1]),
    _turn(["set_finish"], ["plate_builder"], 6, [1]),
    _turn(["request_review"], ["review_order_button"], None, [], chips=()),
]


def test_good_flow_passes_everything():
    assert all(ok for _, ok in mc.evaluate(GOOD))


def test_model_that_skips_tools_fails():
    bad = list(GOOD)
    bad[1] = _turn([], [], None, [])  # "we've started a box" in prose only
    failed = [n for n, ok in mc.evaluate(bad) if not ok]
    assert "box started with start_plate" in failed


def test_restarting_the_box_and_tables_are_caught():
    bad = list(GOOD)
    bad[3] = _turn(["start_plate"], ["plate_builder"], 0, [2], reply="| a |\n|---|")
    failed = [n for n, ok in mc.evaluate(bad) if not ok]
    assert {"overfill refused, box not restarted", "only one box created in the whole flow",
            "no markdown tables in any reply"} <= set(failed)


def test_sse_parsing_and_summary():
    lines = ['data: {"type": "conversation", "conversation_id": "x"}',
             'data: {"type": "tool_call", "name": "start_plate", "arguments": {}}',
             'data: {"type": "token", "text": "Hi"}', "", "data: not json"]
    t = mc.summarize_turn(mc.parse_sse_lines(lines))
    assert t["tools"] == ["start_plate"] and t["reply"] == "Hi" and t["conversation_id"] == "x"


# --- catalog flow ---------------------------------------------------------- #
def _card(**kw):
    base = dict(product_id=1, name="Khudri Dates with Almond", category="Date Packs", price=110,
                variants=[{"variant_id": 7, "label": "500g / S", "price": 110},
                          {"variant_id": 8, "label": "1kg / L", "price": 245}])
    base.update(kw)
    return base


def _cturn(cards=(), reply="ok", tools=(), cart=None, chips=("a",)):
    t = _turn(tools, [], None, [], reply, chips)
    t["cards"] = list(cards)
    if cart is not None:
        t["cart"] = cart
    return t


CART_OK = {"items": [{"product_id": 1, "unit_price": 110, "variant_label": "500g / S"}]}
ROYAL = _card(name="The Royal Assortment", kind="ready_made_box", price=450, variants=[],
              custom_box_same_name={"price": 150})

CATALOG_GOOD = [
    _cturn([_card()], "Our best sellers."),
    _cturn([_card()]),
    _cturn([ROYAL], "The ready-made box is 450 AED; the custom box in that size is 150 AED."),
    _cturn([_card()], tools=["add_single_product"], cart=CART_OK),
    _cturn([], "Subtotal 110 AED, plus 5% VAT."),
]


def test_catalog_flow_good_passes_everything():
    assert all(ok for _, ok in mc.evaluate_catalog(CATALOG_GOOD))


def test_best_sellers_with_per_piece_or_filling_cards_fail():
    bad = list(CATALOG_GOOD)
    bad[0] = _cturn([_card(category="Individual Dates")], "Golden Sukkari, 6 AED per piece")
    failed = [n for n, ok in mc.evaluate_catalog(bad) if not ok]
    assert "best sellers: no 'per piece', no filling products" in failed


def test_royal_assortment_must_label_both_boxes_with_prices():
    bad = list(CATALOG_GOOD)
    bad[2] = _cturn([ROYAL], "The Royal Assortment box is 450 AED.")
    assert "royal assortment: ready-made and custom, both labeled with their prices" in [
        n for n, ok in mc.evaluate_catalog(bad) if not ok]


def test_wrong_variant_price_in_cart_and_missing_vat_fail():
    bad = list(CATALOG_GOOD)
    bad[3] = _cturn([_card()], tools=["add_single_product"],
                    cart={"items": [{"product_id": 1, "unit_price": 245, "variant_label": "500g / S"}]})
    bad[4] = _cturn([], "Your total is 110 AED.")
    failed = [n for n, ok in mc.evaluate_catalog(bad) if not ok]
    assert {"variant added with variant_id at its own price", "cart total mentions subtotal and VAT"} <= set(failed)


def test_variant_product_without_options_fails():
    bad = list(CATALOG_GOOD)
    bad[1] = _cturn([_card(variants=[])])
    assert "variant product shows weight/size options with prices" in [
        n for n, ok in mc.evaluate_catalog(bad) if not ok]


def test_add_variant_message_carries_exact_ids():
    msg = mc._add_variant_message([_cturn([_card()])])
    assert "[add product_id=1 variant_id=7 qty=1]" in msg
