# La Dolce Saveur - Ordering Chatbot

A chat concierge for [ladolcesaveur.com](https://ladolcesaveur.com): answers product
questions, builds custom date boxes within the store's rules (pieces and grams, ribbon
finish, gift message), sells single products in their sizes, and fills the customer's
own store cart. The guest then finishes on the store's checkout page - the chatbot never
touches payment. Prices always come from the store.

Design notes: [`docs/specs/`](docs/specs/). Test results and store-developer notes:
[`docs/store-integration-results.md`](docs/store-integration-results.md).

## Stack

| Service | Tech | Role |
|---|---|---|
| `caddy` | Caddy 2 | Public entry point; automatic HTTPS; `/api/*` -> api, everything else -> web |
| `web`   | React + Vite + TS, nginx | Chat UI and the embeddable `widget.js` |
| `api`   | FastAPI (Python 3.12) | Chat orchestration (SSE), cart, orders, catalog, store quote |
| `db`    | PostgreSQL 16 + pgvector | Catalog, conversations, carts, orders, knowledge base |

Chat model: any OpenAI-compatible provider via `LLM_API_BASE` / `LLM_API_KEY` /
`LLM_MODEL` (tested: OpenRouter `z-ai/glm-4.7`, OpenAI `gpt-4o`). Embeddings: OpenAI.

## Run it (one command)

```bash
cp .env.example .env        # fill in the values (see docs/deploy.md)
docker compose up -d --build
```

On start the api container migrates the database, seeds the catalog the first time,
syncs it from the store and ingests the knowledge base. Locally, set `DOMAIN=localhost`
(self-signed certificate; add `HTTP_PORT=8080 HTTPS_PORT=8443` if 80/443 are busy).

Embed on the store with one tag - see [`docs/deploy.md`](docs/deploy.md).

## Development

```bash
cd api && python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest          # backend tests (SQLite, no network)
cd web && npm install && npm test   # frontend tests
```

Layout: `api/` backend, `web/` frontend, `db/` Alembic migrations, `data/` catalog and
knowledge-base sources, `scripts/` the original catalog-scraping pipeline, `caddy/` proxy config.
