# Deploying to the VPS

Requirements: Docker + Docker Compose, a domain whose DNS A record points at the VPS,
ports 80 and 443 open.

## 1. Configure
```
cp .env.example .env
```
Set in `.env`:
- `DOMAIN` - the chatbot's domain (e.g. `chat.ladolcesaveur.com`). Caddy fetches and
  renews the HTTPS certificate by itself.
- `POSTGRES_PASSWORD` (strong) and the **same** password inside `DATABASE_URL`.
- `OPENAI_API_KEY` - embeddings (knowledge base search), always OpenAI.
- `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` - the chat model. Tested: OpenRouter
  (`https://openrouter.ai/api/v1`, `z-ai/glm-4.7`) and OpenAI (`https://api.openai.com/v1`,
  `gpt-4o`). Not OpenCode Go: it rejects server-side calls (`400 MissingSessionID`).
- `CORS_ORIGINS=https://ladolcesaveur.com,https://www.ladolcesaveur.com`

## 2. Start (the whole deployment)
```
docker compose up -d --build
```
The api container migrates the database, seeds the catalog on the first start only,
syncs it from the store on every start, and ingests the knowledge base. The first start
takes about a minute. Check: `docker compose ps` (all healthy) and
`curl https://YOUR_DOMAIN/api/health`.

## 3. Embed on ladolcesaveur.com
The store adds ONE tag before `</body>`:
```html
<script src="https://YOUR_DOMAIN/widget.js" data-api="https://YOUR_DOMAIN" async></script>
```
- The widget lives in a shadow root (store CSS cannot affect it); Arabic (`localStorage.la_dolce_lang`
  starting with `ar`) renders right to left.
- On confirm, our API saves the order first; the widget then adds the lines to the customer's
  own store cart (`POST /api/cart/items`, `POST /api/cart/bespoke`, `x-cart-token` from
  `localStorage.cartToken`) and links to `STORE_CHECKOUT_URL`. No payment goes through us.
- `widget.js` is served with `max-age=300, must-revalidate`; hashed `/assets/*` for a year.

For the store developer (we cannot change these): restrict the store API's CORS to
`https://ladolcesaveur.com` (it currently reflects any origin with credentials), and hide the
cart's low-stock badge when `availableStock` is null (it shows "Only null left in stock" on boxes).

## 4. Operations
- Logs: `docker compose logs -f api`. Update: `git pull && docker compose up -d --build`.
- Switch the chat model: edit the three `LLM_*` values, then `docker compose up -d api`.
- Refresh the catalog from the store: `docker compose restart api`.
- Backup (daily, keep 14 days):
  ```
  0 3 * * * cd /path/to/project && docker compose exec -T db sh -c 'pg_dump -U $POSTGRES_USER $POSTGRES_DB' | gzip > /backups/ladolce-$(date +\%F).sql.gz && find /backups -name 'ladolce-*.sql.gz' -mtime +14 -delete
  ```
  Restore: `gunzip -c file.sql.gz | docker compose exec -T db sh -c 'psql -U $POSTGRES_USER $POSTGRES_DB'`.

## 5. Smoke test
Open the store page, send a chat message, build a box, Review, Confirm, and check the box
appears in the store cart; stop at the checkout page.

## Comparing chat models

`api/scripts/model_check.py` runs a scripted order flow (sizes, start a box, add dates,
overfill, ribbon, review) against a running API and reports PASS/FAIL per step, including
whether the model really called the cart tools. Change `LLM_MODEL` in `.env`, redeploy,
then run it from any machine with Python and `httpx`:

    python api/scripts/model_check.py --base-url https://YOUR_DOMAIN --label gpt-4.1-mini
