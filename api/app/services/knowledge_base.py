"""Knowledge base / RAG retrieval (Phase 5).

Backs the `search_knowledge_base` tool: embeds the guest's question and finds
the closest ingested document chunks (policies, FAQ, shipping/returns,
certifications - see scripts/ingest_kb.py). Like catalog/cart, this is the
authoritative source the model must ground its answer in; the tool result
makes it explicit when nothing relevant was found so the model says so instead
of inventing an answer (see the system prompt guardrail in app.services.chat).

Dialect note: production runs on Postgres with pgvector's `<=>` cosine-distance
operator, which is by far the fastest path once the ivfflat index exists. The
test suite runs the whole app against SQLite (tests/conftest.py), which has no
such operator, so this module computes cosine similarity in Python there
instead - fine at test-fixture scale, never used in production. This mirrors
the JsonType/EmbeddingType dialect-variant pattern already used in models.py.
"""

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KbChunk

logger = logging.getLogger("app.knowledge_base")

# Chunks scoring below this cosine similarity are treated as not relevant
# enough to ground an answer.
#
# The previous value here (0.5) assumed genuinely relevant OpenAI-embedding
# matches score "well above 0.7" - that's true for some embedding models, but
# NOT for text-embedding-3-small against this corpus: measured directly
# against the real kb_chunks table, correct top-matches for on-topic guest
# questions ("what are your shipping times" -> shipping.md, "is this halal"
# -> dietary_allergens.md, "how long until I get my money back" ->
# returns_refunds.md, ...) score 0.28-0.50, while clearly off-topic queries
# ("what is the capital of France") score under 0.1. At 0.5, EVERY real KB
# document in this corpus except one chunk was silently filtered out even for
# its own most obviously on-topic question - search_knowledge_base returned
# empty and the concierge told guests it "didn't have" info that was sitting
# right there in the KB. 0.2 sits with real margin below every measured true
# positive and well above pure-noise negatives; it will occasionally let
# through a marginally-relevant chunk for a question the KB can't actually
# answer, but that's the safe failure mode - the tool's own system-prompt
# instructions already tell the model to say "I don't have that information"
# when a retrieved passage doesn't actually answer the question, so a
# borderline false positive here just falls through to that same honest
# non-answer. A false negative (this bug) has no such safety net - it hides
# a real answer completely, with no fallback.
SIMILARITY_THRESHOLD = 0.2


@dataclass
class KbChunkResult:
    id: int
    source: str
    content: str
    metadata: dict
    similarity: float


# --------------------------------------------------------------------------- #
# Chunking (shared by the ingestion script and its tests)
# --------------------------------------------------------------------------- #
MIN_CHUNK_TOKENS = 300
MAX_CHUNK_TOKENS = 500
CHUNK_OVERLAP_RATIO = 0.15

# Splits after sentence-ending punctuation followed by whitespace and a capital
# letter/digit/quote (avoids splitting on "Dr." or "3.5kg"), or on blank lines
# (paragraph breaks).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])|\n\s*\n+")


def split_sentences(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


def _word_count(text: str) -> int:
    # Approximate token count without a tokenizer dependency (and the network
    # fetch tiktoken's encoder would need on first use, which the offline
    # ingestion script and its tests should never require): English prose
    # averages ~0.75 words/token, so word count is a good enough proxy for
    # sizing 300-500 token windows.
    return len(text.split())


def chunk_text(text: str) -> list[str]:
    """Sentence-boundary-aware chunking into ~300-500 token windows with ~15%
    overlap. Never cuts mid-sentence; a single sentence longer than the max is
    still emitted whole rather than truncated."""
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    n = len(sentences)
    start = 0
    while start < n:
        count = 0
        end = start
        while end < n:
            wc = _word_count(sentences[end])
            if count >= MIN_CHUNK_TOKENS and count + wc > MAX_CHUNK_TOKENS:
                break
            count += wc
            end += 1
            if count >= MAX_CHUNK_TOKENS:
                break
        end = max(end, start + 1)  # always make progress, even on one giant sentence
        chunks.append(" ".join(sentences[start:end]))

        if end >= n:
            break

        # Step back from the end of this chunk far enough to cover ~15% of it,
        # sentence-by-sentence, so the next chunk starts with real overlap.
        overlap_target = count * CHUNK_OVERLAP_RATIO
        acc = 0.0
        back = 0
        idx = end - 1
        while idx > start and acc < overlap_target:
            acc += _word_count(sentences[idx])
            idx -= 1
            back += 1
        start = max(end - back, start + 1)

    return chunks


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
async def embed_texts(client: Any, model: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = await client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


async def embed_text(client: Any, model: str, text: str) -> list[float]:
    (embedding,) = await embed_texts(client, model, [text])
    return embedding


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _search_postgres(
    session: AsyncSession, query_embedding: list[float], top_k: int
) -> list[KbChunkResult]:
    distance = KbChunk.embedding.cosine_distance(query_embedding)
    stmt = select(KbChunk, distance.label("distance")).order_by(distance).limit(top_k)
    result = await session.execute(stmt)
    rows: list[KbChunkResult] = []
    for chunk, distance_value in result.all():
        similarity = 1.0 - float(distance_value)
        rows.append(
            KbChunkResult(
                id=chunk.id,
                source=chunk.source,
                content=chunk.content,
                metadata=chunk.metadata_,
                similarity=similarity,
            )
        )
    return rows


async def _search_python_fallback(
    session: AsyncSession, query_embedding: list[float], top_k: int
) -> list[KbChunkResult]:
    """Non-Postgres dialects (SQLite, in tests) have no vector index or `<=>`
    operator, so score every row in Python. Fine at test-fixture scale;
    production always takes the pgvector path above."""
    result = await session.execute(select(KbChunk))
    scored = [
        KbChunkResult(
            id=chunk.id,
            source=chunk.source,
            content=chunk.content,
            metadata=chunk.metadata_,
            similarity=_cosine_similarity(list(chunk.embedding), query_embedding),
        )
        for chunk in result.scalars().all()
    ]
    scored.sort(key=lambda r: r.similarity, reverse=True)
    return scored[:top_k]


async def search_kb(
    session: AsyncSession,
    client: Any,
    query: str,
    top_k: int = 5,
    embedding_model: str = "text-embedding-3-small",
) -> list[KbChunkResult]:
    """Embed `query` and return the top_k closest kb_chunks with similarity >=
    SIMILARITY_THRESHOLD, best first. May return an empty list - that's the
    expected signal for "nothing relevant in the knowledge base"."""
    query_embedding = await embed_text(client, embedding_model, query)

    dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
    if dialect == "postgresql":
        results = await _search_postgres(session, query_embedding, top_k)
    else:
        results = await _search_python_fallback(session, query_embedding, top_k)

    relevant = [r for r in results if r.similarity >= SIMILARITY_THRESHOLD]

    logger.info(
        "kb_search",
        extra={
            "query": query,
            "top1_score": relevant[0].similarity if relevant else (
                results[0].similarity if results else None
            ),
            "num_results": len(relevant),
        },
    )
    return relevant
