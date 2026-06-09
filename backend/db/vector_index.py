"""
Vector indexer for semantic memory search.

Manages embeddings in the memory_embeddings table with cosine
similarity search performed in Python. No extension dependencies.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Optional, Protocol, TYPE_CHECKING

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Memory, Path


if TYPE_CHECKING:
    from .database import DatabaseManager

DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_EMBEDDING_DIMENSIONS = 4096


class EmbeddingProvider(Protocol):
    async def embed(
        self, texts: list[str], *, dimensions: int | None = None
    ) -> list[list[float]]:
        ...


class DummyEmbeddingProvider:
    """Deterministic dummy for tests — no external API calls."""

    def __init__(self, dimensions: int = 128):
        self._dimensions = dimensions

    async def embed(
        self, texts: list[str], *, dimensions: int | None = None
    ) -> list[list[float]]:
        dim = dimensions or self._dimensions
        vectors: list[list[float]] = []
        for i, text in enumerate(texts):
            seed = hash(text) ^ (i * 0x9E3779B9)
            vec = []
            for j in range(dim):
                seed = (seed * 0x5DEECE66D + 0xB) & 0xFFFFFFFFFFFF
                value = ((seed >> 16) & 0x7FFF) / 32767.0
                vec.append(value)
            total = math.sqrt(sum(v * v for v in vec))
            if total > 0:
                vec = [v / total for v in vec]
            vectors.append(vec)
        return vectors


def _pack_floats(floats: list[float]) -> bytes:
    return struct.pack(f"!{len(floats)}f", *floats)


def _unpack_floats(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"!{count}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(ai * bi for ai, bi in zip(a, b))
    mag_a = math.sqrt(sum(ai * ai for ai in a))
    mag_b = math.sqrt(sum(bi * bi for bi in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    return 1.0 - _cosine_similarity(a, b)


class VectorIndexer:
    """Maintains the memory_embeddings table and runs semantic search."""

    def __init__(
        self,
        db: "DatabaseManager",
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self._session = db.session
        self.db = db
        self._embedding_provider = embedding_provider

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            dims = DEFAULT_EMBEDDING_DIMENSIONS
            try:
                import config as _cfg
                dims = int(_cfg.get("embedding_dimensions") or DEFAULT_EMBEDDING_DIMENSIONS)
            except Exception:
                pass
            self._embedding_provider = DummyEmbeddingProvider(dimensions=dims)
        return self._embedding_provider

    @property
    def embedding_model(self) -> str:
        try:
            import config as _cfg
            return _cfg.get("embedding_model") or DEFAULT_EMBEDDING_MODEL
        except Exception:
            return DEFAULT_EMBEDDING_MODEL

    @property
    def embedding_dimensions(self) -> int:
        try:
            import config as _cfg
            return int(_cfg.get("embedding_dimensions") or DEFAULT_EMBEDDING_DIMENSIONS)
        except Exception:
            return DEFAULT_EMBEDDING_DIMENSIONS

    async def index_memory(
        self,
        *,
        node_uuid: str,
        namespace: str,
        source_memory_id: int | None,
        domain: str,
        path: str,
        source_type: str,
        source_text: str,
        session: AsyncSession | None = None,
    ) -> None:
        model = self.embedding_model
        dimensions = self.embedding_dimensions
        provider = self.embedding_provider

        vectors = await provider.embed([source_text], dimensions=dimensions)
        if not vectors:
            return

        blob = _pack_floats(vectors[0])
        query = text(
            "INSERT OR REPLACE INTO memory_embeddings "
            "(node_uuid, namespace, source_memory_id, domain, path, "
            " source_type, source_text, embedding_model, embedding_dimension, embedding) "
            "VALUES (:node_uuid, :namespace, :source_memory_id, :domain, :path, "
            " :source_type, :source_text, :embedding_model, :embedding_dimension, :embedding)"
        )
        params = {
            "node_uuid": node_uuid, "namespace": namespace,
            "source_memory_id": source_memory_id, "domain": domain, "path": path,
            "source_type": source_type, "source_text": source_text,
            "embedding_model": model, "embedding_dimension": dimensions,
            "embedding": blob,
        }
        if session:
            await session.execute(query, params)
        else:
            async with self._session() as s:
                await s.execute(query, params)

    async def delete_embeddings_for_node(
        self, node_uuid: str, namespace: str = "",
        session: AsyncSession | None = None,
    ) -> None:
        query = text(
            "DELETE FROM memory_embeddings "
            "WHERE node_uuid = :node_uuid AND namespace = :namespace"
        )
        params = {"node_uuid": node_uuid, "namespace": namespace}
        if session:
            await session.execute(query, params)
        else:
            async with self._session() as s:
                await s.execute(query, params)

    async def delete_orphan_embeddings(
        self, session: AsyncSession | None = None,
    ) -> int:
        query = text(
            "DELETE FROM memory_embeddings "
            "WHERE rowid IN ("
            "  SELECT me.rowid FROM memory_embeddings me "
            "  LEFT JOIN paths p ON p.node_uuid = me.node_uuid AND p.namespace = me.namespace "
            "  WHERE p.node_uuid IS NULL"
            "  AND me.source_type != 'remote_summary'"
            ")"
        )
        if session:
            result = await session.execute(query)
        else:
            async with self._session() as s:
                result = await s.execute(query)
        return result.rowcount or 0

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain: str | None = None,
        namespace: str = "",
        source_type: str | None = "active_memory",
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        model = self.embedding_model
        dimensions = self.embedding_dimensions
        provider = self.embedding_provider

        query_vecs = await provider.embed([query], dimensions=dimensions)
        if not query_vecs:
            return []
        query_vec = query_vecs[0]

        async def _search(s: AsyncSession) -> list[dict[str, Any]]:
            select_sql = (
                "SELECT node_uuid, domain, path, source_type, source_text, "
                "source_memory_id, embedding "
                "FROM memory_embeddings "
                "WHERE namespace = :namespace "
                "AND embedding_model = :model "
                "AND embedding_dimension = :dim "
            )
            params: dict[str, Any] = {
                "namespace": namespace, "model": model, "dim": dimensions,
            }
            if domain is not None:
                select_sql += " AND domain = :domain"
                params["domain"] = domain
            if source_type is not None:
                select_sql += " AND source_type = :source_type"
                params["source_type"] = source_type

            result = await s.execute(text(select_sql), params)
            rows = result.mappings().all()

            scored = []
            for row in rows:
                blob = row["embedding"]
                if blob is None:
                    continue
                try:
                    vec = _unpack_floats(blob)
                except Exception:
                    continue
                dist = _cosine_distance(query_vec, vec)
                score = 1.0 - dist
                scored.append((score, row))

            scored.sort(key=lambda x: x[0], reverse=True)

            results = []
            seen = set()
            for score, row in scored:
                node_uuid = row["node_uuid"]
                if node_uuid in seen:
                    continue
                seen.add(node_uuid)
                uri = f"{row['domain']}://{row['path']}"
                results.append({
                    "uri": uri,
                    "node_uuid": node_uuid,
                    "domain": row["domain"],
                    "path": row["path"],
                    "source_type": row["source_type"],
                    "source_text": row["source_text"],
                    "source_memory_id": row["source_memory_id"],
                    "score": score,
                })
                if len(results) >= limit:
                    break
            return results

        if session:
            return await _search(session)
        else:
            async with self._session() as s:
                return await _search(s)

    async def rebuild_all(
        self, session: AsyncSession | None = None,
    ) -> int:
        model_dim = self.embedding_dimensions
        model_name = self.embedding_model
        provider = self.embedding_provider

        async def _do_rebuild(s: AsyncSession):
            await s.execute(text("DELETE FROM memory_embeddings WHERE source_type = 'active_memory'"))

            result = await s.execute(
                select(
                    Memory.node_uuid,
                    Memory.id,
                    Memory.content,
                    Path.namespace,
                    Path.domain,
                    Path.path,
                )
                .select_from(Memory)
                .join(Path, Memory.node_uuid == Path.node_uuid)
                .where(Memory.deprecated == False)
                .order_by(Path.namespace, Path.domain, Path.path)
            )
            raw_rows = result.all()
            if not raw_rows:
                return 0

            seen: set[tuple[str, str]] = set()
            deduped = []
            for row in raw_rows:
                key = (row.node_uuid, row.namespace)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(row)

            texts = [row.content for row in deduped]
            vectors = await provider.embed(texts, dimensions=model_dim)

            indexed = 0
            for row, vec in zip(deduped, vectors):
                blob = _pack_floats(vec)
                await s.execute(text(
                    "INSERT OR REPLACE INTO memory_embeddings "
                    "(node_uuid, namespace, source_memory_id, domain, path, "
                    " source_type, source_text, embedding_model, embedding_dimension, embedding) "
                    "VALUES (:node_uuid, :namespace, :source_memory_id, :domain, :path, "
                    " :source_type, :source_text, :embedding_model, :embedding_dimension, :embedding)"
                ), {
                    "node_uuid": row.node_uuid, "namespace": row.namespace,
                    "source_memory_id": row.id, "domain": row.domain,
                    "path": row.path, "source_type": "active_memory",
                    "source_text": row.content, "embedding_model": model_name,
                    "embedding_dimension": model_dim, "embedding": blob,
                })
                indexed += 1
            return indexed

        if session:
            return await _do_rebuild(session)
        else:
            async with self._session() as s:
                return await _do_rebuild(s)
