"""Scope-aware follow-up chips.

The chips are chosen deterministically from what the turn actually did (which
tools ran, what the guest asked) so they always fit the conversation's stage -
box building leads to ribbon/gift/review, shipping questions to delivery
follow-ups, and so on. This is instant and free. Only when no rule applies does
the caller fall back to an LLM-written set (with a timeout, see chat.py).
"""

import re

MAX_SUGGESTIONS = 3

_NEEDS_CART_RE = re.compile(r"\b(review|check ?out|place (my|the) order)\b", re.IGNORECASE)
_NEEDS_BOX_RE = re.compile(
    r"(ribbon|gift message|which dates can i add|dates (to|in|into) the box|add more dates)",
    re.IGNORECASE,
)

_DISCOVER = ["What are your bestsellers?", "Show me gift boxes", "Build me a custom box"]


def drop_impossible(chips: list[str], cart_empty: bool | None, has_box: bool | None) -> list[str]:
    """Never offer a step that cannot work right now: reviewing an empty cart, or
    ribbon / gift message / more dates without a custom box in the cart. Applied to
    rule chips and to LLM-written ones alike."""
    out = []
    for c in chips:
        if cart_empty and _NEEDS_CART_RE.search(c):
            continue
        if has_box is False and _NEEDS_BOX_RE.search(c):
            continue
        out.append(c)
    return out


def _card_chip(blocks: list[dict]) -> str:
    """One chip for the first product card that always works: compare its two
    weights when it has several, otherwise add it by name."""
    card = next((b["data"] for b in blocks if b.get("type") == "product_card"), {}) or {}
    weights: list[str] = []
    for v in card.get("variants") or []:
        w = str(v.get("label", "")).split("/")[0].strip()
        if w and w not in weights:
            weights.append(w)
    if len(weights) >= 2:
        return f"Which is better value, {weights[0]} or {weights[1]}?"
    if len(card.get("variants") or []) > 1:
        return "Which size is best for a gift?"
    return f"Add {card.get('name') or 'it'} to my order"

_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shipping", ("ship", "deliver", "gcc", "international", "customs", "courier")),
    ("returns", ("return", "refund", "exchange", "damaged", "cancel")),
    ("allergens", ("allerg", "vegan", "nut", "gluten", "dairy", "sesame", "halal")),
    ("promotions", ("discount", "promo", "coupon", "offer", "sale", "code")),
)

_TOPIC_CHIPS: dict[str, list[str]] = {
    "shipping": ["How long does delivery take?", "Do you ship to Saudi Arabia?", "Build me a custom box"],
    "returns": ["What is your return policy?", "How do I report a damaged order?", "Show me gift boxes"],
    "allergens": ["Which dates contain nuts?", "Do you have vegan options?", "Show me plain dates"],
    "promotions": ["Do you have any promotions?", "Show me gift boxes", "Build me a custom box"],
}


def _box_chips(blocks: list[dict]) -> list[str]:
    plate = next((b["data"] for b in reversed(blocks) if b.get("type") == "plate_builder"), None)
    if plate and plate.get("capacity_total") and plate.get("capacity_used", 0) >= plate["capacity_total"]:
        return ["Choose a ribbon finish", "Add a gift message", "Review my order"]
    return ["Which dates can I add?", "Choose a ribbon finish", "Add a gift message"]


def rule_suggestions(
    user_text: str,
    tool_names: list[str],
    ui_blocks: list[dict],
    failed_tools: list[str] | None = None,
    cart_empty: bool | None = None,
) -> list[str]:
    """Return up to MAX_SUGGESTIONS chips for this turn, or [] if no rule fits."""
    from app.services.tools import _is_bestseller_query

    failed = set(failed_tools or [])
    if failed and tool_names and tool_names[-1] in failed and tool_names[-1] == "add_single_product":
        return list(_DISCOVER)  # nothing was added: do not point at review
    for name in reversed(tool_names):
        if name in failed:
            continue
        if name == "request_review":
            if any(b.get("type") == "review_order_button" for b in ui_blocks):
                return []  # the Review Order button is the next step
            # review was refused (e.g. no ribbon yet): point at what is missing
            return ["Choose a ribbon finish", "Add a gift message", "Add more dates to the box"]
        if name == "set_gift_message":
            return ["Review my order", "Add more dates to the box", "How long does delivery take?"]
        if name == "set_finish":
            return ["Add a gift message", "Review my order", "Add more dates to the box"]
        if name in ("start_plate", "add_item_to_plate", "remove_item_from_plate"):
            return _box_chips(ui_blocks)
        if name == "add_single_product":
            return ["Review my order", "Show me gift boxes", "Build me a custom box"]
        if name == "get_cart_summary":
            if cart_empty:
                return list(_DISCOVER)
            return ["Review my order", "Add something else", "Build me a custom box"]
        if name == "list_plate_sizes":
            return ["Which size is best for a gift?", "What can go inside a box?", "Which is the most popular?"]
        if name in ("search_products", "recommend_items"):
            if any(b.get("type") == "product_card" for b in ui_blocks):
                if _is_bestseller_query(user_text):
                    return ["Show me gift boxes", "Build me a custom box", "What sizes do you have?"]
                return [_card_chip(ui_blocks), "Show me gift boxes", "Build me a custom box"]
            return list(_DISCOVER)
        if name == "search_knowledge_base":
            text = (user_text or "").lower()
            for topic, words in _TOPIC_KEYWORDS:
                if any(w in text for w in words):
                    return _TOPIC_CHIPS[topic][:MAX_SUGGESTIONS]
            return ["What are your bestsellers?", "Do you ship internationally?", "Build me a custom box"]
    return []
