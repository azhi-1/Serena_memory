import pytest
import pytest_asyncio

from db.vector_index import DummyEmbeddingProvider
from db.recall import RecallService, estimate_tokens


@pytest_asyncio.fixture
async def recall_service(search_indexer, vector_indexer):
    return RecallService(search_indexer, vector_indexer)


async def _create_memory_with_embedding(graph_service, vector_indexer, title, content,
                                        domain="core", namespace="", priority=3):
    await graph_service.create_memory(
        parent_path="",
        content=content,
        priority=priority,
        title=title,
        disclosure="When relevant",
        domain=domain,
    )
    mem = await graph_service.get_memory_by_path(title, domain, namespace=namespace)
    await vector_indexer.index_memory(
        node_uuid=mem["node_uuid"],
        namespace=namespace,
        source_memory_id=mem["id"],
        domain=domain,
        path=title,
        source_type="active_memory",
        source_text=mem["content"],
    )
    return mem


class TestRecallSemanticOnly:
    async def test_recall_semantic_only(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "tea_pref", "The user prefers tea over coffee every morning.",
        )

        result = await recall_service.recall("tea preference")

        assert "[SEMANTIC] score=" in result
        assert "uri: core://tea_pref" in result
        assert "source: active_memory" in result
        assert "tea" in result.lower()


class TestRecallLexicalOnly:
    async def test_recall_lexical_only(self, graph_service, recall_service):
        await graph_service.create_memory(
            parent_path="",
            content="The user runs a small pottery business on weekends.",
            priority=2,
            title="pottery_business",
            disclosure="When discussing hobbies",
        )

        result = await recall_service.recall("pottery business")

        assert "[LEXICAL] snippet_match" in result
        assert "uri: core://pottery_business" in result
        assert "pottery" in result.lower()


class TestRecallBothMerged:
    async def test_recall_both_merged(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        content = "The user visited Kyoto temples in autumn 2024."
        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "kyoto_visit", content,
        )

        # Use the exact same text as content so the dummy embedding matches
        # (hash-based) AND lexical FTS finds the text.
        result = await recall_service.recall(content)

        assert "[BOTH]" in result
        assert "uri: core://kyoto_visit" in result
        assert "snippet:" in result
        assert "priority:" in result


class TestRecallDedup:
    async def test_recall_dedup_by_node_uuid(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        mem = await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "pet_dog", "The user has a golden retriever named Max.",
        )

        result = await recall_service.recall("golden retriever dog pet Max")

        count = result.count("uri: core://pet_dog")
        assert count == 1, f"Expected 1 occurrence of pet_dog, got {count}"


class TestRecallNamespaceIsolation:
    async def test_recall_namespace_isolation(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        # Create memory in ns_a with embedding
        await graph_service.create_memory(
            parent_path="",
            content="Secret Alpha project launch date is June 15.",
            priority=3,
            title="alpha_secret",
            disclosure="Secret project",
            namespace="ns_a",
        )
        mem_a = await graph_service.get_memory_by_path("alpha_secret", "core", namespace="ns_a")
        await vector_indexer.index_memory(
            node_uuid=mem_a["node_uuid"],
            namespace="ns_a",
            source_memory_id=mem_a["id"],
            domain="core",
            path="alpha_secret",
            source_type="active_memory",
            source_text=mem_a["content"],
        )

        # Create memory in ns_b with embedding
        await graph_service.create_memory(
            parent_path="",
            content="Public blog post about coffee brewing techniques.",
            priority=3,
            title="coffee_blog",
            disclosure="Public info",
            namespace="ns_b",
        )
        mem_b = await graph_service.get_memory_by_path("coffee_blog", "core", namespace="ns_b")
        await vector_indexer.index_memory(
            node_uuid=mem_b["node_uuid"],
            namespace="ns_b",
            source_memory_id=mem_b["id"],
            domain="core",
            path="coffee_blog",
            source_type="active_memory",
            source_text=mem_b["content"],
        )

        # Recall in ns_a should NOT find ns_b's memory
        result_a = await recall_service.recall("coffee brewing", namespace="ns_a")
        assert "coffee_blog" not in result_a

        # Recall in ns_b SHOULD find ns_b's memory
        result_b = await recall_service.recall("coffee brewing", namespace="ns_b")
        assert "coffee_blog" in result_b


class TestRecallEmpty:
    async def test_recall_empty_both(self, graph_service, recall_service):
        result = await recall_service.recall("nonexistent_xyz_query_12345")
        assert "No memories found" in result


class TestRecallDomainFilter:
    async def test_recall_domain_filter(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "core_mem", "Core memory about the assistant's personality.",
            domain="core",
        )
        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "game_mem", "The magic system uses elemental crystals.",
            domain="game",
        )

        result_core = await recall_service.recall("personality", domain="core")
        assert "core_mem" in result_core
        assert "game_mem" not in result_core

        result_game = await recall_service.recall("magic system", domain="game")
        assert "game_mem" in result_game
        assert "core_mem" not in result_game


class TestRecallEmbeddingFailure:
    async def test_recall_embedding_failure_graceful(self, graph_service, vector_indexer, recall_service):
        class FailingProvider:
            async def embed(self, texts, **kwargs):
                raise RuntimeError("API unavailable")

        vector_indexer._embedding_provider = FailingProvider()

        await graph_service.create_memory(
            parent_path="",
            content="The user lives in Seattle and works remote.",
            priority=2,
            title="user_location",
            disclosure="Location info",
        )

        result = await recall_service.recall("Seattle location")

        assert "[LEXICAL] snippet_match" in result
        assert "user_location" in result
        assert "Error:" not in result


class TestRecallScoreOrdering:
    async def test_recall_score_ordering(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        mem_a = await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "tokyo_visit", "Tokyo is a vibrant city with amazing food and transit.",
            priority=3,
        )
        mem_b = await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "kyoto_visit", "Kyoto has beautiful temples and traditional tea houses.",
            priority=3,
        )
        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "osaka_food", "Osaka is famous for street food and friendly locals.",
            priority=3,
        )

        result = await recall_service.recall("Japan cities I visited")

        lines = result.split("\n")
        sem_lines = [l for l in lines if "[SEMANTIC]" in l]
        assert len(sem_lines) >= 2, f"Expected >= 2 semantic results, got {len(sem_lines)}"


class TestRecallRRFDeterministic:
    async def test_recall_rrf_deterministic(self, graph_service, vector_indexer, recall_service):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "a_mem", "Alpha memory about project planning.",
        )
        await _create_memory_with_embedding(
            graph_service, vector_indexer,
            "b_mem", "Beta memory about testing strategies.",
        )

        result1 = await recall_service.recall("project testing")
        result2 = await recall_service.recall("project testing")
        result3 = await recall_service.recall("project testing")

        assert result1 == result2
        assert result2 == result3


class TestEstimateTokens:
    def test_estimate_tokens_short(self):
        assert estimate_tokens("Hello") == 1

    def test_estimate_tokens_six_chars(self):
        assert estimate_tokens("abcdef") == 2

    def test_estimate_tokens_empty(self):
        assert estimate_tokens("") == 1
