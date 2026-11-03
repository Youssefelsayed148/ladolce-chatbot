# Deploying to the VPS

## 1. Configure
1. `cp .env.example .env` and set real values: a **strong** `POSTGRES_PASSWORD`
   (and the same password inside `DATABASE_URL`), the OpenAI key (embeddings),
   the chat provider values (`LLM_*`), `ENVIRONMENT=production`, and
   `CORS_ORIGINS` = the exact site origin(s) that embed the widget
   (e.g. `https://www.ladolcesaveur.com`).
2. Remove the `ports: 127.0.0.1:5432` mapping from `db` in `docker-compose.yml`.

## 2. First start
```
docker compose up -d --build
docker compose run --rm -w /db api alembic upgrade head
docker compose run --rm api python scripts/seed_catalog.py
docker compose run --rm api python scripts/ingest_kb.py
```

## 3. HTTPS (Let's Encrypt)
1. Point the domain's DNS A record at the VPS.
2. In `nginx/nginx.prod.conf` replace `YOUR_DOMAIN`.
3. Get a certificate once (stand-alone, before enabling the TLS config):
   `certbot certonly --standalone -d YOUR_DOMAIN`
4. In `docker-compose.yml` (nginx service): mount `nginx.prod.conf` instead of
   `nginx.conf`, mount `/etc/letsencrypt:/etc/letsencrypt:ro`, and publish `443:443`.
5. `docker compose up -d nginx`. Renew with `certbot renew` (cron), then
   `docker compose exec nginx nginx -s reload`.

## 4. Backups (daily, keep 14 days)
```
# crontab -e
0 3 * * * cd /path/to/project && docker compose exec -T db pg_dump -U ladolce ladolce | gzip > /backups/ladolce-$(date +\%F).sql.gz && find /backups -name 'ladolce-*.sql.gz' -mtime +14 -delete
```
Restore: `gunzip -c file.sql.gz | docker compose exec -T db psql -U ladolce ladolce`.

## 5. Switching the chat model
Edit `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` in `.env`, then
`docker compose up -d api`. No code change. Embeddings are unaffected.

## 6. Smoke test after deploy
`curl https://YOUR_DOMAIN/api/health`, then one real chat + review + confirm.

## Embedding the widget on ladolcesaveur.com

The client adds ONE tag (before `</body>`):

```html
<script src="https://CHAT_DOMAIN/widget.js" data-api="https://CHAT_DOMAIN" async></script>
```

- `widget.js` (built by `npm run build` in `web/`) mounts the launcher inside a shadow root, so store CSS cannot affect it and vice versa. Arabic (`localStorage.lang` starting with `ar`) renders right-to-left.
- Set `CORS_ORIGINS=https://ladolcesaveur.com,https://www.ladolcesaveur.com` in `.env` (the browser calls our API cross-origin).
- On confirm the widget calls the store API (`STORE_API_BASE`) from the customer's browser with their own cart token, then links to `STORE_CHECKOUT_URL`. The store API must allow the store's origin (it currently reflects any origin with credentials - restrict it to ladolcesaveur.com).
- `widget.js` is served with `max-age=300, must-revalidate`; hashed `/assets/*` are cached for a year.
- Local check: `cd web && npm run build && cp embed-test/store.html dist/ && python -m http.server 4173 -d dist`, then open `/store.html`.
