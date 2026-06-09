import uuid

import pytest
import pytest_asyncio


class TestValidSources:
    async def test_valid_source_single(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Content for validation test.",
            priority=5, title="validate_me", disclosure="test",
        )

        sources = [{
            "node_uuid": mem["node_uuid"],
            "memory_id": mem["id"],
        }]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["total"] == 1
        assert result["summary"]["valid_count"] == 1
        assert result["summary"]["rejected_count"] == 0
        assert result["summary"]["stale_count"] == 0

        v = result["valid"][0]
        assert v["node_uuid"] == mem["node_uuid"]
        assert v["memory_id"] == mem["id"]
        assert v["domain"] == "core"
        assert v["path"] == "validate_me"
        assert v["uri"] == "core://validate_me"
        assert v["namespace"] == ""
        assert "Content for validation test." in v["content_snippet"]
        assert v["warning"] is None

    async def test_valid_source_multiple(self, graph_service, source_validator):
        m1 = await graph_service.create_memory(
            parent_path="", content="Mem one.",
            priority=0, title="m1", disclosure="",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Mem two.",
            priority=0, title="m2", disclosure="",
        )
        m3 = await graph_service.create_memory(
            parent_path="", content="Mem three.",
            priority=0, title="m3", disclosure="",
        )

        sources = [
            {"node_uuid": m["node_uuid"], "memory_id": m["id"]}
            for m in [m1, m2, m3]
        ]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["total"] == 3
        assert result["summary"]["valid_count"] == 3
        assert result["summary"]["rejected_count"] == 0
        assert len(result["valid"]) == 3
        assert all(v["namespace"] == "" for v in result["valid"])


class TestRejectedNodeNotFound:
    async def test_node_not_found(self, source_validator):
        fake_uuid = str(uuid.uuid4())
        sources = [{"node_uuid": fake_uuid, "memory_id": 99999}]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["valid_count"] == 0
        assert result["summary"]["rejected_count"] == 1
        r = result["rejected"][0]
        assert r["error_code"] == "NODE_NOT_FOUND"
        assert r["input"]["node_uuid"] == fake_uuid
        assert "not found" in r["reason"].lower()

    async def test_memory_not_found(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Valid node.",
            priority=0, title="valid_node", disclosure="",
        )

        sources = [{"node_uuid": mem["node_uuid"], "memory_id": 999999}]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["rejected_count"] == 1
        r = result["rejected"][0]
        assert r["error_code"] == "MEMORY_NOT_FOUND"

    async def test_memory_node_mismatch(self, graph_service, source_validator):
        m1 = await graph_service.create_memory(
            parent_path="", content="Node A memory.",
            priority=0, title="node_a", disclosure="",
        )
        m2 = await graph_service.create_memory(
            parent_path="", content="Node B memory.",
            priority=0, title="node_b", disclosure="",
        )

        sources = [{"node_uuid": m1["node_uuid"], "memory_id": m2["id"]}]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["rejected_count"] == 1
        r = result["rejected"][0]
        assert r["error_code"] == "MEMORY_NODE_MISMATCH"


class TestStaleSources:
    async def test_stale_deprecated_memory(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Original.",
            priority=0, title="versioned", disclosure="",
        )
        old_id = mem["id"]
        node_uuid = mem["node_uuid"]

        updated = await graph_service.update_memory(
            path="versioned", domain="core",
            content="Updated content.",
        )
        assert updated["old_memory_id"] == old_id

        sources = [{"node_uuid": node_uuid, "memory_id": old_id}]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["stale_count"] == 1
        assert result["summary"]["valid_count"] == 0
        s = result["stale"][0]
        assert s["node_uuid"] == node_uuid
        assert s["memory_id"] == old_id
        assert s["stale_reason"] == "memory_migrated"
        assert s["migrated_to"] == updated["new_memory_id"]

    async def test_deprecated_no_successor(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Orphan deprecation.",
            priority=0, title="orphan_mem", disclosure="",
        )

        from sqlalchemy import text
        from db import get_db_manager
        db = get_db_manager()
        async with db.session() as s:
            await s.execute(
                text("UPDATE memories SET deprecated = 1 WHERE id = :id"),
                {"id": mem["id"]},
            )

        sources = [{"node_uuid": mem["node_uuid"], "memory_id": mem["id"]}]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["rejected_count"] == 1
        r = result["rejected"][0]
        assert r["error_code"] == "NO_ACTIVE_SUCCESSOR"


class TestNamespaceChecks:
    async def test_wrong_namespace(self, graph_service, source_validator):
        from db import set_namespace

        set_namespace("ns_alpha")
        mem = await graph_service.create_memory(
            parent_path="", content="Alpha namespace memory.",
            priority=0, title="alpha_mem", disclosure="",
            namespace="ns_alpha",
        )

        sources = [{"node_uuid": mem["node_uuid"], "memory_id": mem["id"]}]
        result = await source_validator.validate(sources, namespace="ns_beta")

        assert result["summary"]["rejected_count"] == 1
        r = result["rejected"][0]
        assert r["error_code"] == "NAMESPACE_MISMATCH"


class TestSnapshotAndWarnings:
    async def test_db_derived_snapshot(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Snapshot test.",
            priority=0, title="snap_mem", disclosure="",
        )

        sources = [{"node_uuid": mem["node_uuid"], "memory_id": mem["id"]}]
        result = await source_validator.validate(sources, namespace="")

        v = result["valid"][0]
        assert v["domain"] == "core"
        assert v["path"] == "snap_mem"
        assert v["uri"] == "core://snap_mem"
        assert v["caller_provided"]["domain"] is None
        assert v["caller_provided"]["path"] is None
        assert v["caller_provided"]["uri"] is None

    async def test_caller_uri_diverges(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Divergence test.",
            priority=0, title="div_mem", disclosure="",
        )

        sources = [{
            "node_uuid": mem["node_uuid"],
            "memory_id": mem["id"],
            "uri": "core://wrong/path",
        }]
        result = await source_validator.validate(sources, namespace="")

        v = result["valid"][0]
        assert v["uri"] == "core://div_mem"
        assert v["warning"] is not None
        assert "differs" in v["warning"]
        assert "wrong/path" in v["warning"]

    async def test_caller_uri_matches_no_warning(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="Match test.",
            priority=0, title="match_mem", disclosure="",
        )

        sources = [{
            "node_uuid": mem["node_uuid"],
            "memory_id": mem["id"],
            "domain": "core",
            "path": "match_mem",
            "uri": "core://match_mem",
        }]
        result = await source_validator.validate(sources, namespace="")

        v = result["valid"][0]
        assert v["warning"] is None


class TestRejectedBatch:
    async def test_all_rejected(self, source_validator):
        fake_uuid = str(uuid.uuid4())
        sources = [
            {"node_uuid": fake_uuid, "memory_id": 1},
            {"node_uuid": fake_uuid, "memory_id": 2},
        ]
        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["total"] == 2
        assert result["summary"]["valid_count"] == 0
        assert result["summary"]["rejected_count"] == 2
        assert len(result["valid"]) == 0
        assert len(result["rejected"]) == 2
        assert all(r["error_code"] == "NODE_NOT_FOUND"
                   for r in result["rejected"])


class TestMixedCategories:
    async def test_mixed_valid_rejected_stale(self, graph_service, source_validator):
        mem_valid = await graph_service.create_memory(
            parent_path="", content="Valid memory.",
            priority=0, title="valid_mem", disclosure="",
        )
        mem_versioned = await graph_service.create_memory(
            parent_path="", content="Versionable.",
            priority=0, title="vers_mem", disclosure="",
        )
        old_id = mem_versioned["id"]
        vers_node = mem_versioned["node_uuid"]
        await graph_service.update_memory(
            path="vers_mem", domain="core",
            content="New version.",
        )

        fake_uuid = str(uuid.uuid4())

        sources = [
            {"node_uuid": mem_valid["node_uuid"],
             "memory_id": mem_valid["id"]},
            {"node_uuid": fake_uuid, "memory_id": 99999},
            {"node_uuid": vers_node, "memory_id": old_id},
        ]

        result = await source_validator.validate(sources, namespace="")

        assert result["summary"]["valid_count"] == 1
        assert result["summary"]["rejected_count"] == 1
        assert result["summary"]["stale_count"] == 1

        assert result["valid"][0]["node_uuid"] == mem_valid["node_uuid"]
        assert result["rejected"][0]["error_code"] == "NODE_NOT_FOUND"
        assert result["stale"][0]["stale_reason"] == "memory_migrated"


class TestNoSideEffects:
    async def test_no_side_effects(self, graph_service, source_validator):
        mem = await graph_service.create_memory(
            parent_path="", content="No side effects.",
            priority=0, title="nse_mem", disclosure="",
        )

        before = await graph_service.get_memory_by_path("nse_mem", "core")
        sources = [{"node_uuid": mem["node_uuid"], "memory_id": mem["id"]}]
        await source_validator.validate(sources, namespace="")
        after = await graph_service.get_memory_by_path("nse_mem", "core")

        assert before["id"] == after["id"]
        assert before["content"] == after["content"]
        assert before["deprecated"] == after["deprecated"]
        assert before["node_uuid"] == after["node_uuid"]


class TestEmptySources:
    async def test_empty_sources(self, source_validator):
        result = await source_validator.validate([], namespace="")

        assert result["valid"] == []
        assert result["rejected"] == []
        assert result["stale"] == []
        assert result["summary"]["total"] == 0
        assert result["summary"]["valid_count"] == 0
        assert result["summary"]["rejected_count"] == 0
        assert result["summary"]["stale_count"] == 0


class TestCreateCompatibility:
    async def test_valid_output_compatible_with_create(
        self, graph_service, source_validator, remote_summary_service,
        vector_indexer,
    ):
        from db.vector_index import DummyEmbeddingProvider
        vector_indexer._embedding_provider = DummyEmbeddingProvider(dimensions=128)

        mem = await graph_service.create_memory(
            parent_path="", content="Compatible source.",
            priority=0, title="compat_mem", disclosure="",
        )

        sources = [{
            "node_uuid": mem["node_uuid"],
            "memory_id": mem["id"],
        }]
        validation = await source_validator.validate(sources, namespace="")

        assert validation["summary"]["valid_count"] == 1
        validated_source = validation["valid"][0]

        batch = await remote_summary_service.create(
            namespace="",
            domain="core",
            title="Compatibility Test",
            summary_text="Created from validated source.",
            summary_model="test-model",
            sources=[validated_source],
        )

        assert batch["status"] == "active"
        assert batch["source_count"] == 1

        stored = await remote_summary_service.get_sources(batch["id"])
        assert len(stored) == 1
        assert stored[0]["source_node_uuid"] == mem["node_uuid"]
        assert stored[0]["source_memory_id"] == mem["id"]
        assert stored[0]["source_uri"] == "core://compat_mem"
