"""Phase 3: orders table

Creates the orders table (section 3). An order is created at confirm-time with
status 'pending_handoff' and the full handoff_payload; the checkout adapter
(Phase 4) may later move it to 'sent_to_checkout'.

Revision ID: 0003_phase3
Revises: 0002_phase2
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_phase3"
down_revision: Union[str, None] = "0002_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

order_status = sa.Enum("pending_handoff", "sent_to_checkout", name="order_status")


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cart_draft_id", sa.Integer(), sa.ForeignKey("cart_drafts.id"), nullable=False
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "status", order_status, nullable=False, server_default="pending_handoff"
        ),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "handoff_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_index("ix_orders_conversation_id", "orders", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_conversation_id", table_name="orders")
    op.drop_table("orders")
    order_status.drop(op.get_bind(), checkfirst=True)
