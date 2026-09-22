"""Phase 5: knowledge base (RAG) - pgvector extension + kb_chunks table

Adds the pgvector extension and a kb_chunks table (source, content, a
vector(1536) embedding matching text-embedding-3-small, and metadata) for the
search_knowledge_base tool. An ivfflat cosine-distance index is added; ivfflat
(rather than hnsw) is fine for the small corpus this phase targets (a few
hundred to low-thousands of chunks) and is cheaper to build. lists=100 is
pgvector's own rule-of-thumb default for that size range - revisit if the
corpus grows past the low tens of thousands of rows.

Revision ID: 0005_kb_chunks
Revises: 0004_plate_price
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_kb_chunks"
down_revision: Union[str, None] = "0004_plate_price"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_kb_chunks_source", "kb_chunks", ["source"])

    # ivfflat requires ANALYZE (or rows present) to pick good centroids; safe to
    # create empty since ingestion always runs before this index is load-bearing.
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_cosine ON kb_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_cosine")
    op.drop_index("ix_kb_chunks_source", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
