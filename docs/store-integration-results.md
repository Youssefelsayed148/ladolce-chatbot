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

## GLM run
Blocked: OpenCode Go answers server-side calls with `400 MissingSessionID`
(needs the `x-opencode-session` header of its own client). Fallback is OpenRouter;
needs an OpenRouter key. Not yet measured: tool-calling quality, tokens per message
(`llm_usage` log lines now record prompt/completion tokens per round).

## For the store developer
- Restrict the store API's CORS to `https://ladolcesaveur.com` (+ `www`). It currently
  reflects any origin with credentials, so any site could use a visitor's cart token.
- Bespoke-only dates come through the catalog with price 0; they are not sold alone.
