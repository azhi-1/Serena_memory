import pytest
import pytest_asyncio

from db.vector_index import DummyEmbeddingProvider
from db.recall import RecallService, estimate_tokens


@pytest_asyncio.fixture
async def recall_with_remote(search_indexer, vector_indexer, remote_summary_service):
    return RecallService(search_indexer, vector_indexer, remote_summary_service=remote_summary_service)


class TestRecallRemoteBasic:
    async def test_remote_appears_in_recall(self, graph_service, vector_indexer,
                                             remote_summary_service, recall_with_remote):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="", content="Tokyo memories of ramen shops and temples.",
            priority=3, title="tokyo_trip", disclosure="travel",
        )
        mem = await graph_service.get_memory_by_path("tokyo_trip", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"], namespace="",
            source_memory_id=mem["id"], domain="core",
            path="tokyo_trip", source_type="active_memory",
            source_text=mem["content"],
        )

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Japan Travel Summary",
            summary_text="Tokyo trip review of ramen shops and temples visited in 2024.",
            summary_model="test-model",
            sources=[{"node_uuid": mem["node_uuid"], "memory_id": mem["id"],
                       "domain": "core", "path": "tokyo_trip",
                       "uri": "core://tokyo_trip"}],
        )

        result = await recall_with_remote.recall("Japan travel food")
        assert "[REMOTE]" in result
        assert "Japan Travel Summary" in result
        assert "sources: 1 memories" in result

    async def test_remote_inactive_without_remote_service(self, graph_service,
                                                            vector_indexer, recall_service):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await graph_service.create_memory(
            parent_path="", content="Some content about cats.",
            priority=1, title="cat_mem", disclosure="pets",
        )
        mem = await graph_service.get_memory_by_path("cat_mem", "core")
        await vec.index_memory(
            node_uuid=mem["node_uuid"], namespace="",
            source_memory_id=mem["id"], domain="core",
            path="cat_mem", source_type="active_memory",
            source_text=mem["content"],
        )

        result = await recall_service.recall("cats")
        assert "[REMOTE]" not in result
        assert "No memories found" not in result


class TestRecallRemoteNamespace:
    async def test_remote_namespace_isolation(self, graph_service, vector_indexer,
                                                remote_summary_service, search_indexer):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="ns_a", domain="core",
            title="NS-A Summary", summary_text="Alpha content here.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-a", "memory_id": 1,
                       "domain": "core", "path": "a", "uri": "core://a"}],
        )
        await remote_summary_service.create(
            namespace="ns_b", domain="core",
            title="NS-B Summary", summary_text="Beta content here.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-b", "memory_id": 1,
                       "domain": "core", "path": "b", "uri": "core://b"}],
        )

        recall_a = RecallService(search_indexer, vec, remote_summary_service=remote_summary_service)
        recall_b = RecallService(search_indexer, vec, remote_summary_service=remote_summary_service)

        result_a = await recall_a.recall("Alpha content", namespace="ns_a")
        assert "NS-A Summary" in result_a
        assert "NS-B Summary" not in result_a

        result_b = await recall_b.recall("Beta content", namespace="ns_b")
        assert "NS-B Summary" in result_b
        assert "NS-A Summary" not in result_b

    async def test_cross_namespace_not_visible(self, graph_service, vector_indexer,
                                                 remote_summary_service, search_indexer):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="private", domain="core",
            title="Private Summary", summary_text="Secret project details.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-p", "memory_id": 1,
                       "domain": "core", "path": "p", "uri": "core://p"}],
        )

        recall = RecallService(search_indexer, vec, remote_summary_service=remote_summary_service)
        result = await recall.recall("Secret project", namespace="public")
        assert "Private Summary" not in result


class TestRecallRemoteMerge:
    async def test_three_pool_merge(self, graph_service, vector_indexer,
                                      remote_summary_service, recall_with_remote):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await graph_service.create_memory(
            parent_path="", content="Semantic memory about machine learning.",
            priority=3, title="ml_mem", disclosure="tech",
        )
        mem_sem = await graph_service.get_memory_by_path("ml_mem", "core")
        await vec.index_memory(
            node_uuid=mem_sem["node_uuid"], namespace="",
            source_memory_id=mem_sem["id"], domain="core",
            path="ml_mem", source_type="active_memory",
            source_text=mem_sem["content"],
        )

        await graph_service.create_memory(
            parent_path="", content="machine learning neural networks deep learning.",
            priority=5, title="ml_lex", disclosure="tech",
        )
        mem_lex = await graph_service.get_memory_by_path("ml_lex", "core")

        await remote_summary_service.create(
            namespace="", domain="core",
            title="ML Summary", summary_text="machine learning overview of neural nets.",
            summary_model="test",
            sources=[{"node_uuid": mem_sem["node_uuid"], "memory_id": mem_sem["id"],
                       "domain": "core", "path": "ml_mem", "uri": "core://ml_mem"}],
        )

        result = await recall_with_remote.recall("machine learning")
        assert "[REMOTE]" in result or "[SEMANTIC]" in result or "[LEXICAL]" in result
        assert "ml" in result.lower()


class TestRecallRemoteSuperseded:
    async def test_superseded_excluded_from_recall(self, graph_service, vector_indexer,
                                                     remote_summary_service, recall_with_remote):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        batch = await remote_summary_service.create(
            namespace="", domain="core",
            title="Old Summary", summary_text="outdated information that was replaced.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-x", "memory_id": 1,
                       "domain": "core", "path": "x", "uri": "core://x"}],
        )

        await remote_summary_service.supersede_batch(batch["id"])

        result = await recall_with_remote.recall("outdated information")
        assert "Old Summary" not in result


class TestRecallRemoteTokenBudget:
    async def test_token_budget_applies_to_remote(self, graph_service, vector_indexer,
                                                    remote_summary_service, recall_with_remote):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Budget Test",
            summary_text="A very long remote summary text that describes many details "
                         "about the budget test scenario and should be truncated when "
                         "the token budget is small enough to require cutting content "
                         "from the formatted output.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-b", "memory_id": 1,
                       "domain": "core", "path": "b", "uri": "core://b"}],
        )

        result = await recall_with_remote.recall("budget test scenario", token_budget=200)
        assert estimate_tokens(result) <= 200

    async def test_recall_with_only_remote(self, graph_service, vector_indexer,
                                             remote_summary_service, search_indexer):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Solo Remote", summary_text="unique remote summary only result text.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-solo", "memory_id": 1,
                       "domain": "core", "path": "solo", "uri": "core://solo"}],
        )

        recall = RecallService(search_indexer, vec, remote_summary_service=remote_summary_service)
        result = await recall.recall("unique remote summary only result text")
        assert "[REMOTE]" in result
        assert "Solo Remote" in result


class TestRecallRemoteDegraded:
    async def test_remote_search_failure_fallback(self, graph_service, vector_indexer,
                                                    remote_summary_service, recall_service):
        vec = vector_indexer
        vec._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await graph_service.create_memory(
            parent_path="", content="Fallback memory about coffee brewing techniques.",
            priority=3, title="coffee", disclosure="food",
        )
        mem = await graph_service.get_memory_by_path("coffee", "core")
        await vec.index_memory(
            node_uuid=mem["node_uuid"], namespace="",
            source_memory_id=mem["id"], domain="core",
            path="coffee", source_type="active_memory",
            source_text=mem["content"],
        )

        result = await recall_service.recall("coffee brewing")
        assert "No memories found" not in result
        assert "[REMOTE]" not in result
