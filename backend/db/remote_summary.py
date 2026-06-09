"""
Remote Summary Service — settled long-term memory summaries.

Manages remote_summary_batches and remote_summary_sources tables.
All writes are transactional. Embeddings are indexed via VectorIndexer.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    RemoteSummaryBatch,
    RemoteSummarySource,
    Node,
    Memory,
    Path,
)

if TYPE_CHECKING:
    from .database import DatabaseManager
    from .vector_index import VectorIndexer
    from .graph import GraphService

SUMMARY_PATH_PREFIX = "@summary/"


class RemoteSummaryService:

    def __init__(
        self,
        db: "DatabaseManager",
        vector_indexer: "VectorIndexer",
    ):
        self._session = db.session
        self._vector = vector_indexer

    async def create(
        self,
        *,
        namespace: str,
        domain: str,
        title: str,
        summary_text: str,
        summary_model: str,
        sources: list[dict[str, Any]],
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        if not sources:
            raise ValueError("sources must be non-empty")

        batch_id = uuid.uuid4().hex
        source_count = len(sources)

        async def _create(s: AsyncSession) -> dict[str, Any]:
            await s.execute(text(
                "INSERT INTO remote_summary_batches "
                "(id, namespace, domain, title, summary_text, status, "
                " source_count, summary_model) "
                "VALUES (:id, :namespace, :domain, :title, :summary_text, "
                " 'active', :source_count, :summary_model)"
            ), {
                "id": batch_id, "namespace": namespace, "domain": domain,
                "title": title, "summary_text": summary_text,
                "source_count": source_count, "summary_model": summary_model,
            })

            for src in sources:
                await s.execute(text(
                    "INSERT INTO remote_summary_sources "
                    "(batch_id, namespace, source_node_uuid, source_memory_id, "
                    " source_domain, source_path, source_uri) "
                    "VALUES (:batch_id, :namespace, :source_node_uuid, "
                    " :source_memory_id, :source_domain, :source_path, :source_uri)"
                ), {
                    "batch_id": batch_id, "namespace": namespace,
                    "source_node_uuid": src["node_uuid"],
                    "source_memory_id": src["memory_id"],
                    "source_domain": src.get("domain", domain),
                    "source_path": src.get("path", ""),
                    "source_uri": src.get("uri", ""),
                })

            await self._vector.index_memory(
                node_uuid=batch_id,
                namespace=namespace,
                source_memory_id=None,
                domain=domain,
                path=f"{SUMMARY_PATH_PREFIX}{batch_id}",
                source_type="remote_summary",
                source_text=summary_text,
                session=s,
            )

            return {
                "id": batch_id,
                "namespace": namespace,
                "domain": domain,
                "title": title,
                "summary_text": summary_text,
                "status": "active",
                "source_count": source_count,
                "summary_model": summary_model,
            }

        if session:
            return await _create(session)
        else:
            async with self._session() as s:
                return await _create(s)

    async def get_batch(
        self,
        batch_id: str,
        namespace: str = "",
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        async def _get(s: AsyncSession):
            result = await s.execute(text(
                "SELECT * FROM remote_summary_batches "
                "WHERE id = :id AND namespace = :namespace"
            ), {"id": batch_id, "namespace": namespace})
            row = result.mappings().first()
            return dict(row) if row else None

        if session:
            return await _get(session)
        else:
            async with self._session() as s:
                return await _get(s)

    async def list_batches(
        self,
        namespace: str = "",
        domain: str | None = None,
        status: str | None = "active",
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        async def _list(s: AsyncSession):
            sql = "SELECT * FROM remote_summary_batches WHERE namespace = :namespace"
            params: dict[str, Any] = {"namespace": namespace}
            if domain is not None:
                sql += " AND domain = :domain"
                params["domain"] = domain
            if status is not None:
                sql += " AND status = :status"
                params["status"] = status
            sql += " ORDER BY created_at DESC"
            result = await s.execute(text(sql), params)
            return [dict(r) for r in result.mappings().all()]

        if session:
            return await _list(session)
        else:
            async with self._session() as s:
                return await _list(s)

    async def supersede_batch(
        self,
        batch_id: str,
        namespace: str = "",
        session: AsyncSession | None = None,
    ) -> None:
        async def _supersede(s: AsyncSession):
            await s.execute(text(
                "UPDATE remote_summary_batches "
                "SET status = 'superseded', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :id AND namespace = :namespace AND status = 'active'"
            ), {"id": batch_id, "namespace": namespace})

        if session:
            await _supersede(session)
        else:
            async with self._session() as s:
                await _supersede(s)

    async def get_sources(
        self,
        batch_id: str,
        namespace: str = "",
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        async def _get_src(s: AsyncSession):
            result = await s.execute(text(
                "SELECT * FROM remote_summary_sources "
                "WHERE batch_id = :batch_id AND namespace = :namespace"
            ), {"batch_id": batch_id, "namespace": namespace})
            return [dict(r) for r in result.mappings().all()]

        if session:
            return await _get_src(session)
        else:
            async with self._session() as s:
                return await _get_src(s)


    # ------------------------------------------------------------------
    # Phase 6B: coverage tracking, stale detection, consolidation plan
    # ------------------------------------------------------------------

    async def get_coverage_stats(
        self,
        *,
        namespace: str,
        domain: str,
        path_prefix: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, int]:
        async def _do(s: AsyncSession) -> dict[str, int]:
            prefix = (path_prefix or "") + "%"
            result = await s.execute(text(
                "SELECT"
                "  COUNT(DISTINCT m.id) AS total_active,"
                "  COUNT(DISTINCT CASE WHEN covered.mid IS NOT NULL"
                "    THEN m.id END) AS covered,"
                "  COUNT(DISTINCT CASE WHEN covered.mid IS NULL"
                "    THEN m.id END) AS uncovered "
                "FROM paths p "
                "JOIN memories m"
                "  ON m.node_uuid = p.node_uuid AND m.deprecated = 0 "
                "LEFT JOIN ("
                "  SELECT DISTINCT rss.source_memory_id AS mid"
                "  FROM remote_summary_sources rss"
                "  JOIN remote_summary_batches rsb"
                "    ON rsb.id = rss.batch_id"
                "   AND rsb.namespace = rss.namespace"
                "   AND rsb.status = 'active'"
                "  WHERE rss.namespace = :namespace"
                ") covered ON covered.mid = m.id "
                "WHERE p.namespace = :namespace"
                "  AND p.domain = :domain"
                "  AND p.path LIKE :prefix"
            ), {"namespace": namespace, "domain": domain, "prefix": prefix})
            row = result.mappings().first()
            if not row:
                return {"total_active": 0, "covered": 0, "uncovered": 0}
            return {
                "total_active": row["total_active"],
                "covered": row["covered"],
                "uncovered": row["uncovered"],
            }

        if session:
            return await _do(session)
        else:
            async with self._session() as s:
                return await _do(s)

    async def get_uncovered_candidates(
        self,
        *,
        namespace: str,
        domain: str,
        path_prefix: str | None = None,
        limit: int = 10,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        async def _do(s: AsyncSession) -> list[dict[str, Any]]:
            prefix = (path_prefix or "") + "%"
            result = await s.execute(text(
                "SELECT"
                "  p.node_uuid,"
                "  p.path,"
                "  p.domain,"
                "  m.id AS memory_id,"
                "  SUBSTR(m.content, 1, 200) AS content_snippet,"
                "  COALESCE(e.priority, 0) AS priority,"
                "  COALESCE(e.disclosure, '') AS disclosure,"
                "  m.created_at "
                "FROM paths p "
                "JOIN memories m"
                "  ON m.node_uuid = p.node_uuid AND m.deprecated = 0 "
                "LEFT JOIN edges e ON e.id = p.edge_id "
                "WHERE p.namespace = :namespace"
                "  AND p.domain = :domain"
                "  AND p.path LIKE :prefix"
                "  AND m.id NOT IN ("
                "    SELECT DISTINCT rss.source_memory_id"
                "    FROM remote_summary_sources rss"
                "    JOIN remote_summary_batches rsb"
                "      ON rsb.id = rss.batch_id"
                "     AND rsb.namespace = rss.namespace"
                "     AND rsb.status = 'active'"
                "    WHERE rss.namespace = :namespace"
                "  ) "
                "ORDER BY COALESCE(e.priority, 0) ASC, m.created_at DESC "
                "LIMIT :limit"
            ), {"namespace": namespace, "domain": domain,
                "prefix": prefix, "limit": limit})
            rows = result.mappings().all()
            return [
                {
                    "node_uuid": r["node_uuid"],
                    "path": r["path"],
                    "domain": r["domain"],
                    "memory_id": r["memory_id"],
                    "content_snippet": r["content_snippet"],
                    "priority": r["priority"],
                    "disclosure": r["disclosure"],
                    "uri": f"{r['domain']}://{r['path']}",
                }
                for r in rows
            ]

        if session:
            return await _do(session)
        else:
            async with self._session() as s:
                return await _do(s)

    async def get_stale_batches(
        self,
        *,
        namespace: str,
        domain: str | None = None,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        async def _do(s: AsyncSession) -> list[dict[str, Any]]:
            sql = (
                "SELECT rsb.*,"
                "  COUNT(rss.id) AS total_sources,"
                "  SUM(CASE"
                "    WHEN n.uuid IS NULL THEN 1"
                "    WHEN m.id IS NULL THEN 1"
                "    WHEN m.deprecated = 1 THEN 1"
                "    ELSE 0"
                "  END) AS issues_count "
                "FROM remote_summary_batches rsb "
                "JOIN remote_summary_sources rss"
                "  ON rss.batch_id = rsb.id AND rss.namespace = rsb.namespace "
                "LEFT JOIN nodes n ON n.uuid = rss.source_node_uuid "
                "LEFT JOIN memories m ON m.id = rss.source_memory_id "
                "WHERE rsb.namespace = :namespace"
                "  AND rsb.status = 'active'"
            )
            params: dict[str, Any] = {"namespace": namespace}
            if domain is not None:
                sql += " AND rsb.domain = :domain"
                params["domain"] = domain
            sql += " GROUP BY rsb.id HAVING issues_count > 0"
            sql += " ORDER BY issues_count DESC"
            result = await s.execute(text(sql), params)
            return [dict(r) for r in result.mappings().all()]

        if session:
            return await _do(session)
        else:
            async with self._session() as s:
                return await _do(s)

    async def get_batch_source_statuses(
        self,
        *,
        batch_id: str,
        namespace: str,
        session: AsyncSession | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        async def _do(s: AsyncSession) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
            batch_result = await s.execute(text(
                "SELECT * FROM remote_summary_batches "
                "WHERE id = :id AND namespace = :namespace"
            ), {"id": batch_id, "namespace": namespace})
            batch_row = batch_result.mappings().first()
            if not batch_row:
                return None, []

            result = await s.execute(text(
                "SELECT"
                "  rss.*,"
                "  m.deprecated AS mem_deprecated,"
                "  m.migrated_to AS mem_migrated_to,"
                "  CASE"
                "    WHEN n.uuid IS NULL THEN 'node_deleted'"
                "    WHEN m.id IS NULL THEN 'memory_deleted'"
                "    WHEN m.deprecated = 1 AND m.migrated_to IS NOT NULL"
                "      THEN 'stale'"
                "    WHEN m.deprecated = 1 AND m.migrated_to IS NULL"
                "      THEN 'stale_no_successor'"
                "    ELSE 'current'"
                "  END AS source_status "
                "FROM remote_summary_sources rss "
                "LEFT JOIN nodes n ON n.uuid = rss.source_node_uuid "
                "LEFT JOIN memories m ON m.id = rss.source_memory_id "
                "WHERE rss.batch_id = :batch_id"
                "  AND rss.namespace = :namespace"
            ), {"batch_id": batch_id, "namespace": namespace})
            sources = [dict(r) for r in result.mappings().all()]
            return dict(batch_row), sources

        if session:
            return await _do(session)
        else:
            async with self._session() as s:
                return await _do(s)

    async def plan_consolidation(
        self,
        *,
        namespace: str,
        domain: str,
        path_prefix: str = "",
        candidate_limit: int = 10,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        async def _do(s: AsyncSession) -> dict[str, Any]:
            coverage = await self.get_coverage_stats(
                namespace=namespace, domain=domain,
                path_prefix=path_prefix or None, session=s,
            )
            uncovered = await self.get_uncovered_candidates(
                namespace=namespace, domain=domain,
                path_prefix=path_prefix or None,
                limit=candidate_limit, session=s,
            )
            stale = await self.get_stale_batches(
                namespace=namespace, domain=domain, session=s,
            )

            stale_ids = [b["id"] for b in stale]
            current_batches = await self.list_batches(
                namespace=namespace, domain=domain,
                status="active", session=s,
            )
            current_batches = [
                b for b in current_batches if b["id"] not in stale_ids
            ]

            stale_details: dict[str, list[dict[str, Any]]] = {}
            for b in stale:
                _, sources = await self.get_batch_source_statuses(
                    batch_id=b["id"], namespace=namespace, session=s,
                )
                stale_details[b["id"]] = sources

            return {
                "domain": domain,
                "path_prefix": path_prefix,
                "coverage": coverage,
                "uncovered": uncovered,
                "stale_batches": stale,
                "current_batches": current_batches,
                "stale_source_details": stale_details,
            }

        if session:
            return await _do(session)
        else:
            async with self._session() as s:
                return await _do(s)


class RemoteSummarySourceValidator:

    def __init__(self, graph_service: "GraphService"):
        self._graph = graph_service

    async def validate(
        self,
        sources: list[dict[str, Any]],
        namespace: str,
        domain: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        if not sources:
            return {
                "valid": [],
                "rejected": [],
                "stale": [],
                "summary": {
                    "total": 0,
                    "valid_count": 0,
                    "rejected_count": 0,
                    "stale_count": 0,
                },
            }

        unique_node_uuids = list({src["node_uuid"] for src in sources})
        unique_memory_ids = list({src["memory_id"] for src in sources})

        async def _do(s: AsyncSession) -> dict[str, Any]:
            existing_nodes: set[str] = set()
            if unique_node_uuids:
                node_result = await s.execute(
                    select(Node.uuid).where(Node.uuid.in_(unique_node_uuids))
                )
                existing_nodes = {r[0] for r in node_result.all()}

            memory_map: dict[int, Any] = {}
            if unique_memory_ids:
                mem_result = await s.execute(
                    select(
                        Memory.id,
                        Memory.node_uuid,
                        Memory.deprecated,
                        Memory.migrated_to,
                        Memory.content,
                    ).where(Memory.id.in_(unique_memory_ids))
                )
                for r in mem_result.all():
                    memory_map[r[0]] = r

            paths_by_node: dict[str, list[Any]] = {}
            if unique_node_uuids:
                path_result = await s.execute(
                    select(
                        Path.node_uuid,
                        Path.domain,
                        Path.path,
                        Path.namespace,
                    )
                    .where(Path.node_uuid.in_(unique_node_uuids))
                    .where(Path.namespace == namespace)
                )
                for r in path_result.all():
                    node_uuid = r[0]
                    if node_uuid not in paths_by_node:
                        paths_by_node[node_uuid] = []
                    paths_by_node[node_uuid].append(r)

            valid: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            stale: list[dict[str, Any]] = []

            for src in sources:
                nuuid: str = src["node_uuid"]
                mid: int = src["memory_id"]

                if nuuid not in existing_nodes:
                    rejected.append({
                        "input": src,
                        "reason": f"Node {nuuid} not found in database",
                        "error_code": "NODE_NOT_FOUND",
                    })
                    continue

                mem_row = memory_map.get(mid)
                if mem_row is None:
                    rejected.append({
                        "input": src,
                        "reason": f"Memory {mid} not found in database",
                        "error_code": "MEMORY_NOT_FOUND",
                    })
                    continue

                db_memory_id: int = mem_row[0]
                db_node_uuid: str = mem_row[1]
                db_deprecated: bool = bool(mem_row[2])
                db_migrated_to: int | None = mem_row[3]
                db_content: str = mem_row[4] or ""

                if db_node_uuid != nuuid:
                    rejected.append({
                        "input": src,
                        "reason": (
                            f"Memory {mid} belongs to node {db_node_uuid}, "
                            f"not {nuuid}"
                        ),
                        "error_code": "MEMORY_NODE_MISMATCH",
                    })
                    continue

                node_paths = paths_by_node.get(nuuid, [])
                if not node_paths:
                    rejected.append({
                        "input": src,
                        "reason": (
                            f"Node {nuuid} has no paths in "
                            f"namespace {namespace!r}"
                        ),
                        "error_code": "NAMESPACE_MISMATCH",
                    })
                    continue

                if db_deprecated:
                    if db_migrated_to is not None:
                        best_path = node_paths[0]
                        db_domain: str = best_path[1]
                        db_path: str = best_path[2]
                        db_uri: str = f"{db_domain}://{db_path}"

                        stale.append({
                            "node_uuid": nuuid,
                            "memory_id": mid,
                            "domain": db_domain,
                            "path": db_path,
                            "uri": db_uri,
                            "namespace": namespace,
                            "content_snippet": db_content[:200],
                            "caller_provided": {
                                "domain": src.get("domain"),
                                "path": src.get("path"),
                                "uri": src.get("uri"),
                            },
                            "warning": None,
                            "stale_reason": "memory_migrated",
                            "migrated_to": db_migrated_to,
                        })
                    else:
                        rejected.append({
                            "input": src,
                            "reason": (
                                f"Memory {mid} is deprecated with no "
                                f"active successor"
                            ),
                            "error_code": "NO_ACTIVE_SUCCESSOR",
                        })
                    continue

                best_path = node_paths[0]
                db_domain = best_path[1]
                db_path = best_path[2]
                db_uri = f"{db_domain}://{db_path}"

                caller_domain: str | None = src.get("domain")
                caller_path: str | None = src.get("path")
                caller_uri: str | None = src.get("uri")

                warning: str | None = None
                if caller_uri is not None and caller_uri != db_uri:
                    warning = (
                        f"caller uri {caller_uri!r} differs from "
                        f"db uri {db_uri!r}"
                    )
                elif (caller_domain is not None
                        and caller_domain != db_domain):
                    warning = (
                        f"caller domain {caller_domain!r} differs "
                        f"from db domain {db_domain!r}"
                    )
                elif caller_path is not None and caller_path != db_path:
                    warning = (
                        f"caller path {caller_path!r} differs from "
                        f"db path {db_path!r}"
                    )

                valid.append({
                    "node_uuid": nuuid,
                    "memory_id": mid,
                    "domain": db_domain,
                    "path": db_path,
                    "uri": db_uri,
                    "namespace": namespace,
                    "content_snippet": db_content[:200],
                    "caller_provided": {
                        "domain": caller_domain,
                        "path": caller_path,
                        "uri": caller_uri,
                    },
                    "warning": warning,
                })

            return {
                "valid": valid,
                "rejected": rejected,
                "stale": stale,
                "summary": {
                    "total": len(sources),
                    "valid_count": len(valid),
                    "rejected_count": len(rejected),
                    "stale_count": len(stale),
                },
            }

        if session is not None:
            return await _do(session)
        else:
            async with self._graph.session() as s:
                return await _do(s)
