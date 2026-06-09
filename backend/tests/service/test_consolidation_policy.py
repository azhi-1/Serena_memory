"""Tests for Phase 6B consolidation policy: coverage, stale detection, plan."""
import uuid

from db.vector_index import DummyEmbeddingProvider
from sqlalchemy import text


async def _create_summary(service, vi, namespace, domain, title, sources):
    """Helper: create a remote summary batch with given sources."""
    vi._embedding_provider = DummyEmbeddingProvider(dimensions=128)
    return await service.create(
        namespace=namespace,
        domain=domain,
        title=title,
        summary_text=f"Summary: {title}",
        summary_model="test",
        sources=sources,
    )


class TestCoverageStats:
    async def test_basic_coverage(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m1 = await graph_service.create_memory(
            parent_path="", content="Mem 1.", priority=0,
            title="cov_m1", disclosure="test",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Mem 2.", priority=1,
            title="cov_m2", disclosure="test",
        )

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Partial Coverage",
            [{"node_uuid": m1["node_uuid"], "memory_id": m1["id"],
              "domain": "core", "path": "cov_m1", "uri": "core://cov_m1"}],
        )

        stats = await remote_summary_service.get_coverage_stats(
            namespace="", domain="core",
        )
        assert stats["total_active"] >= 2
        assert stats["covered"] >= 1
        assert stats["uncovered"] >= 1

    async def test_coverage_empty_domain(self, remote_summary_service):
        stats = await remote_summary_service.get_coverage_stats(
            namespace="", domain="writer",
        )
        assert stats["total_active"] == 0
        assert stats["covered"] == 0
        assert stats["uncovered"] == 0

    async def test_coverage_with_path_prefix(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m1 = await graph_service.create_memory(
            parent_path="", content="Root mem.", priority=0,
            title="root_mem", disclosure="test",
        )
        parent = await graph_service.create_memory(
            parent_path="", content="Parent.", priority=0,
            title="sub_parent", disclosure="test",
        )
        child = await graph_service.create_memory(
            parent_path="sub_parent", content="Child mem.", priority=0,
            title="child_mem", disclosure="test",
        )

        stats_sub = await remote_summary_service.get_coverage_stats(
            namespace="", domain="core", path_prefix="sub_parent",
        )
        assert stats_sub["total_active"] >= 1

        stats_root = await remote_summary_service.get_coverage_stats(
            namespace="", domain="core",
        )
        assert stats_root["total_active"] > stats_sub["total_active"]


class TestUncoveredCandidates:
    async def test_basic_uncovered(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m1 = await graph_service.create_memory(
            parent_path="", content="Uncovered.", priority=2,
            title="unc_m1", disclosure="when testing",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Covered.", priority=5,
            title="unc_m2", disclosure="when testing",
        )

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Cover m2",
            [{"node_uuid": m2["node_uuid"], "memory_id": m2["id"],
              "domain": "core", "path": "unc_m2", "uri": "core://unc_m2"}],
        )

        candidates = await remote_summary_service.get_uncovered_candidates(
            namespace="", domain="core",
        )
        candidate_mids = [c["memory_id"] for c in candidates]
        assert m1["id"] in candidate_mids
        assert m2["id"] not in candidate_mids

    async def test_priority_sort(
        self, graph_service, remote_summary_service,
    ):
        await graph_service.create_memory(
            parent_path="", content="Low priority.", priority=10,
            title="ps_low", disclosure="test",
        )
        await graph_service.create_memory(
            parent_path="", content="High priority.", priority=0,
            title="ps_high", disclosure="test",
        )

        candidates = await remote_summary_service.get_uncovered_candidates(
            namespace="", domain="core",
        )
        priorities = [c["priority"] for c in candidates]
        assert priorities == sorted(priorities)

    async def test_limit(self, graph_service, remote_summary_service):
        for i in range(5):
            await graph_service.create_memory(
                parent_path="", content=f"Limit test {i}.", priority=i,
                title=f"lim_{i}", disclosure="test",
            )

        candidates = await remote_summary_service.get_uncovered_candidates(
            namespace="", domain="core", limit=3,
        )
        assert len(candidates) == 3

    async def test_uri_field(self, graph_service, remote_summary_service):
        await graph_service.create_memory(
            parent_path="", content="URI check.", priority=0,
            title="uri_chk", disclosure="test",
        )
        candidates = await remote_summary_service.get_uncovered_candidates(
            namespace="", domain="core",
        )
        match = [c for c in candidates if c["path"] == "uri_chk"]
        assert len(match) == 1
        assert match[0]["uri"] == "core://uri_chk"


class TestStaleBatches:
    async def test_no_stale(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m = await graph_service.create_memory(
            parent_path="", content="Fresh.", priority=0,
            title="fresh_m", disclosure="test",
        )
        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Fresh Summary",
            [{"node_uuid": m["node_uuid"], "memory_id": m["id"],
              "domain": "core", "path": "fresh_m", "uri": "core://fresh_m"}],
        )

        stale = await remote_summary_service.get_stale_batches(
            namespace="", domain="core",
        )
        assert len(stale) == 0

    async def test_stale_after_update(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m = await graph_service.create_memory(
            parent_path="", content="Before update.", priority=0,
            title="stale_m", disclosure="test",
        )
        old_id = m["id"]

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Will Be Stale",
            [{"node_uuid": m["node_uuid"], "memory_id": old_id,
              "domain": "core", "path": "stale_m", "uri": "core://stale_m"}],
        )

        await graph_service.update_memory(
            path="stale_m", domain="core",
            content="After update.",
        )

        stale = await remote_summary_service.get_stale_batches(
            namespace="", domain="core",
        )
        assert len(stale) == 1
        assert stale[0]["title"] == "Will Be Stale"
        assert stale[0]["issues_count"] == 1

    async def test_stale_domain_filter(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m = await graph_service.create_memory(
            parent_path="", content="Core mem.", priority=0,
            title="dom_stale", disclosure="test",
        )
        old_id = m["id"]

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Core Stale",
            [{"node_uuid": m["node_uuid"], "memory_id": old_id,
              "domain": "core", "path": "dom_stale", "uri": "core://dom_stale"}],
        )

        await graph_service.update_memory(
            path="dom_stale", domain="core",
            content="Updated.",
        )

        stale_core = await remote_summary_service.get_stale_batches(
            namespace="", domain="core",
        )
        stale_writer = await remote_summary_service.get_stale_batches(
            namespace="", domain="writer",
        )
        assert len(stale_core) == 1
        assert len(stale_writer) == 0


class TestBatchSourceStatuses:
    async def test_all_current(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m = await graph_service.create_memory(
            parent_path="", content="Current.", priority=0,
            title="bss_current", disclosure="test",
        )
        batch = await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "All Current",
            [{"node_uuid": m["node_uuid"], "memory_id": m["id"],
              "domain": "core", "path": "bss_current", "uri": "core://bss_current"}],
        )

        b, sources = await remote_summary_service.get_batch_source_statuses(
            batch_id=batch["id"], namespace="",
        )
        assert b is not None
        assert len(sources) == 1
        assert sources[0]["source_status"] == "current"

    async def test_mixed_statuses(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m1 = await graph_service.create_memory(
            parent_path="", content="Stay current.", priority=0,
            title="bss_ok", disclosure="test",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Will deprecate.", priority=0,
            title="bss_old", disclosure="test",
        )
        old_m2_id = m2["id"]

        batch = await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Mixed",
            [
                {"node_uuid": m1["node_uuid"], "memory_id": m1["id"],
                 "domain": "core", "path": "bss_ok", "uri": "core://bss_ok"},
                {"node_uuid": m2["node_uuid"], "memory_id": old_m2_id,
                 "domain": "core", "path": "bss_old", "uri": "core://bss_old"},
            ],
        )

        await graph_service.update_memory(
            path="bss_old", domain="core",
            content="Updated content.",
        )

        b, sources = await remote_summary_service.get_batch_source_statuses(
            batch_id=batch["id"], namespace="",
        )
        statuses = {s["source_status"] for s in sources}
        assert "current" in statuses
        assert "stale" in statuses

    async def test_not_found(self, remote_summary_service):
        b, sources = await remote_summary_service.get_batch_source_statuses(
            batch_id="nonexistent", namespace="",
        )
        assert b is None
        assert sources == []


class TestPlanConsolidation:
    async def test_basic_plan(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m1 = await graph_service.create_memory(
            parent_path="", content="Plan mem 1.", priority=0,
            title="plan_m1", disclosure="test",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Plan mem 2.", priority=1,
            title="plan_m2", disclosure="test",
        )

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Plan Summary",
            [{"node_uuid": m1["node_uuid"], "memory_id": m1["id"],
              "domain": "core", "path": "plan_m1", "uri": "core://plan_m1"}],
        )

        plan = await remote_summary_service.plan_consolidation(
            namespace="", domain="core",
        )

        assert plan["domain"] == "core"
        assert plan["coverage"]["covered"] >= 1
        assert plan["coverage"]["uncovered"] >= 1
        assert len(plan["uncovered"]) >= 1
        uncov_mids = [u["memory_id"] for u in plan["uncovered"]]
        assert m2["id"] in uncov_mids
        assert len(plan["stale_batches"]) == 0
        assert len(plan["current_batches"]) >= 1

    async def test_plan_with_stale(
        self, graph_service, remote_summary_service, vector_indexer,
    ):
        m = await graph_service.create_memory(
            parent_path="", content="Plan stale.", priority=0,
            title="plan_stale_m", disclosure="test",
        )
        old_id = m["id"]

        await _create_summary(
            remote_summary_service, vector_indexer, "", "core",
            "Stale Plan Summary",
            [{"node_uuid": m["node_uuid"], "memory_id": old_id,
              "domain": "core", "path": "plan_stale_m",
              "uri": "core://plan_stale_m"}],
        )

        await graph_service.update_memory(
            path="plan_stale_m", domain="core",
            content="Plan stale updated.",
        )

        plan = await remote_summary_service.plan_consolidation(
            namespace="", domain="core",
        )

        assert len(plan["stale_batches"]) == 1
        batch_id = plan["stale_batches"][0]["id"]
        assert batch_id in plan["stale_source_details"]
        details = plan["stale_source_details"][batch_id]
        statuses = {d["source_status"] for d in details}
        assert "stale" in statuses

    async def test_plan_empty_domain(self, remote_summary_service):
        plan = await remote_summary_service.plan_consolidation(
            namespace="", domain="writer",
        )
        assert plan["coverage"]["total_active"] == 0
        assert plan["uncovered"] == []
        assert plan["stale_batches"] == []
        assert plan["current_batches"] == []
