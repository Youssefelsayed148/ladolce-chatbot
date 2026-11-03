"""Shared test fixtures.

Runs the whole app against a throwaway SQLite database (async via aiosqlite),
so no Postgres, network, or OpenAI key is required. The OpenAI client is
replaced with a fake that emits canned streaming chunks.
"""

import os
import tempfile
from pathlib import Path

# --- Environment MUST be set before importing the app (settings are cached) ---
_TMPDIR = tempfile.mkdtemp(prefix="ladolce_test_")
_DB_PATH = Path(_TMPDIR) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["OPENAI_MODEL"] = "gpt-4o-mini"
os.environ["OPENAI_EMBEDDING_MODEL"] = "text-embedding-3-small"
# Active chat provider for tests. FakeOpenAIClient is interface-compatible with
# openai.AsyncOpenAI, so it works for either provider abstraction.
os.environ["LLM_PROVIDER"] = "opencodego"
os.environ["LLM_API_BASE"] = "https://opencode.ai/zen/go/v1"
os.environ["LLM_API_KEY"] = "sk-test"
os.environ["LLM_MODEL"] = "kimi-k2.7-code"
os.environ["CHAT_RATE_LIMIT"] = "1000/minute"  # effectively disabled for tests
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core import db as db_module  # noqa: E402

db_module.reset_engine()

from app.core.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app import models  # noqa: E402,F401  (register tables)
from app.deps import get_embedding_client, get_openai_client  # noqa: E402
from app.main import app  # noqa: E402
from app.services.chat import SUGGESTIONS_SYSTEM_PROMPT  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake OpenAI streaming client
# --------------------------------------------------------------------------- #
class _FunctionDelta:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _ToolCallDelta:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = _FunctionDelta(name=name, arguments=arguments)


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    def __init__(self, delta):
        self.choices = [_Choice(delta)]


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class _FakeCompletions:
    def __init__(self, mode, suggestions_mode="ok"):
        self.mode = mode
        self.suggestions_mode = suggestions_mode
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        first_call = len(self.calls) == 1

        # The suggestions follow-up call (generate_suggestions) is identified
        # by its system prompt, independent of round/mode - it always happens
        # last, after the main tool loop has finished.
        messages = kwargs.get("messages") or []
        if messages and messages[0].get("content") == SUGGESTIONS_SYSTEM_PROMPT:
            if self.suggestions_mode == "broken":
                return _FakeStream([_Chunk(_Delta(content="not valid json"))])
            if self.suggestions_mode == "fenced":
                # gpt-4o occasionally wraps its JSON in a markdown code fence
                # despite instructions not to - real-world quirk, not test-only.
                return _FakeStream(
                    [
                        _Chunk(
                            _Delta(
                                content=(
                                    '```json\n["What flavours do you have?", '
                                    '"Show me gift boxes"]\n```'
                                )
                            )
                        )
                    ]
                )
            return _FakeStream(
                [
                    _Chunk(
                        _Delta(
                            content=(
                                '["What are your bestsellers?", '
                                '"Do you ship internationally?", '
                                '"Build me a custom box"]'
                            )
                        )
                    )
                ]
            )

        # Emit a tool call only on the FIRST round (mimicking a real model that
        # calls a tool, gets the result, then answers). Subsequent rounds return
        # plain content so the loop terminates.
        if self.mode == "tool" and first_call:
            return _FakeStream(
                [
                    _Chunk(
                        _Delta(
                            tool_calls=[
                                _ToolCallDelta(
                                    index=0,
                                    id="call_1",
                                    name="search_products",
                                    arguments='{"query": "pistachio"}',
                                )
                            ]
                        )
                    )
                ]
            )

        if self.mode == "kb" and first_call:
            return _FakeStream(
                [
                    _Chunk(
                        _Delta(
                            tool_calls=[
                                _ToolCallDelta(
                                    index=0,
                                    id="call_1",
                                    name="search_knowledge_base",
                                    arguments='{"query": "return policy"}',
                                )
                            ]
                        )
                    )
                ]
            )
        if self.mode == "kb" and not first_call:
            return _FakeStream(
                [
                    _Chunk(_Delta(content="You may return dates within 14 days of delivery.")),
                ]
            )

        if self.mode == "kb_empty" and first_call:
            return _FakeStream(
                [
                    _Chunk(
                        _Delta(
                            tool_calls=[
                                _ToolCallDelta(
                                    index=0,
                                    id="call_1",
                                    name="search_knowledge_base",
                                    arguments='{"query": "do you offer pony rides"}',
                                )
                            ]
                        )
                    )
                ]
            )
        if self.mode == "kb_empty" and not first_call:
            return _FakeStream(
                [
                    _Chunk(_Delta(content="I'm sorry, I don't have that information on hand.")),
                ]
            )

        return _FakeStream(
            [
                _Chunk(_Delta(content="Bonjour! ")),
                _Chunk(_Delta(content="Our pistachio dates are exquisite.")),
            ]
        )


class _FakeEmbeddingItem:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embeddings):
        self.data = [_FakeEmbeddingItem(e) for e in embeddings]


class _FakeEmbeddings:
    """Deterministic fake for client.embeddings.create - never calls OpenAI.

    Returns one-hot-ish vectors keyed by a small vocabulary so that
    semantically-matched fixture text in tests scores near 1.0 cosine
    similarity against a matching query, and near 0 against an unrelated one,
    without needing a real embedding model.
    """

    DIM = 8
    _VOCAB = {
        "return": 0,
        "returns": 0,
        "shipping": 1,
        "ship": 1,
        "certification": 2,
        "certified": 2,
        "organic": 2,
    }

    def __init__(self):
        self.calls = []

    async def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        texts = input if isinstance(input, list) else [input]
        return _FakeEmbeddingResponse([self._embed(t) for t in texts])

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        vec = [0.0] * cls.DIM
        words = text.lower().replace(",", " ").replace(".", " ").split()
        hit = False
        for w in words:
            if w in cls._VOCAB:
                vec[cls._VOCAB[w]] = 1.0
                hit = True
        if not hit:
            # Unrecognised text still gets a stable, distinct direction so it
            # never accidentally scores high against a real topic vector.
            vec[cls.DIM - 1] = 1.0
        return vec


class _FakeChat:
    def __init__(self, mode, suggestions_mode="ok"):
        self.completions = _FakeCompletions(mode, suggestions_mode)


class FakeOpenAIClient:
    def __init__(self, mode="plain", suggestions_mode="ok"):
        self.chat = _FakeChat(mode, suggestions_mode)
        self.embeddings = _FakeEmbeddings()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def prepare_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(prepare_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def use_fake_openai():
    """Return a setter that installs a FakeOpenAIClient of the given mode."""

    def _install(mode="plain", suggestions_mode="ok"):
        fake = FakeOpenAIClient(mode=mode, suggestions_mode=suggestions_mode)
        app.dependency_overrides[get_openai_client] = lambda: fake
        app.dependency_overrides[get_embedding_client] = lambda: fake
        return fake

    yield _install
    app.dependency_overrides.pop(get_openai_client, None)
    app.dependency_overrides.pop(get_embedding_client, None)


@pytest_asyncio.fixture
async def db_session():
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture(autouse=True)
def _no_live_store_quote(monkeypatch):
    """Never hit the real store from tests; review falls back to the local price."""
    from app.services import store_quote

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(store_quote, "quote_box", _none)
