"""Tests for POST /api/chat — conversation creation, message persistence, and
streaming behaviour, with the OpenAI call mocked."""

import json

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, KbChunk, Message
from tests.conftest import _FakeEmbeddings


async def _collect_events(client, payload):
    events = []
    async with client.stream("POST", "/api/chat", json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


async def test_chat_streams_tokens_and_persists_messages(client, use_fake_openai):
    use_fake_openai("plain")
    events = await _collect_events(client, {"message": "hello"})

    types = [e["type"] for e in events]
    # First frame announces the conversation id; last frame is the
    # suggestions_block that always follows 'done' (see Phase 6).
    assert types[0] == "conversation"
    assert types[-1] == "suggestions_block"
    assert types[-2] == "done"
    conversation_id = events[0]["conversation_id"]

    # Streaming: content arrived as multiple token frames, not one blob.
    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) >= 2
    full_reply = "".join(e["text"] for e in token_events)
    assert "pistachio" in full_reply.lower()

    # Persistence: one conversation, a user message, and an assistant message.
    async with get_sessionmaker()() as session:
        conversations = (await session.execute(select(Conversation))).scalars().all()
        assert len(conversations) == 1
        assert conversations[0].session_token == conversation_id

        messages = (
            await session.execute(select(Message).order_by(Message.id))
        ).scalars().all()
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == "hello"
        assert "pistachio" in (messages[1].content or "").lower()


async def test_chat_tool_call_executed_and_persisted(client, use_fake_openai):
    use_fake_openai("tool")
    events = await _collect_events(client, {"message": "any pistachio treats?"})

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "search_products"
    assert tool_events[0]["arguments"] == {"query": "pistachio"}
    assert [e["type"] for e in events][-2] == "done"

    async with get_sessionmaker()() as session:
        messages = (
            await session.execute(select(Message).order_by(Message.id))
        ).scalars().all()
        assert [m.role for m in messages] == ["user", "assistant"]
        # The tool call the model made is persisted on the assistant message.
        assert messages[1].tool_calls == [
            {"name": "search_products", "arguments": {"query": "pistachio"}}
        ]


async def test_chat_reuses_existing_conversation(client, use_fake_openai):
    use_fake_openai("plain")
    first = await _collect_events(client, {"message": "first"})
    conversation_id = first[0]["conversation_id"]

    second = await _collect_events(
        client, {"conversation_id": conversation_id, "message": "second"}
    )
    assert second[0]["conversation_id"] == conversation_id

    async with get_sessionmaker()() as session:
        conversations = (await session.execute(select(Conversation))).scalars().all()
        assert len(conversations) == 1  # no new conversation created

        messages = (
            await session.execute(select(Message).order_by(Message.id))
        ).scalars().all()
        # Two turns, each a user + assistant message.
        assert [m.role for m in messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert messages[0].content == "first"
        assert messages[2].content == "second"


async def test_chat_system_prompt_lists_real_category_names(client, use_fake_openai):
    # Regression coverage for the "gift boxes" gap found alongside the
    # bestsellers fix: search_products' `category` param is an exact match,
    # but the model was never told the real category names, so a
    # category-shaped ask ("show me gift boxes") could never resolve via that
    # param - see _categories_context in routers/chat.py.
    async with get_sessionmaker()() as session:
        session.add(Category(name="Gift Boxes & Trays", sort_order=0))
        await session.commit()

    fake = use_fake_openai("plain")
    await _collect_events(client, {"message": "hello"})

    first_call = fake.chat.completions.calls[0]
    system_content = first_call["messages"][0]["content"]
    assert "Gift Boxes & Trays" in system_content


async def _seed_kb_chunk(source: str, content: str, vocab_text: str) -> None:
    async with get_sessionmaker()() as session:
        session.add(
            KbChunk(
                source=source,
                content=content,
                embedding=_FakeEmbeddings._embed(vocab_text),
                metadata_={"chunk_index": 0},
            )
        )
        await session.commit()


async def test_chat_kb_tool_grounds_response_in_retrieved_content(client, use_fake_openai):
    await _seed_kb_chunk(
        "returns.md",
        "You may return dates within 14 days of delivery for a full refund.",
        "return policy returns",
    )
    use_fake_openai("kb")
    events = await _collect_events(client, {"message": "What's your return policy?"})

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "search_knowledge_base"

    full_reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "14 days" in full_reply

    async with get_sessionmaker()() as session:
        messages = (
            await session.execute(select(Message).order_by(Message.id))
        ).scalars().all()
        assert messages[1].tool_calls == [
            {"name": "search_knowledge_base", "arguments": {"query": "return policy"}}
        ]


async def test_chat_kb_tool_empty_result_does_not_hallucinate(client, use_fake_openai):
    # Seed an unrelated chunk so retrieval genuinely runs and genuinely finds
    # nothing relevant, rather than trivially having an empty table.
    await _seed_kb_chunk(
        "returns.md",
        "You may return dates within 14 days of delivery.",
        "return policy returns",
    )
    use_fake_openai("kb_empty")
    events = await _collect_events(client, {"message": "Do you offer pony rides?"})

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_events[0]["name"] == "search_knowledge_base"

    full_reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "don't have that information" in full_reply.lower()
    assert "14 days" not in full_reply  # never blended in the unrelated chunk


# --------------------------------------------------------------------------- #
# Phase 6: suggested-question chips
# --------------------------------------------------------------------------- #
async def test_chat_greeting_suggestions_endpoint(client):
    resp = await client.get("/api/chat/suggestions/greeting")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) == 3
    assert all(isinstance(s, str) and s for s in data["suggestions"])


async def test_chat_turn_includes_suggestions_block_after_done(client, use_fake_openai):
    use_fake_openai("plain")
    events = await _collect_events(client, {"message": "hello"})

    types = [e["type"] for e in events]
    assert types[-1] == "suggestions_block"
    assert types[-2] == "done"  # visible reply finalises before chips arrive

    suggestions = events[-1]["suggestions"]
    assert 1 <= len(suggestions) <= 3
    assert all(isinstance(s, str) and s for s in suggestions)


async def test_chat_suggestions_degrade_gracefully_on_malformed_output(client, use_fake_openai):
    use_fake_openai("plain", suggestions_mode="broken")
    events = await _collect_events(client, {"message": "hello"})

    # The main reply is completely unaffected by the suggestions failure.
    assert [e["type"] for e in events][-2] == "done"
    full_reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "pistachio" in full_reply.lower()

    assert events[-1] == {"type": "suggestions_block", "suggestions": []}


async def test_chat_suggestions_survive_markdown_fenced_output(client, use_fake_openai):
    # Regression test: gpt-4o sometimes wraps the suggestions JSON in a
    # ```json ... ``` fence even though told to respond with ONLY the array.
    # json.loads on that raw text fails with the same "Expecting value: line 1
    # column 1" error as a genuinely empty response, so this used to silently
    # degrade to [] and hide the chip row - see generate_suggestions.
    use_fake_openai("plain", suggestions_mode="fenced")
    events = await _collect_events(client, {"message": "hello"})

    assert events[-1] == {
        "type": "suggestions_block",
        "suggestions": ["What flavours do you have?", "Show me gift boxes"],
    }


async def test_chat_suggestions_block_present_on_second_turn(client, use_fake_openai):
    # Regression test: a bug review previously accepted the single-turn
    # coverage above as proof suggestions work, but the real app showed no
    # chips reappearing after the first turn. That single test never actually
    # exercised a second turn in the same conversation - assert both turns get
    # a non-empty suggestions_block here so that gap can't hide a regression
    # again.
    use_fake_openai("plain")
    first = await _collect_events(client, {"message": "first"})
    conversation_id = first[0]["conversation_id"]
    assert first[-1]["type"] == "suggestions_block"
    assert len(first[-1]["suggestions"]) > 0

    second = await _collect_events(
        client, {"conversation_id": conversation_id, "message": "second"}
    )
    assert second[-1]["type"] == "suggestions_block"
    assert len(second[-1]["suggestions"]) > 0


async def test_chat_rejects_oversized_message(client):
    resp = await client.post("/api/chat", json={"message": "x" * 1001})
    assert resp.status_code == 422


async def test_ready_endpoint_checks_database(client):
    resp = await client.get("/api/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


async def test_size_question_always_gets_size_cards_even_if_model_skips_the_tool(client, use_fake_openai):
    from app.models import PlateSize

    async with get_sessionmaker()() as session:
        session.add(PlateSize(name="The Classic Petite", capacity=18, base_price=60,
                              store_canvas_id="c1", kind="BOX", capacity_grams=350, max_pieces=18))
        await session.commit()

    use_fake_openai("plain")  # the fake model answers in prose and never calls a tool
    events = await _collect_events(client, {"message": "what sizes do the boxes come in"})
    blocks = [e["block"] for e in events if e["type"] == "ui_block"]
    assert [b["type"] for b in blocks] == ["plate_size_options"]
    assert blocks[0]["data"]["sizes"][0]["name"] == "The Classic Petite"
    # and the follow-up chips fit the size question
    assert "Which size is best for a gift?" in events[-1]["suggestions"]


async def test_non_box_question_gets_no_size_cards(client, use_fake_openai):
    use_fake_openai("plain")
    events = await _collect_events(client, {"message": "hello"})
    assert not [e for e in events if e["type"] == "ui_block"]
