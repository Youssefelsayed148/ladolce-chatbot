"""Chat orchestration (Phases 1-2).

Streaming-first, with a multi-round tool loop: the model may call catalog/cart
tools (search, recommend, start_plate, add_item_to_plate, ...) across several
rounds before producing its final natural-language reply. Every round streams as
Server-Sent Events. All capacity/pricing is computed server-side in the tools;
the model only narrates authoritative results (design doc section 5).

`generate_chat_events` is agnostic to the OpenAI client it's given, so tests
inject a fake client that emits canned streams.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import CartDraft, Conversation
from app.services.tools import ALL_TOOLS, dispatch_tool, parse_tool_args

logger = logging.getLogger("app.chat")

MAX_TOOL_ROUNDS = 6

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
    "(the dates inside add nothing), and it is limited by BOTH a maximum number of "
    "pieces AND a maximum total weight in grams - tool results report the remaining "
    "pieces and grams; relay them, never calculate fit yourself. Only individual "
    "date varieties go in a box. For every custom box also ask which ribbon finish "
    "they would like (set_finish - required before review) and offer an optional "
    "gift message of at most 180 characters (set_gift_message).\n\n"
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
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUGGESTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Guest: {user_text}\nConcierge: {reply_text}"},
            ],
            stream=True,
        )
        content = ""
        async for kind, payload in _consume_stream(stream):
            if kind == "final":
                content = payload["content"]

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

    for _round in range(MAX_TOOL_ROUNDS):
        stream = await client.chat.completions.create(
            model=model, messages=messages, tools=ALL_TOOLS, stream=True,
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
            model=model, messages=messages, stream=True
        )
        async for kind, payload in _consume_stream(stream):
            if kind == "token":
                reply_parts.append(payload)
                yield {"type": "token", "text": payload}

    reply_text = "".join(reply_parts)
    yield {
        "type": "done",
        "reply_text": reply_text,
        "tool_calls": made_tool_calls or None,
        "ui_blocks": ui_blocks,
    }

    suggestions = (
        await generate_suggestions(client, model, user_text, reply_text)
        if get_settings().suggestions_enabled
        else []
    )
    yield {"type": "suggestions_block", "suggestions": suggestions}


def _json_result(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
