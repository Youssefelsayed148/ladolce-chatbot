"""Chosen store variant on single-product cart items

Revision ID: 0010_cart_item_variant
Revises: 0009_box_finish_gift
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_cart_item_variant"
down_revision: Union[str, None] = "0009_box_finish_gift"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cart_items",
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("product_variants.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cart_items", "variant_id")
