# La Dolce Saveur — Ordering Chatbot Design

**Status:** Draft for review
**Stack:** FastAPI + PostgreSQL + React + Node (build tooling) + Docker Compose
**LLM:** OpenAI API (function/tool calling)

---

## 1. Problem & Scope

Build a customer-facing chatbot for ladolcesaveur.com that:
- Answers questions about the company/products
- Recommends plates/products based on conversation
- Lets a user build a custom plate/box (select items into a sized container, tracking capacity + price)
- Produces an order summary with a single persistent "Review Order" action
- On confirmation, hands the assembled order off to the website's checkout

**Explicitly out of scope for this cycle (YAGNI):**
- Real payment processing (checkout page owns this)
- User accounts / login / order history
- Admin dashboard for managing products (Phase 1 uses direct DB seeding / a minimal internal script, not a UI)
- The actual checkout page integration mechanism — deferred to Phase 4 once the store backend status is confirmed

**Out of our control:** whether the site's existing cart/checkout has a working backend. We isolate this behind one adapter so Phases 1–3 are not blocked.

---

## 2. Architecture Overview

```
React Chat Widget (embed)  ->  FastAPI Backend  ->  PostgreSQL
  - message list                - chat orchestration    - products
  - product cards               - tool execution        - sessions
  - plate builder               - cart state            - orders
  - order summary               - OpenAI client
                                      |
                                      v
                              Checkout Adapter (Phase 4, swappable)
                                - redirect w/ prefilled cart
                                - or write to real cart API
```

Containers: `api` (FastAPI), `db` (Postgres), `web` (React static build behind Nginx or served via Node), `nginx` (reverse proxy, optional but recommended so the widget can be embedded same-origin-friendly on the live site later).

---

## 3. Data Model (PostgreSQL)

```sql
-- Catalog
categories (id, name, description, sort_order)

products (
  id, category_id, name, description,
  price, image_url, is_single_item BOOLEAN, -- sellable standalone
  is_active BOOLEAN
)

plate_sizes (
  id, name,            -- e.g. "Small Box", "Grand Plateau"
  capacity INT,        -- number of slots
  base_price NUMERIC,
  image_url
)

-- Some items take more than 1 slot (e.g. a large tart vs a mignardise)
product_slot_cost (product_id, slot_cost INT DEFAULT 1)

-- Conversation & cart
conversations (id, session_token, created_at, last_active_at)

messages (id, conversation_id, role, content, tool_calls JSONB, created_at)

cart_drafts (
  id, conversation_id,
  status ENUM('building','reviewed','confirmed','abandoned'),
  created_at, updated_at
)

cart_items (
  id, cart_draft_id,
  item_type ENUM('single_product','custom_plate'),
  product_id NULLABLE,       -- for single_product
  plate_size_id NULLABLE,    -- for custom_plate
  quantity INT DEFAULT 1,
  unit_price NUMERIC,        -- snapshotted at add-time
  line_total NUMERIC
)

cart_plate_contents (
  id, cart_item_id,          -- FK to cart_items where item_type = custom_plate
  product_id, quantity, slots_used
)

orders (
  id, cart_draft_id, conversation_id,
  status ENUM('pending_handoff','sent_to_checkout'),
  total_price, created_at,
  handoff_payload JSONB       -- what was sent to checkout adapter
)
```

**Key design choice:** prices are snapshotted onto `cart_items` at add-time so later catalog price changes don't retroactively alter an in-progress order — and capacity math (`slots_used` vs `plate_sizes.capacity`) is enforced server-side, never trusted from the LLM.

---

## 4. Backend API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` | Send user message, get assistant response + any tool-driven UI updates. Stateless per call except `conversation_id`. |
| `GET /api/cart/{conversation_id}` | Fetch current cart state (source of truth for the frontend's live card) |
| `POST /api/cart/{conversation_id}/review` | Locks the draft, returns full order summary |
| `POST /api/order/{conversation_id}/confirm` | Finalizes order, invokes checkout adapter, returns redirect/handoff info |
| `GET /api/products`, `GET /api/plate-sizes` | Catalog browsing (also used by admin seed scripts) |

Chat responses return a discriminated payload so the frontend knows what to render:
```json
{
  "reply_text": "...",
  "ui_blocks": [
    {"type": "product_card", "data": {}},
    {"type": "plate_builder", "data": {"plate_size": "", "capacity_used": 6, "capacity_total": 12, "items": [], "price": 42.50}},
    {"type": "review_order_button", "data": {"cart_draft_id": ""}}
  ]
}
```

---

## 5. LLM Tool Schema (OpenAI function calling)

The model **never computes prices or capacity itself** — it calls tools, backend computes and returns authoritative numbers, model narrates.

- `search_products(query, category?)` — returns matching catalog items
- `recommend_items(preference_notes)` — returns ranked suggestions from catalog
- `start_plate(plate_size_id)` — creates/returns a custom_plate cart_item
- `add_item_to_plate(cart_item_id, product_id, quantity)` — backend validates capacity, returns updated state or a capacity-exceeded error for the model to relay
- `remove_item_from_plate(cart_item_id, product_id)`
- `add_single_product(product_id, quantity)`
- `get_cart_summary(conversation_id)` — full itemized state
- `request_review()` — triggers the `review_order_button` UI block (idempotent — repeated calls don't duplicate)

System prompt constrains the model to: stay in character for a luxury patisserie brand, only discuss company/products, always use tools for anything involving price/inventory/state rather than inventing numbers.

---

## 6. Frontend Components (React)

- `ChatWidget` — container, manages conversation_id/session token
- `MessageList` / `MessageBubble`
- `ProductCard` — single item, add button
- `PlateBuilderCard` — live capacity bar, item list, price, add/remove controls (dynamic, re-renders from `GET /api/cart/{id}` after each tool action)
- `OrderSummaryCard` — itemized final view
- `ConfirmCheckoutButton` — the one persistent, non-per-message action; disabled until `request_review()` has fired

Styling: match the site's existing luxury patisserie aesthetic.

---

## 7. Error Handling

- Capacity exceeded — tool returns structured error, model explains and suggests removing/upsizing, never silently overfills
- OpenAI API failure/timeout — friendly fallback message, cart state untouched (state lives in Postgres, not conversation memory)
- Checkout adapter unknown/unavailable (Phase 4 risk) — order is still saved as `pending_handoff` in DB so nothing is lost; frontend shows "your order is saved, redirecting..." with a manual fallback link if redirect fails

---

## 8. Testing Strategy

- Unit tests: capacity math, price snapshotting, cart state transitions (FastAPI + pytest)
- Tool-calling tests: mock OpenAI responses, verify backend never trusts model-provided prices/capacity
- Integration: full conversation -> cart -> order flow against a seeded test catalog
- Manual: conversational QA for tone/brand-fit (luxury patisserie voice)

---

## 9. Build Order (recap)

1. **Phase 1:** Data model + catalog import from PDF + Q&A-only bot
2. **Phase 2:** Recommendations + plate builder with live dynamic cards
3. **Phase 3:** Order summary + confirm flow — saved as `orders` (status `pending_handoff`)
4. **Phase 4:** Real checkout handoff adapter, once agency confirms backend state

---

## 10. Decisions (added after initial review)

- **Data pipeline runs to completion before any chatbot logic is built.** Order: scrape website -> extract PDF catalogue -> merge & dedupe -> single `data/unique_products.json` -> only then seed the DB and start Phase 1.
- **Frontend visual direction:** match the live site's existing look (colors, fonts, spacing) rather than a generic chat UI — pull real tokens from the live site once accessible. Must read as modern, professional, and dynamic (live-updating cards, not static text dumps), consistent with a luxury patisserie brand.
- **Streaming:** `/api/chat` will stream tokens (SSE or chunked response) to reduce perceived latency, rather than waiting for the full OpenAI response before replying. This affects the chat endpoint's implementation from Phase 1 onward — build it streaming-first rather than retrofitting later.
- **Deployment target:** company VPS. Docker Compose as already planned deploys cleanly there; add Nginx as the public-facing reverse proxy + TLS termination (Let's Encrypt).
- **Rate limiting:** `/api/chat` gets per-IP/per-session rate limiting (e.g. via `slowapi` or Nginx-level limiting) since each message costs real OpenAI API spend on an unauthenticated public endpoint.
- **Logging/monitoring:** structured logging (request id, conversation id, tool calls, errors) from day one; basic uptime/error alerting once deployed to the VPS.
- **Data retention/privacy:** conversations and order drafts are customer data — apply a sensible retention window (e.g. auto-purge conversations older than 90 days with no confirmed order) and disclose chatbot data use in the site's existing privacy policy. Session identification (cookie/localStorage token) should be disclosed too if the site has cookie consent.

---

## 11. Open Items to Resolve Before/During Build

- Confirm with agency/dev: does a real cart/order API exist to write into, or do we redirect with URL params only?
- Get access to the live site's design tokens (colors/fonts) for the widget
- Extract actual product/plate data from the PDF catalogue (manual entry or OCR pass)
