# Step G: live verification (prompt for the VPS agent)

Give the block below to the agent that has the VPS. It is read-only: it deploys nothing
and changes no data. Paste its full answer back into the chat.

Prerequisite: steps A to F are merged into `main` and deployed (`git pull` + `docker compose
up -d --build` on the VPS). The api container re-syncs the catalog from the store on every
start, which also clears the old `is_bestseller` flags on box fillings.

---

You are verifying the La Dolce Saveur chatbot on the VPS against the real shop. READ-ONLY:
do not edit files, do not deploy, do not run `sync_store_catalog.py --apply`, do not run any
INSERT/UPDATE/DELETE, and never print `.env`, API keys or the database password.

Work in the repo directory that contains `docker-compose.yml`.

1. Version. Print `git rev-parse --short HEAD`, `git log --oneline -8`, and
   `docker compose ps`. Confirm the api container is healthy and was started after the
   last `git pull` (`docker compose ps --format json` or `docker inspect` StartedAt).

2. Catalog diff against the store (read-only):
   `docker compose exec -T api python scripts/sync_store_catalog.py --dry-run`
   Paste the full markdown report.

3. Bestsellers, fillings, categories and a 10-product price comparison:
   `docker compose exec -T api python scripts/verify_live.py --sample 10`
   Paste the full output including the "## Result" section.

4. Shop price rules (public GETs only, no login). With `curl -s` fetch
   `https://ladolcesaveur.com/shop` and `https://ladolcesaveur.com/checkout` and report any
   text you can find about: VAT percentage and whether prices include it, shipping fee,
   the free-shipping threshold, and the DOLCE promo (percentage, any minimum). If these
   pages are rendered client-side and the HTML has no such text, say so and try the store
   API base from `.env` as `STORE_API_BASE` (only the variable's value, not other lines),
   e.g. `/api/products?limit=5`, and look for shipping/settings/promo endpoints in the
   site's JavaScript bundle names. Report exactly what you found and where; do not guess.

5. Rounding. If you find a checkout/order-summary example (subtotal, VAT, total), report
   how the total is rounded (for example 990 + 49.5 shown as 1040 or 1039.50).

6. Live chat script (uses the real model; costs a few cents; run it ONCE, it sends 11
   messages and the chat rate limit is 20 per minute):
   `docker compose exec -T api python scripts/model_check.py --base-url http://localhost:8000 --label "$(grep -E '^LLM_MODEL=' .env | cut -d= -f2)"`
   Paste the full PASS/FAIL list. If a check FAILS, also paste the reply text of that turn
   (rerun that one message with `curl -N -s -X POST http://localhost:8000/api/chat -H 'content-type: application/json' -d '{"message":"What are your best sellers?"}'`).

7. Final answer format:
   - Commit deployed.
   - Section 2 report (verbatim).
   - Section 3 output (verbatim).
   - What you found for step 4 and 5 (with the source URL for each fact), or "not found".
   - Section 6 results (verbatim).
   - A short list of anything that looks wrong or surprising. Do not fix anything.
