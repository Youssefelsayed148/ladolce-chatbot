# Store integration - test results and notes (2026-11-04)

## OpenAI chat run (gpt-4o, 3 messages, fresh conversation)
Box (350g / 18 pcs: 12 Ajwa + 6 Golden Sukkari, Royal Gold, gift message) -> 60 AED
(store canvas price; dates add 0). Single "Khudri Dates with Almond" 500g / S variant -> 110.
Cart total 170, then review succeeded. Grams/pieces limits are enforced server-side
(tests/test_store_box.py), not by the model.

Bugs found in the first attempt and fixed (tests first):
- The model guessed category "Stuffed Dates" (real: "Stuffed & Flavored Dates"); the
  search returned nothing and the model then improvised. Search now retries without the
  category when the guessed one matches nothing.
- The model called `start_plate` repeatedly, stacking empty boxes. `start_plate` now
  returns an existing empty box of the same size.
- Price-0 products (bespoke-only dates) can no longer be added as single products.

## GLM run (OpenRouter, z-ai/glm-4.7)
OpenCode Go rejected server-side calls (`400 MissingSessionID`), so the base is
`https://openrouter.ai/api/v1`, model `z-ai/glm-4.7` (same GLM generation).
Same 3-message conversation as the OpenAI run: identical outcome (box 60, variant 110,
total 170, review OK). Tool calling was correct, including parallel calls.
Tokens, 3 messages: 9 LLM rounds, 26.6k prompt + 0.8k completion = ~9.1k/message
(~$0.006/message at $0.6/$2.2 per M). Prompt is ~3k tokens per round (no caching).
Prompt changes, only where GLM got it wrong: no narration between tool calls (replies
came out glued together), never say we take payment, never quote per-piece prices for
a box's fillings. Without `max_tokens`, OpenRouter reserved 131k output tokens and
refused on a small balance; replies are now capped (MAX_REPLY_TOKENS = 1500).

## Live-store test (widget script tag, no order placed)
Widget injected on ladolcesaveur.com; Chrome showed a Local Network Access prompt
(allowed). Review + Confirm saved our order #1 (`sent_to_checkout`).
- `cartToken`: a UUID (36 chars); the store cart has its own separate id.
- `POST /api/cart/bespoke` needs no login (guest token only).
- Cart drawer renders a box with no layout token/preview: canvas thumbnail, finish,
  contents, gift message, totals (60 + VAT 3 + shipping 20 = 83). Checkout page shows it too.
- Misrender: a badge "Only null left in stock" on the bespoke line (`availableStock` is
  null; `available` is true). Fix for the store developer: hide the low-stock badge when
  `availableStock` is null / for `kind: BESPOKE`.
- Stock: bespoke lines are not stock-limited (null); single-product stock comes from the
  variant `stock` we sync (our search lists only in-stock variants; adding more than the
  stock is refused). Not exercised live to avoid unlabelled cart writes.
- The TEST box was left in that browser's guest cart; remove it with the cart's REMOVE.

## For the store developer
- Restrict the store API's CORS to `https://ladolcesaveur.com` (+ `www`). It currently
  reflects any origin with credentials, so any site could use a visitor's cart token.
- Bespoke-only dates come through the catalog with price 0; they are not sold alone.
