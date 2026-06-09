"""Tests for Phase 6B MCP consolidation tools."""
from db.vector_index import DummyEmbeddingProvider


async def test_list_remote_summaries_empty(mcp_module):
    result = await mcp_module.list_remote_summaries(domain="core")
    assert "No active remote summaries" in result


async def test_list_remote_summaries_basic(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="List test.", priority=0,
        title="list_src", disclosure="test",
    )
    await mcp_module.create_remote_summary(
        title="List Test Batch",
        summary_text="A batch for listing.",
        source_uris=["core://list_src"],
    )

    result = await mcp_module.list_remote_summaries(domain="core")
    assert "REMOTE SUMMARIES" in result
    assert "List Test Batch" in result
    assert "1 batch(es) shown" in result


async def test_list_remote_summaries_domain_filter(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Core batch.", priority=0,
        title="core_list_src", disclosure="test",
    )
    await mcp_module.create_remote_summary(
        title="Core Batch",
        summary_text="Core only.",
        source_uris=["core://core_list_src"],
    )

    result_writer = await mcp_module.list_remote_summaries(domain="writer")
    assert "No active remote summaries" in result_writer

    result_core = await mcp_module.list_remote_summaries(domain="core")
    assert "Core Batch" in result_core


async def test_inspect_batch_not_found(mcp_module):
    result = await mcp_module.inspect_remote_summary_batch("nonexistent_id")
    assert "Error" in result
    assert "found" in result.lower()


async def test_inspect_batch_basic(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Inspect batch src.", priority=0,
        title="insp_batch_src", disclosure="test",
    )
    create_result = await mcp_module.create_remote_summary(
        title="Inspect Batch Title",
        summary_text="Detailed summary for inspection.",
        source_uris=["core://insp_batch_src"],
    )

    batch_id_line = [l for l in create_result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()

    result = await mcp_module.inspect_remote_summary_batch(batch_id)
    assert "REMOTE SUMMARY BATCH" in result
    assert "Inspect Batch Title" in result
    assert "Detailed summary for inspection." in result
    assert "[current]" in result
    assert "insp_batch_src" in result


async def test_inspect_batch_with_stale(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Will go stale.", priority=0,
        title="insp_stale_src", disclosure="test",
    )
    create_result = await mcp_module.create_remote_summary(
        title="Stale Inspect",
        summary_text="Will have stale source.",
        source_uris=["core://insp_stale_src"],
    )

    batch_id_line = [l for l in create_result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()

    await graph_service.update_memory(
        path="insp_stale_src", domain="core",
        content="Updated content.",
    )

    result = await mcp_module.inspect_remote_summary_batch(batch_id)
    assert "[stale]" in result


async def test_plan_consolidation_basic(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Plan target 1.", priority=0,
        title="plan_t1", disclosure="test",
    )
    await graph_service.create_memory(
        parent_path="", content="Plan target 2.", priority=1,
        title="plan_t2", disclosure="test",
    )

    result = await mcp_module.plan_consolidation(domain="core")
    assert "CONSOLIDATION PLAN" in result
    assert "COVERAGE:" in result
    assert "UNCOVERED CANDIDATES" in result
    assert "plan_t1" in result or "plan_t2" in result


async def test_plan_consolidation_shows_stale(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Plan stale src.", priority=0,
        title="plan_stale", disclosure="test",
    )
    await mcp_module.create_remote_summary(
        title="Plan Stale Batch",
        summary_text="Will be stale.",
        source_uris=["core://plan_stale"],
    )

    await graph_service.update_memory(
        path="plan_stale", domain="core",
        content="Plan stale updated.",
    )

    result = await mcp_module.plan_consolidation(domain="core")
    assert "STALE SUMMARIES" in result
    assert "Plan Stale Batch" in result


async def test_plan_consolidation_all_covered(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Covered.", priority=0,
        title="all_cov", disclosure="test",
    )
    await mcp_module.create_remote_summary(
        title="Full Coverage",
        summary_text="Everything is covered.",
        source_uris=["core://all_cov"],
    )

    result = await mcp_module.plan_consolidation(domain="core")
    assert "CONSOLIDATION PLAN" in result


async def test_supersede_basic(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Supersede source.", priority=0,
        title="sup_src", disclosure="test",
    )
    create_result = await mcp_module.create_remote_summary(
        title="Supersede Target",
        summary_text="This will be superseded.",
        source_uris=["core://sup_src"],
    )

    batch_id_line = [l for l in create_result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()

    result = await mcp_module.supersede_remote_summary(batch_id)
    assert "superseded" in result.lower()
    assert batch_id in result

    list_result = await mcp_module.list_remote_summaries(domain="core")
    assert batch_id[:12] not in list_result


async def test_supersede_idempotent(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Idem source.", priority=0,
        title="idem_src", disclosure="test",
    )
    create_result = await mcp_module.create_remote_summary(
        title="Idem Target",
        summary_text="Idempotent test.",
        source_uris=["core://idem_src"],
    )

    batch_id_line = [l for l in create_result.split("\n") if "Batch ID:" in l][0]
    batch_id = batch_id_line.split("Batch ID:")[1].strip()

    await mcp_module.supersede_remote_summary(batch_id)
    result = await mcp_module.supersede_remote_summary(batch_id)
    assert "already superseded" in result.lower()


async def test_supersede_not_found(mcp_module):
    result = await mcp_module.supersede_remote_summary("fake_id")
    assert "Error" in result
    assert "found" in result.lower()


async def test_plan_supersede_create_recall_roundtrip(
    mcp_module, graph_service, vector_indexer,
):
    vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

    await graph_service.create_memory(
        parent_path="", content="Roundtrip source A.", priority=0,
        title="rt6_a", disclosure="test",
    )
    await graph_service.create_memory(
        parent_path="", content="Roundtrip source B.", priority=1,
        title="rt6_b", disclosure="test",
    )

    create_result = await mcp_module.create_remote_summary(
        title="Old Summary",
        summary_text="Old content.",
        source_uris=["core://rt6_a"],
    )
    batch_id_line = [l for l in create_result.split("\n") if "Batch ID:" in l][0]
    old_batch_id = batch_id_line.split("Batch ID:")[1].strip()

    await graph_service.update_memory(
        path="rt6_a", domain="core",
        content="Roundtrip source A updated.",
    )

    plan_result = await mcp_module.plan_consolidation(domain="core")
    assert "STALE SUMMARIES" in plan_result

    await mcp_module.supersede_remote_summary(old_batch_id)

    create2 = await mcp_module.create_remote_summary(
        title="New Summary",
        summary_text="Fresh content covering both sources.",
        source_uris=["core://rt6_a", "core://rt6_b"],
    )
    assert "Remote summary created successfully" in create2

    recall = await mcp_module.recall_memory("roundtrip")
    assert "[REMOTE]" in recall
    assert "New Summary" in recall


async def test_mcp_tool_count_phase6(mcp_module):
    tools = list(mcp_module.mcp._tool_manager._tools.keys())
    for name in [
        "list_remote_summaries",
        "inspect_remote_summary_batch",
        "plan_consolidation",
        "supersede_remote_summary",
    ]:
        assert name in tools, f"Missing MCP tool: {name}"
