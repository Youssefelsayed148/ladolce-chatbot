"""Phase 2: cart tables

Creates cart_drafts, cart_items, cart_plate_contents (section 3). Order/checkout
tables come in Phase 3.

Revision ID: 0002_phase2
Revises: 0001_phase1
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_phase2"
down_revision: Union[str, None] = "0001_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

cart_status = sa.Enum(
    "building", "reviewed", "confirmed", "abandoned", name="cart_status"
)
cart_item_type = sa.Enum("single_product", "custom_plate", name="cart_item_type")


def upgrade() -> None:
    op.create_table(
        "cart_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "status", cart_status, nullable=False, server_default="building"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cart_drafts_conversation_id", "cart_drafts", ["conversation_id"])

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cart_draft_id",
            sa.Integer(),
            sa.ForeignKey("cart_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", cart_item_type, nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column(
            "plate_size_id", sa.Integer(), sa.ForeignKey("plate_sizes.id"), nullable=True
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=10, scale=2), nullable=False),
    )
    op.create_index("ix_cart_items_cart_draft_id", "cart_items", ["cart_draft_id"])

    op.create_table(
        "cart_plate_contents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cart_item_id",
            sa.Integer(),
            sa.ForeignKey("cart_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("slots_used", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_cart_plate_contents_cart_item_id", "cart_plate_contents", ["cart_item_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cart_plate_contents_cart_item_id", table_name="cart_plate_contents")
    op.drop_table("cart_plate_contents")
    op.drop_index("ix_cart_items_cart_draft_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_cart_drafts_conversation_id", table_name="cart_drafts")
    op.drop_table("cart_drafts")
    bind = op.get_bind()
    cart_item_type.drop(bind, checkfirst=True)
    cart_status.drop(bind, checkfirst=True)
