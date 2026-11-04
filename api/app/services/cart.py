"""Cart / plate-builder logic — the authoritative server-side source of truth.

Every number the customer sees (capacity used, prices, totals) is computed here
from the database, never taken from the LLM. The LLM's tools call into these
functions; a capacity-exceeded attempt raises CapacityExceeded (relayed to the
model as a structured error) instead of silently overfilling.

Pricing model (see the Phase 2 ambiguities note in the handoff):
  * single_product line = snapshotted unit_price * quantity
  * custom_plate line   = the plate's base_price (a flat charge for a box/tray of
    up to `capacity` slots). Contents are capacity-tracked only; section 3's
    cart_plate_contents has no price column, so fillings do not add to the price.
Prices are snapshotted onto cart_items at add-time.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CartDraft,
    CartItem,
    CartPlateContent,
    Finish,
    PlateSize,
    Product,
    ProductSlotCost,
    ProductVariant,
)

from app.services import store_quote

logger = logging.getLogger("app.cart")

MAX_GIFT_MESSAGE_CHARS = 180


class CartError(Exception):
    """Base for cart errors that should be relayed to the model/user."""

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra

    def as_result(self) -> dict:
        return {"error": self.message, **self.extra}


class CapacityExceeded(CartError):
    pass


class NotFound(CartError):
    pass


@dataclass
class ToolResult:
    """What a cart-mutating tool returns: authoritative data for the model plus
    optional ui_blocks for the frontend."""

    data: dict
    ui_blocks: list[dict]


# --------------------------------------------------------------------------- #
# Draft + lookups
# --------------------------------------------------------------------------- #
async def get_active_draft(
    session: AsyncSession, conversation_id: int, for_update: bool = False
) -> CartDraft | None:
    """The most recent open draft (building or reviewed), or None. Does not
    create - a confirmed/abandoned draft is terminal. `for_update` row-locks the
    draft (Postgres) so concurrent confirms can't both pass the status check."""
    query = (
        select(CartDraft)
        .where(CartDraft.conversation_id == conversation_id)
        .where(CartDraft.status.in_(("building", "reviewed")))
        .order_by(CartDraft.id.desc())
    )
    if for_update:
        query = query.with_for_update()
    result = await session.execute(query)
    return result.scalars().first()


async def get_or_create_draft(session: AsyncSession, conversation_id: int) -> CartDraft:
    draft = await get_active_draft(session, conversation_id)
    if draft is None:
        draft = CartDraft(conversation_id=conversation_id, status="building")
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
    return draft


def _revert_to_building(draft: CartDraft) -> None:
    """Any modification to a reviewed cart invalidates that review, so the guest
    must review again (keeps the confirm button honest - it's gated on the draft
    actually being in 'reviewed' state)."""
    if draft.status == "reviewed":
        draft.status = "building"


async def _get_slot_cost(session: AsyncSession, product_id: int) -> int:
    result = await session.execute(
        select(ProductSlotCost.slot_cost).where(ProductSlotCost.product_id == product_id)
    )
    slot_cost = result.scalar_one_or_none()
    return slot_cost if slot_cost is not None else 1


async def _get_product(session: AsyncSession, product_id: int) -> Product:
    # Eager-load category via an explicit select (not session.get(options=...)
    # - selectinload's secondary query doesn't get awaited correctly through
    # get() here): _product_card_block reads product.category.name, which
    # would trigger a forbidden lazy load under async otherwise.
    result = await session.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.category))
    )
    product = result.scalar_one_or_none()
    if product is None or not product.is_active:
        raise NotFound(f"No such product (id={product_id}).", product_id=product_id)
    return product


async def _get_plate_item(session: AsyncSession, draft_id: int, cart_item_id: int) -> CartItem:
    # populate_existing=True forces the eager-loaded collections to be refreshed
    # even if the instance is already in the identity map. Without it (and with
    # expire_on_commit=False), a re-read after a commit returns the stale
    # collection from a prior load, which would under-count used slots and let a
    # plate silently overfill.
    result = await session.execute(
        select(CartItem)
        .where(CartItem.id == cart_item_id)
        .where(CartItem.cart_draft_id == draft_id)
        .options(
            selectinload(CartItem.plate_size),
            selectinload(CartItem.finish),
            selectinload(CartItem.plate_contents).selectinload(CartPlateContent.product),
        )
        .execution_options(populate_existing=True)
    )
    item = result.scalar_one_or_none()
    if item is None or item.item_type != "custom_plate":
        raise NotFound(f"No custom plate with id={cart_item_id} in this cart.")
    return item


def _plate_slots_used(item: CartItem) -> int:
    return sum(c.slots_used for c in item.plate_contents)


def _is_store_plate(item: CartItem) -> bool:
    return bool(item.plate_size and item.plate_size.store_canvas_id)


def _plate_grams_used(item: CartItem) -> int:
    return sum((c.product.weight_grams or 0) * c.quantity for c in item.plate_contents if c.product)


def _plate_limits(item: CartItem) -> dict:
    """Store-box limits + usage (pieces and grams). Pieces == slots_used."""
    plate = item.plate_size
    pieces, grams = _plate_slots_used(item), _plate_grams_used(item)
    return {
        "pieces_used": pieces,
        "pieces_total": plate.max_pieces,
        "grams_used": grams,
        "grams_total": plate.capacity_grams,
        "remaining_pieces": plate.max_pieces - pieces,
        "remaining_grams": plate.capacity_grams - grams,
    }


def bespoke_items_payload(item: CartItem) -> list[dict]:
    """Store `items` lines ({dateId, quantity<=99}) for a custom box."""
    return store_quote.split_items(
        [(c.product.store_date_id, c.quantity) for c in item.plate_contents if c.product]
    )


def _plate_line_total(item: CartItem) -> float:
    """Custom-plate price = plate base_price + sum(filling unit_price * qty).
    item.unit_price holds the snapshotted plate base_price."""
    fillings = sum(float(c.unit_price) * c.quantity for c in item.plate_contents)
    return round(float(item.unit_price) + fillings, 2)


async def _plate_price(item: CartItem) -> tuple[float, bool]:
    """(total, estimated) for a custom box. Store boxes ask the store's own quote so
    the chat shows exactly what the store will charge; if the store can't be
    reached we fall back to the local figure and flag it as an estimate."""
    local = _plate_line_total(item)
    if not _is_store_plate(item) or not item.plate_contents:
        return local, False
    finish = getattr(item, "finish", None)
    total = await store_quote.quote_box(
        item.plate_size.store_canvas_id,
        bespoke_items_payload(item),
        finish.store_finish_id if finish else None,
    )
    if total is None:
        return local, True
    return float(total), False


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
async def _resolve_variant(
    session: AsyncSession, product: Product, variant_id: int | None, quantity: int
) -> ProductVariant | None:
    """The store variant to buy, or None for a legacy product without variants.
    Several active variants and no choice -> an error listing the options."""
    result = await session.execute(
        select(ProductVariant)
        .where(ProductVariant.product_id == product.id)
        .where(ProductVariant.is_active.is_(True))
        .order_by(ProductVariant.id)
    )
    variants = list(result.scalars().all())
    if not variants:
        return None
    if variant_id is None:
        if len(variants) > 1:
            raise CartError(
                f"'{product.name}' comes in several sizes - ask the guest which one "
                "and pass its variant_id.",
                options=[
                    {"variant_id": v.id, "label": v.label, "price": float(v.price)}
                    for v in variants
                ],
            )
        variant = variants[0]
    else:
        variant = next((v for v in variants if v.id == variant_id), None)
        if variant is None:
            raise NotFound(f"No such size (variant_id={variant_id}) for '{product.name}'.")
    if variant.stock is not None and quantity > variant.stock:
        raise CartError(
            f"Only {variant.stock} of '{product.name}' ({variant.label}) in stock."
            if variant.stock > 0
            else f"'{product.name}' ({variant.label}) is out of stock.",
            available=max(variant.stock, 0),
        )
    return variant


async def add_single_product(
    session: AsyncSession,
    draft: CartDraft,
    product_id: int,
    quantity: int,
    variant_id: int | None = None,
) -> ToolResult:
    if quantity < 1:
        raise CartError("Quantity must be at least 1.")
    product = await _get_product(session, product_id)
    variant = await _resolve_variant(session, product, variant_id, quantity)
    price = variant.price if variant else product.price
    # Price 0 = a bespoke-only date (a box filling, free inside a box), never sold alone.
    if price is None or float(price) <= 0:
        raise CartError(f"'{product.name}' is not available for purchase.")
    _revert_to_building(draft)

    # Merge into an existing identical single-product line if present.
    result = await session.execute(
        select(CartItem)
        .where(CartItem.cart_draft_id == draft.id)
        .where(CartItem.item_type == "single_product")
        .where(CartItem.product_id == product_id)
        .where(
            CartItem.variant_id == variant.id if variant else CartItem.variant_id.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    unit_price = float(price)
    if item is None:
        item = CartItem(
            cart_draft_id=draft.id,
            item_type="single_product",
            product_id=product_id,
            variant_id=variant.id if variant else None,
            quantity=quantity,
            unit_price=unit_price,  # snapshot at add-time
            line_total=unit_price * quantity,
        )
        session.add(item)
    else:
        item.quantity += quantity
        # Keep the original snapshot; just recompute the line from it.
        item.line_total = float(item.unit_price) * item.quantity
    await session.commit()

    state = await get_cart_state_by_draft(session, draft)
    return ToolResult(
        data={
            "added": {
                "product": product.name,
                "quantity": quantity,
                "unit_price": unit_price,
                **({"variant": variant.label} if variant else {}),
            },
            "cart": state,
        },
        ui_blocks=[_product_card_block(product)],
    )


async def start_plate(
    session: AsyncSession, draft: CartDraft, plate_size_id: int
) -> ToolResult:
    plate = await session.get(PlateSize, plate_size_id)
    if plate is None:
        raise NotFound(f"No such plate size (id={plate_size_id}).")
    _revert_to_building(draft)

    # Reuse an untouched box of this size rather than stacking empty duplicates
    # (the model sometimes calls start_plate again instead of using cart_item_id).
    for existing in await _load_items(session, draft.id):
        if (
            existing.item_type == "custom_plate"
            and existing.plate_size_id == plate_size_id
            and not existing.plate_contents
        ):
            existing = await _get_plate_item(session, draft.id, existing.id)
            return ToolResult(
                data={
                    "cart_item_id": existing.id,
                    "plate_size": plate.name,
                    "capacity_total": plate.capacity,
                    "capacity_used": 0,
                    "price": float(existing.unit_price),
                },
                ui_blocks=[await build_plate_builder_block(session, existing)],
            )

    base_price = float(plate.base_price)
    item = CartItem(
        cart_draft_id=draft.id,
        item_type="custom_plate",
        plate_size_id=plate_size_id,
        quantity=1,
        unit_price=base_price,  # snapshot plate base price at start-time
        line_total=base_price,
    )
    session.add(item)
    await session.commit()
    item = await _get_plate_item(session, draft.id, item.id)

    block = await build_plate_builder_block(session, item)
    return ToolResult(
        data={
            "cart_item_id": item.id,
            "plate_size": plate.name,
            "capacity_total": plate.capacity,
            "capacity_used": 0,
            "price": base_price,
        },
        ui_blocks=[block],
    )


async def add_item_to_plate(
    session: AsyncSession,
    draft: CartDraft,
    cart_item_id: int,
    product_id: int,
    quantity: int,
) -> ToolResult:
    if quantity < 1:
        raise CartError("Quantity must be at least 1.")
    item = await _get_plate_item(session, draft.id, cart_item_id)
    product = await _get_product(session, product_id)
    store_plate = _is_store_plate(item)
    if store_plate:
        if not product.store_date_id or not product.weight_grams:
            raise CartError(
                f"'{product.name}' cannot go into a custom box - only individual date "
                "varieties can."
            )
    elif product.price is None:
        raise CartError(f"'{product.name}' has no price and can't be added to a plate.")
    capacity = item.plate_size.capacity
    _revert_to_building(draft)

    if store_plate:
        lim = _plate_limits(item)
        add_g = product.weight_grams * quantity
        if quantity > lim["remaining_pieces"] or add_g > lim["remaining_grams"]:
            raise CapacityExceeded(
                f"That won't fit: the {item.plate_size.name} holds "
                f"{lim['pieces_total']} pieces / {lim['grams_total']}g, "
                f"{lim['pieces_used']} pieces / {lim['grams_used']}g are used, and adding "
                f"{quantity}x '{product.name}' needs {quantity} pieces / {add_g}g.",
                **lim,
                requested_pieces=quantity,
                requested_grams=add_g,
            )

    slot_cost = 1 if store_plate else await _get_slot_cost(session, product_id)
    added_slots = slot_cost * quantity
    used = _plate_slots_used(item)

    if not store_plate and used + added_slots > capacity:
        raise CapacityExceeded(
            f"That won't fit: the {item.plate_size.name} holds {capacity} slots, "
            f"{used} are used, and adding {quantity}x '{product.name}' needs "
            f"{added_slots} more.",
            capacity_total=capacity,
            capacity_used=used,
            requested_slots=added_slots,
            available_slots=capacity - used,
        )

    existing = next(
        (c for c in item.plate_contents if c.product_id == product_id), None
    )
    if existing is None:
        session.add(
            CartPlateContent(
                cart_item_id=item.id,
                product_id=product_id,
                quantity=quantity,
                slots_used=added_slots,
                # Store boxes are priced by canvas only; dates add nothing.
                unit_price=0.0 if store_plate else float(product.price),  # snapshot at add-time
            )
        )
    else:
        # Keep the original snapshot; only grow quantity/slots.
        existing.quantity += quantity
        existing.slots_used += added_slots
    await session.commit()

    item = await _get_plate_item(session, draft.id, cart_item_id)
    item.line_total = _plate_line_total(item)
    await session.commit()

    block = await build_plate_builder_block(session, item)
    return ToolResult(
        data={
            "added": {"product": product.name, "quantity": quantity, "slots": added_slots},
            "capacity_used": _plate_slots_used(item),
            "capacity_total": capacity,
            "plate_price": block["data"]["price"],
            **(_plate_limits(item) if store_plate else {}),
        },
        ui_blocks=[block],
    )


async def remove_item_from_plate(
    session: AsyncSession, draft: CartDraft, cart_item_id: int, product_id: int
) -> ToolResult:
    item = await _get_plate_item(session, draft.id, cart_item_id)
    existing = next(
        (c for c in item.plate_contents if c.product_id == product_id), None
    )
    if existing is None:
        raise NotFound("That item isn't in the plate.")
    _revert_to_building(draft)
    await session.delete(existing)
    await session.commit()

    item = await _get_plate_item(session, draft.id, cart_item_id)
    item.line_total = _plate_line_total(item)
    await session.commit()

    block = await build_plate_builder_block(session, item)
    return ToolResult(
        data={
            "removed": {"product_id": product_id},
            "capacity_used": _plate_slots_used(item),
            "capacity_total": item.plate_size.capacity,
            "plate_price": block["data"]["price"],
        },
        ui_blocks=[block],
    )


async def set_finish(
    session: AsyncSession, draft: CartDraft, cart_item_id: int, finish_id: int
) -> ToolResult:
    item = await _get_plate_item(session, draft.id, cart_item_id)
    finish = await session.get(Finish, finish_id)
    if finish is None:
        raise NotFound(f"No such ribbon finish (id={finish_id}).")
    _revert_to_building(draft)
    item.finish_id = finish.id
    await session.commit()
    item = await _get_plate_item(session, draft.id, cart_item_id)
    return ToolResult(
        data={"cart_item_id": item.id, "finish": finish.name_en},
        ui_blocks=[await build_plate_builder_block(session, item)],
    )


async def set_gift_message(
    session: AsyncSession, draft: CartDraft, cart_item_id: int, message: str
) -> ToolResult:
    item = await _get_plate_item(session, draft.id, cart_item_id)
    message = (message or "").strip()
    if len(message) > MAX_GIFT_MESSAGE_CHARS:
        raise CartError(
            f"The gift message is {len(message)} characters; the limit is "
            f"{MAX_GIFT_MESSAGE_CHARS}. Please shorten it.",
            max_chars=MAX_GIFT_MESSAGE_CHARS,
        )
    _revert_to_building(draft)
    item.gift_message = message or None
    await session.commit()
    item = await _get_plate_item(session, draft.id, cart_item_id)
    return ToolResult(
        data={"cart_item_id": item.id, "gift_message": item.gift_message},
        ui_blocks=[await build_plate_builder_block(session, item)],
    )


# --------------------------------------------------------------------------- #
# State / serialization
# --------------------------------------------------------------------------- #
async def _load_items(session: AsyncSession, draft_id: int) -> list[CartItem]:
    # populate_existing=True (see _get_plate_item above) resets loader state for
    # every relationship on an already-identity-mapped row to whatever this
    # query's options specify - so Product.category must be listed here too,
    # not just wherever a product is first fetched (e.g. add_single_product's
    # _get_product), or a product shared between that earlier eager load and
    # this refresh loses its category and lazy-loads it later (forbidden under
    # async - see _product_card_block).
    result = await session.execute(
        select(CartItem)
        .where(CartItem.cart_draft_id == draft_id)
        .options(
            selectinload(CartItem.product).selectinload(Product.category),
            selectinload(CartItem.variant),
            selectinload(CartItem.plate_size),
            selectinload(CartItem.finish),
            selectinload(CartItem.plate_contents)
            .selectinload(CartPlateContent.product)
            .selectinload(Product.category),
        )
        .order_by(CartItem.id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


def _product_card_block(product: Product) -> dict:
    return {
        "type": "product_card",
        "data": {
            "product_id": product.id,
            "name": product.name,
            "description": product.description,
            "price": float(product.price) if product.price is not None else None,
            "image_url": product.image_url,
            # ProductCard uses this to label a per-piece Individual Dates price
            # ("6 AED / piece") - without it, that price sits next to a weight-
            # tiered card ("500g — 65 AED") with no unit, reading as inconsistent.
            "category": product.category.name if product.category else None,
        },
    }


async def build_plate_builder_block(session: AsyncSession, item: CartItem) -> dict:
    """The section-4 plate_builder ui_block for a custom_plate cart item."""
    plate = item.plate_size
    used = _plate_slots_used(item)
    total, estimated = await _plate_price(item)
    base = float(item.unit_price)
    if _is_store_plate(item) and not estimated and float(item.line_total) != total:
        item.line_total = total
        await session.commit()

    # Per-date lines only when they add up to the store's total, so the card
    # never shows a breakdown that disagrees with the price the store charges.
    lines = {c.product_id: float(c.product.price or 0) * c.quantity if c.product else 0.0
             for c in item.plate_contents}
    show_lines = (
        not _is_store_plate(item)
        or (not estimated and sum(lines.values()) > 0 and abs(base + sum(lines.values()) - total) < 0.01)
    )
    return {
        "type": "plate_builder",
        "data": {
            "cart_item_id": item.id,
            "plate_size": plate.name,
            "capacity_used": used,
            "capacity_total": plate.capacity,
            "items": [
                {
                    "product_id": c.product_id,
                    "name": c.product.name if c.product else None,
                    "quantity": c.quantity,
                    "slots_used": c.slots_used,
                    "unit_price": (
                        float(c.unit_price) if not _is_store_plate(item)
                        else (float(c.product.price) if show_lines and c.product else 0.0)
                    ),
                    "line_total": (
                        round(float(c.unit_price) * c.quantity, 2) if not _is_store_plate(item)
                        else (round(lines[c.product_id], 2) if show_lines else 0.0)
                    ),
                }
                for c in item.plate_contents
            ],
            "base_price": base,
            "price": total,
            "price_estimated": estimated,
            **_box_extras(item),
        },
    }


def _box_extras(item: CartItem) -> dict:
    if not _is_store_plate(item):
        return {}
    return {
        **_plate_limits(item),
        "finish": item.finish.name_en if item.finish else None,
        "gift_message": item.gift_message,
    }


def _serialize_item(item: CartItem) -> dict:
    if item.item_type == "single_product":
        return {
            "type": "single_product",
            "cart_item_id": item.id,
            "product_id": item.product_id,
            "name": item.product.name if item.product else None,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "line_total": float(item.line_total),
            **(
                {
                    "variant_id": item.variant_id,
                    "variant_label": item.variant.label,
                    "store_variant_id": item.variant.store_variant_id,
                }
                if item.variant
                else {}
            ),
        }
    return {
        "type": "custom_plate",
        "cart_item_id": item.id,
        "plate_size": item.plate_size.name if item.plate_size else None,
        "capacity_used": _plate_slots_used(item),
        "capacity_total": item.plate_size.capacity if item.plate_size else None,
        "contents": [
            {
                "product_id": c.product_id,
                "name": c.product.name if c.product else None,
                "quantity": c.quantity,
                "slots_used": c.slots_used,
                "unit_price": float(c.unit_price),
                "line_total": round(float(c.unit_price) * c.quantity, 2),
            }
            for c in item.plate_contents
        ],
        # unit_price = plate base price; line_total = base + fillings.
        "base_price": float(item.unit_price),
        "unit_price": float(item.unit_price),
        "line_total": float(item.line_total),
        **_box_extras(item),
    }


async def get_cart_state_by_draft(session: AsyncSession, draft: CartDraft) -> dict:
    items = await _load_items(session, draft.id)
    serialized = [_serialize_item(i) for i in items]
    total = sum(i["line_total"] for i in serialized)
    return {
        "cart_draft_id": draft.id,
        "status": draft.status,
        "items": serialized,
        "total_price": round(total, 2),
    }


async def get_cart_state(session: AsyncSession, conversation_id: int) -> dict:
    draft = await get_or_create_draft(session, conversation_id)
    return await get_cart_state_by_draft(session, draft)


# --------------------------------------------------------------------------- #
# Review / order handoff (Phase 3)
# --------------------------------------------------------------------------- #
async def request_review(session: AsyncSession, draft: CartDraft) -> ToolResult:
    """Lock the draft for review (status -> 'reviewed') and surface the
    review_order_button ui_block. Idempotent: repeat calls don't duplicate state
    or error - they return the same result."""
    if draft.status not in ("building", "reviewed"):
        raise CartError("This cart can no longer be reviewed.")

    items = await _load_items(session, draft.id)
    if not items:
        raise CartError("The cart is empty - add something before reviewing.")

    for item in items:
        if item.item_type != "custom_plate" or not _is_store_plate(item):
            continue
        name = item.plate_size.name
        if not item.plate_contents:
            raise CartError(f"The {name} is empty - add dates to it before reviewing.")
        if item.finish_id is None:
            raise CartError(f"Choose a ribbon finish for the {name} before reviewing.")
        total = await store_quote.quote_box(
            item.plate_size.store_canvas_id,
            bespoke_items_payload(item),
            item.finish.store_finish_id,
        )
        if total is None:
            logger.warning("quote_fallback_local_price", extra={"cart_item_id": item.id})
            total = float(item.plate_size.base_price)
        item.line_total = total

    if draft.status != "reviewed":
        draft.status = "reviewed"
    await session.commit()

    return ToolResult(
        data={"reviewed": True, "cart_draft_id": draft.id, "status": "reviewed"},
        ui_blocks=[{"type": "review_order_button", "data": {"cart_draft_id": draft.id}}],
    )


async def build_order_summary(session: AsyncSession, draft: CartDraft) -> dict:
    """Full itemized order summary, all computed server-side."""
    return await get_cart_state_by_draft(session, draft)


async def build_handoff_payload(
    session: AsyncSession, conversation, draft: CartDraft
) -> dict:
    """The complete order data captured on the order row and handed to the
    checkout adapter (Phase 4)."""
    summary = await get_cart_state_by_draft(session, draft)
    return {
        "conversation_id": conversation.session_token,
        "cart_draft_id": draft.id,
        "items": summary["items"],
        "total_price": summary["total_price"],
        # What the widget replays into the store's own cart (prices are always
        # recomputed by the store's server).
        "store_lines": await build_store_lines(session, draft),
    }


async def build_store_lines(session: AsyncSession, draft: CartDraft) -> list[dict]:
    lines: list[dict] = []
    for item in await _load_items(session, draft.id):
        if item.item_type == "single_product":
            if item.variant:
                lines.append({
                    "kind": "single",
                    "variantId": item.variant.store_variant_id,
                    "quantity": item.quantity,
                    "name": item.product.name if item.product else None,
                })
        elif _is_store_plate(item) and item.finish:
            lines.append({
                "kind": "bespoke",
                "canvasId": item.plate_size.store_canvas_id,
                "finishId": item.finish.store_finish_id,
                "items": bespoke_items_payload(item),
                **({"giftMessage": item.gift_message} if item.gift_message else {}),
                "name": item.plate_size.name,
            })
    return lines
