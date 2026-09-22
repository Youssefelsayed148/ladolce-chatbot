# La Dolce Saveur — Ordering Chatbot

Customer-facing chatbot for [ladolcesaveur.com](https://ladolcesaveur.com): answers
product questions, recommends items, lets a customer build a custom date box/tray
within capacity limits, and hands a finished order off to checkout.

Design spec: [`docs/specs/2026-07-23-ordering-chatbot-design.md`](docs/specs/2026-07-23-ordering-chatbot-design.md).

> **Status:** scaffold. All API endpoints are stubs returning HTTP 200 — no LLM,
> cart, or persistence logic yet. This stage exists to stand the container stack up.

## Stack

| Service | Tech | Role |
|---|---|---|
| `nginx` | Nginx | Public reverse proxy (`/api/*` → api, `/*` → web), TLS termination on the VPS |
| `web`   | React + Vite + TypeScript | Chat widget SPA (served static behind its own internal nginx) |
| `api`   | FastAPI (Python 3.12), pip | Chat orchestration, cart, orders, catalog. `/api/chat` is streaming-first (SSE) |
| `db`    | PostgreSQL 16 | Catalog, conversations, carts, orders |

Migrations live in [`db/`](db/) (Alembic). The data pipeline that builds the seed
catalog lives in [`scripts/`](scripts/) with output in [`data/`](data/).

## Prerequisites

- Docker + Docker Compose
- (For running the data pipeline scripts locally: Python 3.11+, Node.js)

## Run it

```bash
# 1. Configure environment
cp .env.example .env
# edit .env — at minimum set a real OPENAI_API_KEY (not needed for the scaffold
# stubs, but required once chat logic lands) and change the Postgres password.

# 2. Build and start the whole stack
docker compose up --build
```

Then:

- App (via reverse proxy): <http://localhost>
- API health through the proxy: <http://localhost/api/health>
- API docs (Swagger): the api container exposes `:8000` internally; through the
  proxy, API routes are under `/api/*`.

Stop with `Ctrl+C`, or `docker compose down` (add `-v` to also drop the DB volume).

### Verify the stubs

```bash
curl http://localhost/api/health
# {"status":"ok","environment":"development"}

curl http://localhost/api/products      # []
curl http://localhost/api/plate-sizes   # []

# Streaming chat stub (Server-Sent Events):
curl -N -X POST http://localhost/api/chat \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"demo","message":"hi"}'
```

## Database migrations (Alembic)

The api container has Alembic installed and mounts `./db` at `/db`:

```bash
# Create a new migration once ORM models exist:
docker compose run --rm -w /db api alembic revision --autogenerate -m "message"

# Apply migrations:
docker compose run --rm -w /db api alembic upgrade head
```

(There are no models or migrations yet — this is wired for Phase 1.)

## Project layout

```
api/          FastAPI backend (app/ with core/ + routers/)
web/          React + Vite frontend
db/           Alembic migration project
nginx/        Public reverse-proxy config (TLS placeholder for Let's Encrypt)
scripts/      One-off data pipeline (site scraper, PDF extract, merge/dedupe)
data/         Pipeline output (scraped_*.json, unique_products.json, ...)
docs/specs/   Design docs
docker-compose.yml
.env.example
```

## Notes

- **No secrets in the repo.** All config comes from `.env` (gitignored); only
  `.env.example` with placeholders is committed.
- **TLS** is not configured locally. On the VPS, issue certs with Let's Encrypt and
  enable the commented 443 server block in [`nginx/nginx.conf`](nginx/nginx.conf).
- **`/api/chat` is built streaming-first** (SSE) so real OpenAI token streaming
  drops in without an endpoint rewrite.
