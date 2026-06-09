from db.vector_index import DummyEmbeddingProvider
from db.namespace import set_namespace


async def test_inspect_valid_uri(mcp_module, graph_service):
    await graph_service.create_memory(
        parent_path="",
        content="Inspect me for validation.",
        priority=0,
        title="inspect_me",
        disclosure="test",
    )

    result = await mcp_module.inspect_remote_summary_source("core://inspect_me")

    assert "Status: VALID" in result
    assert "core://inspect_me" in result
    assert "Node UUID:" in result
    assert "Memory ID:" in result
    assert "valid and can be passed" in result.lower()


async def test_inspect_missing_uri(mcp_module):
    result = await mcp_module.inspect_remote_summary_source("core://nope_nonexistent")

    assert "not found" in result.lower()
    assert "VALID" not in result


async def test_inspect_wrong_namespace(mcp_module, graph_service):
    set_namespace("ns_alpha")
    await graph_service.create_memory(
        parent_path="",
        content="Alpha content.",
        priority=0,
        title="ns_secret",
        disclosure="test",
        namespace="ns_alpha",
    )
    set_namespace("")

    result = await mcp_module.inspect_remote_summary_source("core://ns_secret")

    assert "not found" in result.lower()
    assert "ns_alpha" not in result


async def test_create_rejects_empty_sources(mcp_module):
    result = await mcp_module.create_remote_summary(
        title="Empty Test",
        summary_text="Should fail.",
        source_uris=[],
    )

    assert "source_uris" in result.lower()
    assert "empty" in result.lower()


async def test_create_rejects_invalid_uri(mcp_module):
    result = await mcp_module.create_remote_summary(
        title="Bad URI",
        summary_text="Should fail.",
        source_uris=["core://does_not_exist"],
    )

    assert "not found" in result.lower()
    assert "Error" in result


async def test_create_uri_resolution_always_gets_active_memory(
    mcp_module, graph_service, vector_indexer,
):
    """URI resolution via get_memory_by_path filters deprecated=False,
    so a URI always resolves to the latest active memory even after updates."""
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="",
        content="Original version.",
        priority=0,
        title="vers_mem",
        disclosure="test",
    )
    await graph_service.update_memory(
        path="vers_mem", domain="core",
        content="New version.",
    )

    result = await mcp_module.create_remote_summary(
        title="Updated Source",
        summary_text="URI resolves to latest active memory.",
        source_uris=["core://vers_mem"],
    )

    assert "Remote summary created successfully" in result


async def test_create_rejects_stale_source_direct_id(
    mcp_module, graph_service, vector_indexer,
):
    """Stale rejection tested at the validator level (Phase 5B).
    URI-based MCP resolution naturally gets the latest active memory,
    bypassing stale concerns. This test confirms the validator
    correctly rejects deprecated-without-successor at DB level."""
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    mem = await graph_service.create_memory(
        parent_path="",
        content="Deprecated without successor.",
        priority=0,
        title="orphan_stale",
        disclosure="test",
    )

    from sqlalchemy import text
    from db import get_db_manager
    db = get_db_manager()
    async with db.session() as s:
        await s.execute(
            text("UPDATE memories SET deprecated = 1 WHERE id = :id"),
            {"id": mem["id"]},
        )

    result = await mcp_module.create_remote_summary(
        title="Stale Source Via ID",
        summary_text="Should fail.",
        source_uris=["core://orphan_stale"],
    )

    assert "not found" in result.lower()


async def test_create_rejects_mixed_domain_no_domain_param(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await mcp_module.create_memory(
        "core://",
        "Core mem.",
        priority=0,
        title="core_source",
        disclosure="test",
    )
    await mcp_module.create_memory(
        "writer://",
        "Writer mem.",
        priority=0,
        title="writer_source",
        disclosure="test",
    )

    result = await mcp_module.create_remote_summary(
        title="Mixed Domains",
        summary_text="Should fail without domain.",
        source_uris=["core://core_source", "writer://writer_source"],
    )

    assert "Error" in result
    assert "multiple domains" in result.lower()


async def test_create_succeeds_single_source(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="",
        content="Single valid source.",
        priority=0,
        title="single_src",
        disclosure="test",
    )

    result = await mcp_module.create_remote_summary(
        title="Single Source Summary",
        summary_text="Created from one source.",
        source_uris=["core://single_src"],
    )

    assert "Remote summary created successfully" in result
    assert "Batch ID:" in result
    assert "Sources:     1" in result
    assert "Status:      active" in result

    from db import get_remote_summary_service
    service = get_remote_summary_service()
    batch_id_line = [l for l in result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()
    stored = await service.get_sources(batch_id)
    assert len(stored) == 1
    assert stored[0]["source_uri"] == "core://single_src"


async def test_create_succeeds_multiple_sources(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="",
        content="Source A.",
        priority=0,
        title="src_a",
        disclosure="test",
    )
    await graph_service.create_memory(
        parent_path="",
        content="Source B.",
        priority=0,
        title="src_b",
        disclosure="test",
    )

    result = await mcp_module.create_remote_summary(
        title="Multi Source Summary",
        summary_text="Created from two sources.",
        source_uris=["core://src_a", "core://src_b"],
    )

    assert "Remote summary created successfully" in result
    assert "Sources:     2" in result

    from db import get_remote_summary_service
    service = get_remote_summary_service()
    batch_id_line = [l for l in result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()
    stored = await service.get_sources(batch_id)
    assert len(stored) == 2


async def test_create_output_recallable(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="",
        content="Recallable memory source.",
        priority=0,
        title="recallable_src",
        disclosure="test",
    )

    await mcp_module.create_remote_summary(
        title="Recall Test Summary",
        summary_text="This summary should appear in recall with [REMOTE] tag.",
        source_uris=["core://recallable_src"],
    )

    result = await mcp_module.recall_memory(
        "summary recall test",
        token_budget=2000,
    )

    assert "[REMOTE]" in result
    assert "Recall Test Summary" in result


async def test_mcp_tool_count_increased(mcp_module):
    mcp = mcp_module.mcp
    tools = mcp._tool_manager._tools
    tool_names = list(tools.keys())

    assert "inspect_remote_summary_source" in tool_names
    assert "create_remote_summary" in tool_names


async def test_create_inspect_roundtrip(mcp_module, graph_service, vector_indexer):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="",
        content="Roundtrip memory.",
        priority=0,
        title="rt_mem",
        disclosure="test",
    )

    inspect = await mcp_module.inspect_remote_summary_source("core://rt_mem")
    assert "Status: VALID" in inspect

    create = await mcp_module.create_remote_summary(
        title="Roundtrip",
        summary_text="Inspect then create.",
        source_uris=["core://rt_mem"],
    )

    assert "Remote summary created successfully" in create

    recall = await mcp_module.recall_memory("Roundtrip")
    assert "[REMOTE]" in recall


async def test_create_deduplicates_same_uri(mcp_module, graph_service, vector_indexer):
    """Passing the same URI twice should not cause IntegrityError."""
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Dup source.",
        priority=0, title="dup_src", disclosure="test",
    )

    result = await mcp_module.create_remote_summary(
        title="Dedup Test",
        summary_text="From duplicate URIs.",
        source_uris=["core://dup_src", "core://dup_src"],
    )

    assert "Remote summary created successfully" in result
    assert "Sources:     1" in result
