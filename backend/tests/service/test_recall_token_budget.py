import pytest
import pytest_asyncio

from db.vector_index import DummyEmbeddingProvider
from db.recall import RecallService, estimate_tokens


@pytest_asyncio.fixture
async def recall_service(search_indexer, vector_indexer):
    return RecallService(search_indexer, vector_indexer)


class TestBudgetZero:
    async def test_budget_zero(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="",
            content="The user has a cat named Whiskers.",
            priority=3,
            title="cat_name",
            disclosure="Pet info",
        )
        mem = await graph_service.get_memory_by_path("cat_name", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"],
            namespace="",
            source_memory_id=mem["id"],
            domain="core",
            path="cat_name",
            source_type="active_memory",
            source_text=mem["content"],
        )

        result = await recall_service.recall("Whiskers cat", token_budget=0)
        assert "token_budget too small" in result


class TestBudgetOneItem:
    async def test_budget_one_item_only(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="",
            content="The user has a cat named Whiskers.",
            priority=3,
            title="cat_name",
            disclosure="Pet info",
        )
        mem = await graph_service.get_memory_by_path("cat_name", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"],
            namespace="",
            source_memory_id=mem["id"],
            domain="core",
            path="cat_name",
            source_type="active_memory",
            source_text=mem["content"],
        )

        result = await recall_service.recall("cat Whiskers", token_budget=150)
        assert "cat_name" in result
        assert "items" in result


class TestBudgetVeryLarge:
    async def test_budget_very_large(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        for i in range(5):
            await graph_service.create_memory(
                parent_path="",
                content=f"User likes coffee number {i} and drinks it daily.",
                priority=3,
                title=f"coffee_mem_{i}",
                disclosure="Test",
            )
            mem = await graph_service.get_memory_by_path(f"coffee_mem_{i}", "core")
            await vector_indexer.index_memory(
                node_uuid=mem["node_uuid"],
                namespace="",
                source_memory_id=mem["id"],
                domain="core",
                path=f"coffee_mem_{i}",
                source_type="active_memory",
                source_text=mem["content"],
            )

        result = await recall_service.recall("coffee", token_budget=100000)
        sem_count = result.count("[SEMANTIC]")
        lex_count = result.count("[LEXICAL]")
        both_count = result.count("[BOTH]")
        total = sem_count + lex_count + both_count
        assert total >= 3, f"Expected >= 3 items with large budget, got {total}"


class TestBudgetPerItemCap:
    async def test_budget_per_item_cap(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        long_text = "Very " + "very " * 500 + "long text about a specific topic."
        await graph_service.create_memory(
            parent_path="",
            content=long_text,
            priority=3,
            title="long_mem",
            disclosure="Test",
        )
        mem = await graph_service.get_memory_by_path("long_mem", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"],
            namespace="",
            source_memory_id=mem["id"],
            domain="core",
            path="long_mem",
            source_type="active_memory",
            source_text=mem["content"],
        )

        result = await recall_service.recall("very long text", token_budget=500)
        assert "long_mem" in result
        assert "items" in result


class TestEstimateTokensConsistent:
    def test_estimate_tokens_consistent(self):
        text = "Hello world, this is a test sentence."
        assert estimate_tokens(text) == estimate_tokens(text)
        assert estimate_tokens(text) == estimate_tokens(text)

    def test_estimate_tokens_known_values(self):
        assert estimate_tokens("abc") == 1
        assert estimate_tokens("abcdef") == 2
        assert estimate_tokens("abcdefghi") == 3
        assert estimate_tokens("") == 1


class TestBudgetRegressionBoundary:
    async def test_result_estimate_never_exceeds_budget(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        for i in range(5):
            await graph_service.create_memory(
                parent_path="",
                content=f"Boundary test memory number {i} with concrete recall budget facts.",
                priority=3,
                title=f"boundary_{i}",
                disclosure="Test",
            )
            mem = await graph_service.get_memory_by_path(f"boundary_{i}", "core")
            await vector_indexer.index_memory(
                node_uuid=mem["node_uuid"],
                namespace="",
                source_memory_id=mem["id"],
                domain="core",
                path=f"boundary_{i}",
                source_type="active_memory",
                source_text=mem["content"],
            )

        budgets = [50, 100, 150, 200, 500, 2000]
        for budget in budgets:
            result = await recall_service.recall("boundary concrete facts", token_budget=budget)
            actual = estimate_tokens(result)
            assert actual <= budget, (
                f"estimate_tokens(result)={actual} exceeds token_budget={budget}\n"
                f"result[:200]: {result[:200]}"
            )
