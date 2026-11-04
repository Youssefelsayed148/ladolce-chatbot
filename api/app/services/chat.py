"""Chat orchestration (Phases 1-2).

Streaming-first, with a multi-round tool loop: the model may call catalog/cart
tools (search, recommend, start_plate, add_item_to_plate, ...) across several
rounds before producing its final natural-language reply. Every round streams as
Server-Sent Events. All capacity/pricing is computed server-side in the tools;
the model only narrates authoritative results (design doc section 5).

`generate_chat_events` is agnostic to the OpenAI client it's given, so tests
inject a fake client that emits canned streams.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import CartDraft, Conversation, Finish
from app.services import cart as cart_service
from app.services import catalog as catalog_service
from app.services.suggestions import rule_suggestions
from app.services.tools import ALL_TOOLS, dispatch_tool, parse_tool_args

logger = logging.getLogger("app.chat")

# Cap each reply: providers like OpenRouter reserve credit for the model's maximum
# output when none is set, and a concierge reply never needs more than this.
MAX_REPLY_TOKENS = 1500

MAX_TOOL_ROUNDS = 6

# Box-size questions must always get the size cards, even when a weaker model
# answers in prose without calling list_plate_sizes (observed with gpt-4o-mini).
_SIZE_INTENT_RE = re.compile(
    r"\b(sizes?|trays?|custom box|(build|make|create|design)\b.*\bbox|boxes come in)\b",
    re.IGNORECASE,
)

# Checkout steps must not depend on the model remembering to call a tool (gpt-4o
# answered "review my order" in prose and never showed the Review button). When the
# guest clearly asks for one of these, the server performs it BEFORE the model
# replies, and the model then narrates the real result.
_REVIEW_INTENT_RE = re.compile(
    r"\b(review (my |the )?order|check ?out|place (my |the )?order|confirm (my |the )?order"
    r"|ready to (order|review|pay))\b",
    re.IGNORECASE,
)


_BUILD_INTENT_RE = re.compile(r"\b(build|start|make|create|want|like|choose|pick|go with|take)\b", re.IGNORECASE)


# The product card's "Add" button appends this marker so the exact product and
# variant are added server-side, not re-guessed by the model from a name.
_ADD_MARKER_RE = re.compile(r"\[add product_id=(\d+)(?: variant_id=(\d+))?(?: qty=(\d+))?\]")


async def _shortcut_calls(session: AsyncSession, draft: CartDraft, user_text: str) -> list[tuple[str, dict]]:
    """Tool calls the guest's message unambiguously asks for, in order."""
    calls: list[tuple[str, dict]] = []
    marker = _ADD_MARKER_RE.search(user_text)
    if marker:
        args = {"product_id": int(marker.group(1)), "quantity": int(marker.group(3) or 1)}
        if marker.group(2):
            args["variant_id"] = int(marker.group(2))
        return [("add_single_product", args)]
    text = user_text.lower()
    plates = [
        i for i in await cart_service._load_items(session, draft.id) if i.item_type == "custom_plate"
    ]
    if not plates:
        # Naming a box size (tapping a size card sends "...build a custom box in X")
        # starts that box, whether or not the model remembers to call start_plate.
        sizes = await catalog_service.list_plate_sizes(session)
        wanted = [
            p for p in sizes
            if p.name.lower() in text or p.name.split(" (")[0].lower() in text
        ]
        if wanted and (_BUILD_INTENT_RE.search(user_text) or len(text.split()) <= 6):
            best = max(wanted, key=lambda p: len(p.name))
            calls.append(("start_plate", {"plate_size_id": best.id}))
    if len(plates) == 1:
        finishes = (await session.execute(select(Finish))).scalars().all()
        named = next((f for f in finishes if f.name_en and f.name_en.lower() in text), None)
        if named is not None:
            calls.append(("set_finish", {"cart_item_id": plates[0].id, "finish_id": named.id}))
    if _REVIEW_INTENT_RE.search(user_text):
        calls.append(("request_review", {}))
    return calls


SYSTEM_PROMPT = (
    "You are the concierge for La Dolce Saveur, a luxury patisserie specialising in "
    "gourmet dates, stuffed dates, date pastes, and elegant gift boxes and trays. "
    "Speak in a warm, refined, and concise voice - gracious and knowledgeable, never "
    "verbose or salesy. Only discuss La Dolce Saveur and helping the guest choose; if "
    "asked about anything unrelated, gently steer back to the boutique.\n\n"
    "You have tools for searching and recommending products, and for building the "
    "guest's order: adding standalone products, and building a custom box/tray "
    "(start_plate, then add_item_to_plate). You MUST use these tools for anything "
    "involving products, prices, capacity, or the cart - never invent products, "
    "prices, or whether something fits. The backend computes all prices and capacity; "
    "if a tool returns an error (e.g. a plate is full), relay it gracefully and suggest "
    "alternatives. Reference products and plates by the ids the tools return. All "
    "prices the tools return are in AED (UAE Dirhams) - always write them as e.g. "
    "'450 AED', never with a $ or any other currency symbol.\n\n"
    "Custom boxes/trays follow the store's rules: a box is priced by its size only "
    "(quote the box total exactly as the tool results' plate_price - it comes from the store, never add up or calculate prices yourself), and it is limited by BOTH a maximum number of "
    "pieces AND a maximum total weight in grams - tool results report the remaining "
    "pieces and grams; relay them, never calculate fit yourself. Only individual "
    "date varieties go in a box. For every custom box also ask which ribbon finish "
    "they would like (set_finish - required before review) and offer an optional "
    "gift message of at most 180 characters (set_gift_message).\n\n"
    "FORMATTING: the chat window is narrow. Never use markdown tables or ASCII "
    "tables, and never paste raw lists of prices or sizes - the interface shows "
    "products, box sizes and the box contents as cards. Whenever the guest asks "
    "about box/tray sizes or wants to build a custom box, call list_plate_sizes and "
    "then reply with ONE or TWO short sentences (the cards show the details); after "
    "search_products/recommend_items, give a one-line lead-in only. Use short "
    "paragraphs and, when you must list, a short bulleted list with bold names. "
    "Keep replies under about 80 words.\n\n"
    "The context lists the current cart (with cart_item_ids) and every date that fits a "
    "custom box (with product_ids): use those ids exactly, never guess one, and when "
    "the guest sends only a number it is the quantity for the date just discussed.\n\n"
    "If add_item_to_plate returns an error (e.g. the pieces would be too heavy for "
    "the box's weight limit), tell the guest the exact reason and offer fewer pieces "
    "or a different date or size. NEVER start a new box or 'restart the order' to "
    "recover - keep using the existing cart_item_id. Add exactly the variety the "
    "guest named, never a similar one.\n\n"
    "Call tools silently: write NO text before or between tool calls, only one reply "
    "after all tools are done. You only collect the order - payment and checkout "
    "happen on the store's own checkout page after the guest taps Review Order; "
    "never say you take payment.\n\n"
    "READY-MADE vs CUSTOM boxes: a result with kind=ready_made_box is a finished box "
    "sold at its own price; a custom box (list_plate_sizes, box_type=custom) is a size "
    "the guest fills with dates, priced by the size only. Always say which one you mean "
    "(\"ready-made box\" / \"custom box\"). Some share a name (e.g. Royal Assortment: "
    "ready-made 450 AED, custom size 150 AED): when a row has custom_box_same_name, "
    "mention both in two short lines. Never present a custom box price as the price of "
    "a ready-made box, or the other way round.\n\n"
    "Store products that list `variants` come in sizes/weights (e.g. '500g / M', "
    "'1kg / L') each with its own price: ask which one the guest wants, quote that "
    "variant's price, and pass its variant_id to add_single_product - never guess.\n\n"
    "Many date varieties exist in more than one catalog form: sold individually as a "
    "single piece (category 'Individual Dates', for building a custom box), and "
    "separately sold as a weighed pack in 500g/1kg tiers - these are different "
    "products with different prices, not the same item. Always state the unit "
    "alongside the price so the two forms never read as inconsistent: a per-piece "
    "'Individual Dates' price as '6 AED / piece', a weighed pack as '65 AED for "
    "500g' or '120 AED for 1kg' (matching how the product cards label them) - never "
    "a bare number with no unit. If search_products or recommend_items returns more "
    "than one result for what looks like the same variety, do not silently pick one "
    "and state its price as 'the' price - list each option with its own price (and "
    "unit), or ask the guest which they'd like. Plural/weight/pack phrasing ('dates', "
    "'a pack of', 'in a box', '500g', '1kg') leans toward the weighed pack; singular, "
    "unqualified phrasing ('a date', 'one Ajwa date') leans toward the individual "
    "piece - but when it's genuinely unclear, ask rather than guess.\n\n"
    "For general or policy questions (shipping, returns, certifications, company "
    "background, FAQs) - anything that is NOT about a specific product, price, or the "
    "cart - call search_knowledge_base instead. Answer ONLY using the passages it "
    "returns; never blend in outside knowledge or guesses, even if you think you know "
    "the answer. If it returns no results (or the results plainly don't answer the "
    "question), say plainly and warmly that you don't have that information on hand, "
    "rather than inventing or approximating an answer - but where a warmer, more "
    "useful non-answer is available (e.g. redirecting to the team for a bulk-order "
    "quote or a specific allergy concern), give that instead of a flat refusal.\n\n"
    "Dietary/allergen questions about a SPECIFIC product are a narrow exception to "
    "'only from KB passages': after checking search_knowledge_base for our general "
    "allergen/vegan policy, you may also reason from that product's own name and "
    "description (from search_products/recommend_items) - our product names name "
    "their visible ingredients (e.g. 'Milk Chocolate' or 'White Chocolate' means "
    "dairy, 'With Cashew'/'With Pistachio'/'With Almond' means that tree nut, 'With "
    "Tahina' means sesame). Always frame this as a best-effort read of the listed "
    "ingredients, not a certified allergen or vegan guarantee (we don't currently "
    "issue either - see the KB policy), and for anything allergy-critical or a "
    "strictly vegan order, tell the guest to confirm with the team directly rather "
    "than relying solely on your read of the name."
)

MAX_SUGGESTIONS = 3

# The fallback LLM call must never hold the stream open for long: the guest's
# composer stays usable once the reply is done, and chips are best-effort.
SUGGESTIONS_TIMEOUT_S = 6

# Phase 6: a cheap follow-up completion (approach (a) from the design note -
# preferred over a rule-based tool->suggestion mapping because this is a
# luxury-concierge experience where relevant, well-phrased suggestions matter
# more than shaving the small added cost/latency of one extra short call).
# It always runs AFTER the visible reply has already been streamed in full
# (see the `yield {"type": "done", ...}` in generate_chat_events below), so it
# can never delay or gate what the guest sees - only the chips arrive a beat
# later, on the same SSE stream.
SUGGESTIONS_SYSTEM_PROMPT = (
    f"Based on the guest's last message and the concierge's reply below, suggest "
    f"exactly {MAX_SUGGESTIONS} short follow-up questions the guest might naturally ask "
    "next, each under 8 words. Keep them generic topic nudges - never reference order "
    "numbers, ids, or any other private/internal details. Respond with ONLY a "
    "JSON array of strings, nothing else."
)


# The model is told to respond with ONLY a JSON array, but some models still
# wrap it in markdown fences (```json [...] ```) or add a stray preamble/trailing
# sentence. json.loads on the raw content then fails with "Expecting value: line
# 1 column 1" - which looked identical to a genuinely empty/malformed response,
# so every fenced reply silently degraded to no chips. Strip fences first, then
# pull out the first top-level [...] span; this is provider-agnostic, not
# gpt-4o-specific.
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _extract_json_array(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    match = _JSON_ARRAY_RE.search(content)
    return match.group(0) if match else content


async def generate_suggestions(client, model: str, user_text: str, reply_text: str) -> list[str]:
    """Best-effort follow-up suggestions. Never raises - any failure (network,
    malformed model output) degrades to an empty list so a suggestion hiccup
    never breaks the chat response."""
    try:
        async def _call() -> str:
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SUGGESTIONS_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Guest: {user_text}\nConcierge: {reply_text}"},
                ],
                stream=True,
                max_tokens=200,
            )
            out = ""
            async for kind, payload in _consume_stream(stream):
                if kind == "final":
                    out = payload["content"]
            return out

        content = await asyncio.wait_for(_call(), timeout=SUGGESTIONS_TIMEOUT_S)

        data = json.loads(_extract_json_array(content))
        if not isinstance(data, list):
            return []
        return [str(s).strip() for s in data if str(s).strip()][:MAX_SUGGESTIONS]
    except Exception:
        logger.warning("suggestions_generation_failed", exc_info=True)
        return []


def _assistant_tool_call_message(tool_calls: dict[int, dict]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
            }
            for _, slot in sorted(tool_calls.items())
        ],
    }


def _delta_value(delta, name: str, default=None):
    """Read a delta attribute whether the SDK returned an object or a dict."""
    if delta is None:
        return default
    if isinstance(delta, dict):
        return delta.get(name, default)
    return getattr(delta, name, default)


async def _consume_stream(stream):
    """Yield ("token", text) as content arrives; finally ("final",
    {content, tool_calls}).

    Defensive against provider differences: OpenCode Go exposes an
    OpenAI-compatible chat/completions endpoint, so the openai SDK parses its
    SSE into the same ChatCompletionChunk objects. This parser also tolerates
    raw dict chunks (e.g. from test fakes or future non-SDK clients).
    """
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}

    async for chunk in stream:
        usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
        if usage:
            u = usage if isinstance(usage, dict) else usage.model_dump()
            logger.info(
                "llm_usage",
                extra={"prompt_tokens": u.get("prompt_tokens"),
                       "completion_tokens": u.get("completion_tokens")},
            )
        if isinstance(chunk, dict):
            choices = chunk.get("choices") or []
        else:
            choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue

        choice = choices[0]
        if isinstance(choice, dict):
            delta = choice.get("delta")
        else:
            delta = getattr(choice, "delta", None)
        if not delta:
            continue

        content = _delta_value(delta, "content")
        if content:
            content_parts.append(content)
            yield ("token", content)

        for tc in _delta_value(delta, "tool_calls") or []:
            idx = _delta_value(tc, "index")
            if idx is None:
                continue
            slot = tool_calls.setdefault(idx, {"id": None, "name": "", "args": ""})
            tc_id = _delta_value(tc, "id")
            if tc_id:
                slot["id"] = tc_id
            fn = _delta_value(tc, "function")
            if fn is not None:
                fn_name = _delta_value(fn, "name")
                fn_args = _delta_value(fn, "arguments")
                if fn_name:
                    slot["name"] = fn_name
                if fn_args:
                    slot["args"] += fn_args

    yield ("final", {"content": "".join(content_parts), "tool_calls": tool_calls})


async def generate_chat_events(
    session: AsyncSession,
    client,
    model: str,
    conversation: Conversation,
    draft: CartDraft,
    history: list[dict],
    user_text: str,
    context_note: str = "",
    embedding_client=None,
) -> AsyncGenerator[dict, None]:
    """Yield events: {'type': 'token'|'tool_call'|'ui_block'|'done', ...}."""
    system_content = SYSTEM_PROMPT + (f"\n\n{context_note}" if context_note else "")
    messages: list[dict] = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    reply_parts: list[str] = []
    made_tool_calls: list[dict] = []
    ui_blocks: list[dict] = []

    shortcuts = await _shortcut_calls(session, draft, user_text)
    if shortcuts:
        slots = {
            i: {"id": f"auto_{i}", "name": name, "args": json.dumps(args)}
            for i, (name, args) in enumerate(shortcuts)
        }
        messages.append(_assistant_tool_call_message(slots))
        for i, (name, args) in enumerate(shortcuts):
            made_tool_calls.append({"name": name, "arguments": args})
            yield {"type": "tool_call", "name": name, "arguments": args}
            result = await dispatch_tool(
                session, client, conversation, draft, name, args, embedding_client
            )
            for block in result.ui_blocks:
                ui_blocks.append(block)
                yield {"type": "ui_block", "block": block}
            messages.append(
                {"role": "tool", "tool_call_id": f"auto_{i}", "content": _json_result(result.data)}
            )

    for _round in range(MAX_TOOL_ROUNDS):
        stream = await client.chat.completions.create(
            model=model, messages=messages, tools=ALL_TOOLS, stream=True, max_tokens=MAX_REPLY_TOKENS,
            stream_options={"include_usage": True},
        )
        final = None
        async for kind, payload in _consume_stream(stream):
            if kind == "token":
                reply_parts.append(payload)
                yield {"type": "token", "text": payload}
            else:
                final = payload

        tool_calls = (final or {}).get("tool_calls") or {}
        if not tool_calls:
            break

        messages.append(_assistant_tool_call_message(tool_calls))
        for _, slot in sorted(tool_calls.items()):
            args = parse_tool_args(slot["args"])
            made_tool_calls.append({"name": slot["name"], "arguments": args})
            yield {"type": "tool_call", "name": slot["name"], "arguments": args}

            result = await dispatch_tool(
                session, client, conversation, draft, slot["name"], args, embedding_client
            )
            for block in result.ui_blocks:
                ui_blocks.append(block)
                yield {"type": "ui_block", "block": block}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": slot["id"],
                    "content": _json_result(result.data),
                }
            )
    else:
        # Loop exhausted without a plain-text finish - ask once more, no tools.
        stream = await client.chat.completions.create(
            model=model, messages=messages, stream=True, max_tokens=MAX_REPLY_TOKENS
        )
        async for kind, payload in _consume_stream(stream):
            if kind == "token":
                reply_parts.append(payload)
                yield {"type": "token", "text": payload}

    if _SIZE_INTENT_RE.search(user_text) and not any(
        c["name"] in ("list_plate_sizes", "start_plate", "add_item_to_plate") for c in made_tool_calls
    ):
        made_tool_calls.append({"name": "list_plate_sizes", "arguments": {}})
        result = await dispatch_tool(
            session, client, conversation, draft, "list_plate_sizes", {}, embedding_client
        )
        for block in result.ui_blocks:
            ui_blocks.append(block)
            yield {"type": "ui_block", "block": block}

    reply_text = "".join(reply_parts)
    yield {
        "type": "done",
        "reply_text": reply_text,
        "tool_calls": made_tool_calls or None,
        "ui_blocks": ui_blocks,
    }

    suggestions: list[str] = []
    if get_settings().suggestions_enabled:
        tool_names = [c["name"] for c in made_tool_calls]
        suggestions = rule_suggestions(user_text, tool_names, ui_blocks)
        if not suggestions and not any(
            c["name"] == "request_review" for c in made_tool_calls
        ):
            suggestions = await generate_suggestions(client, model, user_text, reply_text)
    yield {"type": "suggestions_block", "suggestions": suggestions}


def _json_result(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
