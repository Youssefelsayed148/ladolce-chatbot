#!/usr/bin/env python3
"""Ingest company documents (policies, FAQ, about-us, shipping/returns,
certifications) into kb_chunks for the search_knowledge_base RAG tool.

Reads every .pdf/.md/.txt file in data/kb_sources/, extracts its text, chunks
it (app.services.knowledge_base.chunk_text - sentence-boundary aware,
~300-500 token windows, ~15% overlap), embeds each chunk with
text-embedding-3-small, and upserts into kb_chunks.

Idempotency: each file's extracted text is hashed (sha256); the hash is stored
in every chunk's metadata.file_hash.
  - If a source file's stored chunks already carry the current hash, it's
    skipped entirely - no re-embedding, no OpenAI cost, no duplicate rows.
  - Otherwise every existing chunk for that source is deleted and replaced
    with freshly chunked + embedded ones.
Deleting and reinserting on change (rather than diffing chunk-by-chunk) is the
simpler choice and correct here: editing a document shifts sentence
boundaries, which shifts every downstream chunk's content anyway, so a
chunk-level diff would rarely find real matches. Whole-file hashing gets the
same idempotency at a fraction of the complexity.

Run locally:   python api/scripts/ingest_kb.py
Run in Docker: docker compose run --rm api python scripts/ingest_kb.py
               (compose mounts ./data at /data)
"""

import hashlib
import os
import sys
from pathlib import Path

from openai import OpenAI
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

# Make the app package importable when run as a standalone script.
API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.models import KbChunk  # noqa: E402
from app.services.knowledge_base import chunk_text  # noqa: E402

REPO_ROOT = API_DIR.parent
EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_BATCH_SIZE = 100  # OpenAI accepts up to 2048 inputs/call; keep well under.


def log(message: str) -> None:
    print(f"[ingest_kb] {message}", file=sys.stderr)


def _source_dir() -> Path:
    override = os.environ.get("KB_SOURCE_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "data" / "kb_sources"


def _sync_engine():
    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://ladolce:ladolce@db:5432/ladolce"
    ).replace("+asyncpg", "+psycopg")
    return create_engine(url, future=True)


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend(item.embedding for item in response.data)
    return embeddings


def ingest_file(session: Session, client: OpenAI, path: Path) -> tuple[str, int]:
    """Returns (status, chunk_count) where status is 'created', 'updated', or
    'skipped'."""
    source = path.name
    text = _extract_text(path)
    content_hash = _content_hash(text)

    existing = list(
        session.execute(select(KbChunk).where(KbChunk.source == source)).scalars()
    )
    if existing and all(c.metadata_.get("file_hash") == content_hash for c in existing):
        return "skipped", len(existing)

    status = "updated" if existing else "created"
    if existing:
        session.execute(delete(KbChunk).where(KbChunk.source == source))
        session.flush()

    chunks = chunk_text(text)
    if not chunks:
        log(f"  {source}: no extractable text, nothing to embed")
        return status, 0

    embeddings = _embed_batch(client, chunks)
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        session.add(
            KbChunk(
                source=source,
                content=chunk,
                embedding=embedding,
                metadata_={"chunk_index": i, "file_hash": content_hash},
            )
        )
    session.commit()
    return status, len(chunks)


def main() -> None:
    source_dir = _source_dir()
    if not source_dir.is_dir():
        log(f"source directory not found: {source_dir}")
        sys.exit(1)

    paths = sorted(
        p for p in source_dir.iterdir() if p.suffix.lower() in (".pdf", ".md", ".txt")
    )
    if not paths:
        log(f"no .pdf/.md/.txt files found in {source_dir}")
        return

    # OpenCode Go has no /v1/embeddings endpoint (probed 404 on both
    # /zen/go/v1/embeddings and /zen/v1/embeddings). KB ingestion therefore
    # stays on the OpenAI embedding path as an explicit exception; see
    # docs/llm-layer-audit.md Section 4.5.
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    engine = _sync_engine()

    files_created = files_updated = files_skipped = 0
    chunks_created = chunks_skipped = 0
    with Session(engine) as session:
        for path in paths:
            status, count = ingest_file(session, client, path)
            if status == "created":
                files_created += 1
                chunks_created += count
                log(f"  {path.name}: created ({count} chunks)")
            elif status == "updated":
                files_updated += 1
                chunks_created += count
                log(f"  {path.name}: updated ({count} chunks)")
            else:
                files_skipped += 1
                chunks_skipped += count
                log(f"  {path.name}: skipped, unchanged ({count} chunks)")

    log(
        f"done: {len(paths)} files processed "
        f"({files_created} created, {files_updated} updated, {files_skipped} skipped unchanged); "
        f"{chunks_created} chunks embedded, {chunks_skipped} chunks left untouched"
    )


if __name__ == "__main__":
    main()
