"""OpenAI function-calling tool schemas (design doc section 5) and the dispatcher
that executes them server-side.

All cart mutation and pricing/capacity math happens in app.services.cart, which
is the authoritative source. Tools return authoritative data for the model plus
ui_blocks for the frontend. Cart errors (e.g. capacity exceeded) are returned as
structured `{"error": ...}` results for the model to relay - never silent.
"""

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import CartDraft, Conversation
from app.services import cart as cart_service
from app.services import catalog as catalog_service
from app.services import knowledge_base as kb_service

logger = logging.getLogger("app.tools")

# Phrases the model tends to use verbatim for a bestsellers-style ask (see the
# real transcript: "recommend_items" called with preference_notes="bestsellers").
# None of these ever substring-match an actual product name/description, so
# without this, search_products/recommend_items silently return zero rows and
# the concierge tells the guest it "can't retrieve" bestsellers. Routing on
# this keyword set to the curated products.is_bestseller flag (see
# catalog_service.list_bestsellers) is a deterministic, structural fix - it
# doesn't depend on the LLM re-emitting well-formed JSON or exact wording
# beyond already reliably deciding "this is a bestseller-ish ask".
#
# A plain keyword set (over e.g. a classifier LLM call) is deliberate: it's
# free, instant, and fully deterministic/testable, at the cost of only
# covering phrasings we've actually enumerated - so this list is intentionally
# broad rather than a handful of exact synonyms of "bestseller". Substring
# matching means most plurals/superlatives ("bestsellers", "top sellers") are
# already covered by their singular root and don't need their own entry.
_BESTSELLER_KEYWORDS = (
    "bestseller",
    "best seller",
    "best-seller",
    "best selling",
    "best-selling",
    "sell the best",
    "sells the best",
    "sell the most",
    "sells the most",
    "most popular",
    "top seller",
    "top pick",
    "top rated",
    "top-rated",
    "top selling",
    "top-selling",
    "popular item",
    "popular product",
    "popular choice",
    "most loved",
    "customer favorite",
    "customer favourite",
    "fan favorite",
    "fan favourite",
    "crowd favorite",
    "crowd favourite",
    "favorite",
    "favourite",
    "order the most",
    "order most",
    "ordered the most",
    "most ordered",
)


def _is_bestseller_query(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in _BESTSELLER_KEYWORDS)


SEARCH_PRODUCTS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_products",
        "description": (
            "Search the catalog for products by free text. Use for any question about "
            "what exists, prices, or flavours. Returns rows with product_id you can pass "
            "to add_single_product / add_item_to_plate."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Free-text search terms."},
                "category": {"type": "string", "description": "Optional exact category name."},
            },
            "required": ["query"],
        },
    },
}

RECOMMEND_ITEMS_TOOL = {
    "type": "function",
    "function": {
        "name": "recommend_items",
        "description": (
            "Recommend products based on the guest's stated preferences. Returns ranked "
            "catalog suggestions with product_id. Base recommendations only on what this "
            "returns - never invent products."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "preference_notes": {
                    "type": "string",
                    "description": "What the guest likes, e.g. 'nutty, not too sweet, a gift'.",
                }
            },
            "required": ["preference_notes"],
        },
    },
}

START_PLATE_TOOL = {
    "type": "function",
    "function": {
        "name": "start_plate",
        "description": (
            "Begin a custom box/tray of a given plate size. Call it ONCE per box; to add to a box that already exists, reuse its cart_item_id. Returns the cart_item_id "
            "(use it for add_item_to_plate) and the plate's capacity and price."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "plate_size_id": {"type": "integer", "description": "Plate size id (see the plate sizes listed in context)."}
            },
            "required": ["plate_size_id"],
        },
    },
}

ADD_ITEM_TO_PLATE_TOOL = {
    "type": "function",
    "function": {
        "name": "add_item_to_plate",
        "description": (
            "Add a product into a custom plate. The backend validates capacity and "
            "returns the updated plate state, or a structured error if it won't fit - "
            "relay that error, never assume it was added."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cart_item_id": {"type": "integer", "description": "The custom plate's cart_item_id from start_plate."},
                "product_id": {"type": "integer"},
                "quantity": {"type": "integer", "minimum": 1, "default": 1},
            },
            "required": ["cart_item_id", "product_id", "quantity"],
        },
    },
}

REMOVE_ITEM_FROM_PLATE_TOOL = {
    "type": "function",
    "function": {
        "name": "remove_item_from_plate",
        "description": "Remove a product from a custom plate.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cart_item_id": {"type": "integer"},
                "product_id": {"type": "integer"},
            },
            "required": ["cart_item_id", "product_id"],
        },
    },
}

SET_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "set_finish",
        "description": (
            "Choose the ribbon finish for a custom box (ids are listed in context). "
            "Required before the order can be reviewed."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cart_item_id": {"type": "integer", "description": "The custom box's cart_item_id."},
                "finish_id": {"type": "integer"},
            },
            "required": ["cart_item_id", "finish_id"],
        },
    },
}

SET_GIFT_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_gift_message",
        "description": (
            "Set (or clear, with an empty string) the optional gift message printed "
            "with a custom box. Maximum 180 characters."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cart_item_id": {"type": "integer"},
                "message": {"type": "string", "maxLength": 180},
            },
            "required": ["cart_item_id", "message"],
        },
    },
}

ADD_SINGLE_PRODUCT_TOOL = {
    "type": "function",
    "function": {
        "name": "add_single_product",
        "description": (
            "Add a standalone product (a pack, gift box, tray, etc.) to the cart. If the "
            "product lists variants (sizes/weights), ask the guest which one and pass "
            "its variant_id."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product_id": {"type": "integer"},
                "variant_id": {"type": "integer", "description": "From the product's variants list."},
                "quantity": {"type": "integer", "minimum": 1, "default": 1},
            },
            "required": ["product_id", "quantity"],
        },
    },
}

GET_CART_SUMMARY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_cart_summary",
        "description": "Return the current cart: all items, quantities, prices, and total.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}

REQUEST_REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "request_review",
        "description": (
            "Lock the cart for review and show the guest the persistent 'Review Order' "
            "button. Call this when the guest indicates they're ready to review/checkout. "
            "Idempotent - safe to call more than once."
        ),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}

SEARCH_KNOWLEDGE_BASE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "Search company documents (policies, shipping & returns, certifications, "
            "FAQs, about-us) for GENERAL / non-product questions. Use this for "
            "anything about company policy or background - NOT for products, prices, "
            "or the cart (use search_products / recommend_items for those). Returns "
            "matched passages with their source, or an empty result if nothing is "
            "relevant. You MUST answer general/policy questions only from what this "
            "returns; if it returns nothing relevant, say plainly that you don't have "
            "that information rather than guessing."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "The guest's question, as free text."}
            },
            "required": ["query"],
        },
    },
}

ALL_TOOLS = [
    SEARCH_PRODUCTS_TOOL,
    RECOMMEND_ITEMS_TOOL,
    START_PLATE_TOOL,
    ADD_ITEM_TO_PLATE_TOOL,
    REMOVE_ITEM_FROM_PLATE_TOOL,
    SET_FINISH_TOOL,
    SET_GIFT_MESSAGE_TOOL,
    ADD_SINGLE_PRODUCT_TOOL,
    GET_CART_SUMMARY_TOOL,
    REQUEST_REVIEW_TOOL,
    SEARCH_KNOWLEDGE_BASE_TOOL,
]


async def dispatch_tool(
    session: AsyncSession,
    client: Any,
    conversation: Conversation,
    draft: CartDraft,
    name: str,
    args: dict,
    embedding_client: Any = None,
) -> cart_service.ToolResult:
    """Execute a tool call. Returns ToolResult(data, ui_blocks). Cart errors are
    caught and returned as structured error data for the model to relay."""
    try:
        if name == "search_knowledge_base":
            settings = get_settings()
            results = await kb_service.search_kb(
                session, embedding_client or client, args.get("query", ""), embedding_model=settings.openai_embedding_model
            )
            if not results:
                return cart_service.ToolResult(
                    data={
                        "results": [],
                        "message": "No relevant information found in the knowledge base for this query.",
                    },
                    ui_blocks=[],
                )
            return cart_service.ToolResult(
                data={
                    "results": [
                        {
                            "content": r.content,
                            "source": r.source,
                            "similarity": round(r.similarity, 4),
                        }
                        for r in results
                    ]
                },
                ui_blocks=[],
            )

        if name == "search_products":
            query = args.get("query", "")
            if _is_bestseller_query(query) and not args.get("category"):
                rows = await catalog_service.list_bestsellers(session)
            else:
                rows = await catalog_service.search_products(
                    session, query=query, category=args.get("category")
                )
            return cart_service.ToolResult(
                data={"results": rows},
                ui_blocks=[_product_card_from_row(r) for r in rows],
            )

        if name == "recommend_items":
            preference_notes = args.get("preference_notes", "")
            if _is_bestseller_query(preference_notes):
                rows = await catalog_service.list_bestsellers(session)
            else:
                rows = await catalog_service.search_products(
                    session, query=preference_notes, limit=5
                )
            return cart_service.ToolResult(
                data={"recommendations": rows},
                ui_blocks=[_product_card_from_row(r) for r in rows],
            )

        if name == "add_single_product":
            return await cart_service.add_single_product(
                session,
                draft,
                int(args["product_id"]),
                int(args.get("quantity", 1)),
                int(args["variant_id"]) if args.get("variant_id") is not None else None,
            )

        if name == "start_plate":
            return await cart_service.start_plate(
                session, draft, int(args["plate_size_id"])
            )

        if name == "add_item_to_plate":
            return await cart_service.add_item_to_plate(
                session,
                draft,
                int(args["cart_item_id"]),
                int(args["product_id"]),
                int(args.get("quantity", 1)),
            )

        if name == "remove_item_from_plate":
            return await cart_service.remove_item_from_plate(
                session, draft, int(args["cart_item_id"]), int(args["product_id"])
            )

        if name == "set_finish":
            return await cart_service.set_finish(
                session, draft, int(args["cart_item_id"]), int(args["finish_id"])
            )

        if name == "set_gift_message":
            return await cart_service.set_gift_message(
                session, draft, int(args["cart_item_id"]), str(args.get("message", ""))
            )

        if name == "get_cart_summary":
            state = await cart_service.get_cart_state_by_draft(session, draft)
            ui_blocks = [
                await cart_service.build_plate_builder_block(session, i)
                for i in await cart_service._load_items(session, draft.id)
                if i.item_type == "custom_plate"
            ]
            return cart_service.ToolResult(data={"cart": state}, ui_blocks=ui_blocks)

        if name == "request_review":
            return await cart_service.request_review(session, draft)

        return cart_service.ToolResult(data={"error": f"unknown tool: {name}"}, ui_blocks=[])

    except cart_service.CartError as exc:
        logger.info(
            "cart_tool_error",
            extra={"tool": name, "error": exc.message, "conversation_id": conversation.session_token},
        )
        return cart_service.ToolResult(data=exc.as_result(), ui_blocks=[])


def _product_card_from_row(row: dict) -> dict:
    return {
        "type": "product_card",
        "data": {
            "product_id": row.get("product_id"),
            "name": row.get("name"),
            "description": row.get("description"),
            "price": row.get("price"),
            # ProductCard uses this to label a per-piece Individual Dates price
            # ("6 AED / piece") - without it, that price sits next to a weight-
            # tiered card ("500g — 65 AED") with no unit, reading as inconsistent.
            "category": row.get("category"),
        },
    }


def parse_tool_args(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
