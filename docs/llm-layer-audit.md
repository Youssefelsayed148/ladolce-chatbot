# LLM Layer Audit — La Dolce Saveur Ordering Chatbot

**Scope:** This document maps the current OpenAI integration in the FastAPI backend so a second, switchable provider (OpenCode Go) can be added without breaking the existing OpenAI path.

**Status:** Phase 2 complete — OpenCode Go is now the active chat/tool-calling provider. OpenAI remains present as a commented-out revert path and is still used for embeddings/RAG (OpenCode Go has no embeddings endpoint).

---

## 1. Configuration & Client Instantiation

### 1.1 Environment variables / config source

Configuration lives in `api/app/core/config.py` via `pydantic_settings.BaseSettings` reading the repo-root `.env`.

| Env var | Default | Usage |
|---|---|---|
| `OPENAI_API_KEY` | `""` | API key for the OpenAI client |
| `OPENAI_MODEL` | `"gpt-4o"` | Chat completion model passed to `client.chat.completions.create()` |
| `OPENAI_EMBEDDING_MODEL` | `"text-embedding-3-small"` | Embedding model passed to `client.embeddings.create()` |
| `CHAT_RATE_LIMIT` | `"20/minute"` | slowapi rate limit for `POST /api/chat` |

`docker-compose.yml` explicitly forwards these to the `api` container and documents the choice to use `env_file: .env` so ambient shell variables cannot shadow the project key.

### 1.2 Where the OpenAI client is created

**Async runtime client (chat + RAG):**

- File: `api/app/deps.py`
- Function: `get_openai_client()`
- Returns: `openai.AsyncOpenAI(api_key=settings.openai_api_key or "sk-not-configured")`
- Injected as a FastAPI dependency in `api/app/routers/chat.py` so tests can override it via `app.dependency_overrides`.

**Sync ingestion client (offline script):**

- File: `api/scripts/ingest_kb.py`
- Constructor: `OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))`
- Used only to embed KB chunks and upsert them into `kb_chunks`.

---

## 2. Every LLM Call Site

### 2.1 Chat streaming + tool-calling loop

**File:** `api/app/services/chat.py`

1. `generate_chat_events(...)` — main streaming chat orchestrator.
   - Calls `client.chat.completions.create(model=model, messages=messages, tools=ALL_TOOLS, stream=True)` up to `MAX_TOOL_ROUNDS = 6` times.
   - Consumes the async stream via `_consume_stream()`.
   - On each tool round, appends the assistant tool-call message + each tool result message to `messages`, then loops again.
   - If the loop exhausts without a plain-text finish, it makes one final `create(model=model, messages=messages, stream=True)` call **without** `tools`.
   - After the final `done` event, it calls `generate_suggestions()`.

2. `generate_suggestions(client, model, user_text, reply_text)` — second small completion.
   - Calls `client.chat.completions.create(model=model, messages=[...], stream=True)` with no tools.
   - Accumulates the full content, then parses it as JSON (with a regex fallback to strip markdown fences).
   - Never raises; any failure degrades to an empty suggestion list.

3. `_consume_stream(stream)` — OpenAI-specific stream parser.
   - Iterates `async for chunk in stream`.
   - Assumes `chunk.choices[0].delta` exposes:
     - `delta.content` (string token)
     - `delta.tool_calls` (list of tool-call deltas)
   - Each tool-call delta has `index`, `id`, `function.name`, `function.arguments`.
   - Accumulates arguments across streamed chunks.
   - Yields `("token", text)` and finally `("final", {"content": ..., "tool_calls": ...})`.

### 2.2 Tool execution / RAG embedding

**File:** `api/app/services/tools.py` → `dispatch_tool()`

- `search_knowledge_base` tool calls `kb_service.search_kb(session, client, query, embedding_model=settings.openai_embedding_model)`.
- `client` is passed straight through to the KB service.

**File:** `api/app/services/knowledge_base.py`

- `embed_texts(client, model, texts)` calls `client.embeddings.create(model=model, input=texts)` and reads `response.data[i].embedding`.
- `search_kb(...)` uses the returned embedding to query `kb_chunks` via pgvector cosine distance.

### 2.3 KB ingestion (offline script)

**File:** `api/scripts/ingest_kb.py`

- `_embed_batch(client, texts)` calls `client.embeddings.create(model=EMBEDDING_MODEL, input=batch)`.
- `EMBEDDING_MODEL` defaults to `OPENAI_EMBEDDING_MODEL` env var or `"text-embedding-3-small"`.
- Reads `item.embedding` from the response.

---

## 3. All Tool / Function Definitions Passed to the Model

All tools are defined in `api/app/services/tools.py` and assembled as `ALL_TOOLS`.

| Tool | Purpose | Parameters |
|---|---|---|
| `search_products` | Catalog free-text search | `query` (required), `category` (optional exact category name) |
| `recommend_items` | Preference-based recommendations | `preference_notes` (required) |
| `start_plate` | Create a custom box/tray | `plate_size_id` (required int) |
| `add_item_to_plate` | Add a product into a custom plate | `cart_item_id`, `product_id`, `quantity` (default 1) |
| `remove_item_from_plate` | Remove a product from a plate | `cart_item_id`, `product_id` |
| `add_single_product` | Add a standalone pack/gift box to cart | `product_id`, `quantity` (default 1) |
| `get_cart_summary` | Return current cart state | none |
| `request_review` | Lock cart for review / show review button | none |
| `search_knowledge_base` | RAG retrieval for general/policy questions | `query` (required) |

They are passed to the model as:

```python
stream = await client.chat.completions.create(
    model=model,
    messages=messages,
    tools=ALL_TOOLS,
    stream=True,
)
```

No `tool_choice` is set, so the default `tool_choice="auto"` applies.

---

## 4. OpenAI-Specific Behavior the Code Depends On

### 4.1 Streaming delta format

`_consume_stream` is tightly coupled to the OpenAI SDK `ChatCompletionChunk` object shape:

```python
delta = chunk.choices[0].delta
# content tokens
delta.content
# tool-call fragments
delta.tool_calls[index].id
delta.tool_calls[index].function.name
delta.tool_calls[index].function.arguments
```

A different provider that returns a different streaming payload (or raw JSON/SSE events) will break the orchestrator.

### 4.2 Tool-call message format

`_assistant_tool_call_message` builds the assistant message to append back into the conversation exactly as OpenAI expects:

```python
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": slot["id"],
            "type": "function",
            "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
        }
    ],
}
```

Tool result messages are also OpenAI-shaped:

```python
{
    "role": "tool",
    "tool_call_id": slot["id"],
    "content": _json_result(result.data),
}
```

### 4.3 Default `tool_choice` and parallel tool calls

The code does not pass `tool_choice`, `parallel_tool_calls`, or `n`. It relies on the provider default (`auto`, single tool per round). It also does not explicitly request or disable parallel tool calls.

### 4.4 Suggestions parsing

`generate_suggestions` assumes the model can be asked to output **only** a JSON array of strings. It includes a regex `_JSON_ARRAY_RE` to strip markdown fences because `gpt-4o` sometimes wraps the array in ` ```json ... ``` `. This is tuned to OpenAI behavior.

### 4.5 Embedding dimensionality

`api/app/models.py` hardcodes:

```python
KB_EMBEDDING_DIM = 1536  # text-embedding-3-small
EmbeddingType = Vector(KB_EMBEDDING_DIM).with_variant(JSON(), "sqlite")
```

This dimension is a schema-level assumption. Any provider whose embedding model does not emit 1536-dimensional vectors will break Postgres `kb_chunks.embedding` storage and pgvector distance queries.

### 4.6 Context / token limits

The code does not truncate or count conversation history. It loads the entire message history into `messages` (`_load_history()` in `api/app/routers/chat.py`). It relies on the model/API to handle context-window overflow.

### 4.7 Retry / error handling

- **No retry logic** for API errors, rate limits, or timeouts.
- `api/app/routers/chat.py` wraps the entire event generator in a broad `try/except Exception` and yields a friendly `FALLBACK_MESSAGE`.
- `generate_suggestions` swallows all exceptions and returns an empty list.

### 4.8 Rate limiting

- Per-session / per-IP rate limiting is handled by `slowapi` in `api/app/core/limiter.py` and applied to `POST /api/chat` in `api/app/routers/chat.py`.
- This is endpoint-level, not API-key-level.

---

## 5. What Is NOT Portable As-Is to Another OpenAI-Compatible Provider

| Area | Issue | Why it matters for OpenCode Go |
|---|---|---|
| Stream parser | `_consume_stream` assumes OpenAI SDK `delta` objects | Another provider may stream raw SSE or a different object shape |
| Tool-call shapes | Assistant/tool messages follow OpenAI `tool_calls`/`tool_call_id` schema | OpenCode Go may support OpenAI-compatible tool calling, but any deviation in message format will break the loop |
| Embedding dimension | Schema hardcoded to 1536 dims | OpenCode Go embedding models may emit a different dimension |
| Type annotations | `client: AsyncOpenAI` everywhere | Mixing in a different client class requires an abstraction or protocol |
| Config model | `openai_*` setting names only | Need a provider-agnostic setting (e.g., `llm_provider`, `llm_api_base`, `llm_model`) |
| Ingestion script | Uses sync `OpenAI` directly with no abstraction | Needs to honor the same provider switch |
| Suggestions parsing | Fence-stripping regex tuned for `gpt-4o` | May not be needed for OpenCode Go, or may need different normalization |
| History loading | No truncation | Same concern across providers, but context-window sizes differ by model |

---

## 6. Test Harness

`api/tests/conftest.py` defines `FakeOpenAIClient` that mimics the OpenAI SDK shape:

- `FakeOpenAIClient.chat.completions.create()` returns a `_FakeStream` of `_Chunk` → `_Choice` → `_Delta` objects.
- `_FakeEmbeddings` implements `client.embeddings.create(model, input)` and returns one-hot-ish vectors of dimension `8` (not 1536) for SQLite tests.
- Tests install the fake via `app.dependency_overrides[get_openai_client]`.

Any provider abstraction must keep this fake-client path working unchanged.

---

## 7. Files to Touch When Adding a Second Provider

Roughly ordered by impact:

1. `api/app/core/config.py` — add provider-agnostic settings (provider name, base URL, API key, model names, embedding model, embedding dimensions).
2. `api/app/deps.py` — introduce a provider-aware LLM client factory instead of hardcoding `AsyncOpenAI`.
3. `api/app/services/chat.py` — keep `_consume_stream` if the provider is OpenAI-compatible; otherwise normalize stream chunks to a provider-neutral format.
4. `api/app/services/knowledge_base.py` — abstract `embed_texts` and make dimensionality configurable / validated.
5. `api/app/models.py` — `KB_EMBEDDING_DIM` should come from config or the chosen embedding model, not be hardcoded.
6. `api/app/services/tools.py` — remove the `AsyncOpenAI` type annotation and import, accept the generic client.
7. `api/app/routers/chat.py` — use the new provider-aware dependency; keep the existing model name usage.
8. `api/scripts/ingest_kb.py` — use the same provider-aware client factory for the sync ingestion path.
9. `.env.example` — document the new provider settings.
10. `docker-compose.yml` — forward the new env vars.
11. `api/tests/conftest.py` — ensure the fake client still conforms to whatever abstraction is chosen.

---

## 8. Recommended Switching Strategy (preliminary, not implemented)

Because OpenCode Go is expected to expose an **OpenAI-compatible HTTP API**, the least invasive approach is:

- Keep using the `openai.AsyncOpenAI` client for both providers.
- Switch the `base_url` and `api_key` at construction time based on a new `LLM_PROVIDER` setting (`openai` or `opencodego`).
- Keep the same model-name setting name, but allow per-provider overrides (`OPENAI_MODEL` / `OPENCODEGO_MODEL` or a generic `LLM_MODEL`).
- Keep the same `tools` schema and `stream=True` flow; confirm that OpenCode Go returns `ChatCompletionChunk`-compatible deltas.
- For embeddings, ensure the chosen model dimension matches the `KB_EMBEDDING_DIM` column, or make the dimension configurable and re-index when switching.

This preserves the existing OpenAI integration exactly while adding the second provider as a construction-time switch.

---

## 9. Phase 2 Implementation Results

### 9.1 Models chosen

| Purpose | Provider | Model | Endpoint | Reason |
|---|---|---|---|---|
| Chat + tool-calling | **OpenCode Go** | `kimi-k2.7-code` | `https://opencode.ai/zen/go/v1/chat/completions` | Strongest OpenAI-compatible tool-caller in the Go lineup at a moderate price point ($0.95/$4.00 per 1M tokens). |
| Embeddings / RAG | **OpenAI** (exception) | `text-embedding-3-small` | `https://api.openai.com/v1/embeddings` | OpenCode Go has **no `/v1/embeddings` endpoint**. Keeping the existing 1536-dim path avoids a forced bad fit. |

### 9.2 Verification performed

- Probed `https://opencode.ai/zen/go/v1/chat/completions` with a dummy key: **401 Unauthorized** → endpoint exists, requires a valid key.
- Probed `https://opencode.ai/zen/go/v1/embeddings` and `https://opencode.ai/zen/v1/embeddings` with a dummy key: **404 Not Found** → no embedding endpoint exposed.
- Confirmed via OpenCode docs that Go models are served through the **AI SDK `@ai-sdk/openai-compatible`** package, which consumes/produces standard OpenAI `chat.completions` SSE deltas.

Because no live API key was available, real inference against OpenCode Go was not exercised. The implementation relies on documented OpenAI compatibility and was validated against the existing `FakeOpenAIClient` test harness.

### 9.3 What had to be adapted

| Area | Change | Why |
|---|---|---|
| `api/app/core/config.py` | Added `llm_provider`, `llm_api_base`, `llm_api_key`, `llm_model`. Kept OpenAI vars for embeddings + revert. | Provider-aware construction without losing OpenAI fallback. |
| `api/app/deps.py` | Commented out the OpenAI `AsyncOpenAI(api_key=...)` constructor; active code constructs `AsyncOpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)`. | OpenCode Go is accessed through the OpenAI SDK with a swapped base URL. |
| `api/app/services/chat.py` | `_consume_stream` now tolerates both SDK objects and dict-like chunks; added `_delta_value` helper. `_extract_json_array` strips markdown fences before extracting the first `[...]` span. | Defensive against any provider-specific delta variation; fence-stripping is now model-agnostic, not gpt-4o-tuned. |
| `api/app/services/tools.py` | Removed `AsyncOpenAI` import/annotation (`client: Any`). Added `"additionalProperties": False` to every tool parameter schema. | Prevents open models from inventing extra parameters; keeps the dispatcher provider-agnostic. |
| `api/app/services/knowledge_base.py` | Removed `AsyncOpenAI` import/annotation (`client: Any`). | Embeddings stay on OpenAI, but the service is provider-agnostic. |
| `api/app/routers/chat.py` | Uses `settings.llm_model` instead of `settings.openai_model`. | Active chat model now comes from OpenCode Go settings. |
| `api/scripts/ingest_kb.py` | Added explicit comment documenting the OpenAI embedding exception. | KB ingestion must still call OpenAI embeddings because Go has no endpoint. |
| `api/tests/conftest.py` | Added `LLM_*` environment variables so tests run with the new provider defaults. | `FakeOpenAIClient` remains compatible. |
| `.env.example` / `docker-compose.yml` | Documented `LLM_*` vars and forwarded them. | Ops configuration matches the new provider. |

### 9.4 What did NOT have to be adapted

- **Streaming delta shape**: OpenCode Go's `@ai-sdk/openai-compatible` path returns the same `ChatCompletionChunk` SSE shape as OpenAI, so the existing `delta.content` / `delta.tool_calls` parsing continues to work. The defensive parser was added purely as future-proofing.
- **Tool-call message format**: The assistant `tool_calls` and `role=tool` messages sent back into the conversation match the OpenAI schema, which the compatible endpoint accepts.
- **Embedding dimension**: No change to `KB_EMBEDDING_DIM` (1536) because embeddings remain on OpenAI `text-embedding-3-small`.

### 9.5 Real compromises forced by OpenCode Go

1. **No embedding model** — the biggest compromise. OpenCode Go only exposes chat completions; there is no `/v1/embeddings` endpoint. Embeddings and KB ingestion therefore remain on OpenAI. This is an explicit exception, not a config swap.

2. **No live end-to-end validation** — without a real OpenCode Go API key, the tool-calling loop was verified only against the fake test client. Real-world reliability with `kimi-k2.7-code` (e.g., argument JSON validity, tool-selection accuracy, multi-round behavior) is assumed based on the documented OpenAI-compatible endpoint and the model's advertised tool-calling support.

3. **Model-specific behavior unknown** — fence-stripping for `generate_suggestions` was generalized, but whether `kimi-k2.7-code` actually emits fenced JSON or empty preambles can only be confirmed with live calls.

### 9.6 Test results

- `tests/test_chat.py` + `tests/test_knowledge_base.py` + `tests/test_tools.py`: **37 passed**.
- Full suite (`tests/`): **70 passed, 1 failed**.
- The single failure (`tests/test_order.py::test_modifying_reviewed_cart_reverts_and_blocks_confirm`) is a pre-existing SQLAlchemy async lazy-loading issue (`MissingGreenlet`) in `app/services/cart.py` and is **out of scope** for the LLM-layer switch (per original audit framing: cart DB logic / checkout adapter are not touched).

### 9.7 Exact revert steps

To restore the OpenAI chat path:

1. In `api/app/deps.py`, uncomment the block inside `# --- OPENAI ... ---` and comment out the active OpenCode Go constructor.
2. In `api/app/routers/chat.py`, change `settings.llm_model` back to `settings.openai_model`.
3. In `.env`, set `OPENAI_API_KEY` and `OPENAI_MODEL` to your desired OpenAI values.
4. Embeddings are already on OpenAI, so no KB re-ingestion is needed.

To switch back to OpenCode Go, reverse the above.
