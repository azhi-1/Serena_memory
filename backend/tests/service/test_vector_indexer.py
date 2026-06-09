import pytest
import pytest_asyncio

from db.vector_index import DummyEmbeddingProvider


@pytest_asyncio.fixture
def _seed_test_data(graph_service):
    return None


async def test_index_and_search_basic(graph_service, vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    await graph_service.create_memory(
        parent_path="",
        content="The user prefers tea over coffee and drinks it every morning.",
        priority=3,
        title="drink_preference",
        disclosure="When discussing beverages",
    )
    mem = await graph_service.get_memory_by_path("drink_preference", "core")
    assert mem is not None

    await vector_indexer.index_memory(
        node_uuid=mem["node_uuid"],
        namespace="",
        source_memory_id=mem["id"],
        domain="core",
        path="drink_preference",
        source_type="active_memory",
        source_text=mem["content"],
    )

    results = await vector_indexer.search("prefers tea in the morning", limit=5)
    assert len(results) >= 1
    assert results[0]["uri"] == "core://drink_preference"
    assert results[0]["source_type"] == "active_memory"
    assert results[0]["score"] > 0


async def test_search_namespace_isolation(graph_service, vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    await graph_service.create_memory(
        parent_path="",
        content="Namespace A secret project codename Phoenix.",
        priority=3,
        title="phoenix_a",
        disclosure="When discussing secret projects",
        namespace="ns_a",
    )
    mem_a = await graph_service.get_memory_by_path("phoenix_a", "core", namespace="ns_a")

    await graph_service.create_memory(
        parent_path="",
        content="Namespace B public blog post about birds.",
        priority=3,
        title="phoenix_b",
        disclosure="When discussing nature",
        namespace="ns_b",
    )
    mem_b = await graph_service.get_memory_by_path("phoenix_b", "core", namespace="ns_b")

    await vector_indexer.index_memory(
        node_uuid=mem_a["node_uuid"], namespace="ns_a",
        source_memory_id=mem_a["id"], domain="core", path="phoenix_a",
        source_type="active_memory", source_text=mem_a["content"],
    )
    await vector_indexer.index_memory(
        node_uuid=mem_b["node_uuid"], namespace="ns_b",
        source_memory_id=mem_b["id"], domain="core", path="phoenix_b",
        source_type="active_memory", source_text=mem_b["content"],
    )

    raw = await vector_indexer.search("secret project codename", limit=5, namespace="ns_a")
    assert len(raw) >= 1
    assert raw[0]["node_uuid"] == mem_a["node_uuid"]

    b_results = await vector_indexer.search("blog about birds", limit=5, namespace="ns_b")
    assert len(b_results) >= 1
    assert b_results[0]["node_uuid"] == mem_b["node_uuid"]

    cross_a = await vector_indexer.search("blog about birds", limit=5, namespace="ns_a")
    assert not any(r["node_uuid"] == mem_b["node_uuid"] for r in cross_a)

    cross_b = await vector_indexer.search("secret project codename", limit=5, namespace="ns_b")
    assert not any(r["node_uuid"] == mem_a["node_uuid"] for r in cross_b)


async def test_rebuild_all_active_memories(graph_service, vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    await graph_service.create_memory(
        parent_path="",
        content="Active memory about space exploration and Mars missions.",
        priority=3,
        title="space_active",
        disclosure="When discussing space",
    )

    indexed = await vector_indexer.rebuild_all()
    assert indexed >= 1

    results = await vector_indexer.search("Mars exploration", limit=5)
    uris = {r["uri"] for r in results}
    assert "core://space_active" in uris


async def test_delete_embeddings_then_search_empty(graph_service, vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    await graph_service.create_memory(
        parent_path="",
        content="Temporary grocery list: milk, eggs, bread.",
        priority=5,
        title="grocery_temp",
        disclosure="When going shopping",
    )
    mem = await graph_service.get_memory_by_path("grocery_temp", "core")

    await vector_indexer.index_memory(
        node_uuid=mem["node_uuid"], namespace="",
        source_memory_id=mem["id"], domain="core", path="grocery_temp",
        source_type="active_memory", source_text=mem["content"],
    )

    before = await vector_indexer.search("grocery list", limit=5)
    assert any(r["node_uuid"] == mem["node_uuid"] for r in before)

    await vector_indexer.delete_embeddings_for_node(mem["node_uuid"], namespace="")

    after = await vector_indexer.search("grocery list", limit=5)
    assert not any(r["node_uuid"] == mem["node_uuid"] for r in after)


async def test_search_empty_without_embeddings(vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    results = await vector_indexer.search("anything", limit=5)
    assert results == []


async def test_delete_orphan_embeddings(graph_service, vector_indexer):
    dummy = DummyEmbeddingProvider(dimensions=128)
    vector_indexer._embedding_provider = dummy

    await graph_service.create_memory(
        parent_path="",
        content="Orphan target note to be removed.",
        priority=5,
        title="orphan_note",
        disclosure="When testing orphans",
    )
    mem = await graph_service.get_memory_by_path("orphan_note", "core")

    await vector_indexer.index_memory(
        node_uuid=mem["node_uuid"], namespace="",
        source_memory_id=mem["id"], domain="core", path="orphan_note",
        source_type="active_memory", source_text=mem["content"],
    )

    await graph_service.remove_path("orphan_note", "core")

    deleted = await vector_indexer.delete_orphan_embeddings()
    assert deleted >= 1

    results = await vector_indexer.search("orphan target", limit=5)
    assert not any(r["node_uuid"] == mem["node_uuid"] for r in results)
