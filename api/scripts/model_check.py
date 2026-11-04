"""Scripted order flow against a running chat API, to compare LLM models.

Usage (against the live stack, or local):
    python scripts/model_check.py --base-url https://chat.example.com --label gpt-4.1-mini

Set LLM_MODEL in the server's .env, redeploy, run this, repeat per model. Each step
checks what the guest would see (cards) and which tools the model really called.
Uses one fresh conversation; creates a cart draft (no order is placed). Mind the
chat rate limit (default 20/minute): the order flow sends 6 messages and the
catalog flow 6 more, so run it at most once a minute.

Two flows, each on a fresh conversation:
  1. order flow  - size cards, custom box, ribbon, review (STEPS)
  2. catalog flow - best sellers, variants, ready-made vs custom, adding a
     variant, cart totals wording (CATALOG_STEPS)
"""

import argparse
import json
import sys

import httpx

# (message, check name, predicate over that turn's summary)
STEPS = [
    ("what sizes do the boxes come in", "size cards shown",
     lambda t, s: "plate_size_options" in t["blocks"]),
    ("I'd like to build a custom box in The Classic Petite.", "box started with start_plate",
     lambda t, s: "start_plate" in t["tools"] and "plate_builder" in t["blocks"]),
    ("add 6 Ajwa Date to my box", "dates added with add_item_to_plate",
     lambda t, s: "add_item_to_plate" in t["tools"] and t["max_used"] == 6),
    ("add 40 Jordanian Majdool Date to my box", "overfill refused, box not restarted",
     lambda t, s: "start_plate" not in t["tools"] and (t["max_used"] or 0) <= 18),
    ("use the Royal Gold ribbon", "ribbon set with set_finish",
     lambda t, s: "set_finish" in t["tools"]),
    ("review my order", "review requested",
     lambda t, s: "request_review" in t["tools"] and "review_order_button" in t["blocks"]),
]


def _first_variant_card(turns):
    for t in turns:
        for c in t["cards"]:
            if len(c.get("variants") or []) >= 2:
                return c
    return None


def _add_variant_message(turns) -> str:
    card = _first_variant_card(turns)
    if card is None:  # the variants check fails on its own; still send something
        return "add one of those to my order"
    v = card["variants"][0]
    return (f"I'd like to add {card['name']} ({v['label']}) to my order, please. "
            f"[add product_id={card['product_id']} variant_id={v['variant_id']} qty=1]")


def _fillings(cards):
    return [c for c in cards if (c.get("category") or "") == "Individual Dates"]


def _variants_ok(turns) -> bool:
    card = _first_variant_card(turns)
    if card is None:
        return False
    labels = [v["label"].lower() for v in card["variants"]]
    return all(v.get("price") for v in card["variants"]) and (
        any("500g" in l or "1kg" in l for l in labels) or any(l.endswith(("s", "m", "l")) for l in labels))


def _ready_and_custom(t) -> bool:
    ready = next((c for c in t["cards"] if c.get("kind") == "ready_made_box"), None)
    reply = t["reply"].lower()
    if ready is None or not ready.get("custom_box_same_name"):
        return False
    prices = {str(int(ready["price"])), str(int(ready["custom_box_same_name"]["price"]))}
    return "ready-made" in reply and "custom" in reply and all(p in reply for p in prices)


def _cart_line_ok(turns) -> bool:
    card, last = _first_variant_card(turns), turns[-1] if turns else None
    if card is None or not last or not last.get("cart"):
        return False
    v = card["variants"][0]
    lines = [i for i in last["cart"].get("items", []) if i.get("product_id") == card["product_id"]]
    return bool(lines) and lines[0].get("unit_price") == v["price"] and lines[0].get("variant_label") == v["label"]


# Catalog flow: (message or callable(turns_so_far) -> message, check name,
# predicate over (turn, all turns so far)). A turn may also carry "cart" (fetched
# from GET /api/cart after the turn when `fetch_cart` is True in that step).
CATALOG_STEPS = [
    ("What are your best sellers?", "best sellers: no 'per piece', no filling products",
     lambda t, ts: bool(t["cards"]) and not _fillings(t["cards"])
     and "per piece" not in t["reply"].lower() and "/ piece" not in t["reply"].lower(), False),
    ("Tell me about Khudri dates with almond", "variant product shows weight/size options with prices",
     lambda t, ts: _variants_ok([t]), False),
    ("royal assortment", "royal assortment: ready-made and custom, both labeled with their prices",
     lambda t, ts: _ready_and_custom(t), False),
    (lambda ts: _add_variant_message(ts), "variant added with variant_id at its own price",
     lambda t, ts: "add_single_product" in t["tools"] and _cart_line_ok(ts), True),
    ("what is my cart total?", "cart total mentions subtotal and VAT",
     lambda t, ts: "subtotal" in t["reply"].lower() and "vat" in t["reply"].lower(), False),
]


def parse_sse_lines(lines) -> list[dict]:
    events = []
    for line in lines:
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def summarize_turn(events: list[dict]) -> dict:
    blocks = [e["block"] for e in events if e["type"] == "ui_block"]
    plates = [b["data"] for b in blocks if b["type"] == "plate_builder"]
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    suggestions = next((e["suggestions"] for e in reversed(events) if e["type"] == "suggestions_block"), [])
    return {
        "tools": [e["name"] for e in events if e["type"] == "tool_call"],
        "blocks": [b["type"] for b in blocks],
        "plate_ids": sorted({p["cart_item_id"] for p in plates}),
        "max_used": max((p["capacity_used"] for p in plates), default=None),
        "cards": [b["data"] for b in blocks if b["type"] == "product_card"],
        "reply": reply,
        "suggestions": suggestions,
        "conversation_id": next((e["conversation_id"] for e in events if e["type"] == "conversation"), None),
    }


def evaluate(turns: list[dict]) -> list[tuple[str, bool]]:
    """Per-step results plus flow-wide checks, from the summarized turns."""
    results = [(name, bool(pred(t, None))) for (_, name, pred), t in zip(STEPS, turns)]
    all_plate_ids = {i for t in turns for i in t["plate_ids"]}
    results.append(("only one box created in the whole flow", len(all_plate_ids) <= 1))
    results.append(("no markdown tables in any reply", not any("|---" in t["reply"] for t in turns)))
    results.append(("follow-up chips on every turn", all(len(t["suggestions"]) > 0 for t in turns[:-1])))
    return results


def evaluate_catalog(turns: list[dict]) -> list[tuple[str, bool]]:
    """Catalog-flow results. A step whose turn is missing counts as failed."""
    out = []
    for i, (_, name, pred, _) in enumerate(CATALOG_STEPS):
        ok = i < len(turns) and bool(pred(turns[i], turns[: i + 1]))
        out.append((name, ok))
    out.append(("no impossible chips (review with an empty cart)",
                not any("review" in c.lower() for t in turns[:3] for c in t["suggestions"])))
    return out


def _run_flow(client, steps) -> list[dict]:
    turns, conversation_id = [], None
    for step in steps:
        message, fetch_cart = step[0], (step[3] if len(step) > 3 else False)
        if callable(message):
            message = message(turns)
        with client.stream("POST", "/api/chat",
                           json={"message": message, "conversation_id": conversation_id}) as resp:
            resp.raise_for_status()
            events = parse_sse_lines(resp.iter_lines())
        turn = summarize_turn(events)
        conversation_id = turn["conversation_id"] or conversation_id
        if fetch_cart and conversation_id:
            turn["cart"] = client.get(f"/api/cart/{conversation_id}").json()
        turns.append(turn)
        print(f"  > {message[:90]}\n    tools={turn['tools']} blocks={turn['blocks']}")
    return turns


def run(base_url: str) -> tuple[list[dict], list[dict]]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120) as client:
        order = _run_flow(client, STEPS)
        catalog = _run_flow(client, CATALOG_STEPS)
    return order, catalog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--label", default="", help="model name, for the report header only")
    args = ap.parse_args()

    print(f"Model check {args.label} against {args.base_url}")
    order, catalog = run(args.base_url)
    results = evaluate(order) + evaluate_catalog(catalog)
    failed = [name for name, ok in results if not ok]
    print()
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (" - OK to use" if not failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
