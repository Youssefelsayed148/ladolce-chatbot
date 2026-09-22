"""Phase 6 revision: bestseller flag on products

Adds products.is_bestseller so the "what are your bestsellers" chat path can
filter on a real structural flag instead of relying on the LLM's free-text
query substring-matching a product's name/description (which fails for a
literal query like "bestsellers" - no product is named that).

Revision ID: 0006_bestseller
Revises: 0005_kb_chunks
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_bestseller"
down_revision: Union[str, None] = "0005_kb_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_bestseller", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("products", "is_bestseller", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "is_bestseller")
