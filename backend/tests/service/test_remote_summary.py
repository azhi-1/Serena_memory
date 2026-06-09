import pytest
import pytest_asyncio

from sqlalchemy.exc import IntegrityError


class TestRemoteSummaryCreate:
    async def test_create_basic(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        batch = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Test Summary",
            summary_text="This is a test summary of several memories.",
            summary_model="test-model",
            sources=[
                {"node_uuid": "uuid-1", "memory_id": 1, "domain": "core",
                 "path": "test/mem1", "uri": "core://test/mem1"},
                {"node_uuid": "uuid-2", "memory_id": 2, "domain": "core",
                 "path": "test/mem2", "uri": "core://test/mem2"},
            ],
        )

        assert batch["id"]
        assert batch["title"] == "Test Summary"
        assert batch["status"] == "active"
        assert batch["source_count"] == 2
        assert batch["namespace"] == ""

    async def test_create_with_namespace(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        batch = await remote_summary_service.create(
            namespace="ns_alpha",
            domain="game",
            title="Game Summary",
            summary_text="Game world events summary.",
            summary_model="test-model",
            sources=[
                {"node_uuid": "uuid-a", "memory_id": 10, "domain": "game",
                 "path": "game/event1", "uri": "game://game/event1"},
            ],
        )

        assert batch["namespace"] == "ns_alpha"
        assert batch["domain"] == "game"

    async def test_create_empty_sources_raises(self, remote_summary_service):
        with pytest.raises(ValueError, match="non-empty"):
            await remote_summary_service.create(
                namespace="",
                domain="core",
                title="Empty",
                summary_text="No sources.",
                summary_model="test",
                sources=[],
            )


class TestRemoteSummaryGet:
    async def test_get_batch_by_id(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        created = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Lookup Test",
            summary_text="Summary for lookup.",
            summary_model="model-x",
            sources=[
                {"node_uuid": "u1", "memory_id": 1, "domain": "core",
                 "path": "p1", "uri": "core://p1"},
            ],
        )

        batch = await remote_summary_service.get_batch(created["id"])
        assert batch is not None
        assert batch["title"] == "Lookup Test"
        assert batch["summary_text"] == "Summary for lookup."
        assert batch["source_count"] == 1

    async def test_get_nonexistent(self, remote_summary_service):
        batch = await remote_summary_service.get_batch("nonexistent-id")
        assert batch is None

    async def test_get_wrong_namespace(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        created = await remote_summary_service.create(
            namespace="ns_x",
            domain="core",
            title="NS Test",
            summary_text="Namespaced summary.",
            summary_model="model",
            sources=[
                {"node_uuid": "u1", "memory_id": 1, "domain": "core",
                 "path": "p1", "uri": "core://p1"},
            ],
        )

        batch = await remote_summary_service.get_batch(created["id"], namespace="ns_y")
        assert batch is None

        batch = await remote_summary_service.get_batch(created["id"], namespace="ns_x")
        assert batch is not None


class TestRemoteSummaryList:
    async def test_list_active(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="",
            domain="core",
            title="A",
            summary_text="Summary A.",
            summary_model="m",
            sources=[{"node_uuid": "u1", "memory_id": 1, "domain": "core",
                       "path": "", "uri": ""}],
        )
        await remote_summary_service.create(
            namespace="",
            domain="core",
            title="B",
            summary_text="Summary B.",
            summary_model="m",
            sources=[{"node_uuid": "u2", "memory_id": 2, "domain": "core",
                       "path": "", "uri": ""}],
        )

        batches = await remote_summary_service.list_batches()
        assert len(batches) == 2
        assert all(b["status"] == "active" for b in batches)

    async def test_list_by_domain(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Core",
            summary_text="x",
            summary_model="m",
            sources=[{"node_uuid": "u1", "memory_id": 1, "domain": "core",
                       "path": "", "uri": ""}],
        )
        await remote_summary_service.create(
            namespace="",
            domain="game",
            title="Game",
            summary_text="x",
            summary_model="m",
            sources=[{"node_uuid": "u2", "memory_id": 2, "domain": "game",
                       "path": "", "uri": ""}],
        )

        cores = await remote_summary_service.list_batches(domain="core")
        assert len(cores) == 1
        assert cores[0]["title"] == "Core"

    async def test_list_namespace_isolation(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await remote_summary_service.create(
            namespace="ns1",
            domain="core",
            title="NS1 Batch",
            summary_text="a",
            summary_model="m",
            sources=[{"node_uuid": "u1", "memory_id": 1, "domain": "core",
                       "path": "", "uri": ""}],
        )
        await remote_summary_service.create(
            namespace="ns2",
            domain="core",
            title="NS2 Batch",
            summary_text="b",
            summary_model="m",
            sources=[{"node_uuid": "u2", "memory_id": 2, "domain": "core",
                       "path": "", "uri": ""}],
        )

        ns1 = await remote_summary_service.list_batches(namespace="ns1")
        assert len(ns1) == 1
        assert ns1[0]["title"] == "NS1 Batch"

        ns2 = await remote_summary_service.list_batches(namespace="ns2")
        assert len(ns2) == 1
        assert ns2[0]["title"] == "NS2 Batch"


class TestRemoteSummarySupersede:
    async def test_supersede_active(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        created = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="To Supersede",
            summary_text="Will be superseded.",
            summary_model="m",
            sources=[{"node_uuid": "u1", "memory_id": 1, "domain": "core",
                       "path": "", "uri": ""}],
        )

        await remote_summary_service.supersede_batch(created["id"])

        batch = await remote_summary_service.get_batch(created["id"])
        assert batch["status"] == "superseded"

        active = await remote_summary_service.list_batches(status="active")
        assert len(active) == 0

        superseded = await remote_summary_service.list_batches(status="superseded")
        assert len(superseded) == 1

    async def test_supersede_nonexistent_no_error(self, remote_summary_service):
        await remote_summary_service.supersede_batch("nonexistent-id")


class TestRemoteSummarySources:
    async def test_get_sources(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        created = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Sources Test",
            summary_text="With sources.",
            summary_model="m",
            sources=[
                {"node_uuid": "u1", "memory_id": 1, "domain": "core",
                 "path": "a/b", "uri": "core://a/b"},
                {"node_uuid": "u2", "memory_id": 2, "domain": "core",
                 "path": "c/d", "uri": "core://c/d"},
            ],
        )

        sources = await remote_summary_service.get_sources(created["id"])
        assert len(sources) == 2
        paths = {s["source_path"] for s in sources}
        assert paths == {"a/b", "c/d"}
        uris = {s["source_uri"] for s in sources}
        assert uris == {"core://a/b", "core://c/d"}

    async def test_source_count_matches(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        sources = [{"node_uuid": f"u{i}", "memory_id": i, "domain": "core",
                     "path": f"p{i}", "uri": f"core://p{i}"} for i in range(5)]

        created = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Count Test",
            summary_text="Five sources.",
            summary_model="m",
            sources=sources,
        )

        assert created["source_count"] == 5
        stored = await remote_summary_service.get_sources(created["id"])
        assert len(stored) == 5

    async def test_duplicate_source_constraint(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        with pytest.raises(IntegrityError):
            await remote_summary_service.create(
                namespace="",
                domain="core",
                title="Dup Test",
                summary_text="x",
                summary_model="m",
                sources=[
                    {"node_uuid": "same-uuid", "memory_id": 1, "domain": "core",
                     "path": "p1", "uri": "core://p1"},
                    {"node_uuid": "same-uuid", "memory_id": 1, "domain": "core",
                     "path": "p2", "uri": "core://p2"},
                ],
            )


class TestRemoteSummaryEmbedding:
    async def test_create_indexes_embedding(self, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        created = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Embed Test",
            summary_text="Embedded summary for vector search.",
            summary_model="test-model",
            sources=[
                {"node_uuid": "u1", "memory_id": 1, "domain": "core",
                 "path": "p1", "uri": "core://p1"},
            ],
        )

        results = await vector_indexer.search(
            "Embedded summary",
            source_type="remote_summary",
        )
        assert len(results) >= 1
        found = [r for r in results if r["node_uuid"] == created["id"]]
        assert len(found) == 1
        assert found[0]["source_type"] == "remote_summary"
        assert found[0]["source_memory_id"] is None

    async def test_remote_and_active_coexist(self, graph_service, remote_summary_service, vector_indexer):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        await graph_service.create_memory(
            parent_path="", content="Active memory content for test.",
            priority=3, title="active_mem", disclosure="test",
        )
        mem = await graph_service.get_memory_by_path("active_mem", "core")
        await vector_indexer.index_memory(
            node_uuid=mem["node_uuid"], namespace="",
            source_memory_id=mem["id"], domain="core",
            path="active_mem", source_type="active_memory",
            source_text=mem["content"],
        )

        await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Remote Coexist",
            summary_text="Remote summary for coexistence test.",
            summary_model="m",
            sources=[{"node_uuid": mem["node_uuid"], "memory_id": mem["id"],
                       "domain": "core", "path": "active_mem",
                       "uri": "core://active_mem"}],
        )

        active = await vector_indexer.search("content", source_type="active_memory")
        assert len(active) >= 1
        remote = await vector_indexer.search("summary", source_type="remote_summary")
        assert len(remote) >= 1
