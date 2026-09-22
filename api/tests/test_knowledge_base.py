"""Tests for the knowledge base / RAG service (Phase 5): chunking and
retrieval. The OpenAI embedding call is always mocked via FakeOpenAIClient -
these tests never hit the real API."""

from app.core.db import get_sessionmaker
from app.models import KbChunk
from app.services.knowledge_base import SIMILARITY_THRESHOLD, chunk_text, search_kb
from tests.conftest import FakeOpenAIClient, _FakeEmbeddings


def _make_sentence(i: int, word_count: int = 20) -> str:
    words = [f"Sentence{i:02d}"] + ["filler"] * (word_count - 1)
    return " ".join(words) + "."


def test_chunk_text_respects_sentence_boundaries_size_and_overlap():
    sentences = [_make_sentence(i) for i in range(40)]  # 40 * 20 = 800 words
    doc = " ".join(sentences)

    chunks = chunk_text(doc)

    assert len(chunks) == 2
    # Every chunk is built from whole sentences - re-splitting it recovers
    # exactly the sentences it was built from, never a fragment.
    for chunk in chunks:
        word_count = len(chunk.split())
        assert 300 <= word_count <= 500

    # ~15% overlap: the tail of chunk 1 reappears at the head of chunk 2.
    assert chunks[0].startswith("Sentence00")
    assert chunks[1].startswith("Sentence21")
    assert "Sentence21" in chunks[0]  # the overlapping sentence is shared
    assert chunks[0].split(".")[-2].strip().startswith("Sentence24")


def test_chunk_text_empty_input():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_never_splits_a_single_long_sentence():
    long_sentence = "Word " * 600 + "."
    chunks = chunk_text(long_sentence)
    assert len(chunks) == 1
    assert chunks[0] == long_sentence.strip()


async def test_search_kb_returns_matching_chunk_above_threshold(prepare_db):
    async with get_sessionmaker()() as session:
        session.add_all(
            [
                KbChunk(
                    source="returns.md",
                    content="Our return policy allows returns within 14 days of delivery.",
                    embedding=_FakeEmbeddings._embed("return policy returns"),
                    metadata_={"chunk_index": 0},
                ),
                KbChunk(
                    source="shipping.md",
                    content="We offer worldwide shipping on all orders.",
                    embedding=_FakeEmbeddings._embed("shipping ship"),
                    metadata_={"chunk_index": 0},
                ),
            ]
        )
        await session.commit()

        fake = FakeOpenAIClient()
        results = await search_kb(session, fake, "What is your return policy?", top_k=5)

    assert len(results) == 1
    assert results[0].source == "returns.md"
    assert "return" in results[0].content.lower()
    assert results[0].similarity >= SIMILARITY_THRESHOLD
    # The query was actually embedded through the (fake) client, not skipped.
    assert fake.embeddings.calls


async def test_search_kb_returns_empty_when_nothing_relevant(prepare_db):
    async with get_sessionmaker()() as session:
        session.add(
            KbChunk(
                source="shipping.md",
                content="We offer worldwide shipping on all orders.",
                embedding=_FakeEmbeddings._embed("shipping ship"),
                metadata_={"chunk_index": 0},
            )
        )
        await session.commit()

        fake = FakeOpenAIClient()
        # Unrelated query - the fake embedder gives it a distinct direction
        # that scores near 0 cosine similarity against the shipping chunk.
        results = await search_kb(session, fake, "do you offer pony rides", top_k=5)

    assert results == []
