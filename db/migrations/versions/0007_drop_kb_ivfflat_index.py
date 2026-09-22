"""Drop the kb_chunks ivfflat vector index - it was silently wrong

0005_kb_chunks created an ivfflat (lists=100) index on kb_chunks.embedding
BEFORE any rows existed, on the (documented) assumption that this was safe
because ingestion always runs before the index is load-bearing. That
assumption is false: ivfflat's centroids are fixed at index build time and
are never recomputed as rows are added, so an index built on an empty (or
near-empty) table stays degenerate for its whole life unless someone manually
REINDEXes it. Verified directly against the live kb_chunks table (4 real
chunks, built via the original empty-table index): `ORDER BY embedding <=>
:q LIMIT 1` silently returned ZERO rows, while the same query with LIMIT 4/5
correctly returned all 4 (Postgres's planner fell back to a sequential scan
for the larger limit, sidestepping the broken index entirely - LIMIT 1 was
small enough to actually use it). This is a live, real bug, independent of
and in addition to the SIMILARITY_THRESHOLD miscalibration fixed alongside
this migration (see knowledge_base.py) - either one alone was enough to make
search_knowledge_base silently return nothing for real, on-topic questions.

At the corpus size this project actually has (a handful to a few dozen KB
source documents so far; the original design doc's "few hundred to
low-thousands" ceiling is still a long way off), a plain sequential scan is
both simpler and exactly correct - pgvector's own guidance is that an
approximate index like ivfflat/hnsw isn't worth the complexity until a table
reaches many thousands of rows. Just drop it for now.

If/when the corpus genuinely grows large enough to need an approximate index
again: build (or REINDEX) it as a one-off *after* ingestion has populated the
table with real data, never as a migration step that runs before ingestion -
that ordering is exactly what produced this bug.

Revision ID: 0007_drop_kb_ivfflat
Revises: 0006_bestseller
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_drop_kb_ivfflat"
down_revision: Union[str, None] = "0006_bestseller"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_cosine")


def downgrade() -> None:
    # Recreated empty, same as the original migration - see this file's
    # module docstring for why that's exactly the state that caused the bug.
    # Only present so `alembic downgrade` doesn't error; don't rely on it.
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_cosine ON kb_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
