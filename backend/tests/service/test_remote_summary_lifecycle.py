import pytest
import pytest_asyncio

from db.vector_index import DummyEmbeddingProvider


class TestWriteLifecycleHappyPath:
    async def test_full_create_cycle(self, graph_service, remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="", content="Memory one about gardening.",
            priority=3, title="garden_1", disclosure="hobby",
        )
        await graph_service.create_memory(
            parent_path="", content="Memory two about planting vegetables.",
            priority=3, title="garden_2", disclosure="hobby",
        )

        mem1 = await graph_service.get_memory_by_path("garden_1", "core")
        mem2 = await graph_service.get_memory_by_path("garden_2", "core")

        batch = await remote_summary_service.create(
            namespace="", domain="core",
            title="Gardening Summary",
            summary_text="Combined gardening knowledge about planting and vegetables.",
            summary_model="test-model",
            sources=[
                {"node_uuid": mem1["node_uuid"], "memory_id": mem1["id"],
                 "domain": "core", "path": "garden_1", "uri": "core://garden_1"},
                {"node_uuid": mem2["node_uuid"], "memory_id": mem2["id"],
                 "domain": "core", "path": "garden_2", "uri": "core://garden_2"},
            ],
        )

        assert batch["source_count"] == 2
        assert batch["status"] == "active"

        sources = await remote_summary_service.get_sources(batch["id"])
        assert len(sources) == 2
        src_paths = {s["source_path"] for s in sources}
        assert src_paths == {"garden_1", "garden_2"}

        results = await vector_indexer.search(
            "gardening planting", source_type="remote_summary",
        )
        assert any(r["node_uuid"] == batch["id"] for r in results)


class TestWriteLifecycleSourceSafety:
    async def test_source_memories_unchanged_after_summary(self, graph_service,
                                                             remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="", content="Original content about astronomy.",
            priority=3, title="astro", disclosure="science",
        )
        before = await graph_service.get_memory_by_path("astro", "core")

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Astronomy Summary",
            summary_text="Summary of astronomy knowledge.",
            summary_model="m",
            sources=[{"node_uuid": before["node_uuid"], "memory_id": before["id"],
                       "domain": "core", "path": "astro", "uri": "core://astro"}],
        )

        after = await graph_service.get_memory_by_path("astro", "core")
        assert after["id"] == before["id"]
        assert after["content"] == before["content"]
        assert after["deprecated"] == before["deprecated"]
        assert after["node_uuid"] == before["node_uuid"]

    async def test_source_snapshots_preserved(self, graph_service, remote_summary_service,
                                                vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="", content="Snapshot test memory.",
            priority=2, title="snap_test", disclosure="test",
        )
        mem = await graph_service.get_memory_by_path("snap_test", "core")

        batch = await remote_summary_service.create(
            namespace="", domain="core",
            title="Snapshot Summary",
            summary_text="Snapshot test.",
            summary_model="m",
            sources=[{"node_uuid": mem["node_uuid"], "memory_id": mem["id"],
                       "domain": "core", "path": "snap_test",
                       "uri": "core://snap_test"}],
        )

        sources = await remote_summary_service.get_sources(batch["id"])
        assert len(sources) == 1
        assert sources[0]["source_path"] == "snap_test"
        assert sources[0]["source_uri"] == "core://snap_test"
        assert sources[0]["source_node_uuid"] == mem["node_uuid"]
        assert sources[0]["source_memory_id"] == mem["id"]


class TestWriteLifecycleRollback:
    async def test_rollback_on_embedding_failure(self, graph_service,
                                                   remote_summary_service, vector_indexer):
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await graph_service.create_memory(
            parent_path="", content="Test content.", priority=1,
            title="rollback_test", disclosure="test",
        )
        mem = await graph_service.get_memory_by_path("rollback_test", "core")

        original_provider = vector_indexer._embedding_provider

        class FailingProvider:
            async def embed(self, texts, *, dimensions=None):
                raise RuntimeError("Simulated embedding failure")

        vector_indexer._embedding_provider = FailingProvider()

        with pytest.raises(RuntimeError, match="Simulated"):
            await remote_summary_service.create(
                namespace="", domain="core",
                title="Should Rollback",
                summary_text="This batch should not persist.",
                summary_model="m",
                sources=[{"node_uuid": mem["node_uuid"], "memory_id": mem["id"],
                           "domain": "core", "path": "rollback_test",
                           "uri": "core://rollback_test"}],
            )

        vector_indexer._embedding_provider = original_provider

        batches = await remote_summary_service.list_batches(status=None)
        # Either no batches exist, or if any exist, none should match our title
        batch_titles = [b["title"] for b in batches]
        assert "Should Rollback" not in batch_titles

    async def test_source_count_matches_sources(self, remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        batch = await remote_summary_service.create(
            namespace="", domain="core",
            title="Count Match",
            summary_text="Testing count integrity.",
            summary_model="m",
            sources=[
                {"node_uuid": f"u{i}", "memory_id": i, "domain": "core",
                 "path": f"p{i}", "uri": f"core://p{i}"} for i in range(3)
            ],
        )

        assert batch["source_count"] == 3
        sources = await remote_summary_service.get_sources(batch["id"])
        assert len(sources) == 3


class TestDeleteOrphanSafety:
    async def test_remote_embeddings_not_deleted_as_orphans(self, graph_service,
                                                              remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        batch = await remote_summary_service.create(
            namespace="", domain="core",
            title="Orphan Safety",
            summary_text="Remote summary that should survive orphan cleanup.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-o", "memory_id": 1,
                       "domain": "core", "path": "orphan", "uri": "core://orphan"}],
        )

        count_before = len(await vector_indexer.search(
            "orphan", source_type="remote_summary",
        ))

        deleted = await vector_indexer.delete_orphan_embeddings()

        count_after = len(await vector_indexer.search(
            "orphan", source_type="remote_summary",
        ))
        assert count_after == count_before

    async def test_rebuild_preserves_remote_embeddings(self, graph_service,
                                                         remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Rebuild Safety",
            summary_text="Remote summary that should survive rebuild_all.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-rb", "memory_id": 1,
                       "domain": "core", "path": "rb", "uri": "core://rb"}],
        )

        remote_before = len(await vector_indexer.search("summary", source_type="remote_summary"))

        await vector_indexer.rebuild_all()

        remote_after = len(await vector_indexer.search("summary", source_type="remote_summary"))
        assert remote_after == remote_before

    async def test_rebuild_recreates_active_embeddings(self, graph_service,
                                                         remote_summary_service, vector_indexer):
        dummy = DummyEmbeddingProvider(dimensions=128)
        vector_indexer._embedding_provider = dummy

        await graph_service.create_memory(
            parent_path="", content="Rebuild active test content.",
            priority=3, title="rebuild_active", disclosure="test",
        )
        mem = await graph_service.get_memory_by_path("rebuild_active", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"], namespace="",
            source_memory_id=mem["id"], domain="core",
            path="rebuild_active", source_type="active_memory",
            source_text=mem["content"],
        )

        await remote_summary_service.create(
            namespace="", domain="core",
            title="Keep Me",
            summary_text="Remote token that should stay.",
            summary_model="m",
            sources=[{"node_uuid": "uuid-keep", "memory_id": 1,
                       "domain": "core", "path": "k", "uri": "core://k"}],
        )

        remote_before = len(await vector_indexer.search("token", source_type="remote_summary"))

        count = await vector_indexer.rebuild_all()
        assert count >= 1

        remote_after = len(await vector_indexer.search("token", source_type="remote_summary"))
        assert remote_after == remote_before
