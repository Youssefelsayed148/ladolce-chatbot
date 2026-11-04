"""Scope-aware follow-up chips.

The chips are chosen deterministically from what the turn actually did (which
tools ran, what the guest asked) so they always fit the conversation's stage -
box building leads to ribbon/gift/review, shipping questions to delivery
follow-ups, and so on. This is instant and free. Only when no rule applies does
the caller fall back to an LLM-written set (with a timeout, see chat.py).
"""

MAX_SUGGESTIONS = 3

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
    return ["Show me Ajwa dates", "Show me stuffed dates", "Choose a ribbon finish"]


def rule_suggestions(user_text: str, tool_names: list[str], ui_blocks: list[dict]) -> list[str]:
    """Return up to MAX_SUGGESTIONS chips for this turn, or [] if no rule fits."""
    for name in reversed(tool_names):
        if name == "request_review":
            return []  # the Review Order button is the next step
        if name == "set_gift_message":
            return ["Review my order", "Add more dates to the box", "How long does delivery take?"]
        if name == "set_finish":
            return ["Add a gift message", "Review my order", "Add more dates to the box"]
        if name in ("start_plate", "add_item_to_plate", "remove_item_from_plate"):
            return _box_chips(ui_blocks)
        if name == "add_single_product":
            return ["Review my order", "Show me gift boxes", "Build me a custom box"]
        if name == "get_cart_summary":
            return ["Review my order", "Add something else", "Build me a custom box"]
        if name == "list_plate_sizes":
            return ["Which size is best for a gift?", "What can go inside a box?", "Which is the most popular?"]
        if name in ("search_products", "recommend_items"):
            if any(b.get("type") == "product_card" for b in ui_blocks):
                return ["Add the first one to my order", "Show me something different", "Build me a custom box"]
            return ["What are your bestsellers?", "Show me gift boxes", "Build me a custom box"]
        if name == "search_knowledge_base":
            text = (user_text or "").lower()
            for topic, words in _TOPIC_KEYWORDS:
                if any(w in text for w in words):
                    return _TOPIC_CHIPS[topic][:MAX_SUGGESTIONS]
            return ["What are your bestsellers?", "Do you ship internationally?", "Build me a custom box"]
    return []
