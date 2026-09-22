"""Phase 2 revision: snapshot filling price on cart_plate_contents

Custom-plate pricing changes from a flat plate base_price to
base_price + sum(filling unit_price * quantity). Each filling's unit_price is
snapshotted at add-time (like cart_items), so later catalog price changes don't
retroactively alter an in-progress plate.

Revision ID: 0004_plate_price
Revises: 0003_phase3
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_plate_price"
down_revision: Union[str, None] = "0003_phase3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default keeps the migration safe if any rows already exist; the app
    # always sets unit_price explicitly on insert.
    op.add_column(
        "cart_plate_contents",
        sa.Column(
            "unit_price",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("cart_plate_contents", "unit_price", server_default=None)


def downgrade() -> None:
    op.drop_column("cart_plate_contents", "unit_price")
