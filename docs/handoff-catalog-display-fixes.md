# Handoff: catalog, price and card display fixes (for a new session)

Written 2026-11-04 from live testing at https://ladolce-chatbot.theosirislabs.com against
the real shop (ladolcesaveur.com). Merged and live before this: size cards, store-quoted box
totals, server-side start/ribbon/review, cart + boxable-date ids injected every turn (#1-#5).

## What the real shop does (evidence from screenshots)

- **Shop page (`/shop`)**: products are sold by **weight/size variants with fixed prices**.
  Example: "Khudri Dates with Almond", weights 500g / 1kg, sizes S / M / L, price changes per
  variant (500g M = 120). "The Classic Petite" (350g) is a **ready-made (pre-curated) box at
  AED 200**. Collections: Pre-curated, Gourmet Packs, Gift Collection; filters by date variety.
- **Checkout**: lines like "THE ROYAL ASSORTMENT 1kg x1 = 450", "KHUDRI DATES WITH ALMOND
  500g / M x1 = 120". Then **Subtotal + VAT (5%) + Shipping (FREE here) = Total** (990 + 49.5
  = 1040). Banner: promo code DOLCE for 15% off, free shipping over a threshold.
- **Custom arrangement (`/curation`)**: a tray is priced **by size only**. Large Rectangular
  Tray with 90 of 180 pieces still shows **AED 400**. Dates have no individual price there,
  only a count and a running weight. This confirms the store quote (size only) is right.
- **Name collision**: "The Classic Petite" is AED 200 as a ready-made box in the shop but the
  custom-box canvas of the same name has a base price of 60. Same for Royal Assortment
  (450 ready-made vs 150 canvas) and Signature Selection (350 vs 100).

## What the bot gets wrong today

1. **Best sellers list per-piece dates** ("Golden Sukkari Date 6 AED per piece", "Jordanian
   Majdool Date 8 AED per piece", "Khudri Date with Pistachio 7 AED per piece"). These are
   **box fillings, not shop products**. The shop sells dates by 500g/1kg packs. Cause:
   `products.is_bestseller` is true for legacy "Individual Dates" rows
   (`api/app/services/catalog.py: list_bestsellers`, flags seeded by `scripts/seed_catalog.py`).
2. **Product cards show one price, not the size options.** `_product_card_from_row`
   (`api/app/services/tools.py`) drops `variants`, and `ProductCard.tsx` only knows the old
   "(500g)" name-suffix trick. The sync stores real variants (`ProductVariant`: label like
   "500g / M", price) but the card cannot show 500g / 1kg and S / M / L with prices.
   `Product.price` is only the default variant's price.
3. **Per-piece prices appear outside a custom box.** Search/recommend return the legacy
   individual-date rows with prices 5-8, and `add_single_product` accepts them (only price 0
   is blocked), so a guest could "buy" one date piece, which the shop does not sell.
4. **Ready-made vs custom box is ambiguous.** The bot says "The Royal Assortment Box 450 AED"
   in one place and lists custom sizes "Royal Assortment 150" in another, without saying which
   is which. Guests cannot tell a finished 450 AED box from a 150 AED custom canvas.
5. **Bot totals do not show VAT/shipping/promo.** The card and cart show the subtotal only. The
   shop adds 5% VAT, shipping rules and the DOLCE code at checkout. Guests see a different
   final number.
6. **Chips can lead nowhere** ("Add the first one to my order" after a per-piece best-seller
   list, earlier "Show me stuffed dates" while building a box, now fixed).
7. **Catalog mismatch risk.** Live shop collections are Pre-curated / Gourmet Packs / Gift
   Collection / Stuffed Patisserie. The bot DB categories came from the old scrape
   ("Individual Dates", "Stuffed & Flavored Dates", "Gift Boxes & Trays"...). The diff report
   `docs/store-catalog-diff.md` already lists "only in ours" and price differences (Khudri Dates
   with Almond: ours 230 vs live 110-245 by variant).

## Work to do (in this order)

A. **Separate "shop products" from "box fillings" everywhere.**
   - Fillings = `Product` rows with `store_date_id` and `weight_grams` (Individual Dates).
   - Exclude fillings from `search_products`, `recommend_items`, `list_bestsellers` and from
     product cards, unless the guest is building a box or asks for box dates.
   - Reject fillings in `add_single_product` (not just price 0).
   - Clean the bestseller flag: bestsellers must be shop products with variants.
   - Files: `catalog.py`, `tools.py`, `cart.py`, `scripts/sync_store_catalog.py`.

B. **Variant-aware cards.**
   - `product_card` block gets `variants: [{variant_id, label, price}]` and `price_from`.
   - `ProductCard.tsx`: show weight and size options (500g/1kg, S/M/L) with each price, let the
     guest tap one; "Add" sends the chosen `variant_id` (`add_single_product` already takes it).
   - Never show "/ piece" on shop cards. Remove the per-piece label and the `PER_PIECE_CATEGORY`
     special case (`ProductCard.tsx`), or limit it to filling cards inside a box.
   - Filling cards (inside a box): show name and weight in grams, no price.

C. **Label ready-made vs custom.**
   - Tool results and prompt: "Ready-made box" (store product, price from variant) versus
     "Custom box" (canvas, price = size). Never present a canvas price as the box price.
   - The size cards title: "Build your own: price depends on the box size, not the dates".
   - Match the shop's collection names in the bot's wording and categories.

D. **Totals the way checkout shows them.**
   - Cart / review sheet: Subtotal, VAT 5%, Shipping, Total. Confirm the exact rules from the
     store (VAT included or added, free-shipping threshold, promo DOLCE 15%). Do not hard-code
     without checking the store API or KB (`data/kb_sources/shipping.md`, `promotions_discounts.md`).
   - If unknown, label the number "Subtotal (before VAT, delivery and promo)".

E. **Chips and intent rules for the new states** (`api/app/services/suggestions.py`): after best
   sellers offer "Show me gift boxes", "Build me a custom box", "What sizes do you have?"; after a
   variant card offer the other weight; never offer an action that cannot work.

F. **Extend `api/scripts/model_check.py`** with these checks, then run it on gpt-4o and the
   cheaper candidate (gpt-4.1-mini):
   - best sellers reply and cards contain no "per piece" and no filling products;
   - a product with variants shows its weight/size options with prices;
   - "royal assortment" is answered as ready-made 450 AND custom 150 canvas, clearly labeled;
   - add a variant product with `variant_id` and see the right line price in the cart;
   - cart total shows the VAT/shipping wording agreed in D.

G. **Verify against the live store** (read-only, via the VPS agent): run
   `scripts/sync_store_catalog.py` diff again, list products with `is_bestseller` and their
   categories, and compare shop prices to the bot's for 10 products across S/M/L and 500g/1kg.

## Already confirmed good (do not redo)

- Box total = store quote (`/api/bespoke/quote`); size-only pricing matches `/curation`.
- Pieces/grams left shown on the box card; one box card per reply; wrong-date and "restart"
  problems addressed by #5 (re-test after deploy).
- Live setup: gpt-4o, `model_check.py` 9/9 twice before #5.

## Acceptance (what "done" looks like in the chat)

1. "What are your best sellers?" -> 4-6 shop products with weight/size options and prices, no
   per-piece lines, no filling dates.
2. "Khudri dates with almond" -> one card with 500g/1kg and S/M/L prices; tapping adds that exact
   variant at that price.
3. "What sizes do the boxes come in?" -> custom sizes, clearly "build your own, price by size".
4. "Royal assortment" -> both the ready-made box and the custom size explained in two lines.
5. Cart/review totals read like the shop's order summary.
