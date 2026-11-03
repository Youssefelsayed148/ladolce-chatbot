"""Store integration: store ids on products/plate sizes, variants, finishes

Revision ID: 0008_store_integration
Revises: 0007_drop_kb_ivfflat
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_store_integration"
down_revision: Union[str, None] = "0007_drop_kb_ivfflat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("store_product_id", sa.String(36), nullable=True))
    op.add_column("products", sa.Column("store_date_id", sa.String(36), nullable=True))
    op.add_column("products", sa.Column("weight_grams", sa.Integer(), nullable=True))
    op.create_index("ix_products_store_product_id", "products", ["store_product_id"])
    op.create_index("ix_products_store_date_id", "products", ["store_date_id"])

    op.add_column("plate_sizes", sa.Column("store_canvas_id", sa.String(36), nullable=True))
    op.add_column("plate_sizes", sa.Column("kind", sa.String(16), nullable=True))
    op.add_column("plate_sizes", sa.Column("capacity_grams", sa.Integer(), nullable=True))
    op.add_column("plate_sizes", sa.Column("max_pieces", sa.Integer(), nullable=True))
    op.create_index("ix_plate_sizes_store_canvas_id", "plate_sizes", ["store_canvas_id"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("store_variant_id", sa.String(36), nullable=False, unique=True),
        sa.Column("sku", sa.String(64), nullable=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=True),
        sa.Column("size", sa.String(8), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])

    op.create_table(
        "finishes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_finish_id", sa.String(36), nullable=False, unique=True),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("finishes")
    op.drop_index("ix_product_variants_product_id", table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index("ix_plate_sizes_store_canvas_id", table_name="plate_sizes")
    for c in ("max_pieces", "capacity_grams", "kind", "store_canvas_id"):
        op.drop_column("plate_sizes", c)
    op.drop_index("ix_products_store_date_id", table_name="products")
    op.drop_index("ix_products_store_product_id", table_name="products")
    for c in ("weight_grams", "store_date_id", "store_product_id"):
        op.drop_column("products", c)
