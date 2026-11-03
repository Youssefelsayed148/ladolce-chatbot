"""Custom box ribbon finish and gift message on cart items

Revision ID: 0009_box_finish_gift
Revises: 0008_store_integration
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_box_finish_gift"
down_revision: Union[str, None] = "0008_store_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cart_items", sa.Column("finish_id", sa.Integer(), sa.ForeignKey("finishes.id"), nullable=True))
    op.add_column("cart_items", sa.Column("gift_message", sa.String(180), nullable=True))


def downgrade() -> None:
    op.drop_column("cart_items", "gift_message")
    op.drop_column("cart_items", "finish_id")
