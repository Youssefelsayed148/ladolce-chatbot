"""Tests for the bestsellers routing in dispatch_tool (Phase 6).

"What are your bestsellers?" used to reach search_products/recommend_items as
a literal free-text query ("bestsellers"), which never substring-matches any
product's name/description - so the tool silently returned zero rows and the
concierge said it couldn't retrieve bestsellers. These tests cover the fix:
routing a bestseller-style ask to the curated products.is_bestseller flag.
"""

import pytest
import pytest_asyncio

from app.core.db import get_sessionmaker
from app.models import Category, Conversation, Product
from app.services.tools import ALL_TOOLS, dispatch_tool, _is_bestseller_query


@pytest_asyncio.fixture
async def seeded(prepare_db):
    async with get_sessionmaker()() as session:
        dates = Category(name="Individual Dates", sort_order=0)
        boxes = Category(name="Gift Boxes & Trays", sort_order=1)
        session.add_all([dates, boxes])
        await session.flush()

        session.add_all(
            [
                Product(
                    category_id=dates.id,
                    name="Jordanian Majdool Date",
                    price=8,
                    is_active=True,
                    is_bestseller=True,
                ),
                Product(
                    category_id=boxes.id,
                    name="The Royal Assortment",
                    price=450,
                    is_active=True,
                    is_bestseller=True,
                ),
                Product(
                    category_id=dates.id,
                    name="Ajwa Date",
                    price=6,
                    is_active=True,
                    is_bestseller=False,
                ),
            ]
        )
        conversation = Conversation(session_token="test-token")
        session.add(conversation)
        await session.commit()
        return conversation


async def test_recommend_items_routes_bestseller_phrasing_to_curated_flag(seeded):
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, seeded, None, "recommend_items", {"preference_notes": "bestsellers"}
        )
        names = {r["name"] for r in result.data["recommendations"]}
        assert names == {"Jordanian Majdool Date", "The Royal Assortment"}
        # Product cards render for every matched item, not just a text answer.
        assert len(result.ui_blocks) == 2
        assert all(b["type"] == "product_card" for b in result.ui_blocks)


async def test_search_products_routes_bestseller_phrasing_to_curated_flag(seeded):
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, seeded, None, "search_products", {"query": "what are your best sellers"}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"Jordanian Majdool Date", "The Royal Assortment"}


@pytest.mark.parametrize(
    "phrasing",
    [
        "what are your bestsellers?",
        "what are your current bestsellers",
        "best sellers",
        "most popular",
        "top sellers",
        "favorites",
        "what do people order most",
        "what sells the best",
        "best-selling items",
        "what are the top rated dates",
    ],
)
async def test_search_products_routes_broad_bestseller_phrasings(seeded, phrasing):
    # The original fix only caught a handful of exact keywords ("bestseller",
    # "most popular", ...) - "what are your current bestsellers" happened to
    # still substring-match "bestseller", but plenty of equally natural asks
    # ("favorites", "what do people order most", "best-selling items") didn't,
    # and fell through to a literal-text search_products call that never
    # matches any product name/description, returning nothing.
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, seeded, None, "search_products", {"query": phrasing}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"Jordanian Majdool Date", "The Royal Assortment"}


def test_is_bestseller_query_does_not_over_match_unrelated_text():
    # A broad keyword set must stay a keyword set, not a catch-all - plain
    # product questions must still reach the ordinary search path.
    assert _is_bestseller_query("do you have pistachio dates") is False
    assert _is_bestseller_query("what's in a custom box") is False
    assert _is_bestseller_query("") is False


async def test_search_products_non_bestseller_query_is_unaffected(seeded):
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, seeded, None, "search_products", {"query": "Ajwa"}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"Ajwa Date"}


async def test_search_products_exact_category_still_matches(seeded):
    # Not a bestseller path - exercises the pre-existing exact-category filter
    # that a category-shaped question ("show me gift boxes") relies on once
    # the model is told the real category names (see _categories_context).
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session,
            None,
            seeded,
            None,
            "search_products",
            {"query": "", "category": "Gift Boxes & Trays"},
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"The Royal Assortment"}


async def test_recommend_items_non_bestseller_preference_is_unaffected(seeded):
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session,
            None,
            seeded,
            None,
            "recommend_items",
            {"preference_notes": "something with almonds"},
        )
        # No product matches "almonds" here - unaffected by the bestseller
        # routing means it stays an ordinary (empty) search, not a fallback
        # to the curated list.
        assert result.data["recommendations"] == []
        assert result.ui_blocks == []


# --------------------------------------------------------------------------- #
# search_products: cross-category "sold individually vs sold by weight"
# near-duplicates (see app.services.catalog._normalized_base_name).
#
# "Golden Sukkari Date" (Individual Dates, per-piece) and "Golden Sukkari
# Dates (500g)"/"(1kg)" (Date Packs, weighed tiers) are three separate rows
# for the same variety. A free-text query used to substring-match only
# whichever of these happened to contain the query and then sort
# alphabetically - so "Golden Sukkari Dates" (as literally asked) could
# silently resolve to the wrong one instead of surfacing all matching options.
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def variant_seeded(prepare_db):
    async with get_sessionmaker()() as session:
        individual = Category(name="Individual Dates", sort_order=0)
        packs = Category(name="Date Packs", sort_order=1)
        session.add_all([individual, packs])
        await session.flush()

        session.add_all(
            [
                Product(
                    category_id=individual.id,
                    name="Golden Sukkari Date",
                    price=6,
                    is_active=True,
                ),
                Product(
                    category_id=packs.id,
                    name="Golden Sukkari Dates (500g)",
                    price=65,
                    is_active=True,
                ),
                Product(
                    category_id=packs.id,
                    name="Golden Sukkari Dates (1kg)",
                    price=120,
                    is_active=True,
                ),
                Product(
                    category_id=individual.id,
                    name="Ajwa Date",
                    price=6,
                    is_active=True,
                ),
            ]
        )
        conversation = Conversation(session_token="variant-test-token")
        session.add(conversation)
        await session.commit()
        return conversation


async def test_search_products_singular_query_surfaces_all_variety_siblings(variant_seeded):
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, variant_seeded, None, "search_products", {"query": "Golden Sukkari Date"}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {
            "Golden Sukkari Date",
            "Golden Sukkari Dates (500g)",
            "Golden Sukkari Dates (1kg)",
        }
        # Every match renders its own card - the guest sees all three options
        # (and their distinct prices) rather than the concierge picking one.
        assert len(result.ui_blocks) == 3
        assert all(b["type"] == "product_card" for b in result.ui_blocks)


async def test_search_products_plural_query_surfaces_all_variety_siblings(variant_seeded):
    # The literal phrasing from the reported bug ("Show me Golden Sukkari
    # Dates") - must not silently resolve to just the per-piece product.
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, variant_seeded, None, "search_products", {"query": "Golden Sukkari Dates"}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {
            "Golden Sukkari Date",
            "Golden Sukkari Dates (500g)",
            "Golden Sukkari Dates (1kg)",
        }


async def test_search_products_category_filter_scopes_to_the_tiered_pack_only(variant_seeded):
    # The earlier bestsellers-fix mechanism (category as an exact-match
    # disambiguator) must still work and must NOT get diluted by sibling
    # expansion - "show me date packs" should return only the Date Packs rows.
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session,
            None,
            variant_seeded,
            None,
            "search_products",
            {"query": "", "category": "Date Packs"},
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"Golden Sukkari Dates (500g)", "Golden Sukkari Dates (1kg)"}


async def test_search_products_unrelated_query_does_not_pull_in_siblings(variant_seeded):
    # "Ajwa" has no cross-category variant siblings in this catalog - sibling
    # expansion must be a no-op here, not a blanket "return everything".
    async with get_sessionmaker()() as session:
        result = await dispatch_tool(
            session, None, variant_seeded, None, "search_products", {"query": "Ajwa"}
        )
        names = {r["name"] for r in result.data["results"]}
        assert names == {"Ajwa Date"}


def test_all_tools_have_additional_properties_false():
    """Open models tend to invent extra parameters if not explicitly forbidden.
    Every tool schema should declare additionalProperties: False.
    """
    assert len(ALL_TOOLS) == 11
    for tool in ALL_TOOLS:
        params = tool["function"]["parameters"]
        assert params.get("type") == "object"
        assert params.get("additionalProperties") is False, (
            f"{tool['function']['name']} is missing additionalProperties: False"
        )


async def test_knowledge_base_search_embeds_via_embedding_client_not_chat_client(prepare_db):
    # Free chat providers have no embeddings endpoint, so KB search must use the
    # dedicated embedding client and never touch the chat client.
    from tests.conftest import FakeOpenAIClient

    class ChatClientWithoutEmbeddings:
        @property
        def embeddings(self):
            raise AssertionError("chat client must not be used for embeddings")

    embedding_client = FakeOpenAIClient()
    async with get_sessionmaker()() as session:
        conversation = Conversation(session_token="kb-embed-token")
        session.add(conversation)
        await session.commit()
        await dispatch_tool(
            session,
            ChatClientWithoutEmbeddings(),
            conversation,
            None,
            "search_knowledge_base",
            {"query": "shipping"},
            embedding_client,
        )
    assert embedding_client.embeddings.calls
