"""SQLAlchemy ORM models — Phase 1 tables only.

Mirrors section 3 of the design doc. The cart/order tables (cart_drafts,
cart_items, cart_plate_contents, orders) are intentionally NOT defined yet —
they land in Phases 2–3.

Portability note: `tool_calls` uses SQLAlchemy's generic JSON with a PostgreSQL
JSONB variant, so the same models create cleanly on Postgres (production) and
SQLite (tests) without a live database.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Enum value sets (kept as plain constants so services/tests can reference them).
CART_STATUSES = ("building", "reviewed", "confirmed", "abandoned")
CART_ITEM_TYPES = ("single_product", "custom_plate")
ORDER_STATUSES = ("pending_handoff", "sent_to_checkout")

JsonType = JSON().with_variant(JSONB, "postgresql")

KB_EMBEDDING_DIM = 1536  # text-embedding-3-small
# pgvector's Vector type only compiles for Postgres; tests run the whole app
# against SQLite (see tests/conftest.py), so - mirroring JsonType above - it
# falls back to a plain JSON column of floats there. app.services.knowledge_base
# branches on dialect at query time to match.
EmbeddingType = Vector(KB_EMBEDDING_DIM).with_variant(JSON(), "sqlite")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_single_item: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Curated flag (seeded by scripts/seed_catalog.py) backing the bestsellers
    # tool path - a structural filter so "what are your bestsellers" doesn't
    # depend on the LLM's free-text query happening to substring-match a
    # product's name/description in search_products.
    is_bestseller: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    category: Mapped["Category | None"] = relationship(back_populates="products")
    slot_cost: Mapped["ProductSlotCost | None"] = relationship(
        back_populates="product", uselist=False
    )


class PlateSize(Base):
    __tablename__ = "plate_sizes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    base_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProductSlotCost(Base):
    __tablename__ = "product_slot_cost"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), primary_key=True
    )
    slot_cost: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="slot_cost")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Public, non-guessable handle the client passes back as `conversation_id`.
    session_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # system|user|assistant|tool
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | list | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class CartDraft(Base):
    __tablename__ = "cart_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*CART_STATUSES, name="cart_status"),
        default="building",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart_draft", cascade="all, delete-orphan", order_by="CartItem.id"
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_draft_id: Mapped[int] = mapped_column(
        ForeignKey("cart_drafts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_type: Mapped[str] = mapped_column(
        Enum(*CART_ITEM_TYPES, name="cart_item_type"), nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    plate_size_id: Mapped[int | None] = mapped_column(
        ForeignKey("plate_sizes.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # unit_price is snapshotted from the catalog at add-time so later catalog
    # price edits never retroactively change an in-progress cart.
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    cart_draft: Mapped["CartDraft"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship()
    plate_size: Mapped["PlateSize | None"] = relationship()
    plate_contents: Mapped[list["CartPlateContent"]] = relationship(
        back_populates="cart_item",
        cascade="all, delete-orphan",
        order_by="CartPlateContent.id",
    )


class CartPlateContent(Base):
    __tablename__ = "cart_plate_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_item_id: Mapped[int] = mapped_column(
        ForeignKey("cart_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # slots_used = product_slot_cost.slot_cost * quantity, computed server-side.
    slots_used: Mapped[int] = mapped_column(Integer, nullable=False)
    # Filling price snapshotted at add-time (like cart_items.unit_price), so a
    # later catalog price change never alters an in-progress plate.
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    cart_item: Mapped["CartItem"] = relationship(back_populates="plate_contents")
    product: Mapped["Product"] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_draft_id: Mapped[int] = mapped_column(
        ForeignKey("cart_drafts.id"), nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*ORDER_STATUSES, name="order_status"),
        default="pending_handoff",
        nullable=False,
    )
    total_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # The exact order data handed to the checkout adapter (Phase 4).
    handoff_payload: Mapped[dict | None] = mapped_column(JsonType, nullable=True)


class KbChunk(Base):
    """A chunk of an ingested company document (policy/FAQ/about-us/etc), with
    its embedding, for the search_knowledge_base RAG tool (Phase 5)."""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingType, nullable=False)
    # At least {"chunk_index": n}; the ingestion script also stores a
    # source-file content hash here to keep re-ingestion idempotent.
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
